"""Skill inventory and install for the agy integration.

agy "skills" are plain folders containing a ``SKILL.md`` file (with
optional supporting files). They live in two places at runtime:

    1. ``<repo>/assets/skills/agy/<name>/``  — vendored, tracked in git.
    2. ``<install_dir>/<name>/``             — runtime copy (the default
       is ``.agents/skills/`` per the official agy docs).

The vendored assets are the source of truth (no network fetch at
install time — deterministic + offline-friendly per the POR-27 PRD
"Testing Decisions" section). :func:`install` is idempotent: a second
call with the same name is a no-op unless ``force=True`` is passed.

The smoke tests in :mod:`tests.test_agy_smoke` verify that
:func:`list_available` returns ``[]`` (not an exception) when the
vendored asset dir has not been shipped yet (T5 may not have landed),
and that :func:`install` raises :class:`FileNotFoundError` for a
genuinely missing skill.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from streamdoc.integrations.agy.discovery import global_dir, install_dir

logger = logging.getLogger(__name__)


@dataclass
class SkillInfo:
    """A single agy skill known to the system.

    Attributes:
        name: Skill folder name (e.g. ``"web-video-presentation"``).
        path: Absolute path to the skill folder.
        installed: True if this skill is present in the runtime install
            directory (or the global fallback). False if it only exists
            in the vendored assets dir and has not been installed yet.
    """

    name: str
    path: Path
    installed: bool = False
    source: str = "assets"  # "assets" | "install" | "global"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": str(self.path),
            "installed": self.installed,
            "source": self.source,
        }


# Reason: assets/skills/agy/ is a sibling of src/ at the repo root
# (assets/ sits at <repo>/assets/, parallel to <repo>/src/). When the
# package is installed editable (uv / pip -e), Path traversal from the
# source file is the only reliable way to find it — env-based paths
# break in CI / Docker where the workdir is not the repo root.
# parents[4] climbs: agy -> integrations -> streamdoc -> src -> <repo>.
_PACKAGE_PARENT = Path(__file__).resolve().parents[4]  # .../streamdoc/integrations/agy -> repo root
ASSETS_SKILLS_DIR: Path = _PACKAGE_PARENT / "assets" / "skills" / "agy"


def _scan_skill_dir(base: Path) -> list[SkillInfo]:
    """List every ``<name>/SKILL.md`` under ``base``.

    Missing directories yield ``[]`` (no exception) so the smoke tests
    can exercise :func:`list_available` on a clean checkout that has not
    yet received the T5 asset drop.
    """
    if not base.exists() or not base.is_dir():
        return []
    out: list[SkillInfo] = []
    for child in sorted(base.iterdir()):
        if not child.is_dir():
            continue
        if not (child / "SKILL.md").exists():
            # Reason: a folder without SKILL.md is not a valid agy
            # skill. Skip silently — could be a partial checkout or
            # operator scratch. The CLI itself would also reject it.
            continue
        out.append(SkillInfo(name=child.name, path=child.resolve()))
    return out


def _resolve_installed() -> set[str]:
    """Collect the set of skill names present in install + global dirs.

    Used to flip the ``installed`` flag on :class:`SkillInfo` entries
    coming from the assets dir.
    """
    found: set[str] = set()
    for d in (install_dir(), global_dir()):
        if d.exists() and d.is_dir():
            for child in d.iterdir():
                if child.is_dir() and (child / "SKILL.md").exists():
                    found.add(child.name)
    return found


def list_available(
    install_dir_override: Path | None = None,
    include_utility: bool = False,
) -> list[SkillInfo]:
    """Return the inventory of skills shipped in ``assets/skills/agy/``.

    Each entry is annotated with ``installed=True`` if the same name is
    also present in the install dir (or the global fallback dir).
    Returns ``[]`` (not an exception) if the assets dir does not exist
    on this host — the runtime can still function, it just has no skills
    to install until the T5 asset drop lands.

    Utility skills such as ``herenow-publish`` are excluded by default
    because the UI exposes dedicated toggles for them.
    """
    installed = _resolve_installed()
    entries = _scan_skill_dir(ASSETS_SKILLS_DIR)
    out: list[SkillInfo] = []
    for entry in entries:
        if entry.name == _HERENOW_SKILL and not include_utility:
            continue
        entry.installed = entry.name in installed
        entry.source = "assets"
        out.append(entry)
    return out


def list_installed(install_dir_override: Path | None = None) -> list[SkillInfo]:
    """Return the skills currently present in the install / global dirs.

    Dedupes by name; the install dir wins over the global dir when the
    same name appears in both. Each entry has ``installed=True``.
    """
    primary = install_dir_override or install_dir()
    by_name: dict[str, SkillInfo] = {}

    if primary.exists() and primary.is_dir():
        for child in sorted(primary.iterdir()):
            if child.is_dir() and (child / "SKILL.md").exists():
                by_name[child.name] = SkillInfo(
                    name=child.name,
                    path=child.resolve(),
                    installed=True,
                    source="install",
                )

    gd = global_dir()
    if gd.exists() and gd.is_dir() and gd != primary:
        for child in sorted(gd.iterdir()):
            if not (child.is_dir() and (child / "SKILL.md").exists()):
                continue
            if child.name in by_name:
                continue
            by_name[child.name] = SkillInfo(
                name=child.name,
                path=child.resolve(),
                installed=True,
                source="global",
            )

    return list(by_name.values())


# Reason: herenow-publish is a special utility skill invoked automatically
# when the ``agy_publish_herenow`` flag is set. It should not appear in the
# skill selection dropdown because the UI exposes a dedicated here.now
# publish toggle instead.
_HERENOW_SKILL = "herenow-publish"


def list_selectable_skills(install_dir_override: Path | None = None) -> list[SkillInfo]:
    """Return installed skills suitable for the preset skill dropdown.

    Only includes skills that are shipped as vendored agy skills and are
    already installed locally. This prevents generic agent skills that
    happen to live under ``.agents/skills/`` from appearing in the
    Antigravity skill selector, and also excludes the here.now publish
    utility skill because the UI exposes a dedicated toggle for it.
    """
    return [s for s in list_available(install_dir_override=install_dir_override) if s.installed]


def is_herenow_installed(install_dir_override: Path | None = None) -> bool:
    """Return True if the herenow-publish skill is installed locally."""
    installed = {s.name for s in list_installed(install_dir_override=install_dir_override)}
    return _HERENOW_SKILL in installed


def find_skill(name: str, install_dir_override: Path | None = None) -> SkillInfo | None:
    """Return a skill by name if it is installed, else None.

    Searches the install dir first, then the global fallback dir. The
    path returned can be passed to the agy CLI ``--skill`` flag.
    """
    primary = install_dir_override or install_dir()
    for base in (primary, global_dir()):
        if not base.exists() or not base.is_dir():
            continue
        candidate = base / name
        if candidate.is_dir() and (candidate / "SKILL.md").exists():
            return SkillInfo(
                name=name,
                path=candidate.resolve(),
                installed=True,
                source="install" if base == primary else "global",
            )
    return None


def install(
    name: str,
    install_dir_override: Path | None = None,
    force: bool = False,
) -> Path:
    """Copy ``assets/skills/agy/<name>/`` into the install dir.

    Idempotent: if the destination already exists, the function is a
    no-op unless ``force=True`` (in which case the destination is
    replaced via :func:`shutil.copytree` with ``dirs_exist_ok=True`).

    Args:
        name: Skill folder name (must be a child of ``ASSETS_SKILLS_DIR``).
        install_dir_override: Optional override for the destination
            directory. Defaults to :func:`install_dir`.
        force: Replace the destination if it already exists.

    Returns:
        Absolute path to the installed skill folder.

    Raises:
        FileNotFoundError: if the source skill is missing from both
            ``ASSETS_SKILLS_DIR`` and the installed skill directories.
    """
    dest_dir = install_dir_override or install_dir()
    dest = dest_dir / name

    # Reason: skill is already installed (possibly from the global
    # dir). Do not re-copy unless force=True.
    if dest.exists() and not force:
        logger.info("agy skill %r already installed at %s; skipping", name, dest)
        return dest

    # Reason: operator may have installed a skill manually; treat that
    # as satisfied without requiring the vendored asset.
    existing = find_skill(name, install_dir_override=install_dir_override)
    if existing and not force:
        logger.info("agy skill %r found at %s; skipping copy", name, existing.path)
        return existing.path

    src = ASSETS_SKILLS_DIR / name
    if not src.exists() or not src.is_dir():
        raise FileNotFoundError(
            f"agy skill {name!r} not found in {ASSETS_SKILLS_DIR}"
        )
    if not (src / "SKILL.md").exists():
        raise FileNotFoundError(
            f"agy skill {name!r} at {src} is missing SKILL.md"
        )

    dest_dir.mkdir(parents=True, exist_ok=True)

    if dest.exists():
        # Reason: force=True — wipe and replace. shutil.rmtree first so
        # copytree doesn't merge an older revision with the new one
        # (dirs_exist_ok=True is fine for additive files but cannot
        # remove stale files left behind by a previous version).
        shutil.rmtree(dest)

    shutil.copytree(src, dest)
    logger.info("installed agy skill %r -> %s", name, dest)
    return dest


def install_all(
    install_dir_override: Path | None = None,
) -> list[Path]:
    """Install every skill under ``ASSETS_SKILLS_DIR``.

    Returns the list of successfully installed destination paths (in the
    order they were scanned). Individual install failures are logged and
    skipped so a single broken skill does not block the others. If the
    assets dir is missing entirely, returns ``[]`` silently (T5 may not
    have shipped assets yet).
    """
    installed: list[Path] = []
    for entry in list_available(include_utility=True):
        try:
            dest = install(entry.name, install_dir_override=install_dir_override)
            installed.append(dest)
        except FileNotFoundError as exc:
            logger.warning("skipping agy skill %r: %s", entry.name, exc)
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("failed to install agy skill %r: %s", entry.name, exc)
    return installed


def update(
    name: str | None = None,
    install_dir_override: Path | None = None,
) -> Path | list[Path]:
    """Re-install one skill (or every skill) from the vendored assets.

    Thin alias for :func:`install` with ``force=True``:

        update()             -> install_all() (returns list[Path])
        update("foo")        -> install("foo", force=True) (returns Path)

    The return type widens to ``Path | list[Path]`` for the convenience
    of CLI surfaces that want to print a one-line summary.
    """
    if name is None:
        return install_all(install_dir_override=install_dir_override)
    return install(name, install_dir_override=install_dir_override, force=True)


# Reason: parse the "repo--skill name" syntax from
# settings.agy_skills_update_sources. Each entry is a source spec for
# the `npx skills add` command. The delimiter is "--" so the repo can
# contain hyphens (e.g. "heredotnow/skill--skill here-now").
_SOURCE_RE = re.compile(r"^(?P<repo>\S+)\s*--\s*skill\s+(?P<skill>\S+)$")


def _parse_update_sources(raw: str) -> list[tuple[str, str]]:
    """Parse the comma-separated update-sources setting into (repo, skill) pairs.

    Each entry has the form ``"<github-repo>--skill <skill-name>"``.
    Malformed entries are logged and skipped.
    """
    pairs: list[tuple[str, str]] = []
    for entry in (raw or "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        match = _SOURCE_RE.match(entry)
        if match:
            pairs.append((match.group("repo"), match.group("skill")))
        else:
            logger.warning("malformed agy skill update source %r; skipping", entry)
    return pairs


def update_from_upstream(
    sources: str | None = None,
    timeout: float = 120.0,
) -> list[str]:
    """Fetch the latest skill revisions from upstream via ``npx skills add``.

    For each source in ``sources`` (or :attr:`settings.agy_skills_update_sources`
    when omitted), runs ``npx -y skills add <repo> --skill <name>`` in a
    temp directory, then copies the downloaded skill folder into the
    vendored assets directory (``assets/skills/agy/<name>/``) so the next
    :func:`install_all` picks up the fresh copy.

    Args:
        sources: Comma-separated source specs (``"repo--skill name"``).
            Defaults to ``settings.agy_skills_update_sources``.
        timeout: Per-source timeout in seconds for the npx subprocess.

    Returns:
        List of skill names that were successfully updated.
    """
    from streamdoc.config import settings

    raw = sources if sources is not None else settings.agy_skills_update_sources
    pairs = _parse_update_sources(raw)
    if not pairs:
        logger.info("no agy skill update sources configured; skipping upstream update")
        return []

    updated: list[str] = []
    for repo, skill_name in pairs:
        try:
            updated.append(_fetch_skill_via_npx(repo, skill_name, timeout))
        except Exception as exc:
            logger.warning(
                "failed to update agy skill %r from %s: %s",
                skill_name, repo, exc,
            )
    return updated


def _fetch_skill_via_npx(repo: str, skill_name: str, timeout: float) -> str:
    """Fetch the latest skill revision from upstream and vendor it.

    Uses ``git clone --depth 1`` to fetch the repo (non-interactive,
    works on all platforms), then locates the skill folder by name and
    copies it into ``ASSETS_SKILLS_DIR/<vendored_name>/``.

    The ``npx skills add`` CLI is interactive (it prompts for agent
    selection via a TUI), so it cannot be used in a headless
    server/startup context. Git clone is the reliable non-interactive
    alternative — the skill repos are plain GitHub repos with a
    predictable ``<skill_name>/SKILL.md`` layout.

    When the upstream skill name differs from the vendored name (e.g.
    upstream ``here-now`` → vendored ``herenow-publish``), the upstream
    ``scripts/`` directory is merged into the existing vendored skill
    folder, preserving our custom ``SKILL.md`` while updating the
    bundled helper scripts (``publish.sh``, ``drive.sh``).

    Raises on any subprocess failure or if the downloaded skill folder
    cannot be located after the clone completes.
    """
    # Reason: map upstream skill names to our vendored skill names so
    # the upstream update refreshes the existing skill's scripts rather
    # than creating a duplicate folder. The key is the upstream name;
    # the value is the vendored name in assets/skills/agy/.
    UPSTREAM_TO_VENDORED = {
        "here-now": "herenow-publish",
    }
    vendored_name = UPSTREAM_TO_VENDORED.get(skill_name, skill_name)

    with tempfile.TemporaryDirectory(prefix="agy-skill-update-") as tmp:
        tmp_path = Path(tmp)
        clone_url = f"https://github.com/{repo}.git"
        cmd = ["git", "clone", "--depth", "1", clone_url, str(tmp_path / "repo")]
        logger.info("running %s", " ".join(cmd))
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            stdin=subprocess.DEVNULL,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode != 0:
            stderr = (proc.stderr or "")[:512]
            raise RuntimeError(
                f"git clone {clone_url} failed (exit {proc.returncode}): {stderr}"
            )

        repo_path = tmp_path / "repo"
        skill_folder = _find_downloaded_skill(repo_path, skill_name)
        if skill_folder is None:
            raise RuntimeError(
                f"could not locate skill {skill_name!r} in cloned repo {repo}"
            )

        dest = ASSETS_SKILLS_DIR / vendored_name
        ASSETS_SKILLS_DIR.mkdir(parents=True, exist_ok=True)

        if vendored_name != skill_name and dest.exists():
            # Reason: the upstream skill has a different name than our
            # vendored copy (e.g. here-now → herenow-publish). We merge
            # only the scripts/ subdirectory from upstream, preserving
            # our custom SKILL.md (which has the Published: convention
            # the parser depends on).
            upstream_scripts = skill_folder / "scripts"
            if upstream_scripts.exists():
                dest_scripts = dest / "scripts"
                if dest_scripts.exists():
                    shutil.rmtree(dest_scripts)
                shutil.copytree(upstream_scripts, dest_scripts)
                logger.info(
                    "merged upstream scripts/ into vendored agy skill %r from %s",
                    vendored_name, repo,
                )
            else:
                logger.warning(
                    "upstream skill %r has no scripts/ dir; skipping merge into %r",
                    skill_name, vendored_name,
                )
        else:
            # Reason: same name or new skill — replace the entire folder.
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(skill_folder, dest)
            logger.info(
                "updated vendored agy skill %r from upstream %s",
                vendored_name, repo,
            )
        return vendored_name


def _find_downloaded_skill(base: Path, skill_name: str) -> Path | None:
    """Search for a downloaded skill folder by name under ``base``.

    Looks for a directory named ``skill_name`` containing ``SKILL.md``,
    searching recursively up to 3 levels deep. Returns the path or None.
    """
    # Reason: direct match — the most common layout is
    # <cwd>/<skill_name>/SKILL.md or <cwd>/skills/<skill_name>/SKILL.md
    for candidate in [
        base / skill_name,
        base / "skills" / skill_name,
        base / ".agents" / "skills" / skill_name,
    ]:
        if (candidate / "SKILL.md").exists():
            return candidate
    # Reason: recursive search as a fallback for non-standard layouts.
    for skill_md in base.rglob("SKILL.md"):
        if skill_md.parent.name == skill_name:
            return skill_md.parent
    # Reason: if there's only one SKILL.md in the tree, assume it's the
    # one we just downloaded (the temp dir was empty before npx ran).
    all_skills = list(base.rglob("SKILL.md"))
    if len(all_skills) == 1:
        return all_skills[0].parent
    return None


__all__ = [
    "ASSETS_SKILLS_DIR",
    "SkillInfo",
    "find_skill",
    "install",
    "install_all",
    "is_herenow_installed",
    "list_available",
    "list_installed",
    "list_selectable_skills",
    "update",
    "update_from_upstream",
]
