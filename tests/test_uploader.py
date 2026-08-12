"""Tests for upload bundling strategy."""
from __future__ import annotations

from pathlib import Path

import pytest

from streamdoc.config import Settings
from streamdoc.core.uploader import (
    UploadBundle,
    _bundle_combined,
    _bundle_individual,
    _bundle_smart,
    _collect_report_files,
    _combine_md_files,
    build_bundles,
)


@pytest.fixture(autouse=True)
def _patch_settings(monkeypatch):
    s = Settings()
    monkeypatch.setattr("streamdoc.core.uploader.settings", s)
    yield s


def test_collect_report_files(tmp_path: Path):
    (tmp_path / "a.md").write_text("# A")
    (tmp_path / "b.pdf").write_text("pdf")
    (tmp_path / "c.txt").write_text("text")
    files = _collect_report_files(tmp_path)
    assert len(files) == 2
    assert all(p.suffix in (".md", ".pdf") for p, _ in files)


def test_collect_report_files_text_only(tmp_path: Path, _patch_settings: Settings):
    _patch_settings.notebooklm_upload_text_only = True
    (tmp_path / "a.md").write_text("# A")
    (tmp_path / "b.pdf").write_text("pdf")
    files = _collect_report_files(tmp_path)
    assert len(files) == 1
    assert files[0][0].suffix == ".md"


def test_combine_md_files(tmp_path: Path):
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    a.write_text("# Section A")
    b.write_text("# Section B")
    out = tmp_path / "combined.md"
    _combine_md_files([a, b], out)
    text = out.read_text()
    assert "Section A" in text
    assert "Section B" in text


def test_bundle_individual():
    files = [(Path("a.md"), 100), (Path("b.md"), 200)]
    bundles = _bundle_individual(files)
    assert len(bundles) == 2
    assert bundles[0].paths == [Path("a.md")]


def test_bundle_combined(tmp_path: Path):
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    a.write_text("# A")
    b.write_text("# B")
    files = [(a, a.stat().st_size), (b, b.stat().st_size)]
    bundles = _bundle_combined(files, tmp_path)
    assert len(bundles) == 1
    assert bundles[0].paths[0].name == "combined_upload.md"


def test_bundle_smart_fits_individually(tmp_path: Path, _patch_settings: Settings):
    _patch_settings.notebooklm_max_bundle_files = 10
    _patch_settings.notebooklm_max_bundle_size_mb = 190
    files = [(tmp_path / f"f{i}.md", 100) for i in range(3)]
    for p, _ in files:
        p.write_text("# report")
    bundles = _bundle_smart(files, tmp_path)
    # All fit individually
    assert len(bundles) == 3
    assert all(len(b.paths) == 1 for b in bundles)


def test_bundle_smart_bundles_when_too_many_files(tmp_path: Path, _patch_settings: Settings):
    _patch_settings.notebooklm_max_bundle_files = 3
    _patch_settings.notebooklm_max_bundle_size_mb = 190
    files = [(tmp_path / f"f{i}.md", 100) for i in range(5)]
    for p, _ in files:
        p.write_text("# report")
    bundles = _bundle_smart(files, tmp_path)
    # Should bundle to stay within max files
    assert len(bundles) <= 3


def test_build_bundles_empty_dir(tmp_path: Path):
    bundles = build_bundles(tmp_path)
    assert bundles == []


def test_build_bundles_individual_mode(tmp_path: Path, _patch_settings: Settings):
    _patch_settings.notebooklm_upload_mode = "individual"
    (tmp_path / "a.md").write_text("# A")
    (tmp_path / "b.md").write_text("# B")
    bundles = build_bundles(tmp_path)
    assert len(bundles) == 2


def test_build_bundles_combined_mode(tmp_path: Path, _patch_settings: Settings):
    _patch_settings.notebooklm_upload_mode = "combined"
    (tmp_path / "a.md").write_text("# A")
    (tmp_path / "b.md").write_text("# B")
    bundles = build_bundles(tmp_path)
    assert len(bundles) == 1
    assert bundles[0].paths[0].name == "combined_upload.md"
