"""Focused live test for single video n8H8P64x9Mc."""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# Setup
TMP_DIR = Path(tempfile.mkdtemp(prefix="streamdoc_focused_"))
REVIEW_DIR = Path("c:/Users/alexn/projects/StreamDoc/data/LiveTest")
REVIEW_DIR.mkdir(parents=True, exist_ok=True)

os.environ["STREAMDOC_DB_PATH"] = str(TMP_DIR / "state" / "streamdoc.sqlite")
os.environ["STREAMDOC_MEDIA_ROOT"] = str(TMP_DIR / "media")
os.environ["STREAMDOC_OUTPUT_ROOT"] = str(TMP_DIR / "outputs")
os.environ["STREAMDOC_MODEL_ROOT"] = str(TMP_DIR / "models")
os.environ["STREAMDOC_PRESETS_PATH"] = str(TMP_DIR / "presets")
os.environ["STREAMDOC_LOG_LEVEL"] = "INFO"
os.environ["STREAMDOC_YT_DLP_BYPASS_MODE"] = "default"

for sub in ("media", "outputs", "state", "models", "presets"):
    (TMP_DIR / sub).mkdir(parents=True, exist_ok=True)

# Reset DB engine
import streamdoc.db as db_mod
if db_mod._engine is not None:
    db_mod._engine.dispose()
    db_mod._engine = None
    db_mod._session_factory = None

from streamdoc.core.channel import resolve_channel
from streamdoc.core.fetch import run_fetch
from streamdoc.db import init_db, session_scope
from streamdoc.models.preset import Preset
from streamdoc.models.video import Video as VideoModel
from streamdoc.core.frames import extract_and_dedup
from streamdoc.core.transcript import fallback_audio_to_wav, transcribe_audio
from streamdoc.core.report import compile_preset_report

init_db()

REAL_CHANNEL_HANDLE = "https://www.youtube.com/@TradersHelpingTraders"
REAL_VIDEO_ID = "n8H8P64x9Mc"

REPORT = []

def log(msg):
    print(msg)
    REPORT.append(msg)

# =====================================================================
# TEST 1: Channel Resolution
# =====================================================================
log("\n" + "="*60)
log("TEST 1: Channel Resolution")
log("="*60)
channel = resolve_channel(REAL_CHANNEL_HANDLE)
log(f"  ID: {channel.id}")
log(f"  Title: {channel.title}")
assert channel.id.startswith("UC")
log("  PASS")

# =====================================================================
# TEST 2: Single Video Pipeline (lookback=1 hour to limit scope)
# =====================================================================
log("\n" + "="*60)
log("TEST 2: Single Video Pipeline")
log("="*60)
preset_id = "focused_single_video"
p = Preset(
    id=preset_id,
    name=preset_id,
    channel_list_id=REAL_CHANNEL_HANDLE,
    prompt_md="Analyze this trading video.",
    outputs="pdf,markdown",
    lookback_hours=1,  # Very small to limit downloads
    skip_processed=False,
    active=True,
)
with session_scope() as s:
    s.merge(p)

artifacts = run_fetch(preset_id)
log(f"Artifacts: {len(artifacts)}")
for a in artifacts[:5]:
    log(f"  {a.video_id}: status={a.status}")

# =====================================================================
# TEST 3: Check target video processed
# =====================================================================
log("\n" + "="*60)
log("TEST 3: Target Video Check")
log("="*60)
target = next((a for a in artifacts if a.video_id == REAL_VIDEO_ID), None)
if target:
    log(f"Target found: {target.video_id}")
    log(f"Status: {target.status}")
    if target.md_path and target.md_path.exists():
        log(f"MD: {target.md_path.stat().st_size} bytes")
        review_md = REVIEW_DIR / f"{REAL_VIDEO_ID}.md"
        review_md.write_bytes(target.md_path.read_bytes())
        log(f"Saved MD: {review_md}")
    if target.pdf_path and target.pdf_path.exists():
        log(f"PDF: {target.pdf_path.stat().st_size} bytes")
        review_pdf = REVIEW_DIR / f"{REAL_VIDEO_ID}.pdf"
        review_pdf.write_bytes(target.pdf_path.read_bytes())
        log(f"Saved PDF: {review_pdf}")
else:
    log(f"Target {REAL_VIDEO_ID} NOT in artifacts")

# =====================================================================
# TEST 4: Frame Extraction
# =====================================================================
log("\n" + "="*60)
log("TEST 4: Frame Extraction")
log("="*60)
media_dir = Path(os.environ["STREAMDOC_MEDIA_ROOT"])
webm_files = list(media_dir.rglob("*.webm"))
if webm_files:
    test_video = webm_files[0]
    log(f"Testing on: {test_video.name}")
    try:
        frames = extract_and_dedup(test_video)
        log(f"Unique frames: {len(frames)}")
        if frames:
            sample = REVIEW_DIR / "sample_frame.jpg"
            sample.write_bytes(frames[0].read_bytes())
            log(f"Saved sample: {sample}")
    except Exception as exc:
        log(f"Frame extraction failed: {exc}")
else:
    log("No media files found")

# =====================================================================
# TEST 5: Audio + Whisper
# =====================================================================
log("\n" + "="*60)
log("TEST 5: Audio Extraction + Whisper")
log("="*60)
if webm_files:
    test_video = webm_files[0]
    wav_path = TMP_DIR / "test.wav"
    try:
        fallback_audio_to_wav(test_video, wav_path)
        log(f"WAV: {wav_path.stat().st_size} bytes")
        transcript = transcribe_audio(wav_path, languages=["en"])
        log(f"Segments: {len(transcript)}")
        for seg in transcript[:3]:
            log(f"  [{seg['start']:.1f}s] {seg['text'][:60]}")
        review_tx = REVIEW_DIR / "whisper_transcript.txt"
        review_tx.write_text("\n".join(f"[{s['start']:.1f}s] {s['text']}" for s in transcript), encoding="utf-8")
        log(f"Saved transcript: {review_tx}")
    except Exception as exc:
        log(f"Audio/Whisper failed: {exc}")
else:
    log("No media for audio test")

# =====================================================================
# TEST 6: Full Report
# =====================================================================
log("\n" + "="*60)
log("TEST 6: Full Report")
log("="*60)
compile_preset_report(preset_id, artifacts)
report_path = Path(os.environ["STREAMDOC_OUTPUT_ROOT"]) / preset_id / "report.md"
if report_path.exists():
    log(f"Report: {report_path}")
    review_report = REVIEW_DIR / "focused_report.md"
    review_report.write_bytes(report_path.read_bytes())
    log(f"Saved: {review_report}")
else:
    log("Report not found")

# =====================================================================
# TEST 7: DB State
# =====================================================================
log("\n" + "="*60)
log("TEST 7: Database State")
log("="*60)
with session_scope() as s:
    vids = s.query(VideoModel).all()
    log(f"Videos in DB: {len(vids)}")
    for v in vids[:5]:
        log(f"  {v.id}: media={v.media_status} tx={v.transcript_status} out={v.output_status}")

# =====================================================================
# Save Report
# =====================================================================
log("\n" + "="*60)
log("COMPLETE")
log("="*60)
master = REVIEW_DIR / "FOCUSED_TEST_RESULTS.txt"
master.write_text("\n".join(REPORT), encoding="utf-8")
log(f"Saved: {master}")
log(f"Review dir: {REVIEW_DIR}")
for f in sorted(REVIEW_DIR.iterdir()):
    log(f"  {f.name} ({f.stat().st_size} bytes)")
