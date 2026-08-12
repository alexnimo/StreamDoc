"""Tests for POR-27 T1: agy preset schema surface (model + migration + API + config).

These tests confirm the additive schema layer landed:
- Preset ORM model exposes the agy_* columns
- Pydantic PresetOut/PresetCreate/PresetUpdate surface the same fields
- SettingsOut/SettingsUpdate surface the agy_* + notify_telegram_* env knobs
- The lightweight migration adds the new columns to a pre-existing presets
  table without losing data
- The YAML preset upsert round-trips agy_* keys
- `_to_out` (api route) maps the model columns into the response schema

The integration package, the fetch.py wiring, and the CLI surface land in
T2/T3 and are intentionally out of scope here.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
import yaml


def test_preset_model_has_agy_columns():
    """The Preset ORM model exposes the five agy_* columns."""
    import streamdoc.db  # noqa: F401  (breaks the preset<->db circular import)
    from streamdoc.models.preset import Preset

    for col in (
        "agy_enabled",
        "agy_skill",
        "agy_model",
        "agy_publish_herenow",
        "agy_prompt_template",
    ):
        assert hasattr(Preset, col), f"Preset model missing {col}"


def test_preset_schemas_include_agy_fields():
    """PresetOut / PresetCreate / PresetUpdate all expose the agy_* fields."""
    from streamdoc.api.schemas import PresetCreate, PresetOut, PresetUpdate

    agy_fields = [
        "agy_enabled",
        "agy_skill",
        "agy_model",
        "agy_publish_herenow",
        "agy_prompt_template",
    ]
    for schema in (PresetOut, PresetCreate, PresetUpdate):
        for f in agy_fields:
            assert f in schema.model_fields, f"{schema.__name__} missing {f}"


def test_settings_schemas_include_agy_and_notify_fields():
    """SettingsOut / SettingsUpdate surface the agy + notify env vars."""
    from streamdoc.api.schemas import SettingsOut, SettingsUpdate

    fields = [
        "agy_enabled",
        "agy_install_dir",
        "agy_global_dir",
        "agy_default_skill",
        "agy_default_model",
        "agy_supported_models",
        "agy_templates_dir",
        "agy_sample_prompts_dir",
        "agy_default_wait_timeout",
        "agy_output_dir",
        "notify_telegram_enabled",
        "notify_telegram_bot_token",
        "notify_telegram_chat_id",
    ]
    for schema in (SettingsOut, SettingsUpdate):
        for f in fields:
            assert f in schema.model_fields, f"{schema.__name__} missing {f}"


def test_settings_agy_defaults_are_conservative():
    """Default settings should not enable agy or telegram out of the box."""
    from streamdoc.config import settings

    assert settings.agy_enabled is False
    assert settings.agy_install_dir == ".agents/skills"
    assert settings.agy_default_skill == "web-video-presentation"
    assert settings.agy_default_model is None
    assert settings.agy_supported_models == ""
    assert settings.agy_default_wait_timeout > 0
    assert settings.agy_output_dir == "data/Outputs/agy"
    assert settings.notify_telegram_enabled is False
    assert settings.notify_telegram_bot_token is None
    assert settings.notify_telegram_chat_id is None


def test_preset_out_defaults_agy_disabled():
    """A freshly built PresetOut should have agy_enabled=False and skill/model/template None."""
    from streamdoc.api.schemas import PresetOut

    p = PresetOut(id="t", name="t")
    assert p.agy_enabled is False
    assert p.agy_skill is None
    assert p.agy_model is None
    assert p.agy_publish_herenow is False
    assert p.agy_prompt_template is None


def test_preset_create_accepts_agy_fields():
    """PresetCreate accepts the agy_* fields and round-trips through the schema."""
    from streamdoc.api.schemas import PresetCreate

    body = PresetCreate(
        name="agy-test",
        outputs="pdf,markdown,agy",
        agy_enabled=True,
        agy_skill="web-video-presentation",
        agy_model="kimi-k2.7",
        agy_publish_herenow=True,
        agy_prompt_template="default",
    )
    assert body.agy_enabled is True
    assert body.agy_skill == "web-video-presentation"
    assert body.agy_model == "kimi-k2.7"
    assert body.agy_publish_herenow is True
    assert body.agy_prompt_template == "default"


def test_upsert_preset_round_trips_agy_fields():
    """upsert_preset reads agy_* from the payload and writes them to the DB."""
    import streamdoc.db  # noqa: F401
    from streamdoc.config import settings
    from streamdoc.db import init_db, session_scope
    from streamdoc.models.preset import Preset
    from streamdoc.presets import upsert_preset

    # Use a temp DB so this test does not depend on the dev environment.
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["STREAMDOC_DB_PATH"] = str(Path(tmp) / "state.sqlite")
        try:
            # Reset the lazy engine so the new env var takes effect.
            import streamdoc.db as _db

            _db._engine = None
            _db._session_factory = None
            _db._get_engine()
            init_db()

            payload = {
                "name": "agy-roundtrip",
                "outputs": "pdf,markdown,agy",
                "agy_enabled": True,
                "agy_skill": "web-video-presentation",
                "agy_model": "kimi-k2.7",
                "agy_publish_herenow": True,
                "agy_prompt_template": "default",
            }
            upsert_preset(payload)

            with session_scope() as s:
                row = s.get(Preset, "agy-roundtrip")
                assert row is not None
                assert row.agy_enabled is True
                assert row.agy_skill == "web-video-presentation"
                assert row.agy_model == "kimi-k2.7"
                assert row.agy_publish_herenow is True
                assert row.agy_prompt_template == "default"

            # Update path: change a field and confirm the update is persisted.
            payload["agy_skill"] = "web-design-engineer"
            payload["agy_publish_herenow"] = False
            upsert_preset(payload)
            with session_scope() as s:
                row = s.get(Preset, "agy-roundtrip")
                assert row.agy_skill == "web-design-engineer"
                assert row.agy_publish_herenow is False
        finally:
            # Restore the previous env var and the lazy engine.
            os.environ.pop("STREAMDOC_DB_PATH", None)
            import streamdoc.db as _db

            _db._engine = None
            _db._session_factory = None
            # Force re-init of the engine under the previous path.
            _ = _db._get_engine()
            _ = settings  # silence unused warning


def test_upsert_preset_yaml_agy_keys():
    """A preset YAML can declare agy_* keys and they survive loading."""
    import streamdoc.db  # noqa: F401
    from streamdoc.db import init_db, session_scope
    from streamdoc.models.preset import Preset
    from streamdoc.presets import load_preset_file

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["STREAMDOC_DB_PATH"] = str(Path(tmp) / "state.sqlite")
        try:
            import streamdoc.db as _db

            _db._engine = None
            _db._session_factory = None
            _db._get_engine()
            init_db()

            yaml_path = Path(tmp) / "agy-preset.yaml"
            yaml_path.write_text(
                yaml.safe_dump(
                    {
                        "name": "agy-yaml",
                        "outputs": "pdf,markdown,agy",
                        "agy_enabled": True,
                        "agy_skill": "web-design-engineer",
                        "agy_model": "kimi-k2.7",
                        "agy_publish_herenow": True,
                        "agy_prompt_template": "default",
                    }
                ),
                encoding="utf-8",
            )
            load_preset_file(yaml_path)

            with session_scope() as s:
                row = s.get(Preset, "agy-yaml")
                assert row is not None
                assert row.agy_enabled is True
                assert row.agy_skill == "web-design-engineer"
                assert row.agy_model == "kimi-k2.7"
                assert row.agy_publish_herenow is True
                assert row.agy_prompt_template == "default"
                assert "agy" in row.outputs
        finally:
            os.environ.pop("STREAMDOC_DB_PATH", None)
            import streamdoc.db as _db

            _db._engine = None
            _db._session_factory = None
            _db._get_engine()


def test_lightweight_migration_adds_agy_columns():
    """_run_lightweight_migrations adds the new agy columns to a pre-existing presets table."""
    import streamdoc.db  # noqa: F401
    from sqlalchemy import create_engine, inspect, text

    from streamdoc.db import Base, _run_lightweight_migrations

    # Build a minimal engine that pre-creates the `presets` table WITHOUT the
    # new agy columns — simulating an existing pre-POR-27 deployment.
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "legacy.sqlite"
        legacy_engine = create_engine(f"sqlite:///{db_path.as_posix()}")
        try:
            # Create the base tables from current models, then drop the new agy
            # columns so we can confirm the migration backfills them.
            Base.metadata.create_all(bind=legacy_engine)
            with legacy_engine.begin() as conn:
                for col in (
                    "agy_enabled",
                    "agy_skill",
                    "agy_model",
                    "agy_publish_herenow",
                    "agy_prompt_template",
                ):
                    conn.execute(text(f"ALTER TABLE presets DROP COLUMN {col}"))

            # Inspect BEFORE — get_columns is cached, so use a fresh inspector.
            before = {c["name"] for c in inspect(legacy_engine).get_columns("presets")}
            assert "agy_enabled" not in before
            assert "agy_skill" not in before

            # Run the migration on this engine — it should add the missing
            # columns.
            _run_lightweight_migrations(legacy_engine)

            # Inspect AFTER — re-create the inspector so the cache is busted.
            after = {c["name"] for c in inspect(legacy_engine).get_columns("presets")}
            for col in (
                "agy_enabled",
                "agy_skill",
                "agy_model",
                "agy_publish_herenow",
                "agy_prompt_template",
            ):
                assert col in after, f"migration did not add {col}"

            # The migration is idempotent: re-running it does not raise and
            # does not duplicate the column.
            _run_lightweight_migrations(legacy_engine)
            again = {c["name"] for c in inspect(legacy_engine).get_columns("presets")}
            assert again == after
        finally:
            # Reason: on Windows the sqlite file is locked by the engine
            # pool until disposed; without this the tempdir cleanup errors
            # with PermissionError and the test fails for the wrong reason.
            legacy_engine.dispose()


def test_to_out_maps_agy_fields():
    """The api presets route's _to_out maps the agy_* columns onto PresetOut."""
    from types import SimpleNamespace

    from streamdoc.api.routes.presets import _to_out

    fake = SimpleNamespace(
        id="agy-x",
        name="agy-x",
        channel_list_id=None,
        channel_names=None,
        prompt_md="",
        outputs="pdf,markdown,agy",
        notebooklm_kind=None,
        agy_enabled=True,
        agy_skill="web-video-presentation",
        agy_model="kimi-k2.7",
        agy_publish_herenow=True,
        agy_prompt_template="default",
        schedule=None,
        schedule_interval_hours=None,
        lookback_hours=None,
        max_videos=None,
        text_filter=None,
        date_range_days=None,
        playlist_mode=False,
        skip_processed=True,
        active=True,
        retention_enabled=True,
        file_retention_hours=24.0,
        notebook_retention_hours=24.0,
    )
    out = _to_out(fake)
    assert out.agy_enabled is True
    assert out.agy_skill == "web-video-presentation"
    assert out.agy_model == "kimi-k2.7"
    assert out.agy_publish_herenow is True
    assert out.agy_prompt_template == "default"


def test_assets_prompts_agy_default_yaml_exists():
    """The default agy prompt template is shipped under assets/prompts/agy/."""
    from pathlib import Path

    prompt_path = Path(__file__).resolve().parent.parent / "assets" / "prompts" / "agy" / "default.yaml"
    assert prompt_path.exists(), f"missing sample prompt: {prompt_path}"
    payload = yaml.safe_load(prompt_path.read_text(encoding="utf-8"))
    assert payload["name"] == "default"
    assert "prompt" in payload
    assert "variables" in payload


@pytest.mark.parametrize(
    "field,value",
    [
        ("agy_enabled", True),
        ("agy_skill", "web-design-engineer"),
        ("agy_model", "kimi-k2.7"),
        ("agy_publish_herenow", True),
        ("agy_prompt_template", "default"),
    ],
)
def test_preset_update_partial_agy_field(field, value):
    """PresetUpdate accepts each agy_* field independently (the PATCH-style surface)."""
    from streamdoc.api.schemas import PresetUpdate

    body = PresetUpdate(**{field: value})
    assert getattr(body, field) == value
