"""Unified social report builders.

Produces a single Markdown + PDF report that contains every collected post
across all platforms, organized into one dedicated section per platform.
Each platform section follows the same document pattern (per-platform summary
+ posts with metadata, text, and images). Platforms with zero posts are
omitted entirely so no empty sections are emitted.
"""
from __future__ import annotations

import base64
import html
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Flowable
from reportlab.platypus import Image as RLImage
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

from streamdoc.config import settings
from streamdoc.integrations.social.base import SocialPost

logger = logging.getLogger(__name__)

# Reason: stable, human-friendly display order for per-platform sections in
# the unified report. Platforms not listed here are appended alphabetically
# so future integrations still render in a deterministic position.
_PLATFORM_DISPLAY_ORDER: tuple[str, ...] = ("x", "reddit", "stocktwits")

_PLATFORM_LABELS: dict[str, str] = {
    "x": "X / Twitter",
    "reddit": "Reddit",
    "stocktwits": "Stocktwits",
}


def _platform_label(platform: str) -> str:
    """Return a human-friendly label for a platform identifier."""
    return _PLATFORM_LABELS.get(platform, platform.replace("_", " ").title())


def _ordered_platforms(platforms: set[str]) -> list[str]:
    """Return platforms in a stable display order (known first, then alpha)."""
    known = [p for p in _PLATFORM_DISPLAY_ORDER if p in platforms]
    rest = sorted(p for p in platforms if p not in _PLATFORM_DISPLAY_ORDER)
    return known + rest


def _ensure_parent(path: Path) -> None:
    """Create parent directories if they do not exist."""
    path.parent.mkdir(parents=True, exist_ok=True)


def _relative_to_outputs(target: Path) -> str:
    """Return a POSIX path relative to the output root, or the full path."""
    try:
        return target.relative_to(settings.output_root).as_posix()
    except ValueError:
        return target.as_posix()


def _image_exists(path: str) -> bool:
    """Return True when ``path`` points to an existing file."""
    try:
        return Path(path).is_file()
    except (OSError, ValueError):
        return False


def _embed_image_as_b64(path: str) -> tuple[str, str] | None:
    """Return (base64_data, extension) for an image file, or None on failure."""
    try:
        img_path = Path(path)
        data = img_path.read_bytes()
        ext = img_path.suffix.lstrip(".").lower() or "jpeg"
        if ext == "jpg":
            ext = "jpeg"
        return base64.b64encode(data).decode("ascii"), ext
    except (OSError, ValueError) as exc:
        logger.debug("failed to embed image %s: %s", path, exc)
        return None


def _group_posts_by_platform(
    posts: Sequence[SocialPost],
) -> list[tuple[str, list[SocialPost]]]:
    """Group posts by platform, preserving newest-first order within each group.

    Args:
        posts: Collected posts (caller should sort newest-first).

    Returns:
        List of (platform, posts) tuples in stable display order. Platforms
        with zero posts are omitted so the report never emits empty sections.
    """
    by_platform: dict[str, list[SocialPost]] = {}
    for post in posts:
        by_platform.setdefault(post.platform, []).append(post)

    return [
        (platform, by_platform[platform])
        for platform in _ordered_platforms(set(by_platform))
    ]


def build_unified_social_markdown(
    posts: Sequence[SocialPost],
    preset_name: str,
    prompt_md: str = "",
) -> str:
    """Build a single Markdown report containing all collected social posts.

    The report is organized into one dedicated section per platform. Each
    platform section follows the same document pattern: a per-platform
    summary (post count, image count) followed by every post rendered with
    author, platform, publish time, post id, source link, full text, and
    embedded images. Platforms with zero posts are omitted entirely so the
    report never contains empty sections.

    Args:
        posts: Collected posts, sorted newest-first by the caller.
        preset_name: Display name of the preset that collected the posts.
        prompt_md: Optional preset prompt/instructions to include.

    Returns:
        Markdown source text.
    """
    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    today = datetime.now(UTC).date().isoformat()
    total_images = sum(len(p.images) for p in posts)
    platforms_with_posts = {p.platform for p in posts}
    grouped = _group_posts_by_platform(posts)

    lines: list[str] = [
        "---",
        f'title: "Social Report — {preset_name}"',
        f'preset: "{preset_name}"',
        f'date: "{today}"',
        f'platforms: {sorted(platforms_with_posts)}',
        "tags: [streamdoc, notebooklm, social]",
        "---",
        "",
        f"# Social Report — {preset_name}",
        "",
        f"**Generated:** {generated_at}  ",
        f"**Posts collected:** {len(posts)}  ",
        f"**Images included:** {total_images}  ",
        f"**Platforms:** {', '.join(_platform_label(p) for p in _ordered_platforms(platforms_with_posts)) if platforms_with_posts else 'none'}",
        "",
    ]

    if prompt_md.strip():
        lines += [
            "## Instructions",
            "",
            prompt_md.strip(),
            "",
        ]

    # Reason: each platform gets its own dedicated section following the
    # same document pattern, so a reader (or downstream LLM) can treat each
    # section as a standalone per-platform report. Empty platforms are
    # skipped by _group_posts_by_platform.
    for platform, platform_posts in grouped:
        platform_images = sum(len(p.images) for p in platform_posts)
        label = _platform_label(platform)
        lines += [
            f"## {label} Report",
            "",
            f"**Posts:** {len(platform_posts)}  ",
            f"**Images:** {platform_images}  ",
            f"**Platform:** {platform}",
            "",
        ]

        for idx, post in enumerate(platform_posts, start=1):
            ts = (
                post.published_at.strftime("%Y-%m-%d %H:%M UTC")
                if post.published_at
                else "?"
            )
            lines.append(
                f"### Post {idx}: @{post.author} on {post.platform.upper()} — {ts}"
            )
            lines.append("")
            lines.append(f"- **Author:** @{post.author}")
            lines.append(f"- **Platform:** {post.platform}")
            lines.append(f"- **Published:** {ts}")
            lines.append(f"- **Post ID:** `{post.source_id}`")
            if post.url:
                lines.append(f"- **Source:** {post.url}")
            lines.append("")

            lines.append("#### Text")
            lines.append("")
            lines.append(post.text)
            lines.append("")

            if post.images:
                lines.append("#### Images")
                lines.append("")
                for img in post.images:
                    if _image_exists(img):
                        embedded = _embed_image_as_b64(img)
                        if embedded:
                            b64, ext = embedded
                            lines.append(
                                f'<img src="data:image/{ext};base64,{b64}" '
                                f'alt="{Path(img).name}" style="max-width:600px;" />'
                            )
                            lines.append("")
                        else:
                            rel = _relative_to_outputs(Path(img))
                            lines.append(f"![]({rel})")
                            lines.append("")
                    else:
                        lines.append(f"_Image not found: {img}_")
                        lines.append("")

    return "\n".join(lines)


def write_markdown(path: Path, markdown: str) -> Path:
    """Write markdown text to ``path`` and return the path."""
    _ensure_parent(path)
    path.write_text(markdown, encoding="utf-8")
    return path


def _pdf_safe_text(text: str) -> str:
    """Escape text for reportlab ``Paragraph`` and preserve line breaks."""
    escaped = html.escape(text)
    return escaped.replace("\n", "<br/>")


def build_unified_social_pdf(
    md_path: Path,
    posts: Sequence[SocialPost],
    preset_name: str,
) -> Path:
    """Build a PDF report from the collected social posts.

    Args:
        md_path: Path to the source markdown file (used for output naming).
        posts: Collected posts.
        preset_name: Preset display name.

    Returns:
        Path to the generated PDF.
    """
    from PIL import Image as PILImage

    out = md_path.with_suffix(".pdf")
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "SocialUnifiedTitle",
        parent=styles["Title"],
        fontSize=22,
        leading=28,
        alignment=1,
        spaceAfter=8,
    )
    subtitle_style = ParagraphStyle(
        "SocialUnifiedSubtitle",
        parent=styles["Normal"],
        fontSize=11,
        leading=15,
        alignment=1,
        textColor=colors.HexColor("#444444"),
    )
    platform_section_style = ParagraphStyle(
        "SocialPlatformSection",
        parent=styles["Heading1"],
        fontSize=18,
        leading=22,
        spaceBefore=10,
        spaceAfter=6,
        textColor=colors.HexColor("#1f2937"),
    )
    heading_style = ParagraphStyle(
        "SocialPostHeading",
        parent=styles["Heading2"],
        fontSize=14,
        leading=18,
        spaceBefore=14,
        spaceAfter=4,
        borderColor=colors.HexColor("#dddddd"),
        borderWidthBottom=1,
        borderPadding=4,
    )
    meta_style = ParagraphStyle(
        "SocialPostMeta",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#666666"),
    )
    body_style = ParagraphStyle(
        "SocialPostBody",
        parent=styles["Normal"],
        fontSize=10,
        leading=14,
        spaceAfter=6,
    )

    doc = SimpleDocTemplate(
        str(out),
        pagesize=A4,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )
    story: list[Flowable] = []

    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    total_images = sum(len(p.images) for p in posts)
    platforms_with_posts = {p.platform for p in posts}
    grouped = _group_posts_by_platform(posts)

    # Cover / summary
    story.append(Paragraph(f"Social Report — {preset_name}", title_style))
    story.append(
        Paragraph(
            f"{len(posts)} posts across {len(platforms_with_posts)} platform(s) — {generated_at}",
            subtitle_style,
        )
    )
    story.append(Spacer(1, 4 * mm))
    story.append(
        Paragraph(
            f"Platforms: {', '.join(_platform_label(p) for p in _ordered_platforms(platforms_with_posts)) if platforms_with_posts else 'none'}<br/>"
            f"Images included: {total_images}",
            meta_style,
        )
    )
    story.append(PageBreak())

    max_w = A4[0] - 30 * mm
    max_h = A4[1] - 40 * mm

    # Reason: mirror the Markdown layout — one dedicated section per
    # platform, each with its own header and per-platform summary, then
    # the posts. Empty platforms are skipped by _group_posts_by_platform.
    for platform, platform_posts in grouped:
        platform_images = sum(len(p.images) for p in platform_posts)
        label = _platform_label(platform)
        story.append(Paragraph(f"{label} Report", platform_section_style))
        story.append(
            Paragraph(
                f"{len(platform_posts)} posts — {platform_images} images — platform: {platform}",
                meta_style,
            )
        )
        story.append(Spacer(1, 3 * mm))

        for post in platform_posts:
            ts = (
                post.published_at.strftime("%Y-%m-%d %H:%M UTC")
                if post.published_at
                else "?"
            )
            heading = f"@{post.author} on {post.platform.upper()} — {ts}"
            story.append(Paragraph(heading, heading_style))

            meta_parts = [f"Post ID: {post.source_id}"]
            if post.url:
                meta_parts.append(f'<a href="{html.escape(post.url)}">{html.escape(post.url)}</a>')
            story.append(Paragraph(" | ".join(meta_parts), meta_style))
            story.append(Spacer(1, 2 * mm))

            body = _pdf_safe_text(post.text) if post.text.strip() else "<i>No text</i>"
            story.append(Paragraph(body, body_style))

            if post.images:
                for img in post.images:
                    img_path = Path(img)
                    if not img_path.exists():
                        continue
                    try:
                        with PILImage.open(img_path) as pil_img:
                            w_px, h_px = pil_img.size
                        w_mm = (w_px / 72) * 25.4
                        h_mm = (h_px / 72) * 25.4
                        if w_mm > max_w:
                            scale = max_w / w_mm
                            w_mm *= scale
                            h_mm *= scale
                        if h_mm > max_h:
                            scale = max_h / h_mm
                            w_mm *= scale
                            h_mm *= scale
                        story.append(Spacer(1, 3 * mm))
                        story.append(RLImage(str(img_path), width=w_mm, height=h_mm))
                    except (OSError, RuntimeError, ValueError, TypeError) as exc:
                        logger.debug("failed embedding image %s in PDF: %s", img, exc)

            story.append(Spacer(1, 6 * mm))

    doc.build(story)
    return out


def build_unified_social_outputs(
    posts: Sequence[SocialPost],
    preset_name: str,
    prompt_md: str = "",
) -> tuple[Path, Path | None]:
    """Build a single unified Markdown and PDF report for social posts.

    Args:
        posts: Collected posts (caller should sort newest-first).
        preset_name: Preset display name used for the output directory.
        prompt_md: Optional prompt/instructions text.

    Returns:
        Tuple of (markdown_path, pdf_path_or_none).
    """
    out_dir = Path(settings.output_root) / preset_name
    _ensure_parent(out_dir)

    today = datetime.now(UTC).date().isoformat()
    md_path = out_dir / f"social-{today}.md"

    md = build_unified_social_markdown(posts, preset_name, prompt_md)
    write_markdown(md_path, md)

    pdf_path: Path | None = None
    try:
        pdf_path = build_unified_social_pdf(md_path, posts, preset_name)
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        logger.warning("PDF generation failed for social report: %s", exc)

    return md_path, pdf_path
