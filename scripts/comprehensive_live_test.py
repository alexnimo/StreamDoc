"""Comprehensive live test — REAL multi-video, multi-channel pipeline.

This test exercises the FULL end-to-end pipeline on real YouTube videos:
- Downloads videos from multiple channels
- Extracts + deduplicates frames using the configurable pipeline
- Transcribes audio
- Builds per-video Markdown / PDF outputs
- Compiles a REAL omnibus session report with all processed videos
- Tests processed-video skip, date-range filtering, playlist mode, dedup stages

All outputs are saved to data/LiveTest/ for manual review.
"""
from __future__ import annotations

import logging
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("comprehensive_test")

# ---------------------------------------------------------------------------
# 0. Setup
# ---------------------------------------------------------------------------
REVIEW_DIR = Path("c:/Users/alexn/projects/StreamDoc/data/LiveTest")
REVIEW_DIR.mkdir(parents=True, exist_ok=True)
REPORT: list[str] = []


def log(msg: str) -> None:
    print(msg)
    REPORT.append(msg)


log("=" * 70)
log("COMPREHENSIVE LIVE TEST — Real Multi-Video + All Features")
log(f"Started: {datetime.now(timezone.utc).isoformat()}")
log("=" * 70)

# ---------------------------------------------------------------------------
# 1. Settings & Config Verification
# ---------------------------------------------------------------------------
log("\n" + "=" * 70)
log("TEST 1: Settings Verification")
log("=" * 70)

from streamdoc.config import settings

log(f"video_resolution: {settings.video_resolution}")
log(f"frame_min_interval_s: {settings.frame_min_interval_s}")
log(f"frame_hash_threshold: {settings.frame_hash_threshold}")
log(f"frame_dedup_mode: {settings.frame_dedup_mode}")
log(f"frame_dedup_window: {settings.frame_dedup_window}")
log(f"frame_dedup_pipeline: {settings.frame_dedup_pipeline}")
log(f"frame_motion_threshold: {settings.frame_motion_threshold}")
log(f"frame_ssim_threshold: {settings.frame_ssim_threshold}")
log(f"frame_hist_threshold: {settings.frame_hist_threshold}")

# Temporarily shorten interval for fast testing
settings.frame_min_interval_s = 3.0
settings.frame_hash_threshold = 6
log(f"(Test override) frame_min_interval_s: {settings.frame_min_interval_s}")
log(f"(Test override) frame_hash_threshold: {settings.frame_hash_threshold}")

# ---------------------------------------------------------------------------
# 2. Multi-Channel Video Listing
# ---------------------------------------------------------------------------
log("\n" + "=" * 70)
log("TEST 2: Multi-Channel Video Listing")
log("=" * 70)

from streamdoc.core.channel import resolve_channel
from streamdoc.core.fetch import _list_videos

CHANNELS = [
    "https://www.youtube.com/@TradersHelpingTraders",
    "https://www.youtube.com/@McNallieMoney",
    "https://www.youtube.com/@JosephCarlsonShow",
]

channel_map: dict = {}
all_videos: list = []
for url in CHANNELS:
    try:
        ch = resolve_channel(url)
        channel_map[ch.id] = ch
        log(f"\nChannel: {ch.title} ({ch.id})")
        vids = _list_videos(ch, max_videos=5)
        log(f"  Listed {len(vids)} videos")
        for v in vids[:3]:
            log(f"    {v.id}: {v.title[:55]} ({v.duration_seconds or 0}s)")
        all_videos.extend(vids)
    except Exception as exc:
        log(f"  ERROR listing {url}: {exc}")

log(f"\nTotal videos listed across all channels: {len(all_videos)}")

# ---------------------------------------------------------------------------
# 3. Text Filtering
# ---------------------------------------------------------------------------
log("\n" + "=" * 70)
log("TEST 3: Text Filtering")
log("=" * 70)

if all_videos:
    filter_term = "market"
    matched = [v for v in all_videos if filter_term.lower() in v.title.lower()]
    log(f"Filter '{filter_term}': {len(matched)} / {len(all_videos)} videos matched")
    for v in matched[:3]:
        log(f"  MATCH: {v.id}: {v.title[:55]}")

# ---------------------------------------------------------------------------
# 4. Date Range Filtering
# ---------------------------------------------------------------------------
log("\n" + "=" * 70)
log("TEST 4: Date Range Filtering")
log("=" * 70)

from streamdoc.core.fetch import _parse_published

cutoff = datetime.now(timezone.utc) - timedelta(days=7)
recent = [v for v in all_videos if _parse_published(v.published_at) >= cutoff]
log(f"Videos published in last 7 days: {len(recent)} / {len(all_videos)}")

# ---------------------------------------------------------------------------
# 5. Playlist Mode Detection
# ---------------------------------------------------------------------------
log("\n" + "=" * 70)
log("TEST 5: Playlist Mode Detection")
log("=" * 70)

from streamdoc.core.fetch import _is_playlist_url

playlist_urls = [
    "https://www.youtube.com/playlist?list=PLsomeplaylist",
    "https://www.youtube.com/watch?v=abc123&list=PLsomeplaylist",
    "https://www.youtube.com/@TradersHelpingTraders",
]
for url in playlist_urls:
    is_pl = _is_playlist_url(url)
    log(f"  {is_pl} — {url[:60]}")

# ---------------------------------------------------------------------------
# 6. Pick target videos for REAL processing
# ---------------------------------------------------------------------------
# Strategy: pick the shortest video from each of two different channels
# to keep test time reasonable.

TRADERS_CH = channel_map.get("UCMno7bbQKigk6RxiO0uv78g")
JOSEPH_CH = channel_map.get("UCbta0n8i6Rljh0obO7HzG9A")
MCNALLIE_CH = channel_map.get("UCo9gS6UhUVw05pRvuN33h6w")

targets: list[tuple] = []

# Traders Helping Traders — we already have n8H8P64x9Mc downloaded
TRADERS_DIR = Path("c:/Users/alexn/projects/StreamDoc/data/Media/UCMno7bbQKigk6RxiO0uv78g/UCMno7bbQKigk6RxiO0uv78g")
existing_traders = [f for f in TRADERS_DIR.glob("*.webm")] if TRADERS_DIR.exists() else []
if existing_traders:
    # Use the shortest existing video
    existing_traders.sort(key=lambda p: p.stat().st_size)
    traders_video = existing_traders[0]
    traders_vid_id = traders_video.stem
    log(f"\nUsing existing Traders video: {traders_vid_id} ({traders_video.stat().st_size} bytes)")
    targets.append((traders_vid_id, "Traders Helping Traders", traders_video, TRADERS_CH))

# Joseph Carlson — try to find a short one and download it
if JOSEPH_CH:
    joseph_vids = [v for v in all_videos if v.channel_id == JOSEPH_CH.id]
    if joseph_vids:
        joseph_vids.sort(key=lambda v: v.duration_seconds or float("inf"))
        joseph_target = joseph_vids[0]
        log(f"\nJoseph target: {joseph_target.id} — {joseph_target.title[:55]} ({joseph_target.duration_seconds}s)")
        targets.append((joseph_target.id, "Joseph Carlson", None, JOSEPH_CH))

# McNallie Money — fallback if Joseph has no short videos
if len(targets) < 2 and MCNALLIE_CH:
    mcnallie_vids = [v for v in all_videos if v.channel_id == MCNALLIE_CH.id]
    if mcnallie_vids:
        mcnallie_vids.sort(key=lambda v: v.duration_seconds or float("inf"))
        mcnallie_target = mcnallie_vids[0]
        log(f"\nMcNallie target: {mcnallie_target.id} — {mcnallie_target.title[:55]} ({mcnallie_target.duration_seconds}s)")
        targets.append((mcnallie_target.id, "McNallie Money", None, MCNALLIE_CH))

log(f"\nTotal target videos for full processing: {len(targets)}")

# ---------------------------------------------------------------------------
# 7. Process each target video end-to-end
# ---------------------------------------------------------------------------
log("\n" + "=" * 70)
log("TEST 6: Full Pipeline — Download / Frames / Dedup / Transcript / Output")
log("=" * 70)

from streamdoc.core.downloader import download
from streamdoc.core.frames import extract_frames, dedup_frames
from streamdoc.core.transcript import fallback_audio_to_wav, transcribe_audio
from streamdoc.core.output import build_outputs
from streamdoc.core.fetch import RunArtifact

out_dir = Path("c:/Users/alexn/projects/StreamDoc/data/Outputs/comprehensive_test")
if out_dir.exists():
    shutil.rmtree(out_dir)
out_dir.mkdir(parents=True, exist_ok=True)

artifacts: list[RunArtifact] = []

for vid_id, ch_title, existing_path, ch_obj in targets:
    log(f"\n--- Processing {vid_id} ({ch_title}) ---")

    video_path: Path | None = existing_path

    # Download if not already present
    if video_path is None or not video_path.exists():
        try:
            media_ch_dir = Path(settings.media_root) / ch_obj.id / ch_obj.id
            media_ch_dir.mkdir(parents=True, exist_ok=True)
            output_tpl = str(media_ch_dir / "%(id)s.%(ext)s")
            url = f"https://www.youtube.com/watch?v={vid_id}"
            log(f"  Downloading {url} ...")
            result = download(url, output_tpl)
            if result.returncode == 0:
                # Find downloaded file
                candidates = list(media_ch_dir.glob(f"{vid_id}.*"))
                if candidates:
                    video_path = candidates[0]
                    log(f"  Downloaded: {video_path.name}")
                else:
                    log(f"  WARNING: download succeeded but file not found")
                    continue
            else:
                log(f"  Download failed: {result.stderr[:200]}")
                continue
        except Exception as exc:
            log(f"  Download error: {exc}")
            continue

    if not video_path or not video_path.exists():
        log(f"  Skipping — no video file")
        continue

    # Frames
    log(f"  Extracting frames ...")
    raw_frames = extract_frames(video_path)
    log(f"  Raw frames: {len(raw_frames)}")

    # Test each dedup stage independently
    for pipeline in ["phash", "motion,phash", "motion,phash,ssim", "motion,phash,ssim,hist", "motion,phash,ssim,hist,variance"]:
        settings.frame_dedup_pipeline = pipeline
        kept = dedup_frames(raw_frames)
        log(f"  Dedup [{pipeline:35s}] -> {len(kept):3d} frames")

    # Restore full pipeline for final output
    settings.frame_dedup_pipeline = "motion,phash,ssim,hist,variance"
    final_kept = dedup_frames(raw_frames)
    log(f"  Final kept frames: {len(final_kept)}")

    # Save a few review frames
    for i, f in enumerate(final_kept[:6], start=1):
        review = REVIEW_DIR / f"{vid_id}_frame_{i:02d}.jpg"
        review.write_bytes(f.read_bytes())

    # Transcription
    log(f"  Transcribing ...")
    wav_path = REVIEW_DIR / f"{vid_id}_audio.wav"
    if not wav_path.exists():
        try:
            fallback_audio_to_wav(video_path, wav_path)
        except Exception as exc:
            log(f"  Audio extraction failed: {exc}")
    segments = []
    if wav_path.exists():
        try:
            segments = transcribe_audio(wav_path, languages=["en"])
        except Exception as exc:
            log(f"  Transcription failed: {exc}")
    combined = " ".join(seg.get("text", "").strip() for seg in segments if seg.get("text", "").strip())
    word_count = len(combined.split())
    log(f"  Transcript: {len(segments)} segments, {word_count} words")

    # Per-video output
    log(f"  Building outputs ...")
    try:
        md_path, pdf_path = build_outputs(
            video_id=vid_id,
            title=ch_obj.title if ch_obj else vid_id,
            channel_title=ch_title,
            source_url=f"https://www.youtube.com/watch?v={vid_id}",
            published_at=datetime.now(timezone.utc).isoformat(),
            transcript=segments,
            frames=final_kept,
            preset_name="comprehensive_test",
            prompt_md="Analyze trading patterns and market sentiment.",
        )
        log(f"  MD: {md_path.name} ({md_path.stat().st_size} bytes)")
        if pdf_path and pdf_path.exists():
            log(f"  PDF: {pdf_path.name} ({pdf_path.stat().st_size} bytes)")
        else:
            log(f"  PDF: FAILED")
            pdf_path = None
    except Exception as exc:
        log(f"  Output build failed: {exc}")
        md_path = out_dir / f"{vid_id}.md"
        md_path.write_text(f"# {vid_id}\n\nBuild failed: {exc}", encoding="utf-8")
        pdf_path = None

    # Build artifact
    dur = 0
    try:
        from streamdoc.core.frames import _probe_duration_seconds
        dur = int(_probe_duration_seconds(video_path))
    except Exception:
        pass

    artifacts.append(
        RunArtifact(
            video_id=vid_id,
            md_path=md_path,
            pdf_path=pdf_path,
            status="ready",
            title=ch_obj.title if ch_obj else vid_id,
            channel_title=ch_title,
            duration_seconds=dur,
            frame_count=len(final_kept),
            transcript_word_count=word_count,
            transcript_text=combined[:2000],
            frame_paths=final_kept[:3],
        )
    )

log(f"\nProcessed {len(artifacts)} real videos end-to-end")

# ---------------------------------------------------------------------------
# 8. Processed Video Skip Test
# ---------------------------------------------------------------------------
log("\n" + "=" * 70)
log("TEST 7: Processed Video Skip")
log("=" * 70)

from streamdoc.db import init_db, session_scope
from streamdoc.models.video import Video as VideoModel
from streamdoc.core.fetch import _is_processed

init_db()

if targets:
    vid_id, _, _, ch_obj = targets[0]
    with session_scope() as session:
        # Ensure video exists in DB
        existing = session.query(VideoModel).filter_by(id=vid_id).first()
        if existing:
            existing.processed_at = datetime.now(timezone.utc)
            session.commit()
            log(f"Marked {vid_id} as processed in DB")
        else:
            # Insert a stub record so skip logic can be tested
            stub = VideoModel(
                id=vid_id,
                channel_id=ch_obj.id if ch_obj else "unknown",
                title="Test stub",
                published_at=datetime.now(timezone.utc).isoformat(),
                processed_at=datetime.now(timezone.utc),
            )
            session.add(stub)
            session.commit()
            log(f"Inserted stub for {vid_id} and marked processed")

    skipped = _is_processed(vid_id)
    log(f"_is_processed({vid_id}) = {skipped}")

# ---------------------------------------------------------------------------
# 9. Build REAL Multi-Video Session Report
# ---------------------------------------------------------------------------
log("\n" + "=" * 70)
log("TEST 8: Enhanced Session Report (Multi-Video REAL)")
log("=" * 70)

from streamdoc.core.report import compile_preset_report

if artifacts:
    report_path = compile_preset_report("comprehensive_test", artifacts)
    if report_path and report_path.exists():
        log(f"Session report: {report_path} ({report_path.stat().st_size} bytes)")
        review_report = REVIEW_DIR / "comprehensive_report.md"
        review_report.write_bytes(report_path.read_bytes())
        log(f"Saved review copy: {review_report}")
    else:
        log("Report generation failed")
else:
    log("No artifacts — report skipped")

# ---------------------------------------------------------------------------
# 10. Resolution Selector
# ---------------------------------------------------------------------------
log("\n" + "=" * 70)
log("TEST 9: Resolution Selector")
log("=" * 70)

from streamdoc.core.downloader import _format_selector

for res in ["1080", "720", "480", "best"]:
    settings.video_resolution = res
    settings.video_format_fallback = True
    sel = _format_selector()
    log(f"  {res}: {sel[:70]}...")
settings.video_resolution = "1080"

# ---------------------------------------------------------------------------
# 11. Summary
# ---------------------------------------------------------------------------
log("\n" + "=" * 70)
log("COMPLETE — All tests finished")
log("=" * 70)

for f in sorted(REVIEW_DIR.iterdir()):
    log(f"  {f.name} ({f.stat().st_size} bytes)")

master = REVIEW_DIR / "COMPREHENSIVE_TEST_RESULTS.txt"
master.write_text("\n".join(REPORT), encoding="utf-8")
log(f"\nSaved master report: {master}")
