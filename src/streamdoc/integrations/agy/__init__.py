"""Antigravity (agy) integration for StreamDoc.

This package provides integration with the Google Antigravity CLI ("agy"),
a local CLI that runs a "skill" (a folder containing ``SKILL.md``) under
a chosen model and produces an HTML artifact. agy is a sibling generation
backend to the existing NotebookLM integration; StreamDoc owns the skill
installation, prompt plumbing, and here.now publish step, but the
operator installs the agy binary itself.

Public surface (mirrors :mod:`streamdoc.integrations.notebooklm`):

    from streamdoc.integrations.agy import (
        # availability + discovery
        AGYAvailable, find_agy_binary, is_available, install_dir,
        # exceptions
        AGYIntegrationError, AGYNotInstalledError,
        AGYInvocationError, AGYPublishError,
        # skill manager
        SkillInfo, list_available, list_installed,
        install, install_all, update,
        # runner
        AgyRunResult, run_skill, parse_artifact_path,
        # here.now publish
        HerenowResult, publish, parse_published_url,
    )

CLI source of truth:
    https://antigravity.google/docs/cli/using

(When the docs surface a different CLI surface, update
``_build_command`` in :mod:`streamdoc.integrations.agy.runner`.)
"""

# Note: the four agy submodules (discovery, exceptions, runner, skills,
# herenow) are imported by their explicit `from ... import (...)`
# statements below. We intentionally do NOT pre-import them as
# `from streamdoc.integrations.agy import discovery, herenow, runner,
# skills` because ruff flags the imports as unused (the re-exports
# below are what callers actually use). Callers that need to monkey-
# patch the submodule itself (e.g. `monkeypatch.setattr(agy.discovery,
# "find_agy_binary", ...)`) should import it explicitly.
from streamdoc.integrations.agy.discovery import (
    find_agy_binary,
    global_dir,
    install_dir,
    install_url,
    is_available,
    npm_package,
)
from streamdoc.integrations.agy.exceptions import (
    AGYIntegrationError,
    AGYInvocationError,
    AGYNotInstalledError,
    AGYPublishError,
)
from streamdoc.integrations.agy.herenow import (
    HerenowResult,
    parse_published_url,
    publish,
)
from streamdoc.integrations.agy.runner import (
    AgyRunResult,
    list_models,
    parse_artifact_path,
    resolve_agy_model,
    run_skill,
)
from streamdoc.integrations.agy.skills import (
    SkillInfo,
    install,
    install_all,
    list_available,
    list_installed,
    update,
)

# Re-export PromptManager from the notebooklm prompts module so callers
# don't have to import the sibling package just to render a template.
# Reason: PromptManager was already parameterised to take a
# templates_dir + sample_prompts_dir (see T1's
# `notebooklm_sample_prompts_dir` rationale in config.py); agy reuses
# it verbatim by passing (settings.agy_templates_dir,
# settings.agy_sample_prompts_dir). The class is intentionally
# importable from BOTH packages.
from streamdoc.integrations.notebooklm.prompts import (
    ContentType,
    PromptManager,
    PromptTemplate,
)

# Flag: agy is always available at the import level — it's a thin
# subprocess wrapper, not a heavy third-party dep. The runtime check
# is `is_available()` / `find_agy_binary()`.
AGYAvailable: bool = True

__all__ = [
    # availability
    "AGYAvailable",
    "is_available",
    "find_agy_binary",
    "install_dir",
    "global_dir",
    "install_url",
    "npm_package",
    # exceptions
    "AGYIntegrationError",
    "AGYNotInstalledError",
    "AGYInvocationError",
    "AGYPublishError",
    # skill manager
    "SkillInfo",
    "list_available",
    "list_installed",
    "list_selectable_skills",
    "is_herenow_installed",
    "find_skill",
    "install",
    "install_all",
    "update",
    # runner
    "AgyRunResult",
    "list_models",
    "parse_artifact_path",
    "resolve_agy_model",
    "run_skill",
    # herenow publish
    "HerenowResult",
    "publish",
    "parse_published_url",
    # prompt manager (re-exported from notebooklm.prompts)
    "ContentType",
    "PromptManager",
    "PromptTemplate",
]
