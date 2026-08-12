"""Tests for the agy backend wiring in PresetRunner._send_reports.

Three required tests:

1. test_send_to_agy_populates_destinations — happy path: preset with agy enabled,
   upload succeeds, destinations dict is populated correctly.
2. test_send_to_agy_does_not_enter_when_agy_disabled — guard: agy in outputs but
   agy_enabled=False, neither backend is called.
3. test_send_reports_notebooklm_still_works — regression guard: notebooklm-only
   preset follows the existing NotebookLM code path, agy is NOT called.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_preset(**kwargs):
    """Construct a Preset model directly (no DB needed).

    Reason: Preset columns have SQLAlchemy defaults that only apply during
    DB INSERT, so we provide every field used by _send_reports explicitly
    here to avoid None surprises at runtime.
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
        "agy_enabled": False,
        "agy_skill": None,
        "agy_model": None,
        "agy_publish_herenow": False,
        "agy_prompt_template": None,
    }
    defaults.update(kwargs)
    return PresetModel(**defaults)


def _make_artifact(out_dir: Path, video_id: str = "v1") -> object:
    """Create a fake RunArtifact with a PDF on disk."""
    from streamdoc.core.fetch import RunArtifact

    pdf = out_dir / f"{video_id}.pdf"
    md = out_dir / f"{video_id}.md"
    pdf.write_bytes(b"%PDF fake")
    md.write_text("# md")
    return RunArtifact(
        video_id=video_id,
        md_path=md,
        pdf_path=pdf,
    )


# ---------------------------------------------------------------------------
# Test 1: happy path — agy enabled, upload succeeds
# ---------------------------------------------------------------------------

def test_send_to_agy_populates_destinations(monkeypatch, tmp_path):
    """_send_reports dispatches to agy and populates all destination keys."""
    from streamdoc.core.fetch import PresetRunner
    from streamdoc.config import settings

    monkeypatch.setattr(settings, "output_root", str(tmp_path))

    fake_preset = _make_preset(
        name="agytest",
        outputs="pdf,markdown,agy",
        agy_enabled=True,
        agy_skill="web-video-presentation",
        agy_publish_herenow=True,
    )

    out_dir = tmp_path / "agytest"
    out_dir.mkdir()
    artifact = _make_artifact(out_dir)

    art_path = tmp_path / "art.html"
    art_path.write_text("<html/>")

    # Reason: upload_to_agy is async; use AsyncMock so run_async receives a
    # proper coroutine and can schedule it on the shared event loop.
    fake_result = type("R", (), {
        "success": True,
        "herenow_url": "https://here.now/x",
        "artifact_path": art_path,
        "errors": [],
    })()

    mock_upload = AsyncMock(return_value=fake_result)

    with patch("streamdoc.core.agy_upload.upload_to_agy", mock_upload):
        runner = PresetRunner("test")
        dest = runner._send_reports(fake_preset, [artifact], "job-1")

    assert dest["agy"] == "success", f"Expected 'success', got: {dest.get('agy')}"
    assert dest["agy_herenow_url"] == "https://here.now/x"
    assert dest["agy_artifact_path"].endswith("art.html")
    # Confirm NotebookLM was NOT invoked (agy branch short-circuits)
    assert "notebooklm" not in dest


# ---------------------------------------------------------------------------
# Test 2: guard — agy in outputs but agy_enabled=False → no upload at all
# ---------------------------------------------------------------------------

def test_send_to_agy_does_not_enter_when_agy_disabled(monkeypatch, tmp_path):
    """When agy_enabled=False (and no notebooklm_kind), no backend is called."""
    from streamdoc.core.fetch import PresetRunner
    from streamdoc.config import settings

    monkeypatch.setattr(settings, "output_root", str(tmp_path))

    # Reason: agy is in outputs but disabled, and no notebooklm_kind is set.
    # The discriminator should find no valid backend and return {} immediately.
    fake_preset = _make_preset(
        name="nodest",
        outputs="pdf,agy",
        agy_enabled=False,
        notebooklm_kind=None,
    )

    out_dir = tmp_path / "nodest"
    out_dir.mkdir()
    artifact = _make_artifact(out_dir)

    mock_agy = AsyncMock()
    mock_nlm = AsyncMock()

    with patch("streamdoc.core.agy_upload.upload_to_agy", mock_agy), \
         patch("streamdoc.core.notebooklm_upload.upload_to_notebooklm", mock_nlm):
        runner = PresetRunner("test")
        dest = runner._send_reports(fake_preset, [artifact], "job-1")

    assert dest == {}, f"Expected empty dict, got: {dest}"
    assert mock_agy.call_count == 0, "upload_to_agy must NOT be called when agy_enabled=False"
    assert mock_nlm.call_count == 0, "upload_to_notebooklm must NOT be called"


# ---------------------------------------------------------------------------
# Test 3: regression — notebooklm-only preset still works, agy not called
# ---------------------------------------------------------------------------

def test_send_reports_notebooklm_still_works(monkeypatch, tmp_path):
    """Preset with only notebooklm in outputs follows the existing code path."""
    from streamdoc.core.fetch import PresetRunner
    from streamdoc.config import settings

    monkeypatch.setattr(settings, "output_root", str(tmp_path))

    fake_preset = _make_preset(
        name="nlmtest",
        outputs="pdf,markdown,notebooklm",
        notebooklm_kind="slide_deck",
        notebooklm_prompt_template=None,
        agy_enabled=False,
    )

    out_dir = tmp_path / "nlmtest"
    out_dir.mkdir()
    artifact = _make_artifact(out_dir, video_id="v2")

    # Reason: upload_to_notebooklm is async; AsyncMock returns an awaitable so
    # run_async can schedule it on the shared event loop.
    fake_nlm_result = type("R", (), {
        "success": True,
        "notebook_url": "https://notebooklm.example/nb1",
        "notebook_id": "nb1",
        "sources": [],
        "generated_content": [],
        "errors": [],
        "to_dict": lambda self: {},
    })()

    mock_nlm = AsyncMock(return_value=fake_nlm_result)
    mock_agy = AsyncMock()

    with patch("streamdoc.core.notebooklm_upload.upload_to_notebooklm", mock_nlm), \
         patch("streamdoc.core.agy_upload.upload_to_agy", mock_agy):
        runner = PresetRunner("test")
        dest = runner._send_reports(fake_preset, [artifact], "job-1")

    assert dest.get("notebooklm") == "success", f"Expected 'success', got: {dest}"
    assert mock_nlm.call_count == 1, "upload_to_notebooklm must be called exactly once"
    assert mock_agy.call_count == 0, "upload_to_agy must NOT be called for notebooklm-only preset"


# ---------------------------------------------------------------------------
# T6 spec-named tests (added alongside the existing T3 tests)
# ---------------------------------------------------------------------------
#
# Reason: the T6 acceptance criteria name the tests
# `test_send_to_agy_error_when_disabled` and
# `test_send_to_agy_notebooklm_still_works`. The existing T3 tests
# cover the same ground but with different names. We add the
# spec-named variants here (without removing the T3 ones) so both
# the T3 and T6 acceptance criteria are literally satisfied.

def test_send_to_agy_error_when_disabled(monkeypatch, tmp_path):
    """Spec-named: preset with agy in outputs but agy_enabled=False -> no agy call.

    Mirrors the T3 ``test_send_to_agy_does_not_enter_when_agy_disabled``
    test but with the spec's exact test name. When the preset
    specifies outputs containing "agy" but agy is disabled AND
    notebooklm_kind is unset, neither backend is invoked and the
    returned destinations dict is empty.
    """
    from streamdoc.core.fetch import PresetRunner
    from streamdoc.config import settings

    monkeypatch.setattr(settings, "output_root", str(tmp_path))

    fake_preset = _make_preset(
        name="disabledagy",
        outputs="pdf,markdown,agy",
        agy_enabled=False,
        notebooklm_kind=None,
    )

    out_dir = tmp_path / "disabledagy"
    out_dir.mkdir()
    artifact = _make_artifact(out_dir)

    mock_agy = AsyncMock()
    mock_nlm = AsyncMock()

    with patch("streamdoc.core.agy_upload.upload_to_agy", mock_agy), \
         patch("streamdoc.core.notebooklm_upload.upload_to_notebooklm", mock_nlm):
        runner = PresetRunner("test")
        dest = runner._send_reports(fake_preset, [artifact], "job-1")

    # No valid backend -> empty destinations.
    assert dest == {}, f"Expected empty destinations, got: {dest}"
    assert mock_agy.call_count == 0, "upload_to_agy must NOT be called when agy_enabled=False"
    assert mock_nlm.call_count == 0, "upload_to_notebooklm must NOT be called"


def test_send_to_agy_notebooklm_still_works(monkeypatch, tmp_path):
    """Spec-named: regression guard — notebooklm-only preset still works.

    Mirrors the T3 ``test_send_reports_notebooklm_still_works`` test
    but with the spec's exact test name. A preset with only
    ``notebooklm`` in its outputs follows the existing NotebookLM
    path; ``upload_to_agy`` is NOT called even when agy_enabled=True
    (because the outputs discriminator does not include "agy").
    """
    from streamdoc.core.fetch import PresetRunner
    from streamdoc.config import settings

    monkeypatch.setattr(settings, "output_root", str(tmp_path))

    fake_preset = _make_preset(
        name="nlmonly",
        outputs="pdf,markdown,notebooklm",
        notebooklm_kind="slide_deck",
        notebooklm_prompt_template=None,
        # Reason: set agy_enabled=True to make the regression guard
        # stronger — it proves the discriminator (not the flag) is
        # what routes the preset away from agy.
        agy_enabled=True,
    )

    out_dir = tmp_path / "nlmonly"
    out_dir.mkdir()
    artifact = _make_artifact(out_dir, video_id="v3")

    fake_nlm_result = type("R", (), {
        "success": True,
        "notebook_url": "https://notebooklm.example/nb3",
        "notebook_id": "nb3",
        "sources": [],
        "generated_content": [],
        "errors": [],
        "to_dict": lambda self: {},
    })()

    mock_nlm = AsyncMock(return_value=fake_nlm_result)
    mock_agy = AsyncMock()

    with patch("streamdoc.core.notebooklm_upload.upload_to_notebooklm", mock_nlm), \
         patch("streamdoc.core.agy_upload.upload_to_agy", mock_agy):
        runner = PresetRunner("test")
        dest = runner._send_reports(fake_preset, [artifact], "job-1")

    assert dest.get("notebooklm") == "success", f"Expected 'success', got: {dest}"
    assert mock_nlm.call_count == 1, "upload_to_notebooklm must be called exactly once"
    assert mock_agy.call_count == 0, (
        "upload_to_agy must NOT be called when outputs does not include 'agy'"
    )


# ---------------------------------------------------------------------------
# Existing-PDF fallback guard: don't upload stale reports when downloads failed
# ---------------------------------------------------------------------------


def test_send_to_agy_does_not_upload_stale_pdfs_when_downloads_failed(monkeypatch, tmp_path):
    """When candidates_attempted > 0 and artifacts is empty, stale PDFs are NOT uploaded to agy.

    Reason: if all downloads failed, the output directory may still contain
    PDFs from a previous successful run. Uploading those to agy would produce
    a presentation based on old content. The existing-PDF fallback in
    send_reports_to_agy must only trigger when candidates_attempted == 0.
    """
    from streamdoc.core.agy_upload import send_reports_to_agy
    from streamdoc.config import settings

    monkeypatch.setattr(settings, "output_root", str(tmp_path))

    fake_preset = _make_preset(
        name="agyStaleGuard",
        outputs="pdf,markdown,agy",
        agy_enabled=True,
        agy_skill="web-video-presentation",
    )

    out_dir = tmp_path / "agyStaleGuard"
    out_dir.mkdir()
    # Reason: stale PDFs from a previous run that should NOT be uploaded
    (out_dir / "old1.pdf").write_bytes(b"%PDF old")
    (out_dir / "old2.pdf").write_bytes(b"%PDF old")

    mock_upload = AsyncMock()

    with patch("streamdoc.core.agy_upload.upload_to_agy", mock_upload):
        dest = send_reports_to_agy(
            preset=fake_preset,
            artifacts=[],
            job_id="job-fail",
            prompt_template=None,
            custom_prompt="prompt",
            candidates_attempted=3,
        )

    assert not mock_upload.called, (
        "upload_to_agy must NOT be called when all downloads failed"
    )
    assert dest == {}, f"Expected empty destinations, got: {dest}"


def test_send_to_agy_uploads_existing_pdfs_when_all_already_processed(monkeypatch, tmp_path):
    """When candidates_attempted == 0 and artifacts is empty, existing PDFs ARE uploaded to agy.

    Reason: this is the intended re-upload path — all videos were already
    processed and the user re-runs to upload existing reports to agy.
    """
    from streamdoc.core.agy_upload import send_reports_to_agy
    from streamdoc.config import settings

    monkeypatch.setattr(settings, "output_root", str(tmp_path))

    fake_preset = _make_preset(
        name="agyReupload",
        outputs="pdf,markdown,agy",
        agy_enabled=True,
        agy_skill="web-video-presentation",
        agy_publish_herenow=False,
    )

    out_dir = tmp_path / "agyReupload"
    out_dir.mkdir()
    (out_dir / "v1.pdf").write_bytes(b"%PDF existing")
    (out_dir / "v2.pdf").write_bytes(b"%PDF existing")

    art_path = tmp_path / "art.html"
    art_path.write_text("<html/>")
    fake_result = type("R", (), {
        "success": True,
        "herenow_url": None,
        "artifact_path": art_path,
        "errors": [],
    })()
    mock_upload = AsyncMock(return_value=fake_result)

    with patch("streamdoc.core.agy_upload.upload_to_agy", mock_upload):
        dest = send_reports_to_agy(
            preset=fake_preset,
            artifacts=[],
            job_id="job-reupload",
            prompt_template=None,
            custom_prompt="prompt",
            candidates_attempted=0,
        )

    assert mock_upload.called, (
        "upload_to_agy should be called to re-upload existing reports"
    )
    assert dest.get("agy") == "success"
