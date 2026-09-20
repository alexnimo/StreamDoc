"""Tests for POR-91 T1: design_prompt_template preset column + template_kind discriminator.

Covers:
- Preset ORM model / Pydantic schemas expose ``design_prompt_template``
- upsert_preset -> load_preset round-trips the value; missing key coerces to None
- The lightweight migration adds the column to a pre-existing presets table
- PromptTemplate round-trips ``template_kind`` through save/load YAML
- GET /prompts?kind=... filters by kind; POST/PUT persist it; GET /prompts/{name}
  returns the saved kind
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _reset_db_engine() -> None:
    import streamdoc.db as _db

    _db._engine = None
    _db._session_factory = None


@pytest.fixture()
def temp_db():
    """Point STREAMDOC_DB_PATH at a fresh temp DB and restore afterwards."""
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["STREAMDOC_DB_PATH"] = str(Path(tmp) / "state.sqlite")
        try:
            _reset_db_engine()
            import streamdoc.db as _db

            _db._get_engine()
            from streamdoc.db import init_db

            init_db()
            yield tmp
        finally:
            os.environ.pop("STREAMDOC_DB_PATH", None)
            _reset_db_engine()
            import streamdoc.db as _db

            _db._get_engine()


# ---------------------------------------------------------------------------
# Change 1 — design_prompt_template preset column
# ---------------------------------------------------------------------------
def test_preset_model_has_design_prompt_template():
    """The Preset ORM model exposes the design_prompt_template column."""
    import streamdoc.db  # noqa: F401
    from streamdoc.models.preset import Preset

    assert hasattr(Preset, "design_prompt_template")


def test_preset_schemas_include_design_prompt_template():
    """PresetOut / PresetCreate / PresetUpdate all expose the field."""
    from streamdoc.api.schemas import PresetCreate, PresetOut, PresetUpdate

    for schema in (PresetOut, PresetCreate, PresetUpdate):
        assert "design_prompt_template" in schema.model_fields, (
            f"{schema.__name__} missing design_prompt_template"
        )


def test_upsert_preset_round_trips_design_prompt_template(temp_db):
    """AC1: upsert_preset -> load_preset round-trips design_prompt_template."""
    from streamdoc.presets import load_preset, upsert_preset

    upsert_preset({"name": "design-rt", "design_prompt_template": "modern_clean"})
    p = load_preset("design-rt")
    assert p.design_prompt_template == "modern_clean"

    # Update path: overwrite the value and confirm persistence.
    upsert_preset({"name": "design-rt", "design_prompt_template": "minimal_dark"})
    p = load_preset("design-rt")
    assert p.design_prompt_template == "minimal_dark"


def test_upsert_preset_missing_key_defaults_to_none(temp_db):
    """AC1: a payload without design_prompt_template coerces to None."""
    from streamdoc.presets import load_preset, upsert_preset

    upsert_preset({"name": "no-design"})
    p = load_preset("no-design")
    assert p.design_prompt_template is None


def test_lightweight_migration_adds_design_prompt_template():
    """AC2: an existing DB without the column migrates cleanly on init_db."""
    import streamdoc.db  # noqa: F401
    from sqlalchemy import create_engine, inspect, text

    from streamdoc.db import Base, _run_lightweight_migrations

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "legacy.sqlite"
        legacy_engine = create_engine(f"sqlite:///{db_path.as_posix()}")
        try:
            Base.metadata.create_all(bind=legacy_engine)
            with legacy_engine.begin() as conn:
                conn.execute(text("ALTER TABLE presets DROP COLUMN design_prompt_template"))

            before = {c["name"] for c in inspect(legacy_engine).get_columns("presets")}
            assert "design_prompt_template" not in before

            _run_lightweight_migrations(legacy_engine)

            after = inspect(legacy_engine).get_columns("presets")
            names = {c["name"] for c in after}
            assert "design_prompt_template" in names

            # NULL default: existing rows read back as NULL.
            from sqlalchemy.orm import sessionmaker

            from streamdoc.models.preset import Preset

            factory = sessionmaker(bind=legacy_engine)
            with factory() as s:
                s.add(Preset(id="legacy", name="legacy"))
                s.commit()
            with legacy_engine.begin() as conn:
                value = conn.execute(
                    text("SELECT design_prompt_template FROM presets WHERE id = 'legacy'")
                ).scalar()
            assert value is None

            # Idempotent: re-running does not raise or duplicate the column.
            _run_lightweight_migrations(legacy_engine)
            again = {c["name"] for c in inspect(legacy_engine).get_columns("presets")}
            assert again == names
        finally:
            # Reason: on Windows the sqlite file stays locked until the engine
            # pool is disposed; without this the tempdir cleanup errors.
            legacy_engine.dispose()


def test_to_out_maps_design_prompt_template():
    """The api presets route's _to_out maps the column onto PresetOut."""
    from types import SimpleNamespace

    from streamdoc.api.routes.presets import _to_out

    fake = SimpleNamespace(
        id="d1",
        name="d1",
        channel_list_id=None,
        design_prompt_template="modern_clean",
    )
    out = _to_out(fake)
    assert out.design_prompt_template == "modern_clean"


# ---------------------------------------------------------------------------
# Change 2 — template_kind discriminator + prompts API kind filter
# ---------------------------------------------------------------------------
def _make_manager(tmp_dir: Path):
    from streamdoc.integrations.notebooklm.prompts import PromptManager

    return PromptManager(tmp_dir, None)


@pytest.fixture()
def prompts_client(tmp_path):
    """TestClient with the prompts router pointed at a tmp templates dir."""
    from streamdoc.api.routes import prompts as prompts_route

    mgr = _make_manager(tmp_path)
    app = FastAPI()
    app.include_router(prompts_route.router)
    with patch.object(prompts_route, "_get_manager", return_value=mgr):
        yield TestClient(app), tmp_path


def test_template_kind_yaml_round_trip(tmp_path):
    """AC3/AC4: save_template writes template_kind; YAML without the key loads as 'content'."""
    from streamdoc.integrations.notebooklm.prompts import ContentType, PromptTemplate

    mgr = _make_manager(tmp_path)
    mgr.save_template(
        PromptTemplate(
            name="design_x",
            description="d",
            target_types=[ContentType.SLIDE_DECK],
            prompt="p {content_type}",
            variables={},
            template_kind="design",
        )
    )
    mgr.save_template(
        PromptTemplate(
            name="plain",
            description="c",
            target_types=[ContentType.REPORT],
            prompt="p {content_type}",
        )
    )

    # Written YAML carries the key for the design template.
    data = yaml.safe_load((tmp_path / "design_x.yaml").read_text(encoding="utf-8"))
    assert data["template_kind"] == "design"
    # A template saved without an explicit kind persists as "content".
    data_plain = yaml.safe_load((tmp_path / "plain.yaml").read_text(encoding="utf-8"))
    assert data_plain["template_kind"] == "content"

    # A YAML file lacking template_kind loads as "content".
    (tmp_path / "legacy.yaml").write_text(
        yaml.safe_dump({"name": "legacy", "prompt": "x {content_type}"}),
        encoding="utf-8",
    )
    mgr2 = _make_manager(tmp_path)
    assert mgr2.load_template("design_x").template_kind == "design"
    assert mgr2.load_template("legacy").template_kind == "content"
    assert mgr2.load_template("plain").template_kind == "content"


def test_prompts_api_kind_filter_and_crud(prompts_client):
    """AC4/AC5: POST design template, kind filter, unfiltered list, PUT, GET by name."""
    client, tmp_path = prompts_client

    # Create a design template via POST.
    resp = client.post(
        "/prompts",
        json={
            "name": "design_bold",
            "description": "bold design",
            "target_types": ["slide_deck"],
            "prompt": "Design a {content_type} boldly",
            "template_kind": "design",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["template_kind"] == "design"

    # POST defaulting to content.
    resp = client.post("/prompts", json={"name": "content_a"})
    assert resp.status_code == 200
    assert resp.json()["template_kind"] == "content"

    # GET /prompts/{name} returns the saved kind (AC5).
    resp = client.get("/prompts/design_bold")
    assert resp.status_code == 200
    assert resp.json()["template_kind"] == "design"

    # ?kind=design returns only design templates.
    resp = client.get("/prompts", params={"kind": "design"})
    assert resp.status_code == 200
    body = resp.json()
    assert body and all(t["template_kind"] == "design" for t in body)
    assert {t["name"] for t in body} == {"design_bold"}

    # ?kind=content returns only content templates (includes defaults).
    resp = client.get("/prompts", params={"kind": "content"})
    assert resp.status_code == 200
    body = resp.json()
    assert all(t["template_kind"] == "content" for t in body)
    assert "content_a" in {t["name"] for t in body}

    # No kind param returns everything.
    resp = client.get("/prompts")
    assert resp.status_code == 200
    names = {t["name"] for t in resp.json()}
    assert {"design_bold", "content_a"} <= names

    # Invalid kind is rejected with 422.
    resp = client.get("/prompts", params={"kind": "bogus"})
    assert resp.status_code == 422

    # PUT without template_kind preserves the existing kind.
    resp = client.put("/prompts/design_bold", json={"description": "updated"})
    assert resp.status_code == 200
    assert resp.json()["template_kind"] == "design"

    # PUT can update the kind explicitly.
    resp = client.put(
        "/prompts/content_a", json={"template_kind": "design"}
    )
    assert resp.status_code == 200
    assert resp.json()["template_kind"] == "design"

    # Persisted to disk via save_template.
    data = yaml.safe_load((tmp_path / "design_bold.yaml").read_text(encoding="utf-8"))
    assert data["template_kind"] == "design"
