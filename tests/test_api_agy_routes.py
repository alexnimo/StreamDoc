"""Tests for the Antigravity (agy) management API routes (POR-27 T8).

These cover the HTTP surface that powers the Antigravity page:
- ``GET  /agy/status``               — installed / binary / version probe
- ``GET  /agy/skills``               — vendored skill inventory + install flags
- ``POST /agy/skills/install``       — copy one skill into the install dir
- ``POST /agy/skills/install-all``   — copy every vendored skill

The routes are a thin adapter over :mod:`streamdoc.integrations.agy`
(T2). We exercise them through FastAPI's ``TestClient`` against a
minimal app that mounts only the agy router — this avoids the full
``create_app()`` startup (scheduler, DB init, NotebookLM poller) which
is unrelated to this surface.

Discovery + skills functions are patched via ``monkeypatch.setattr`` so
the tests do not depend on the ``agy`` binary being installed on the
host. The skill-listing and install tests use the real vendored
``assets/skills/agy/`` directory and a tmp-path install dir.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from streamdoc.api.routes import agy as agy_route
from streamdoc.integrations.agy import SkillInfo
from streamdoc.integrations.agy import skills as agy_skills


def _build_app() -> FastAPI:
    """Build a minimal app with only the agy router mounted."""
    app = FastAPI()
    app.include_router(agy_route.router)
    return app


@pytest.fixture()
def client() -> TestClient:
    """TestClient wired to a minimal agy-only app (no startup side effects)."""
    return TestClient(_build_app())


# ---------------------------------------------------------------------------
# GET /agy/status
# ---------------------------------------------------------------------------
def test_agy_status_not_installed(client: TestClient) -> None:
    """When agy is not on PATH, status returns 200 with installed=False."""
    with patch.object(agy_route.discovery, "is_available", return_value=False):
        resp = client.get("/agy/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["installed"] is False
    assert body["binary"] is None
    assert body["agy_version"] is None
    assert body["install_url"] == "https://antigravity.google/docs/cli/install"


def test_agy_status_installed(client: TestClient) -> None:
    """When agy is on PATH, status returns 200 with the resolved binary + version."""
    with (
        patch.object(agy_route.discovery, "is_available", return_value=True),
        patch.object(
            agy_route.discovery, "find_agy_binary", return_value="/usr/local/bin/agy"
        ),
        patch.object(agy_route, "_probe_version", return_value="agy 0.4.2"),
    ):
        resp = client.get("/agy/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["installed"] is True
    assert body["binary"] == "/usr/local/bin/agy"
    assert body["agy_version"] == "agy 0.4.2"
    assert body["install_url"] == "https://antigravity.google/docs/cli/install"


# ---------------------------------------------------------------------------
# GET /agy/skills
# ---------------------------------------------------------------------------
def test_agy_skills_available_lists_selectable(client: TestClient) -> None:
    """The real vendored assets dir yields the two selectable skills.

    ``herenow-publish`` is a utility skill and is excluded from the
    available inventory used by the UI; ``install-all`` still installs it.
    """
    # Reason: point install_dir at a non-existent tmp path so none of the
    # vendored skills are considered installed. global_dir is also patched
    # to a non-existent path to avoid host state leaking into the test.
    # The skills module imports install_dir/global_dir as direct names from
    # the discovery module, so we patch them in the skills namespace.
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="agy_skills_test_"))
    with (
        patch.object(agy_route.skills, "install_dir", return_value=tmp),
        patch.object(agy_route.skills, "global_dir", return_value=tmp / "global"),
    ):
        resp = client.get("/agy/skills/available")
    assert resp.status_code == 200
    body = resp.json()
    names = {entry["name"] for entry in body}
    assert names == {
        "web-video-presentation",
        "web-design-engineer",
    }
    for entry in body:
        assert entry["available"] is True
        assert entry["installed"] is False


def test_agy_skills_lists_installed_only(client: TestClient, tmp_path: Path) -> None:
    """GET /agy/skills returns only installed skills and filters herenow-publish."""
    # Reason: install the web-video-presentation skill into the temp install dir;
    # the preset skill dropdown should only list installed selectable skills.
    # Patch global_dir to a non-existent path so host skills don't leak in.
    with (
        patch.object(agy_route.skills, "install_dir", return_value=tmp_path),
        patch.object(agy_route.skills, "global_dir", return_value=tmp_path / "global"),
    ):
        agy_route.skills.install("web-video-presentation", install_dir_override=tmp_path)
        resp = client.get("/agy/skills")
    assert resp.status_code == 200
    body = resp.json()
    names = {entry["name"] for entry in body}
    assert names == {"web-video-presentation"}
    for entry in body:
        assert entry["installed"] is True


# ---------------------------------------------------------------------------
# POST /agy/skills/install
# ---------------------------------------------------------------------------
def test_agy_skills_install_copies_folder(
    client: TestClient, tmp_path: Path
) -> None:
    """Installing one skill copies its folder (with SKILL.md) into the install dir."""
    with patch.object(agy_route.skills, "install_dir", return_value=tmp_path):
        resp = client.post("/agy/skills/install", json={"name": "web-video-presentation"})
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"installed": ["web-video-presentation"]}
    assert (tmp_path / "web-video-presentation" / "SKILL.md").exists()


def test_agy_skills_install_unknown_returns_404(
    client: TestClient, tmp_path: Path
) -> None:
    """Installing a name that isn't vendored returns HTTP 404 with a useful detail."""
    with patch.object(agy_route.skills, "install_dir", return_value=tmp_path):
        resp = client.post("/agy/skills/install", json={"name": "does-not-exist"})
    assert resp.status_code == 404
    assert "does-not-exist" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /agy/skills/install-all
# ---------------------------------------------------------------------------
def test_agy_skills_install_all_copies_everything(
    client: TestClient, tmp_path: Path
) -> None:
    """install-all copies every vendored skill into the install dir."""
    # Reason: T2's install_all() calls install() without force=True, so it
    # skips already-installed skills but still returns every available name.
    # Patch global_dir to a non-existent path so only the tmp install dir is
    # consulted for the "installed" set.
    with (
        patch.object(agy_route.skills, "install_dir", return_value=tmp_path),
        patch.object(agy_route.skills, "global_dir", return_value=tmp_path / "global"),
    ):
        resp = client.post("/agy/skills/install-all")
    assert resp.status_code == 200
    installed = set(resp.json()["installed"])
    assert installed == {
        "web-video-presentation",
        "web-design-engineer",
        "herenow-publish",
    }
    for name in installed:
        assert (tmp_path / name / "SKILL.md").exists()


# ---------------------------------------------------------------------------
# Sanity: the vendored assets dir actually exists with three skills.
# This guards against a partial checkout where T8's asset drop didn't land.
# ---------------------------------------------------------------------------
def test_vendored_skills_dir_has_selectable_skills() -> None:
    """The assets/skills/agy/ dir ships selectable skills, excluding the herenow utility."""
    entries = agy_skills.list_available()
    names = {e.name for e in entries}
    assert names == {
        "web-video-presentation",
        "web-design-engineer",
    }


def test_list_available_can_include_utility_skill() -> None:
    """``list_available(include_utility=True)`` exposes herenow-publish for install-all."""
    entries = agy_skills.list_available(include_utility=True)
    names = {e.name for e in entries}
    assert names == {
        "web-video-presentation",
        "web-design-engineer",
        "herenow-publish",
    }


# Silence the unused-import warning for SkillInfo (kept for documentation of
# the T2 surface these tests exercise).
_ = SkillInfo
