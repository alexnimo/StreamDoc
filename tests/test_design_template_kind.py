"""Tests for POR-91 F2: design-kind templates render as raw payloads.

Covers:
- ``_design_prompt_for_preset`` returns design-kind template prompts verbatim
  (no str.format, no target_types gate).
- The flagship T4 asset "Market dashboard - social sentiment" renders
  identically for every ContentType member with no warnings.
- Literal braces in design-kind prompts survive without KeyError.
- Content-kind templates still route through ``render_prompt``.

Collision avoidance: does NOT extend tests/test_fetch_design_prompt.py
(concurrent card t_8ccf19a3 owns that file).
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

import yaml


def _make_preset(**kwargs):
    """Construct a Preset model directly (no DB needed).

    Mirrors tests/test_fetch_design_prompt.py::_make_preset.
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


def _isolate_template_dirs(monkeypatch, tmp_path):
    """Point the design-template PromptManager at tmp dirs.

    Reason: controls which YAML files the PromptManager discovers so
    tests are deterministic.
    """
    from streamdoc.config import settings

    monkeypatch.setattr(settings, "notebooklm_templates_dir", str(tmp_path / "tpl"))
    monkeypatch.setattr(
        settings, "notebooklm_sample_prompts_dir", str(tmp_path / "samples")
    )


def _seed_flagship_asset(tmp_path):
    """Copy the real shipped T4 flagship asset into the tmp sample dir.

    Returns:
        The template name (stem) used by the YAML.
    """
    asset = (
        Path(__file__).resolve().parent.parent
        / "assets"
        / "prompts"
        / "notebooklm"
        / "Market dashboard - social sentiment.yaml"
    )
    samples_dir = tmp_path / "samples"
    samples_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(asset, samples_dir / asset.name)
    return "Market dashboard - social sentiment"


# ---------------------------------------------------------------------------
# Test 1 — F2 regression: flagship design template renders raw
# ---------------------------------------------------------------------------


def test_flagship_design_template_returns_raw_prompt(monkeypatch, tmp_path, caplog):
    """The flagship T4 template returns its raw prompt text with no warning."""
    from streamdoc.core.fetch import _design_prompt_for_preset
    from streamdoc.integrations.notebooklm.prompts import ContentType

    _isolate_template_dirs(monkeypatch, tmp_path)
    template_name = _seed_flagship_asset(tmp_path)
    preset = _make_preset(design_prompt_template=template_name)

    with caplog.at_level(logging.WARNING):
        result = _design_prompt_for_preset(preset, ContentType.SLIDE_DECK)

    assert result is not None
    assert "senior design engineer" in result
    assert "skipping design injection" not in caplog.text


# ---------------------------------------------------------------------------
# Test 2 — Orthogonality: identical result for every ContentType
# ---------------------------------------------------------------------------


def test_flagship_returns_identical_for_all_content_types(monkeypatch, tmp_path):
    """Design-kind template returns byte-identical text for every ContentType."""
    from streamdoc.core.fetch import _design_prompt_for_preset
    from streamdoc.integrations.notebooklm.prompts import ContentType

    _isolate_template_dirs(monkeypatch, tmp_path)
    template_name = _seed_flagship_asset(tmp_path)
    preset = _make_preset(design_prompt_template=template_name)

    results = {
        ct: _design_prompt_for_preset(preset, ct) for ct in ContentType
    }

    values = list(results.values())
    assert all(v == values[0] for v in values), (
        "Expected identical results for all content types, got varying results"
    )
    assert values[0] is not None
    assert "senior design engineer" in values[0]


# ---------------------------------------------------------------------------
# Test 3 — Braces-proof: literal braces survive verbatim
# ---------------------------------------------------------------------------


def test_literal_braces_in_design_prompt_survive(monkeypatch, tmp_path):
    """A design-kind YAML with literal braces returns verbatim (no KeyError)."""
    from streamdoc.core.fetch import _design_prompt_for_preset
    from streamdoc.integrations.notebooklm.prompts import ContentType

    _isolate_template_dirs(monkeypatch, tmp_path)

    braces_prompt = ":root { --accent: #000; }\n.card { border-radius: 8px; }"
    samples_dir = tmp_path / "samples"
    samples_dir.mkdir(parents=True, exist_ok=True)
    (samples_dir / "braces_design.yaml").write_text(
        yaml.safe_dump({
            "name": "braces_design",
            "description": "Design with literal braces",
            "template_kind": "design",
            "target_types": ["slide_deck"],
            "prompt": braces_prompt,
            "variables": {},
        }),
        encoding="utf-8",
    )

    preset = _make_preset(design_prompt_template="braces_design")
    result = _design_prompt_for_preset(preset, ContentType.SLIDE_DECK)

    assert result == braces_prompt


# ---------------------------------------------------------------------------
# Test 4 — Backward compat: content-kind template still uses render_prompt
# ---------------------------------------------------------------------------


def test_content_kind_template_still_renders_via_render_prompt(
    monkeypatch, tmp_path
):
    """A content-kind design_prompt_template still routes through render_prompt."""
    from streamdoc.core.fetch import _design_prompt_for_preset
    from streamdoc.integrations.notebooklm.prompts import ContentType, PromptManager

    _isolate_template_dirs(monkeypatch, tmp_path)

    preset = _make_preset(design_prompt_template="design_guidelines")
    result = _design_prompt_for_preset(preset, ContentType.SLIDE_DECK)

    # Expected side must use the SAME isolated dirs — building a bare
    # PromptManager() would read real user config and break determinism.
    pm = PromptManager(str(tmp_path / "tpl"), str(tmp_path / "samples"))
    expected = pm.render_prompt("design_guidelines", ContentType.SLIDE_DECK)
    assert result == expected
