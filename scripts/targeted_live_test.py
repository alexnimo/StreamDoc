"""Targeted live test using already-downloaded n8H8P64x9Mc video."""
from __future__ import annotations

import logging
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

REVIEW_DIR = Path("c:/Users/alexn/projects/StreamDoc/data/LiveTest")
REVIEW_DIR.mkdir(parents=True, exist_ok=True)

# Use the already-downloaded video
MEDIA_DIR = Path("c:/Users/alexn/projects/StreamDoc/data/Media/UCMno7bbQKigk6RxiO0uv78g/UCMno7bbQKigk6RxiO0uv78g")
TARGET_VIDEO = MEDIA_DIR / "n8H8P64x9Mc.webm"

REPORT = []

def log(msg):
    print(msg)
    REPORT.append(msg)

log("=" * 60)
log("TARGETED LIVE TEST")
log(f"Video: {TARGET_VIDEO}")
log(f"Exists: {TARGET_VIDEO.exists()}")
log(f"Size: {TARGET_VIDEO.stat().st_size / 1024 / 1024:.1f} MB")
log("=" * 60)

if not TARGET_VIDEO.exists():
    log("ERROR: Target video not found. Run yt-dlp first.")
    sys.exit(1)

# =====================================================================
# TEST 1: Frame Extraction + Deduplication
# =====================================================================
log("\n" + "=" * 60)
log("TEST 1: Frame Extraction + Deduplication")
log("=" * 60)

from streamdoc.core.frames import extract_and_dedup

frames = extract_and_dedup(TARGET_VIDEO)
log(f"Unique frames extracted: {len(frames)}")
if frames:
    for i, f in enumerate(frames):
        log(f"  Frame {i}: {f.name} ({f.stat().st_size} bytes)")
        review_frame = REVIEW_DIR / f"frame_{i+1:02d}.jpg"
        review_frame.write_bytes(f.read_bytes())
    log(f"Saved {len(frames)} frames to review dir")
else:
    log("  No frames extracted (possible error)")

# =====================================================================
# TEST 2: Sound Extraction + faster-whisper Transcription
# =====================================================================
log("\n" + "=" * 60)
log("TEST 2: Sound Extraction + faster-whisper")
log("=" * 60)

from streamdoc.core.transcript import fallback_audio_to_wav, transcribe_audio

wav_path = REVIEW_DIR / "extracted_audio.wav"
try:
    fallback_audio_to_wav(TARGET_VIDEO, wav_path)
    log(f"WAV extracted: {wav_path.stat().st_size / 1024:.1f} KB")
except Exception as exc:
    log(f"Audio extraction failed: {exc}")
    wav_path = None

if wav_path and wav_path.exists():
    try:
        segments = transcribe_audio(wav_path, languages=["en"])
        log(f"Transcript segments: {len(segments)}")
        for seg in segments[:5]:
            log(f"  [{seg['start']:.1f}s] {seg['text'][:80]}")
        review_tx = REVIEW_DIR / "whisper_transcript.txt"
        review_tx.write_text(
            "\n".join(f"[{s['start']:.1f}s] {s['text']}" for s in segments),
            encoding="utf-8",
        )
        log(f"Saved transcript: {review_tx}")
    except Exception as exc:
        log(f"Whisper transcription failed: {exc}")

# =====================================================================
# TEST 3: Markdown + PDF Output Generation
# =====================================================================
log("\n" + "=" * 60)
log("TEST 3: Output Generation (MD + PDF)")
log("=" * 60)

from streamdoc.core.output import build_outputs

# Clean old outputs before regenerating
out_dir = Path("c:/Users/alexn/projects/StreamDoc/data/Outputs/targeted_test")
if out_dir.exists():
    for f in out_dir.glob("*"):
        f.unlink()

md_path, pdf_path = build_outputs(
    video_id="n8H8P64x9Mc",
    title="SPY & QQQ Dumped: Why I'm Buying This Dip (MAG7 Breakdown)",
    channel_title="Traders Helping Traders",
    source_url="https://www.youtube.com/watch?v=n8H8P64x9Mc",
    published_at=datetime.now(timezone.utc).isoformat(),
    transcript=segments if 'segments' in dir() else [],
    frames=frames if frames else [],
    preset_name="targeted_test",
    prompt_md="Analyze this trading video for key patterns and setups.",
)
log(f"MD: {md_path} ({md_path.stat().st_size} bytes)")
review_md = REVIEW_DIR / "n8H8P64x9Mc.md"
review_md.write_bytes(md_path.read_bytes())
log(f"Saved MD: {review_md}")

if pdf_path and pdf_path.exists():
    log(f"PDF: {pdf_path} ({pdf_path.stat().st_size} bytes)")
    review_pdf = REVIEW_DIR / "n8H8P64x9Mc.pdf"
    review_pdf.write_bytes(pdf_path.read_bytes())
    log(f"Saved PDF: {review_pdf}")
else:
    log("PDF generation failed")

# =====================================================================
# TEST 4: Multiple Videos Listing
# =====================================================================
log("\n" + "=" * 60)
log("TEST 4: Multiple Videos from Channel")
log("=" * 60)

from streamdoc.core.channel import resolve_channel
from streamdoc.core.fetch import _list_videos

ch = resolve_channel("https://www.youtube.com/@TradersHelpingTraders")
videos = _list_videos(ch)
log(f"Videos listed: {len(videos)}")
for v in videos[:10]:
    log(f"  {v.id}: {v.title[:60]}")

# =====================================================================
# TEST 5: Full Report
# =====================================================================
log("\n" + "=" * 60)
log("TEST 5: Full Report Generation")
log("=" * 60)

from streamdoc.core.report import compile_preset_report

# Create a fake artifact for report generation
class FakeArtifact:
    video_id = "n8H8P64x9Mc"
    title = "Live Test Video"
    channel_id = ch.id
    channel_title = ch.title
    published_at = datetime.now(timezone.utc)
    md_path = md_path
    pdf_path = pdf_path
    status = "ready"
    error = None

artifacts = [FakeArtifact()]
compile_preset_report("targeted_test", artifacts)
report_src = Path("c:/Users/alexn/projects/StreamDoc/data/Outputs/targeted_test/FULL_REPORT.md")
if report_src.exists():
    review_report = REVIEW_DIR / "targeted_report.md"
    review_report.write_bytes(report_src.read_bytes())
    log(f"Saved report: {review_report}")
else:
    log("Report not generated")

# =====================================================================
# Summary
# =====================================================================
log("\n" + "=" * 60)
log("COMPLETE - All outputs saved to data/LiveTest/")
log("=" * 60)
for f in sorted(REVIEW_DIR.iterdir()):
    log(f"  {f.name} ({f.stat().st_size} bytes)")

master = REVIEW_DIR / "TARGETED_TEST_RESULTS.txt"
master.write_text("\n".join(REPORT), encoding="utf-8")
log(f"\nSaved master report: {master}")
