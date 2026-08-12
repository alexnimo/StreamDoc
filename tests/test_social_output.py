"""Tests for the unified social report builders.

Verifies that the unified report organizes posts into one dedicated section
per platform (following the same document pattern for every platform), that
platforms with zero posts are omitted entirely, and that the Markdown + PDF
outputs stay consistent.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from streamdoc.core.social_output import (
    _group_posts_by_platform,
    _ordered_platforms,
    _platform_label,
    build_unified_social_markdown,
    build_unified_social_outputs,
)
from streamdoc.integrations.social.base import SocialPost


def _post(
    platform: str,
    source_id: str,
    author: str = "user",
    text: str = "body",
    images: list[str] | None = None,
    published_at: datetime | None = None,
) -> SocialPost:
    """Build a minimal SocialPost for report tests."""
    return SocialPost(
        platform=platform,
        source_id=source_id,
        url=f"https://example.com/{platform}/{source_id}",
        author=author,
        text=text,
        published_at=published_at or datetime.now(timezone.utc),
        raw="{}",
        images=images or [],
    )


# ── Platform ordering helpers ───────────────────────────────────────────


def test_ordered_platforms_known_order():
    """Known platforms render in the canonical display order."""
    assert _ordered_platforms({"stocktwits", "reddit", "x"}) == ["x", "reddit", "stocktwits"]


def test_ordered_platforms_unknown_appended_alphabetically():
    """Unknown future platforms are appended alphabetically after known ones."""
    assert _ordered_platforms({"mastodon", "x", "bluesky"}) == [
        "x",
        "bluesky",
        "mastodon",
    ]


def test_platform_label_known_and_unknown():
    """Known platforms get friendly labels; unknown ones get a titled name."""
    assert _platform_label("x") == "X / Twitter"
    assert _platform_label("reddit") == "Reddit"
    assert _platform_label("stocktwits") == "Stocktwits"
    assert _platform_label("mastodon") == "Mastodon"


# ── Grouping ────────────────────────────────────────────────────────────


def test_group_posts_by_platform_preserves_newest_first_within_group():
    """Posts within a platform group keep their caller-provided order."""
    now = datetime.now(timezone.utc)
    posts = [
        _post("reddit", "r1", published_at=now - timedelta(hours=1)),
        _post("x", "x1", published_at=now - timedelta(hours=2)),
        _post("reddit", "r2", published_at=now - timedelta(hours=3)),
    ]
    grouped = _group_posts_by_platform(posts)
    platforms = [p for p, _ in grouped]
    assert platforms == ["x", "reddit"]
    reddit_ids = [p.source_id for p in dict(grouped)["reddit"]]
    assert reddit_ids == ["r1", "r2"]


def test_group_posts_by_platform_omits_empty_platforms():
    """Platforms with no posts never appear in the grouped output."""
    posts = [_post("reddit", "r1"), _post("reddit", "r2")]
    grouped = _group_posts_by_platform(posts)
    assert [p for p, _ in grouped] == ["reddit"]


# ── Markdown report ─────────────────────────────────────────────────────


def test_markdown_has_per_platform_sections(tmp_path, monkeypatch):
    """The report emits one `## <Label> Report` section per platform."""
    monkeypatch.setattr("streamdoc.config.settings.output_root", str(tmp_path))
    monkeypatch.setattr("streamdoc.config.settings.media_root", str(tmp_path / "media"))

    posts = [
        _post("x", "x1", author="trader", text="X post body"),
        _post("reddit", "r1", author="redditor", text="Reddit post body"),
        _post("stocktwits", "s1", author="st_user", text="ST post body"),
    ]
    md = build_unified_social_markdown(posts, preset_name="TestPreset")

    # Each platform gets its own dedicated section header.
    assert "## X / Twitter Report" in md
    assert "## Reddit Report" in md
    assert "## Stocktwits Report" in md

    # Per-platform summary metadata is present for each section.
    assert "**Platform:** x" in md
    assert "**Platform:** reddit" in md
    assert "**Platform:** stocktwits" in md

    # Post bodies appear under their respective platforms.
    assert "X post body" in md
    assert "Reddit post body" in md
    assert "ST post body" in md


def test_markdown_sections_appear_in_stable_display_order(tmp_path, monkeypatch):
    """X section comes before Reddit, which comes before Stocktwits."""
    monkeypatch.setattr("streamdoc.config.settings.output_root", str(tmp_path))

    posts = [
        _post("stocktwits", "s1"),
        _post("reddit", "r1"),
        _post("x", "x1"),
    ]
    md = build_unified_social_markdown(posts, preset_name="P")
    x_idx = md.index("## X / Twitter Report")
    reddit_idx = md.index("## Reddit Report")
    st_idx = md.index("## Stocktwits Report")
    assert x_idx < reddit_idx < st_idx


def test_markdown_omits_empty_platform_section(tmp_path, monkeypatch):
    """A platform with zero posts does not get a section in the report."""
    monkeypatch.setattr("streamdoc.config.settings.output_root", str(tmp_path))

    posts = [
        _post("reddit", "r1", author="u1", text="only reddit"),
    ]
    md = build_unified_social_markdown(posts, preset_name="P")

    assert "## Reddit Report" in md
    # Reason: empty platforms must not produce empty sections — no wasted
    # space or downstream compute on a platform that returned nothing.
    assert "## X / Twitter Report" not in md
    assert "## Stocktwits Report" not in md
    assert "only reddit" in md


def test_markdown_empty_posts_list_produces_no_platform_sections(tmp_path, monkeypatch):
    """An empty post list yields a header-only report with no platform sections."""
    monkeypatch.setattr("streamdoc.config.settings.output_root", str(tmp_path))

    md = build_unified_social_markdown([], preset_name="Empty")
    assert "# Social Report — Empty" in md
    assert "**Posts collected:** 0" in md
    # Reason: no platform collected any posts, so no per-platform section
    # headers (`## <Label> Report`) should be emitted.
    assert "## X / Twitter Report" not in md
    assert "## Reddit Report" not in md
    assert "## Stocktwits Report" not in md


def test_markdown_includes_prompt_instructions(tmp_path, monkeypatch):
    """The preset prompt is rendered into the report instructions section."""
    monkeypatch.setattr("streamdoc.config.settings.output_root", str(tmp_path))

    posts = [_post("x", "x1")]
    md = build_unified_social_markdown(posts, preset_name="P", prompt_md="Summarize sentiment.")
    assert "## Instructions" in md
    assert "Summarize sentiment." in md


# ── Full output (Markdown + PDF) ────────────────────────────────────────


def test_build_unified_social_outputs_writes_md_and_pdf(tmp_path, monkeypatch):
    """build_unified_social_outputs writes a Markdown file and a PDF file."""
    monkeypatch.setattr("streamdoc.config.settings.output_root", str(tmp_path))
    monkeypatch.setattr("streamdoc.config.settings.media_root", str(tmp_path / "media"))

    posts = [
        _post("x", "x1", author="a", text="hello x"),
        _post("reddit", "r1", author="b", text="hello reddit"),
    ]
    md_path, pdf_path = build_unified_social_outputs(posts, preset_name="OutPreset")

    assert md_path.exists()
    assert md_path.suffix == ".md"
    text = md_path.read_text(encoding="utf-8")
    assert "## X / Twitter Report" in text
    assert "## Reddit Report" in text

    # PDF generation is best-effort; when reportlab/PIL are installed it
    # should succeed. If the environment lacks them, pdf_path is None.
    if pdf_path is not None:
        assert pdf_path.exists()
        assert pdf_path.suffix == ".pdf"


def test_build_unified_social_outputs_skips_empty_platforms(tmp_path, monkeypatch):
    """Only platforms with posts appear in the generated Markdown file."""
    monkeypatch.setattr("streamdoc.config.settings.output_root", str(tmp_path))

    posts = [_post("stocktwits", "s1", text="only st")]
    md_path, _ = build_unified_social_outputs(posts, preset_name="SinglePlatform")
    text = md_path.read_text(encoding="utf-8")

    assert "## Stocktwits Report" in text
    assert "## X / Twitter Report" not in text
    assert "## Reddit Report" not in text
