"""
Database engine and session management.

The engine is created lazily so that tests which override
STREAMDOC_DB_PATH via env vars get the correct database.
"""
from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


# Import models to register with SQLAlchemy
# These imports must happen after Base is defined
# Reason: Job must be imported before NotebookLM retention models due to FK reference
from streamdoc.models.job import Job as JobModel  # noqa: F401,E402
from streamdoc.models.video import Channel, Video as VideoModel  # noqa: F401,E402
from streamdoc.models.preset import Preset as PresetModel  # noqa: F401,E402
from streamdoc.models.output import Output as OutputModel  # noqa: F401,E402
from streamdoc.models.generation import Generation as GenerationModel  # noqa: F401,E402
from streamdoc.models.social_post import SocialPost as SocialPostModel  # noqa: F401,E402

try:
    from streamdoc.integrations.notebooklm.retention import (
        NotebookLMContent,  # noqa: F401
        NotebookLMRetentionLog,  # noqa: F401
    )
except ImportError:
    pass  # NotebookLM integration not available


# Reason: lazy initialization avoids stale engine when settings change at runtime
_engine = None
_session_factory = None


def _get_engine():
    global _engine, _session_factory
    from streamdoc.config import settings
    from pathlib import Path

    # Reason: resolve db_path to an absolute path so the engine works
    # regardless of the process's current working directory. Without this,
    # uvicorn started from a different directory (or `uv run` changing cwd)
    # would fail with "unable to open database file".
    db_path = Path(settings.db_path)
    if not db_path.is_absolute():
        # Reason: resolve relative to the project root (parent of src/)
        # so the path is stable regardless of cwd.
        project_root = Path(__file__).resolve().parent.parent.parent
        db_path = project_root / db_path
    db_path = db_path.resolve()

    # Reason: ensure the parent directory exists before SQLite tries to
    # open the file — SQLite cannot create the directory.
    db_path.parent.mkdir(parents=True, exist_ok=True)

    db_url = f"sqlite:///{db_path.as_posix()}"

    # Reason: recreate engine if db_path changed (e.g. in tests with monkeypatch)
    if _engine is not None:
        if str(_engine.url) != db_url:
            _engine.dispose()
            _engine = None

    if _engine is None:
        _engine = create_engine(
            db_url,
            connect_args={"check_same_thread": False},
            pool_pre_ping=True,
        )
        # Reason: WAL mode allows concurrent reads while a write transaction is in progress,
        # preventing the UI from freezing when a background job writes to the DB.
        # busy_timeout tells SQLite to wait up to 5s for a lock instead of failing immediately.
        from sqlalchemy import event

        @event.listens_for(_engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

        _session_factory = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
    return _engine


def _get_session_factory():
    _get_engine()  # ensure initialized
    return _session_factory


def _run_lightweight_migrations(engine) -> None:
    """Add columns that were introduced to models after the table was created.

    Reason: SQLAlchemy's ``create_all`` only creates missing tables — it does
    NOT alter existing tables to add new columns. For SQLite, we use
    ``ALTER TABLE ... ADD COLUMN`` to backfill schema changes on existing
    databases without requiring a full migration framework like Alembic.

    Each entry is (table, column_name, column_sql_type). Only added if the
    column is missing from the live SQLite schema.
    """
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    if not insp.has_table("jobs"):
        return

    existing_columns = {c["name"] for c in insp.get_columns("jobs")}
    # Reason: each tuple describes a column added to the Job model after the
    # initial schema. Add future column additions here.
    pending_columns: list[tuple[str, str]] = [
        ("details", "TEXT DEFAULT ''"),
    ]
    with engine.begin() as conn:
        for column_name, column_type in pending_columns:
            if column_name not in existing_columns:
                conn.execute(
                    text(f"ALTER TABLE jobs ADD COLUMN {column_name} {column_type}")
                )

    # Reason: per-preset retention overrides added after the initial Preset
    # schema. Backfill on existing databases without requiring Alembic.
    if insp.has_table("presets"):
        preset_columns = {c["name"] for c in insp.get_columns("presets")}
        preset_pending: list[tuple[str, str]] = [
            ("file_retention_hours", "FLOAT DEFAULT 24.0"),
            ("notebook_retention_hours", "FLOAT DEFAULT 24.0"),
            ("retention_enabled", "BOOLEAN DEFAULT 1"),
            ("channel_names", "TEXT DEFAULT NULL"),
            ("notebooklm_prompt_template", "TEXT DEFAULT NULL"),
            ("notebooklm_retry_failed", "BOOLEAN DEFAULT 1"),
            ("notebooklm_retry_attempts", "INTEGER DEFAULT 1"),
            ("notebooklm_retry_delay_minutes", "FLOAT DEFAULT 5.0"),
            # Social sentiment pipeline columns — POR-11.
            ("preset_type", "TEXT DEFAULT 'youtube'"),
            ("social_sources", "TEXT DEFAULT NULL"),
            ("social_max_posts", "INTEGER DEFAULT NULL"),
            ("social_lookback_hours", "INTEGER DEFAULT NULL"),
            ("cli_tool", "TEXT DEFAULT NULL"),
            ("cli_tool_template", "TEXT DEFAULT NULL"),
            # Reason: POR-27 Antigravity (agy) generation backend columns.
            # Added alongside the notebooklm_* shape so the preset model can
            # carry both backends; the future _send_reports discriminator
            # picks the active one based on the outputs string + flags.
            ("agy_enabled", "BOOLEAN DEFAULT 0"),
            ("agy_skill", "TEXT DEFAULT NULL"),
            ("agy_model", "TEXT DEFAULT NULL"),
            ("agy_publish_herenow", "BOOLEAN DEFAULT 0"),
            ("agy_prompt_template", "TEXT DEFAULT NULL"),
            ("agy_existing_report", "TEXT DEFAULT NULL"),
        ]
        with engine.begin() as conn:
            for column_name, column_type in preset_pending:
                if column_name not in preset_columns:
                    conn.execute(
                        text(f"ALTER TABLE presets ADD COLUMN {column_name} {column_type}")
                    )

    # Reason: fix videos stuck in "integration-failed" status from the
    # old per-video NotebookLM upload bug. These videos have valid outputs
    # but were marked as failed because NotebookLM wasn't configured.
    # Reset them to "ready" so skip_processed works correctly.
    if insp.has_table("videos"):
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE videos SET output_status = 'ready' WHERE output_status = 'integration-failed'")
            )

    # Reason: social_posts table for deduplication and retention of
    # collected social media posts across preset runs.
    if not insp.has_table("social_posts"):
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE TABLE social_posts ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  platform TEXT NOT NULL,"
                "  source_id TEXT NOT NULL,"
                "  preset_name TEXT NOT NULL,"
                "  processed_at TEXT DEFAULT '',"
                "  processed BOOLEAN DEFAULT 0,"
                "  output_status TEXT DEFAULT 'pending',"
                "  raw_data TEXT DEFAULT NULL"
                ")"
            ))

    # Reason: add the processed marker and unique/index constraints introduced
    # after the initial social_posts schema. Backfill existing rows safely.
    if insp.has_table("social_posts"):
        social_columns = {c["name"] for c in insp.get_columns("social_posts")}
        with engine.begin() as conn:
            if "processed" not in social_columns:
                conn.execute(text(
                    "ALTER TABLE social_posts ADD COLUMN processed BOOLEAN DEFAULT 0"
                ))

            # Remove any duplicate (platform, source_id, preset_name) rows before
            # adding a unique index; keep the earliest inserted record.
            conn.execute(text(
                "DELETE FROM social_posts "
                "WHERE id NOT IN ("
                "  SELECT MIN(id) FROM social_posts "
                "  GROUP BY platform, source_id, preset_name"
                ")"
            ))

            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_social_posts_platform_source_preset "
                "ON social_posts(platform, source_id, preset_name)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS "
                "idx_social_posts_platform_source_id "
                "ON social_posts(platform, source_id)"
            ))


def init_db() -> None:
    engine = _get_engine()
    Base.metadata.create_all(bind=engine)
    _run_lightweight_migrations(engine)


@contextmanager
def session_scope():
    factory = _get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
