"""Tests for POR-91 T2: design prompt threading in the fetch pipeline.

Covers:
- ``_design_prompt_for_preset`` renders ``preset.design_prompt_template`` via
  the NotebookLM PromptManager, returns None for NULL/blank, and degrades to
  None + a WARNING for unknown/invalid template names (never raises).
- ``PresetRunner._send_reports`` threads the rendered text as
  ``design_prompt=`` into ``upload_to_notebooklm`` and (via
  ``send_reports_to_agy``) into ``upload_to_agy``.
- The per-video ``_send_to_notebooklm`` path threads it too.
"""
from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


def _make_preset(**kwargs):
    """Construct a Preset model directly (no DB needed).

    Mirrors tests/test_fetch_agy.py::_make_preset.
    """
    from streamdoc.models.preset import Preset as PresetModel

    defaults = {
        "id": "test",
        "name": "Test",
        "channel_list_id": "",
        "prompt_md": "test prompt",
        "outputs": "pdf,markdown",
        "notebooklm_kind": None,
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


def _make_artifact(out_dir: Path, video_id: str = "v1"):
    from streamdoc.core.fetch import RunArtifact

    pdf = out_dir / f"{video_id}.pdf"
    md = out_dir / f"{video_id}.md"
    pdf.write_bytes(b"%PDF fake")
    md.write_text("# md")
    return RunArtifact(video_id=video_id, md_path=md, pdf_path=pdf)


def _isolate_template_dirs(monkeypatch, tmp_path):
    """Point the design-template PromptManager at empty tmp dirs.

    Reason: renders then come from in-memory DEFAULT_TEMPLATES only, so
    tests are deterministic and nothing is seeded into config/.
    """
    from streamdoc.config import settings

    monkeypatch.setattr(settings, "notebooklm_templates_dir", str(tmp_path / "tpl"))
    monkeypatch.setattr(
        settings, "notebooklm_sample_prompts_dir", str(tmp_path / "samples")
    )


# ---------------------------------------------------------------------------
# Helper-level tests
# ---------------------------------------------------------------------------


def test_design_prompt_for_preset_renders_template(monkeypatch, tmp_path):
    """A set design_prompt_template renders against the given content type."""
    from streamdoc.core.fetch import _design_prompt_for_preset
    from streamdoc.integrations.notebooklm.prompts import ContentType, PromptManager

    _isolate_template_dirs(monkeypatch, tmp_path)
    preset = _make_preset(design_prompt_template="design_guidelines")

    rendered = _design_prompt_for_preset(preset, ContentType.SLIDE_DECK)
    expected = PromptManager().render_prompt(
        "design_guidelines", ContentType.SLIDE_DECK
    )
    assert rendered == expected


def test_design_prompt_for_preset_null_and_blank(monkeypatch, tmp_path):
    """NULL or blank design_prompt_template returns None (off-by-default)."""
    from streamdoc.core.fetch import _design_prompt_for_preset
    from streamdoc.integrations.notebooklm.prompts import ContentType

    _isolate_template_dirs(monkeypatch, tmp_path)
    assert _design_prompt_for_preset(_make_preset(), ContentType.REPORT) is None
    assert (
        _design_prompt_for_preset(
            _make_preset(design_prompt_template="   "), ContentType.REPORT
        )
        is None
    )


def test_design_prompt_for_preset_unknown_template_warns(
    monkeypatch, tmp_path, caplog
):
    """AC3: unknown template name -> WARNING logged, None returned, no raise."""
    from streamdoc.core.fetch import _design_prompt_for_preset
    from streamdoc.integrations.notebooklm.prompts import ContentType

    _isolate_template_dirs(monkeypatch, tmp_path)
    preset = _make_preset(design_prompt_template="bogus_template_xyz")

    with caplog.at_level(logging.WARNING):
        rendered = _design_prompt_for_preset(preset, ContentType.REPORT)

    assert rendered is None
    assert (
        "design template 'bogus_template_xyz' unusable; skipping design injection"
        in caplog.text
    )


# ---------------------------------------------------------------------------
# fetch-level threading tests (mock the upload, capture kwargs)
# ---------------------------------------------------------------------------


def test_send_reports_threads_design_prompt_to_notebooklm(monkeypatch, tmp_path):
    """AC4: _send_reports passes the rendered design text to upload_to_notebooklm."""
    from streamdoc.core.fetch import PresetRunner
    from streamdoc.config import settings
    from streamdoc.integrations.notebooklm.prompts import ContentType, PromptManager

    monkeypatch.setattr(settings, "output_root", str(tmp_path))
    _isolate_template_dirs(monkeypatch, tmp_path)

    preset = _make_preset(
        name="nlmdesign",
        outputs="pdf,markdown,notebooklm",
        notebooklm_kind="slide_deck",
        design_prompt_template="design_guidelines",
    )
    out_dir = tmp_path / "nlmdesign"
    out_dir.mkdir()
    artifact = _make_artifact(out_dir)

    fake_result = type("R", (), {
        "success": True,
        "notebook_url": "https://nb.example/1",
        "notebook_id": "nb1",
        "sources": [],
        "generated_content": [],
        "errors": [],
    })()
    mock_nlm = AsyncMock(return_value=fake_result)

    with patch(
        "streamdoc.core.notebooklm_upload.upload_to_notebooklm", mock_nlm
    ):
        runner = PresetRunner("test")
        dest = runner._send_reports(preset, [artifact], "job-1")

    assert dest.get("notebooklm") == "success"
    assert mock_nlm.call_count == 1
    design = mock_nlm.call_args.kwargs["design_prompt"]
    expected = PromptManager().render_prompt(
        "design_guidelines", ContentType.SLIDE_DECK
    )
    assert design == expected


def test_send_reports_null_design_template_sends_none(monkeypatch, tmp_path):
    """AC4: NULL design_prompt_template -> design_prompt=None."""
    from streamdoc.core.fetch import PresetRunner
    from streamdoc.config import settings

    monkeypatch.setattr(settings, "output_root", str(tmp_path))
    _isolate_template_dirs(monkeypatch, tmp_path)

    preset = _make_preset(
        name="nlmnodesign",
        outputs="pdf,markdown,notebooklm",
        notebooklm_kind="slide_deck",
    )
    out_dir = tmp_path / "nlmnodesign"
    out_dir.mkdir()
    artifact = _make_artifact(out_dir)

    fake_result = type("R", (), {
        "success": True,
        "notebook_url": None,
        "notebook_id": "nb2",
        "sources": [],
        "generated_content": [],
        "errors": [],
    })()
    mock_nlm = AsyncMock(return_value=fake_result)

    with patch(
        "streamdoc.core.notebooklm_upload.upload_to_notebooklm", mock_nlm
    ):
        runner = PresetRunner("test")
        runner._send_reports(preset, [artifact], "job-2")

    assert mock_nlm.call_count == 1
    assert mock_nlm.call_args.kwargs["design_prompt"] is None


def test_send_reports_unknown_design_template_still_uploads(
    monkeypatch, tmp_path, caplog
):
    """AC3 end-to-end: bogus design template -> warning + design_prompt=None."""
    from streamdoc.core.fetch import PresetRunner
    from streamdoc.config import settings

    monkeypatch.setattr(settings, "output_root", str(tmp_path))
    _isolate_template_dirs(monkeypatch, tmp_path)

    preset = _make_preset(
        name="nlmbogus",
        outputs="pdf,markdown,notebooklm",
        notebooklm_kind="slide_deck",
        design_prompt_template="bogus_template_xyz",
    )
    out_dir = tmp_path / "nlmbogus"
    out_dir.mkdir()
    artifact = _make_artifact(out_dir)

    fake_result = type("R", (), {
        "success": True,
        "notebook_url": None,
        "notebook_id": "nb3",
        "sources": [],
        "generated_content": [],
        "errors": [],
    })()
    mock_nlm = AsyncMock(return_value=fake_result)

    with caplog.at_level(logging.WARNING):
        with patch(
            "streamdoc.core.notebooklm_upload.upload_to_notebooklm", mock_nlm
        ):
            runner = PresetRunner("test")
            runner._send_reports(preset, [artifact], "job-3")

    assert (
        "design template 'bogus_template_xyz' unusable; skipping design injection"
        in caplog.text
    )
    # Upload proceeds, with NO design injection.
    assert mock_nlm.call_count == 1
    assert mock_nlm.call_args.kwargs["design_prompt"] is None


def test_send_to_agy_threads_design_prompt(monkeypatch, tmp_path):
    """AC4: the agy path passes rendered design text into send_reports_to_agy."""
    from streamdoc.core.fetch import PresetRunner
    from streamdoc.config import settings
    from streamdoc.integrations.notebooklm.prompts import PromptManager

    monkeypatch.setattr(settings, "output_root", str(tmp_path))
    _isolate_template_dirs(monkeypatch, tmp_path)

    preset = _make_preset(
        name="agydesign",
        outputs="pdf,markdown,agy",
        agy_enabled=True,
        design_prompt_template="design_guidelines",
    )
    out_dir = tmp_path / "agydesign"
    out_dir.mkdir()
    artifact = _make_artifact(out_dir)

    mock_send = MagicMock(return_value={"agy": "success"})

    with patch("streamdoc.core.agy_upload.send_reports_to_agy", mock_send):
        runner = PresetRunner("test")
        dest = runner._send_reports(preset, [artifact], "job-4")

    assert dest.get("agy") == "success"
    assert mock_send.call_count == 1
    # agy renders against _DEFAULT_AGY_CONTENT_TYPE (ContentType.SLIDE_DECK).
    from streamdoc.core.agy_upload import _DEFAULT_AGY_CONTENT_TYPE

    expected = PromptManager().render_prompt(
        "design_guidelines", _DEFAULT_AGY_CONTENT_TYPE
    )
    assert mock_send.call_args.kwargs["design_prompt"] == expected


def test_send_to_agy_null_design_template_sends_none(monkeypatch, tmp_path):
    """AC4: NULL design_prompt_template on the agy path -> design_prompt=None."""
    from streamdoc.core.fetch import PresetRunner
    from streamdoc.config import settings

    monkeypatch.setattr(settings, "output_root", str(tmp_path))
    _isolate_template_dirs(monkeypatch, tmp_path)

    preset = _make_preset(
        name="agynodesign",
        outputs="pdf,markdown,agy",
        agy_enabled=True,
    )
    out_dir = tmp_path / "agynodesign"
    out_dir.mkdir()
    artifact = _make_artifact(out_dir)

    mock_send = MagicMock(return_value={"agy": "success"})

    with patch("streamdoc.core.agy_upload.send_reports_to_agy", mock_send):
        runner = PresetRunner("test")
        runner._send_reports(preset, [artifact], "job-5")

    assert mock_send.call_count == 1
    assert mock_send.call_args.kwargs["design_prompt"] is None


def test_per_video_upload_threads_design_prompt(monkeypatch, tmp_path):
    """AC4: _send_to_notebooklm passes rendered design text to the upload."""
    from streamdoc.core.fetch import _send_to_notebooklm
    from streamdoc.config import settings
    from streamdoc.integrations.notebooklm.prompts import ContentType, PromptManager

    _isolate_template_dirs(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "notebooklm_enabled", True)

    preset = _make_preset(
        name="pervideo",
        notebooklm_kind="slide_deck",
        design_prompt_template="design_guidelines",
    )
    md = tmp_path / "v9.md"
    md.write_text("# md")

    fake_result = type("R", (), {
        "success": True,
        "notebook_id": "nb9",
        "errors": [],
    })()
    mock_nlm = AsyncMock(return_value=fake_result)

    with patch(
        "streamdoc.core.notebooklm_upload.upload_to_notebooklm", mock_nlm
    ):
        assert _send_to_notebooklm(md, preset) is True

    assert mock_nlm.call_count == 1
    expected = PromptManager().render_prompt(
        "design_guidelines", ContentType.SLIDE_DECK
    )
    assert mock_nlm.call_args.kwargs["design_prompt"] == expected
