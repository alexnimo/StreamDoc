"""Unit tests for the agy model-discovery path in the runner.

Covers the failure mode behind the preset form's model picker getting
stuck on "Default": ``agy models`` performs a network fetch and can be
slow or transiently fail, so the discovery layer caches *non-empty*
results for a short TTL and never caches empty results, letting the
picker recover on the next request. ``resolve_agy_model`` shares the
same cache so run-time resolution benefits too.
"""
from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# _parse_model_list: real `agy models` output shape
# ---------------------------------------------------------------------------


def test_parse_model_list_tab_separated_with_banner() -> None:
    """Real output: banner line + '<id>\\t<description>' rows -> ids only."""
    from streamdoc.integrations.agy.runner import _parse_model_list

    out = _parse_model_list(
        "Fetching available models...\n"
        "gemini-3.8-flash-high\tGemini 3.8 Flash (High)\n"
        "gemini-3.8-flash-low\tGemini 3.8 Flash (Low)\n"
        "claude-sonnet-4-6\tClaude Sonnet 4.6 (Thinking)\n"
    )
    assert out == [
        "gemini-3.8-flash-high",
        "gemini-3.8-flash-low",
        "claude-sonnet-4-6",
    ]


def test_parse_model_list_skips_banner_and_blank_lines() -> None:
    """Lines with spaces and no tab (banners) are dropped."""
    from streamdoc.integrations.agy.runner import _parse_model_list

    out = _parse_model_list(
        "Fetching available models...\n\nplain-model-id\nanother line with spaces\n"
    )
    assert out == ["plain-model-id"]


def test_parse_model_list_empty() -> None:
    """Empty/whitespace input -> empty list."""
    from streamdoc.integrations.agy.runner import _parse_model_list

    assert _parse_model_list("") == []
    assert _parse_model_list("   \n  \n") == []


# ---------------------------------------------------------------------------
# list_models: env allowlist fallback
# ---------------------------------------------------------------------------


def test_list_models_falls_back_to_env_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No binary -> operator allowlist (agy_supported_models) is used."""
    from streamdoc.config import settings
    from streamdoc.integrations.agy import runner as runner_mod

    monkeypatch.setattr(runner_mod, "find_agy_binary", lambda: None)
    monkeypatch.setattr(settings, "agy_supported_models", " m1 , m2 ,, ")

    assert runner_mod.list_models() == ["m1", "m2"]


def test_list_models_empty_when_no_binary_and_no_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No binary + no allowlist -> empty list (the stuck-on-Default state)."""
    from streamdoc.config import settings
    from streamdoc.integrations.agy import runner as runner_mod

    monkeypatch.setattr(runner_mod, "find_agy_binary", lambda: None)
    monkeypatch.setattr(settings, "agy_supported_models", "")

    assert runner_mod.list_models() == []


# ---------------------------------------------------------------------------
# list_models_cached: TTL cache behaviour
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_model_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test starts with an empty model-list cache."""
    from streamdoc.integrations.agy import runner as runner_mod

    monkeypatch.setattr(runner_mod, "_list_models_cache", None)


def test_list_models_cached_caches_non_empty_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful probe is served from cache on the second call."""
    from streamdoc.integrations.agy import runner as runner_mod

    calls = {"n": 0}

    def fake_list_models(timeout: float = 15.0) -> list[str]:
        calls["n"] += 1
        return ["m1", "m2"]

    monkeypatch.setattr(runner_mod, "list_models", fake_list_models)

    assert runner_mod.list_models_cached() == ["m1", "m2"]
    assert runner_mod.list_models_cached() == ["m1", "m2"]
    assert calls["n"] == 1


def test_list_models_cached_never_caches_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty probe is NOT cached — the next call re-probes and recovers."""
    from streamdoc.integrations.agy import runner as runner_mod

    results = iter([[], ["m1"]])
    calls = {"n": 0}

    def fake_list_models(timeout: float = 15.0) -> list[str]:
        calls["n"] += 1
        return next(results)

    monkeypatch.setattr(runner_mod, "list_models", fake_list_models)

    assert runner_mod.list_models_cached() == []
    assert runner_mod.list_models_cached() == ["m1"]
    assert calls["n"] == 2


def test_list_models_cached_reprobes_after_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expired cache entries trigger a fresh probe."""
    from streamdoc.integrations.agy import runner as runner_mod

    calls = {"n": 0}

    def fake_list_models(timeout: float = 15.0) -> list[str]:
        calls["n"] += 1
        return ["m1"]

    monkeypatch.setattr(runner_mod, "list_models", fake_list_models)
    # Reason: zero TTL makes the first cached entry immediately stale.
    monkeypatch.setattr(runner_mod, "_LIST_MODELS_TTL_S", 0.0)

    assert runner_mod.list_models_cached() == ["m1"]
    assert runner_mod.list_models_cached() == ["m1"]
    assert calls["n"] == 2


# ---------------------------------------------------------------------------
# resolve_agy_model: requested-model passthrough + fallback
# ---------------------------------------------------------------------------


def test_resolve_agy_model_none_preserves_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty/None model -> empty string (agy uses its own default)."""
    from streamdoc.integrations.agy import runner as runner_mod

    assert runner_mod.resolve_agy_model(None) == ""
    assert runner_mod.resolve_agy_model("") == ""


def test_resolve_agy_model_returns_requested_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A requested model in the discovered list is used verbatim."""
    from streamdoc.integrations.agy import runner as runner_mod

    monkeypatch.setattr(
        runner_mod, "list_models_cached", lambda timeout=15.0: ["m1", "m2"]
    )
    assert runner_mod.resolve_agy_model("m2") == "m2"


def test_resolve_agy_model_passthrough_when_list_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When discovery returns nothing, the requested model is trusted."""
    from streamdoc.integrations.agy import runner as runner_mod

    monkeypatch.setattr(runner_mod, "list_models_cached", lambda timeout=15.0: [])
    assert runner_mod.resolve_agy_model("anything") == "anything"


def test_resolve_agy_model_stale_falls_back_to_flash_low(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale model id falls back to the cheapest flash-low model."""
    from streamdoc.integrations.agy import runner as runner_mod

    monkeypatch.setattr(
        runner_mod,
        "list_models_cached",
        lambda timeout=15.0: ["gemini-3.8-flash-low", "gemini-3.1-pro-high"],
    )
    assert runner_mod.resolve_agy_model("gemini-2.5-pro") == "gemini-3.8-flash-low"
