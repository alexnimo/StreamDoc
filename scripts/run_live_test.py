"""Manual live verification script for video n8H8P64x9Mc and @TradersHelpingTraders."""
from __future__ import annotations

import logging
import os
import sys
import tempfile
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

# Create isolated temp environment
tmp_dir = Path(tempfile.mkdtemp(prefix="streamdoc_live_"))
print(f"Using temp directory: {tmp_dir}")

os.environ["STREAMDOC_DB_PATH"] = str(tmp_dir / "state" / "streamdoc.sqlite")
os.environ["STREAMDOC_MEDIA_ROOT"] = str(tmp_dir / "media")
os.environ["STREAMDOC_OUTPUT_ROOT"] = str(tmp_dir / "outputs")
os.environ["STREAMDOC_MODEL_ROOT"] = str(tmp_dir / "models")
os.environ["STREAMDOC_PRESETS_PATH"] = str(tmp_dir / "presets")
os.environ["STREAMDOC_LOG_LEVEL"] = "INFO"
os.environ["STREAMDOC_YT_DLP_BYPASS_MODE"] = "default"

for sub in ("media", "outputs", "state", "models", "presets"):
    (tmp_dir / sub).mkdir(parents=True, exist_ok=True)

# Reset any cached db engine
import streamdoc.db as db_mod
if db_mod._engine is not None:
    db_mod._engine.dispose()
    db_mod._engine = None
    db_mod._session_factory = None

# Reimport fresh
from streamdoc.core.channel import resolve_channel, Channel
from streamdoc.core.fetch import run_fetch, _list_videos
from streamdoc.db import init_db, session_scope
from streamdoc.models.preset import Preset
from streamdoc.models.video import Video as VideoModel

init_db()

REAL_CHANNEL_HANDLE = "https://www.youtube.com/@TradersHelpingTraders"
REAL_VIDEO_ID = "n8H8P64x9Mc"

print("\n" + "=" * 60)
print("TEST 1: Channel Resolution")
print("=" * 60)
channel = resolve_channel(REAL_CHANNEL_HANDLE)
print(f"  Channel ID: {channel.id}")
print(f"  Channel Title: {channel.title}")
assert isinstance(channel, Channel)
assert channel.id.startswith("UC")
print("  PASS")

print("\n" + "=" * 60)
print("TEST 2: List Videos from Channel")
print("=" * 60)
videos = _list_videos(channel)
print(f"  Found {len(videos)} videos")
for v in videos[:3]:
    print(f"    - {v.id}: {v.title[:60]}")
assert len(videos) > 0
print("  PASS")

print("\n" + "=" * 60)
print("TEST 3: Single Video Pipeline (n8H8P64x9Mc)")
print("=" * 60)
preset_id = "live_single_video"
p = Preset(
    id=preset_id,
    name=preset_id,
    channel_list_id=REAL_CHANNEL_HANDLE,
    prompt_md="Analyze this trading video for key strategies and indicators.",
    outputs="pdf,markdown",
    lookback_hours=8760,
    skip_processed=False,
    active=True,
)
with session_scope() as s:
    s.merge(p)

artifacts = run_fetch(preset_id)
target_art = next((a for a in artifacts if a.video_id == REAL_VIDEO_ID), None)
if target_art is None:
    print(f"  Video {REAL_VIDEO_ID} was NOT processed. Artifacts: {[a.video_id for a in artifacts]}")
    print("  Looking for similar IDs...")
    for a in artifacts:
        if REAL_VIDEO_ID in a.video_id or a.video_id in REAL_VIDEO_ID:
            print(f"    Potential match: {a.video_id}")
else:
    print(f"  Video {REAL_VIDEO_ID} processed!")
    print(f"  Status: {target_art.status}")
    print(f"  MD path: {target_art.md_path}")
    print(f"  PDF path: {target_art.pdf_path}")
    if target_art.md_path and target_art.md_path.exists():
        print(f"  MD size: {target_art.md_path.stat().st_size} bytes")
    if target_art.pdf_path and target_art.pdf_path.exists():
        print(f"  PDF size: {target_art.pdf_path.stat().st_size} bytes")

print("\n" + "=" * 60)
print("TEST 4: Multiple Videos / Recent Preset")
print("=" * 60)
preset_id2 = "live_recent"
p2 = Preset(
    id=preset_id2,
    name="Recent Videos",
    channel_list_id=REAL_CHANNEL_HANDLE,
    prompt_md="Focus on the specific trade entries and exits mentioned.",
    outputs="markdown",
    lookback_hours=168,
    skip_processed=False,
    active=True,
)
with session_scope() as s:
    s.merge(p2)

artifacts2 = run_fetch(preset_id2)
print(f"  Found {len(artifacts2)} recent videos")
for art in artifacts2[:3]:
    print(f"    - {art.video_id}: status={art.status}")
    if art.md_path and art.md_path.exists():
        print(f"      MD: {art.md_path.stat().st_size} bytes")

print("\n" + "=" * 60)
print("TEST 5: Frame Extraction Check")
print("=" * 60)
media_dir = Path(os.environ["STREAMDOC_MEDIA_ROOT"])
frame_dirs = list(media_dir.rglob("frames"))
print(f"  Found {len(frame_dirs)} frame directories")
for fd in frame_dirs[:3]:
    frames = list(fd.glob("*.jpg"))
    print(f"    {fd}: {len(frames)} frames")
    for f in frames[:3]:
        print(f"      - {f.name} ({f.stat().st_size} bytes)")

print("\n" + "=" * 60)
print("TEST 6: Database State")
print("=" * 60)
with session_scope() as s:
    vids = s.query(VideoModel).all()
    print(f"  Total videos in DB: {len(vids)}")
    for v in vids[:5]:
        print(f"    - {v.id}: {v.title[:50]}... status={v.media_status}/{v.transcript_status}/{v.output_status}")

print("\n" + "=" * 60)
print("TEST 7: Full Report")
print("=" * 60)
from streamdoc.core.report import compile_preset_report
compile_preset_report("live_single_video", artifacts)
report_path = Path(os.environ["STREAMDOC_OUTPUT_ROOT"]) / "live_single_video" / "report.md"
if report_path.exists():
    print(f"  Report: {report_path}")
    print(f"  Size: {report_path.stat().st_size} bytes")
    print(f"  Preview (first 500 chars):")
    print(report_path.read_text()[:500])
else:
    print(f"  Report not found at {report_path}")

print("\n" + "=" * 60)
print("ALL LIVE TESTS COMPLETE")
print(f"Temp directory: {tmp_dir}")
print("=" * 60)
