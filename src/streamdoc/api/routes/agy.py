"""Antigravity (agy) CLI management routes.

These routes power the Antigravity management page: they let an operator
check whether the ``agy`` binary is installed, inspect the vendored skill
inventory, and copy skills into the runtime install directory.

The heavy lifting (binary discovery, skill folder scanning, file copies)
lives in :mod:`streamdoc.integrations.agy` (T2). This module is a thin
HTTP adapter over that package — it never shells out to ``agy`` except
for the read-only ``agy --version`` probe in :func:`status`.
"""
from __future__ import annotations

import logging
import subprocess
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from streamdoc.api.schemas import (
    AgyModelsOut,
    AgySkillInfo,
    AgySkillInstallRequest,
    AgySkillInstallResponse,
    AgyStatusOut,
)
from streamdoc.config import settings
from streamdoc.integrations.agy import discovery, skills
from streamdoc.integrations.agy import list_models as agy_list_models
from streamdoc.integrations.agy.skills import update_from_upstream as agy_update_from_upstream

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agy", tags=["agy"])

# Reason: 5s is plenty for a local `agy --version` probe; any longer
# suggests the binary is hanging on a network call or interactive
# prompt, in which case we'd rather surface "version unknown" than
# block the UI.
_VERSION_TIMEOUT_S = 5.0


def _probe_version(binary: str) -> str | None:
    """Run ``<binary> --version`` and return the first trimmed line.

    Never raises — any failure (non-zero exit, timeout, missing binary)
    maps to ``None`` so the status endpoint can stay 200.
    """
    if binary == "npx":
        cmd = ["npx", "-y", discovery.npm_package(), "--version"]
    else:
        cmd = [binary, "--version"]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_VERSION_TIMEOUT_S,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        logger.debug("agy version probe failed: %s", exc)
        return None
    out = (proc.stdout or proc.stderr or "").strip()
    if not out:
        return None
    return out.splitlines()[0].strip() or None


@router.get("/status", response_model=AgyStatusOut)
async def status() -> AgyStatusOut:
    """Report whether the agy CLI is installed on this host.

    Always returns HTTP 200 — the UI needs a "not installed" state to
    render its hint card, so we never 5xx here.
    """
    install_url = discovery.install_url()
    if not discovery.is_available():
        return AgyStatusOut(
            installed=False,
            binary=None,
            agy_version=None,
            install_url=install_url,
        )
    binary = discovery.find_agy_binary()
    return AgyStatusOut(
        installed=True,
        binary=binary,
        agy_version=_probe_version(binary) if binary else None,
        install_url=install_url,
    )


@router.get("/skills", response_model=list[AgySkillInfo])
async def list_skills() -> list[AgySkillInfo]:
    """List installed agy skills suitable for preset selection.

    Returns only skills that are already installed locally and filters
    out the ``herenow-publish`` utility skill because the UI exposes a
    dedicated here.now publish toggle. Use the Antigravity Skills tab to
    install additional skills from the vendored assets.
    """
    entries = skills.list_selectable_skills()
    out: list[AgySkillInfo] = []
    for entry in entries:
        out.append(
            AgySkillInfo(
                name=entry.name,
                available=True,
                installed=True,
            )
        )
    out.sort(key=lambda s: s.name)
    return out


@router.get("/skills/available", response_model=list[AgySkillInfo])
async def list_available_skills() -> list[AgySkillInfo]:
    """List all vendored agy skills with their install status.

    This is the inventory used by the Antigravity Skills tab. It includes
    skills that are not yet installed so the operator can install them.
    """
    entries = skills.list_available()
    out: list[AgySkillInfo] = []
    for entry in entries:
        out.append(
            AgySkillInfo(
                name=entry.name,
                available=True,
                installed=entry.installed,
            )
        )
    out.sort(key=lambda s: s.name)
    return out


@router.post("/skills/install", response_model=AgySkillInstallResponse)
async def install_skill(body: AgySkillInstallRequest) -> AgySkillInstallResponse:
    """Copy one vendored skill into the install directory.

    Raises 404 if the named skill is not in the vendored assets dir;
    500 for any other failure.
    """
    try:
        skills.install(body.name, force=True)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Skill not found: {body.name}")
    except Exception as exc:
        logger.exception("agy skill install failed for %r", body.name)
        raise HTTPException(status_code=500, detail=str(exc))
    return AgySkillInstallResponse(installed=[body.name])


@router.post("/skills/install-all", response_model=AgySkillInstallResponse)
async def install_all_skills() -> AgySkillInstallResponse:
    """Copy every vendored skill into the install directory.

    Returns the list of names installed (empty if nothing is available).
    """
    try:
        installed_paths = skills.install_all()
    except Exception as exc:
        logger.exception("agy install-all failed")
        raise HTTPException(status_code=500, detail=str(exc))
    return AgySkillInstallResponse(installed=[p.name for p in installed_paths])


@router.post("/skills/update-from-upstream", response_model=AgySkillInstallResponse)
async def update_skills_from_upstream() -> AgySkillInstallResponse:
    """Fetch the latest skill revisions from upstream via ``npx skills add``.

    Runs the configured update sources (``agy_skills_update_sources``)
    to download fresh skill folders, vendors them into
    ``assets/skills/agy/``, then re-installs all skills into the runtime
    install directory. This is the manual "Update from upstream" path;
    the automatic path runs on startup when ``agy_skills_auto_update``
    is True.
    """
    try:
        updated = agy_update_from_upstream()
        # Reason: re-install the freshly-vendored skills so the runtime
        # install dir picks up the new copies immediately.
        if updated:
            skills.install_all()
    except Exception as exc:
        logger.exception("agy skills upstream update failed")
        raise HTTPException(status_code=500, detail=str(exc))
    return AgySkillInstallResponse(installed=updated)


@router.get("/models", response_model=AgyModelsOut)
async def get_models() -> AgyModelsOut:
    """Return the list of models supported by the installed agy CLI.

    Probes the agy CLI for its model list and falls back to the
    operator-configured allowlist (``agy_supported_models``) or a
    conservative static default when the CLI is not installed.
    """
    return AgyModelsOut(models=agy_list_models())


class AgyReportFile(BaseModel):
    """A single available report file for the existing-report picker."""

    name: str
    path: str
    size_bytes: int
    modified: str


@router.get("/reports/{preset_name}", response_model=list[AgyReportFile])
async def list_preset_reports(preset_name: str) -> list[AgyReportFile]:
    """List report files (PDF/MD) available for a preset.

    Scans ``<output_root>/<preset_name>/`` for ``.pdf`` and ``.md`` files
    so the preset form's "use an existing report" picker can offer the
    operator a choice without re-running the fetch pipeline. Returns an
    empty list when the directory does not exist yet.
    """
    out_dir = Path(settings.output_root) / preset_name
    if not out_dir.exists() or not out_dir.is_dir():
        return []
    reports: list[AgyReportFile] = []
    for p in sorted(out_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if not p.is_file() or p.suffix.lower() not in (".pdf", ".md"):
            continue
        stat = p.stat()
        reports.append(
            AgyReportFile(
                name=p.name,
                path=str(p),
                size_bytes=stat.st_size,
                modified=datetime.fromtimestamp(stat.st_mtime).isoformat(),
            )
        )
    return reports
