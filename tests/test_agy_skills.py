"""Unit tests for :mod:`streamdoc.integrations.agy.skills`.

These tests exercise the skill inventory and install helpers without
invoking any external CLI or network. They assume the vendored skills
under ``assets/skills/agy/`` are shipped (POR-27 T5).
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest


EXPECTED_SKILL_NAMES = {
    "web-video-presentation",
    "web-design-engineer",
}


EXPECTED_ALL_SKILL_NAMES = EXPECTED_SKILL_NAMES | {"herenow-publish"}


def test_list_available_returns_shipped_skills(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When shipped assets exist, list_available returns the selectable skills."""
    import streamdoc.integrations.agy.skills as skills_mod

    # Reason: real install/global dirs may contain these skills from prior
    # runs; force the "installed" set to empty so the assertion is stable.
    monkeypatch.setattr(skills_mod, "_resolve_installed", lambda: set())

    skills = skills_mod.list_available()
    names = {s.name for s in skills}
    assert names == EXPECTED_SKILL_NAMES, f"unexpected skill inventory: {names}"
    assert all(isinstance(s, skills_mod.SkillInfo) for s in skills)
    assert all(s.installed is False for s in skills)
    assert all(s.source == "assets" for s in skills)


def test_list_available_include_utility_returns_all_skills(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``list_available(include_utility=True)`` exposes herenow-publish for install-all."""
    import streamdoc.integrations.agy.skills as skills_mod

    monkeypatch.setattr(skills_mod, "_resolve_installed", lambda: set())

    skills = skills_mod.list_available(include_utility=True)
    names = {s.name for s in skills}
    assert names == EXPECTED_ALL_SKILL_NAMES, f"unexpected skill inventory: {names}"


def test_install_copies_skill_to_install_dir(tmp_path: Path) -> None:
    """install() copies the vendored skill files to the install dir."""
    import streamdoc.integrations.agy.skills as skills_mod

    install_dir = tmp_path / "skills"
    dest = skills_mod.install(
        "web-video-presentation",
        install_dir_override=install_dir,
    )

    assert dest == install_dir / "web-video-presentation"
    installed_skill = dest / "SKILL.md"
    assert installed_skill.exists()

    source_skill = skills_mod.ASSETS_SKILLS_DIR / "web-video-presentation" / "SKILL.md"
    assert installed_skill.read_text(encoding="utf-8") == source_skill.read_text(
        encoding="utf-8"
    )


def test_install_idempotent(tmp_path: Path) -> None:
    """Repeated installs are no-ops unless force=True."""
    import streamdoc.integrations.agy.skills as skills_mod

    install_dir = tmp_path / "skills"
    dest_file = install_dir / "web-video-presentation" / "SKILL.md"

    skills_mod.install("web-video-presentation", install_dir_override=install_dir)
    first_mtime = dest_file.stat().st_mtime

    # Second install without force should be a no-op.
    skills_mod.install("web-video-presentation", install_dir_override=install_dir)
    assert dest_file.stat().st_mtime == first_mtime

    # Force a measurable mtime delta, then verify force=True re-copies.
    # Reason: on Windows, FAT/NTFS mtime resolution can be as coarse as
    # 2s; pushing the timestamp into the future guarantees the file
    # actually gets replaced rather than coincidentally keeping the
    # same mtime.
    now = time.time()
    os.utime(dest_file, (now + 2, now + 2))
    bumped_mtime = dest_file.stat().st_mtime

    skills_mod.install(
        "web-video-presentation",
        install_dir_override=install_dir,
        force=True,
    )
    assert dest_file.stat().st_mtime != bumped_mtime


def test_install_missing_source_raises_filenotfound(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """install() raises FileNotFoundError when the source skill is missing."""
    import streamdoc.integrations.agy.skills as skills_mod

    empty_skills = tmp_path / "empty_skills"
    empty_skills.mkdir()
    monkeypatch.setattr(skills_mod, "ASSETS_SKILLS_DIR", empty_skills)

    with pytest.raises(FileNotFoundError):
        skills_mod.install(
            "nonexistent",
            install_dir_override=tmp_path / "skills",
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
