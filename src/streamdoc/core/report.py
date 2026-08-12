"""
Omnibus report compilation: merges per-video reports into a single session report.
"""
from __future__ import annotations

import base64
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from streamdoc.config import settings
from streamdoc.core.output import write_markdown

logger = logging.getLogger(__name__)

# Reason: reportlab Paragraph uses XML-like markup; we must convert markdown **bold**
# to <b>...</b> pairs. A simple .replace("**", "<b>") breaks because it converts ALL
# ** to opening tags with no closing tags. This regex alternates open/close.
_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def _md_bold_to_para(text: str) -> str:
    """Convert markdown **bold** to reportlab <b>bold</b> tags.

    Args:
        text: Markdown text potentially containing **bold** spans.

    Returns:
        Text with ** replaced by proper <b>/<b> reportlab tags.
    """
    return _MD_BOLD_RE.sub(r"<b>\1</b>", text)


def compile_preset_report(preset_name: str, artifacts: Sequence) -> Path | None:
    """Compile all video reports for a preset into a structured session report.

    Args:
        preset_name: Preset identifier.
        artifacts: Sequence of RunArtifact objects.

    Returns:
        Path to the generated markdown report, or None if no artifacts.
    """
    if not artifacts:
        logger.warning("No artifacts to compile for preset %s", preset_name)
        return None

    out_dir = Path(settings.output_root) / preset_name
    out_dir.mkdir(parents=True, exist_ok=True)

    master_md_path = out_dir / "FULL_REPORT.md"
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    success_count = sum(1 for a in artifacts if a.status == "ready")
    failed_count = len(artifacts) - success_count

    # Aggregate stats
    total_duration = sum(
        getattr(a, "duration_seconds", 0) or 0 for a in artifacts
    )
    total_frames = sum(
        getattr(a, "frame_count", 0) or 0 for a in artifacts
    )
    total_words = sum(
        getattr(a, "transcript_word_count", 0) or 0 for a in artifacts
    )
    channel_counts: dict[str, int] = {}
    for a in artifacts:
        ch = getattr(a, "channel_title", "—")
        channel_counts[ch] = channel_counts.get(ch, 0) + 1

    lines: list[str] = []
    lines.append("---")
    lines.append(f'title: "Session Report: {preset_name}"')
    lines.append(f'generated_at: "{generated_at}"')
    lines.append("---")
    lines.append("")
    lines.append(f"# Session Report: {preset_name}")
    lines.append("")
    lines.append(f"**Generated:** {generated_at}")
    lines.append("")

    # Executive summary with rich stats
    lines.append("## Executive Summary")
    lines.append("")
    lines.append(f"- **Total Videos Processed:** {len(artifacts)}")
    lines.append(f"- **Successfully Generated:** {success_count}")
    lines.append(f"- **Failed / Integration-Failed:** {failed_count}")
    lines.append(f"- **Total Duration:** {_fmt_duration(total_duration)}")
    lines.append(f"- **Total Frames Extracted:** {total_frames}")
    lines.append(f"- **Total Transcript Words:** {total_words:,}")
    lines.append("")
    lines.append("### Channels")
    lines.append("")
    for ch, count in sorted(channel_counts.items(), key=lambda x: -x[1]):
        lines.append(f"- **{ch}:** {count} video(s)")
    lines.append("")

    # Per-video summary table
    lines.append("## Per-Video Summary")
    lines.append("")
    lines.append("| # | Video ID | Channel | Title | Duration | Frames | Words | Status |")
    lines.append("|---|----------|---------|-------|----------|--------|-------|--------|")
    for i, a in enumerate(artifacts, start=1):
        tx = getattr(a, "title", None) or a.video_id
        ch = getattr(a, "channel_title", "—")
        dur = _fmt_duration(getattr(a, "duration_seconds", 0) or 0)
        fc = getattr(a, "frame_count", "—") or "—"
        wc = getattr(a, "transcript_word_count", "—") or "—"
        lines.append(f"| {i} | `{a.video_id}` | {ch} | {tx[:50]} | {dur} | {fc} | {wc} | {a.status} |")
    lines.append("")

    # Detailed per-video sections with full structure
    lines.append("## Video Details")
    lines.append("")
    for a in artifacts:
        tx = getattr(a, "title", None) or a.video_id
        ch = getattr(a, "channel_title", "—")
        dur = _fmt_duration(getattr(a, "duration_seconds", 0) or 0)
        fc = getattr(a, "frame_count", "—") or "—"
        wc = getattr(a, "transcript_word_count", "—") or "—"

        lines.append(f"---")
        lines.append("")
        lines.append(f"## {ch} — {tx}")
        lines.append("")
        lines.append(f"**Video ID:** `{a.video_id}`  ")
        lines.append(f"**Channel:** {ch}  ")
        lines.append(f"**Duration:** {dur}  ")
        lines.append(f"**Frames Extracted:** {fc}  ")
        lines.append(f"**Transcript Words:** {wc}  ")
        lines.append(f"**Status:** {a.status}")
        lines.append("")

        # Embed transcript excerpt if available
        tx_text = getattr(a, "transcript_text", "")
        if tx_text:
            lines.append("### Transcript")
            lines.append("")
            excerpt = tx_text[:2000] + "..." if len(tx_text) > 2000 else tx_text
            lines.append(excerpt)
            lines.append("")

        # Embed first frame as base64 if available
        frame_paths = getattr(a, "frame_paths", [])
        if frame_paths:
            lines.append("### Frames")
            lines.append("")
            for idx, fp in enumerate(frame_paths[:3], start=1):
                if isinstance(fp, Path) and fp.exists():
                    try:
                        data = fp.read_bytes()
                        b64 = base64.b64encode(data).decode("ascii")
                        ext = fp.suffix.lstrip(".") or "jpeg"
                        lines.append(f"![Frame {idx}](data:image/{ext};base64,{b64})")
                    except Exception:
                        lines.append(f"[Frame {idx}: {fp.name}]")
                else:
                    lines.append(f"[Frame {idx}]")
            lines.append("")

        if getattr(a, "error", None):
            lines.append(f"**Error:** {a.error}")
            lines.append("")

    write_markdown(master_md_path, "\n".join(lines))
    logger.info("Session report saved: %s", master_md_path)

    # Also build PDF version
    try:
        pdf_path = _build_omnibus_pdf(master_md_path, preset_name, lines)
        logger.info("Session report PDF saved: %s", pdf_path)
    except Exception as exc:
        logger.warning("Session PDF generation failed: %s", exc)

    return master_md_path


def _fmt_duration(seconds: int) -> str:
    """Format seconds as HH:MM:SS or MM:SS."""
    if not seconds:
        return "—"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _build_omnibus_pdf(md_path: Path, preset_name: str, lines: list[str]) -> Path:
    """Generate a PDF from the omnibus markdown content via reportlab."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

    pdf_path = md_path.with_suffix(".pdf")
    styles = getSampleStyleSheet()
    heading_style = ParagraphStyle(
        "ReportHeading", parent=styles["Heading1"],
        fontSize=18, leading=24, spaceAfter=10, alignment=1,
    )
    section_style = ParagraphStyle(
        "ReportSection", parent=styles["Heading2"],
        fontSize=14, leading=18, spaceAfter=6, spaceBefore=12,
        borderWidthBottom=1, borderColor=colors.HexColor("#dddddd"),
    )
    sub_style = ParagraphStyle(
        "ReportSub", parent=styles["Heading3"],
        fontSize=12, leading=16, spaceAfter=4, spaceBefore=8,
    )
    normal = ParagraphStyle("ReportNormal", parent=styles["Normal"], fontSize=10, leading=14)

    doc = SimpleDocTemplate(
        str(pdf_path), pagesize=A4,
        rightMargin=15 * mm, leftMargin=15 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
    )
    story: list = []
    story.append(Paragraph(f"Session Report: {preset_name}", heading_style))
    story.append(Spacer(1, 6 * mm))

    # Parse lines into sections
    current_table: list[list] = []
    in_table = False
    for line in lines:
        if line.startswith("# "):
            story.append(Paragraph(line.lstrip("# "), heading_style))
        elif line.startswith("## "):
            story.append(Paragraph(line.lstrip("## "), section_style))
        elif line.startswith("### "):
            story.append(Paragraph(line.lstrip("### "), sub_style))
        elif line.startswith("| "):
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if cells and not all(c.replace("-", "") == "" for c in cells):
                current_table.append([Paragraph(c, normal) for c in cells])
                in_table = True
        elif line.startswith("- "):
            if in_table and current_table:
                t = Table(current_table, colWidths=[A4[0] - 30 * mm])
                t.setStyle(TableStyle([
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("LINEBELOW", (0, 0), (-1, -2), 0.5, colors.HexColor("#eeeeee")),
                ]))
                story.append(t)
                current_table = []
                in_table = False
            story.append(Paragraph(_md_bold_to_para(line.lstrip("- ")), normal))
        elif line.strip() == "---":
            if in_table and current_table:
                t = Table(current_table, colWidths=[A4[0] - 30 * mm])
                t.setStyle(TableStyle([
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("LINEBELOW", (0, 0), (-1, -2), 0.5, colors.HexColor("#eeeeee")),
                ]))
                story.append(t)
                current_table = []
                in_table = False
        elif line.strip():
            story.append(Paragraph(line, normal))

    if in_table and current_table:
        t = Table(current_table, colWidths=[A4[0] - 30 * mm])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("LINEBELOW", (0, 0), (-1, -2), 0.5, colors.HexColor("#eeeeee")),
        ]))
        story.append(t)

    doc.build(story)
    return pdf_path
