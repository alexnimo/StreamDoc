"""Tests for POR-91 F1: design prompt threading in retry/resend + cli_agy.

Covers the two call sites that POR-91 T2 missed:
- ``jobs._send_to_destination`` notebooklm branch (used by retry/resend).
- ``streamdoc agy run <preset>`` manual path in ``cli_agy.py``.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from streamdoc.config import Settings
from streamdoc.core.jobs import _send_to_destination
from streamdoc.db import init_db, session_scope
from streamdoc.models.preset import Preset as PresetModel


def _make_preset_model(**kwargs):
    """Build a Preset model suitable for inserting into the test DB."""
    defaults = {
        "id": "test",
        "name": "Test",
        "channel_list_id": "",
        "prompt_md": "test prompt",
        "outputs": "pdf,markdown",
        "notebooklm_kind": "slide_deck",
        "notebooklm_prompt_template": None,
        "design_prompt_template": None,
        "agy_enabled": False,
        "agy_skill": None,
        "agy_model": None,
        "agy_publish_herenow": False,
        "agy_prompt_template": None,
    }
    defaults.update(kwargs)
    return PresetModel(**defaults)


def _isolate_template_dirs(monkeypatch, tmp_path):
    """Point the design-template PromptManager at empty tmp dirs."""
    from streamdoc.config import settings

    monkeypatch.setattr(settings, "notebooklm_templates_dir", str(tmp_path / "tpl"))
    monkeypatch.setattr(
        settings, "notebooklm_sample_prompts_dir", str(tmp_path / "samples")
    )


@pytest.fixture
def _isolated_db(tmp_path, monkeypatch):
    """Provide a fresh in-memory DB and isolated output root."""
    db_path = tmp_path / "test.sqlite"
    output_root = tmp_path / "outputs"
    s = Settings(
        db_path=str(db_path),
        output_root=str(output_root),
    )
    monkeypatch.setattr("streamdoc.config.settings", s)
    init_db()


# ---------------------------------------------------------------------------
# Jobs retry/resend path
# ---------------------------------------------------------------------------


def test_jobs_retry_design_prompt_threaded(
    _isolated_db, monkeypatch, tmp_path
):
    """AC1: retry/resend with design_prompt_template set appends the <design> block."""
    from types import SimpleNamespace

    from streamdoc.core.fetch import _design_prompt_for_preset
    from streamdoc.integrations.notebooklm.prompts import ContentType

    _isolate_template_dirs(monkeypatch, tmp_path)

    preset = _make_preset_model(
        id="with-design",
        name="with-design",
        design_prompt_template="design_guidelines",
    )
    with session_scope() as session:
        session.add(preset)

    fake_pdf = tmp_path / "report.pdf"
    fake_pdf.write_bytes(b"%PDF fake")

    fake_result = type(
        "R",
        (),
        {
            "success": True,
            "notebook_url": "https://nb.example/1",
            "notebook_id": "nb1",
            "sources": [],
            "generated_content": [],
            "errors": [],
        },
    )()
    mock_nlm = AsyncMock(return_value=fake_result)

    with patch("streamdoc.core.notebooklm_upload.upload_to_notebooklm", mock_nlm):
        _send_to_destination(
            "notebooklm", [fake_pdf], preset_name="with-design", job_id="job-1"
        )

    assert mock_nlm.call_count == 1
    design = mock_nlm.call_args.kwargs["design_prompt"]
    expected = _design_prompt_for_preset(
        SimpleNamespace(design_prompt_template="design_guidelines"),
        ContentType.SLIDE_DECK,
    )
    assert design is not None
    assert design != ""
    assert design == expected


def test_jobs_retry_null_design_template_sends_none(
    _isolated_db, monkeypatch, tmp_path
):
    """AC3: NULL design_prompt_template keeps the prompt byte-identical (None)."""
    _isolate_template_dirs(monkeypatch, tmp_path)

    preset = _make_preset_model(
        id="no-design",
        name="no-design",
        design_prompt_template=None,
    )
    with session_scope() as session:
        session.add(preset)

    fake_pdf = tmp_path / "report.pdf"
    fake_pdf.write_bytes(b"%PDF fake")

    fake_result = type(
        "R",
        (),
        {
            "success": True,
            "notebook_url": None,
            "notebook_id": "nb2",
            "sources": [],
            "generated_content": [],
            "errors": [],
        },
    )()
    mock_nlm = AsyncMock(return_value=fake_result)

    with patch("streamdoc.core.notebooklm_upload.upload_to_notebooklm", mock_nlm):
        _send_to_destination(
            "notebooklm", [fake_pdf], preset_name="no-design", job_id="job-2"
        )

    assert mock_nlm.call_count == 1
    assert mock_nlm.call_args.kwargs["design_prompt"] is None


# ---------------------------------------------------------------------------
# CLI agy manual path
# ---------------------------------------------------------------------------


def test_cli_agy_run_threads_design_prompt(
    monkeypatch, tmp_path
):
    """AC2: ``streamdoc agy run`` passes a rendered design_prompt when set."""
    from click.testing import CliRunner

    from streamdoc.config import settings
    from streamdoc.core.agy_upload import _DEFAULT_AGY_CONTENT_TYPE
    from streamdoc.core.fetch import _design_prompt_for_preset

    _isolate_template_dirs(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "output_root", str(tmp_path))

    out_dir = tmp_path / "agy-design"
    out_dir.mkdir()
    (out_dir / "report.pdf").write_bytes(b"%PDF fake")

    preset = _make_preset_model(
        id="agy-design",
        name="agy-design",
        design_prompt_template="design_guidelines",
    )

    fake_result = type(
        "R",
        (),
        {
            "success": True,
            "artifact_path": out_dir / "artifact.txt",
            "herenow_url": None,
            "skill": "web-video-presentation",
            "model": None,
            "error": None,
            "errors": [],
        },
    )()
    mock_agy = AsyncMock(return_value=fake_result)

    with (
        patch("streamdoc.core.agy_upload.upload_to_agy", mock_agy),
        patch("streamdoc.presets.load_preset", return_value=preset),
    ):
        from streamdoc.cli_agy import agy_run

        result = CliRunner().invoke(agy_run, ["agy-design"])

    assert result.exit_code == 0, result.output
    assert mock_agy.call_count == 1
    design = mock_agy.call_args.kwargs["design_prompt"]
    expected = _design_prompt_for_preset(
        preset, _DEFAULT_AGY_CONTENT_TYPE
    )
    assert design is not None
    assert design != ""
    assert design == expected


def test_cli_agy_run_null_design_template_sends_none(
    monkeypatch, tmp_path
):
    """AC3: ``streamdoc agy run`` with no template passes design_prompt=None."""
    from click.testing import CliRunner

    from streamdoc.config import settings

    _isolate_template_dirs(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "output_root", str(tmp_path))

    out_dir = tmp_path / "agy-no-design"
    out_dir.mkdir()
    (out_dir / "report.pdf").write_bytes(b"%PDF fake")

    preset = _make_preset_model(
        id="agy-no-design",
        name="agy-no-design",
        design_prompt_template=None,
    )

    fake_result = type(
        "R",
        (),
        {
            "success": True,
            "artifact_path": out_dir / "artifact.txt",
            "herenow_url": None,
            "skill": "web-video-presentation",
            "model": None,
            "error": None,
            "errors": [],
        },
    )()
    mock_agy = AsyncMock(return_value=fake_result)

    with (
        patch("streamdoc.core.agy_upload.upload_to_agy", mock_agy),
        patch("streamdoc.presets.load_preset", return_value=preset),
    ):
        from streamdoc.cli_agy import agy_run

        result = CliRunner().invoke(agy_run, ["agy-no-design"])

    assert result.exit_code == 0, result.output
    assert mock_agy.call_count == 1
    assert mock_agy.call_args.kwargs["design_prompt"] is None
