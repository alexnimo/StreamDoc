"""
Output assembly: build Markdown and PDF artifacts from transcript + frames.
"""
from __future__ import annotations

import base64
import logging
from collections.abc import Sequence
from pathlib import Path

from streamdoc.config import settings

logger = logging.getLogger(__name__)


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _fmt_timestamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _relative_to_outputs(target: Path) -> str:
    try:
        return target.relative_to(settings.output_root).as_posix()
    except ValueError:
        return target.as_posix()


def build_markdown(
    video_id: str,
    title: str,
    channel_title: str,
    published_at: str,
    source_url: str,
    transcript: list[dict],
    frames: Sequence[Path],
    preset_name: str,
    prompt_md: str = "",
) -> str:
    """Build a rich, structured Markdown document.

    The output is designed for human review, NotebookLM ingestion, and
    downstream LLM consumption.
    """
    lines: list[str] = []
    lines.append("---")
    lines.append(f'title: "{title}"')
    lines.append(f'source_url: "{source_url}"')
    lines.append(f'channel: "{channel_title}"')
    lines.append(f'published_at: "{published_at}"')
    lines.append("tags: [streamdoc, notebooklm]")
    lines.append("---")
    lines.append("")
    lines.append(f"# {channel_title} — {title}")
    lines.append("")
    lines.append(f"**Video ID:** `{video_id}`  ")
    lines.append(f"**Channel:** {channel_title}  ")
    lines.append(f"**Published:** {published_at}  ")
    lines.append(f"**Source:** {source_url}")
    lines.append("")

    if prompt_md.strip():
        lines.append("## Prompt / Instructions")
        lines.append("")
        lines.append(prompt_md.strip())
        lines.append("")

    # Summary / overview section
    lines.append("## Overview")
    lines.append("")
    tx_words = sum(len(seg.get("text", "").split()) for seg in transcript)
    lines.append(f"- **Transcript segments:** {len(transcript)}")
    lines.append(f"- **Word count:** ~{tx_words}")
    lines.append(f"- **Unique frames extracted:** {len(frames)}")
    lines.append("")

    # Full transcript text (combined, no timestamps)
    lines.append("## Transcript")
    lines.append("")
    full_text = " ".join(seg.get("text", "").strip() for seg in transcript if seg.get("text", "").strip())
    lines.append(full_text)
    lines.append("")

    # Frame gallery
    if frames:
        lines.append("## Frames")
        lines.append("")
        lines.append("> Representative frames extracted and de-duplicated from the video.")
        lines.append("")
        for i, frame in enumerate(frames, start=1):
            ts_tag = f"frame_{i:04d}"
            try:
                data = frame.read_bytes()
                b64 = base64.b64encode(data).decode("ascii")
                ext = frame.suffix.lstrip(".") or "jpeg"
                lines.append(f"### Frame {i} (`{ts_tag}`)")
                lines.append(f'<img src="data:image/{ext};base64,{b64}" alt="{frame.name}" style="max-width:600px;" />')
                lines.append("")
            except Exception as exc:
                logger.debug("failed embedding frame %s: %s", frame, exc)
                rel = _relative_to_outputs(frame)
                lines.append(f"### Frame {i}")
                lines.append(f"![]({rel})")
                lines.append("")
        lines.append("")

    return "\n".join(lines)


def write_markdown(path: Path, markdown: str) -> Path:
    _ensure_parent(path)
    path.write_text(markdown, encoding="utf-8")
    return path


def build_pdf(
    markdown_path: Path,
    video_id: str,
    title: str,
    channel_title: str,
    source_url: str,
    transcript: list[dict] | None = None,
    frames: Sequence[Path] | None = None,
) -> Path:
    """Build a structured, human-readable PDF via reportlab.

    Args:
        markdown_path: Path to the source .md file.
        video_id: Video identifier for logging.
        title: Video title for the PDF header.
        channel_title: Channel name for the PDF header.
        source_url: Original video URL.
        transcript: Optional transcript segments for structured rendering.
        frames: Optional frame paths for embedding.

    Returns:
        Path to the generated .pdf file.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Image as RLImage,
    )
    from reportlab.platypus import (
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
    from reportlab.platypus.doctemplate import PageTemplate
    from reportlab.platypus.frames import Frame

    out = markdown_path.with_suffix(".pdf")
    seg_count = len(transcript) if transcript else 0
    frame_count = len(frames) if frames else 0

    # Styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "VideoTitle", parent=styles["Title"],
        fontSize=22, leading=28, alignment=1, spaceAfter=6,
    )
    subtitle_style = ParagraphStyle(
        "ChannelSubtitle", parent=styles["Normal"],
        fontSize=13, leading=18, alignment=1, textColor=colors.HexColor("#444444"),
        spaceAfter=4, fontName="Helvetica-Bold",
    )
    meta_style = ParagraphStyle(
        "Meta", parent=styles["Normal"],
        fontSize=9, leading=12, alignment=1, textColor=colors.HexColor("#666666"),
    )
    heading_style = ParagraphStyle(
        "SectionHeading", parent=styles["Heading2"],
        fontSize=15, leading=20, spaceAfter=6, spaceBefore=12,
        borderPadding=(0, 0, 4, 0), borderWidth=0, borderColor=colors.HexColor("#dddddd"),
        borderWidthBottom=1, alignment=0,
    )
    text_style = ParagraphStyle(
        "TranscriptText", parent=styles["Normal"],
        fontSize=10, leading=14, alignment=0, spaceAfter=4,
    )

    # Header / footer
    def _header_footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica-Oblique", 8)
        canvas.setFillColor(colors.HexColor("#888888"))
        canvas.drawRightString(
            A4[0] - 12 * mm, A4[1] - 10 * mm,
            f"{channel_title} - {title}",
        )
        canvas.setStrokeColor(colors.HexColor("#dddddd"))
        canvas.line(12 * mm, A4[1] - 14 * mm, A4[0] - 12 * mm, A4[1] - 14 * mm)
        canvas.setFont("Helvetica-Oblique", 8)
        canvas.drawCentredString(A4[0] / 2, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        str(out), pagesize=A4,
        rightMargin=15 * mm, leftMargin=15 * mm,
        topMargin=20 * mm, bottomMargin=20 * mm,
    )
    frame = Frame(
        15 * mm, 20 * mm, A4[0] - 30 * mm, A4[1] - 40 * mm,
        id="normal", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
    )
    doc.addPageTemplates([PageTemplate(id="main", frames=frame, onPage=_header_footer)])

    story: list = []

    # ===== Cover =====
    story.append(Paragraph(title, title_style))
    story.append(Paragraph(f"Channel: {channel_title}", subtitle_style))
    story.append(Paragraph(f"Video ID: {video_id}<br/>Source: {source_url}", meta_style))
    story.append(Spacer(1, 14 * mm))

    # Summary box
    summary_data = [
        [Paragraph("<b>Summary</b>", styles["Normal"])],
        [Paragraph(f"Transcript segments: {seg_count}", styles["Normal"])],
        [Paragraph(f"Unique frames extracted: {frame_count}", styles["Normal"])],
    ]
    summary_table = Table(summary_data, colWidths=[A4[0] - 30 * mm])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f5f5f5")),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("ROUNDEDCORNERS", [4, 4, 4, 4]),
    ]))
    story.append(summary_table)
    story.append(PageBreak())

    # ===== Transcript (combined full text) =====
    story.append(Paragraph("Transcript", heading_style))
    story.append(Spacer(1, 4 * mm))

    if transcript:
        full_text = " ".join(seg.get("text", "").strip() for seg in transcript if seg.get("text", "").strip())
        if full_text:
            story.append(Paragraph(full_text, text_style))
        else:
            story.append(Paragraph("No transcript text available.", styles["Normal"]))
    else:
        story.append(Paragraph("No transcript available.", styles["Normal"]))

    # ===== Frames =====
    if frames:
        for i, frame_path in enumerate(frames, start=1):
            story.append(PageBreak())
            story.append(Paragraph(f"Frame {i}", heading_style))
            story.append(Spacer(1, 4 * mm))
            if frame_path.exists():
                try:
                    # Fit image within page width (max ~170mm), keeping aspect ratio
                    story.append(RLImage(str(frame_path), width=170 * mm, height=220 * mm, kind="proportional"))
                except Exception as exc:
                    logger.debug("reportlab image embed failed for %s: %s", frame_path, exc)
                    story.append(Paragraph(f"[Could not embed {frame_path.name}]", styles["Normal"]))
            else:
                story.append(Paragraph(f"[Frame file not found: {frame_path.name}]", styles["Normal"]))

    doc.build(story)
    return out


def _img_dims_mm(path: Path, max_w: float = 180) -> tuple[float, float]:
    """Return image dimensions in mm, scaled to fit within max_w."""
    from PIL import Image as PILImage

    with PILImage.open(path) as img:
        px_w, px_h = img.size
    # Assume 72 DPI for extracted frames (common default)
    dpi = 72
    mm_per_inch = 25.4
    w_mm = (px_w / dpi) * mm_per_inch
    h_mm = (px_h / dpi) * mm_per_inch
    if w_mm > max_w:
        scale = max_w / w_mm
        w_mm *= scale
        h_mm *= scale
    return w_mm, h_mm


def build_outputs(
    video_id: str,
    title: str,
    channel_title: str,
    published_at: str,
    source_url: str,
    transcript: list[dict],
    frames: Sequence[Path],
    preset_name: str,
    prompt_md: str = "",
) -> tuple[Path, Path | None]:
    """Build markdown and PDF outputs for a single video.

    Returns:
        Tuple of (markdown_path, pdf_path_or_none).
    """
    out_dir = Path(settings.output_root) / preset_name
    _ensure_parent(out_dir)
    md_path = out_dir / f"{video_id}.md"
    md = build_markdown(
        video_id, title, channel_title, published_at, source_url,
        transcript, frames, preset_name, prompt_md,
    )
    write_markdown(md_path, md)

    pdf_path: Path | None = None
    try:
        pdf_path = build_pdf(
            md_path, video_id, title, channel_title, source_url,
            transcript=transcript, frames=frames,
        )
    except Exception as exc:
        # Reason: single attempt — retrying with identical args won't help
        logger.warning("PDF generation failed for %s: %s", video_id, exc)
    return md_path, pdf_path


def mark_integration_failed(
    pdf_md_paths: tuple[Path, Path | None], video_id: str, reason: str
) -> tuple[Path, Path | None, str]:
    """Write an integration-failed marker and return updated status.

    Args:
        pdf_md_paths: Tuple of (md_path, pdf_path).
        video_id: Video identifier.
        reason: Failure reason text.

    Returns:
        Tuple of (md_path, pdf_path, "integration-failed").
    """
    logger.warning("NotebookLM integration-failed for %s: %s", video_id, reason)
    failed_path = pdf_md_paths[0].parent / f"{video_id}.integration-failed"
    failed_path.write_text(reason, encoding="utf-8")
    return (*pdf_md_paths, "integration-failed")



