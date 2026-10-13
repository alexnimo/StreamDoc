"""Tests for preset autoload import-once semantics.

Covers ``autoload_presets`` manifest behavior:
- Fresh install (no manifest) imports every file and writes the
  ``.autoloaded`` manifest.
- An unchanged file is skipped on the next run, so UI-side deletions and
  deactivations survive restarts instead of being clobbered.
- A file whose contents changed is re-imported.
- A newly added file is imported while unchanged files stay skipped.
- A file that fails to load is not marked imported (retries next run).
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import streamdoc.config
from streamdoc.db import init_db, session_scope
from streamdoc.models.preset import Preset
from streamdoc.presets import _AUTOLOAD_MANIFEST, autoload_presets, clone_preset


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path: Path):
    """Point the DB and presets dir at tmp_path.

    Mutates the shared ``settings`` object in place (same approach as
    test_e2e) so modules that bound it at import time see the new values.
    """
    presets_dir = tmp_path / "presets"
    presets_dir.mkdir()
    streamdoc.config.settings.db_path = str(tmp_path / "test.sqlite")
    streamdoc.config.settings.presets_path = str(presets_dir)

    import streamdoc.db as db_mod

    if db_mod._engine is not None:
        db_mod._engine.dispose()
        db_mod._engine = None
        db_mod._session_factory = None
    init_db()
    yield presets_dir
    if db_mod._engine is not None:
        db_mod._engine.dispose()
        db_mod._engine = None
        db_mod._session_factory = None


def _write_preset(path: Path, **overrides) -> None:
    """Write a minimal preset YAML file."""
    payload = {"name": path.stem, "channel_list_id": "fake://chan"}
    payload.update(overrides)
    path.write_text(yaml.dump(payload), encoding="utf-8")


def _db_preset(pid: str) -> Preset | None:
    with session_scope() as s:
        p = s.get(Preset, pid)
        return clone_preset(p) if p is not None else None


def _manifest_lines(presets_dir: Path) -> set[str]:
    manifest = presets_dir / _AUTOLOAD_MANIFEST
    assert manifest.exists(), "manifest was not written"
    return {
        line for line in manifest.read_text(encoding="utf-8").splitlines() if line.strip()
    }


def test_fresh_install_imports_and_writes_manifest(_isolated_env):
    presets_dir = _isolated_env
    _write_preset(presets_dir / "a.yaml")
    _write_preset(presets_dir / "b.yaml")

    loaded = autoload_presets()

    assert {p.id for p in loaded} == {"a", "b"}
    assert _db_preset("a") is not None
    assert _db_preset("b") is not None
    manifest = _manifest_lines(presets_dir)
    assert len(manifest) == 2
    assert {line.split("\t")[1] for line in manifest} == {"a.yaml", "b.yaml"}


def test_deleted_preset_is_not_resurrected(_isolated_env):
    """Deleting a preset in the DB survives the next autoload."""
    presets_dir = _isolated_env
    _write_preset(presets_dir / "a.yaml")
    autoload_presets()

    with session_scope() as s:
        s.delete(s.get(Preset, "a"))

    assert autoload_presets() == []
    assert _db_preset("a") is None


def test_deactivated_preset_stays_inactive(_isolated_env):
    """UI-side ``active=False`` is not overwritten by an unchanged file."""
    presets_dir = _isolated_env
    _write_preset(presets_dir / "a.yaml", active=True)
    autoload_presets()

    with session_scope() as s:
        s.get(Preset, "a").active = False

    assert autoload_presets() == []
    assert _db_preset("a").active is False


def test_changed_file_reimports(_isolated_env):
    """Editing the file on disk re-imports it (file wins on real change)."""
    presets_dir = _isolated_env
    path = presets_dir / "a.yaml"
    _write_preset(path, max_videos=5)
    autoload_presets()

    with session_scope() as s:
        s.get(Preset, "a").active = False

    _write_preset(path, max_videos=10)
    loaded = autoload_presets()

    assert [p.id for p in loaded] == ["a"]
    # File changed, so the whole file is re-upserted — including `active`.
    assert _db_preset("a").active is True
    assert _db_preset("a").max_videos == 10


def test_new_file_imported_while_unchanged_skipped(_isolated_env):
    presets_dir = _isolated_env
    _write_preset(presets_dir / "a.yaml")
    autoload_presets()

    _write_preset(presets_dir / "b.yaml")
    loaded = autoload_presets()

    assert [p.id for p in loaded] == ["b"]
    assert _db_preset("b") is not None


def test_failed_file_not_marked_imported(_isolated_env):
    """A file that fails to parse retries on the next run."""
    presets_dir = _isolated_env
    path = presets_dir / "broken.yaml"
    path.write_text("not-a-mapping: [unclosed", encoding="utf-8")

    assert autoload_presets() == []
    assert _db_preset("broken") is None

    _write_preset(path)
    loaded = autoload_presets()
    assert [p.id for p in loaded] == ["broken"]


def test_manifest_not_parsed_as_preset(_isolated_env):
    """The manifest itself must never be treated as a preset file."""
    presets_dir = _isolated_env
    _write_preset(presets_dir / "a.yaml")
    autoload_presets()
    assert (presets_dir / _AUTOLOAD_MANIFEST).exists()

    loaded = autoload_presets()
    assert loaded == []
    assert _db_preset(_AUTOLOAD_MANIFEST) is None
