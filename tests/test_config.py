import os
from pathlib import Path
import pytest
from streamdoc.config import Settings


def test_settings_defaults(tmp_path: Path):
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        Path(".env").write_text("STREAMDOC_SECRET_KEY=abc\n", encoding="utf-8")
        s = Settings()  # noqa: F841
    finally:
        os.chdir(orig_cwd)


def test_settings_env_prefix_applied(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STREAMDOC_NOTEBOOKLM_MODE", "cookies")
    monkeypatch.setenv("STREAMDOC_NOTEBOOKLM_ACCOUNT", "user@example.com")
    s = Settings()
    assert s.notebooklm_mode == "cookies"
    assert s.notebooklm_account == "user@example.com"
