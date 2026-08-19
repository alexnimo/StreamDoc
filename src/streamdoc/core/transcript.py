"""
Transcript pipeline: official API first, Whisper fallback second.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Sequence

from streamdoc.config import settings

logger = logging.getLogger(__name__)

TRANSCRIPT_SUPPORTED_LANGUAGES: list[str] = [
    lang.strip() for lang in settings.transcript_languages.split(",") if lang.strip()
]


def _fetched_to_dicts(fetched) -> list[dict]:
    """Convert a FetchedTranscript iterable to the dict format used internally.

    Reason: youtube-transcript-api v1.x returns FetchedTranscriptSnippet
    objects with .text/.start/.duration attributes, while the rest of the
    pipeline expects plain dicts. Older versions (0.6.x) returned dicts
    directly, so this helper normalizes both shapes.

    Args:
        fetched: A FetchedTranscript (iterable of snippets) or a list of dicts.

    Returns:
        List of dicts with keys: text, start, duration.
    """
    out: list[dict] = []
    for snip in fetched:
        if isinstance(snip, dict):
            out.append({
                "text": snip.get("text", ""),
                "start": float(snip.get("start", 0.0)),
                "duration": float(snip.get("duration", 0.0)),
            })
        else:
            # Reason: v1.x snippet objects — use attribute access.
            out.append({
                "text": getattr(snip, "text", ""),
                "start": float(getattr(snip, "start", 0.0)),
                "duration": float(getattr(snip, "duration", 0.0)),
            })
    return out


def _transcript_from_official(video_id: str, languages: Sequence[str]) -> list[dict] | None:
    """Attempt to fetch transcript via youtube-transcript-api.

    Reason: youtube-transcript-api v1.x renamed ``get_transcript`` to
    ``fetch`` and changed the return type from list[dict] to
    FetchedTranscript (iterable of snippet objects). The previous code
    called the non-existent ``get_transcript``, which raised
    AttributeError on every call — silently caught by the bare except,
    forcing Whisper fallback on every single video.

    This implementation tries the configured languages first, then falls
    back to fetching any available transcript (first from the list) so
    that non-English videos with only auto-generated captions are still
    served by the official API instead of Whisper.

    Args:
        video_id: YouTube video ID.
        languages: Preferred language codes in priority order.

    Returns:
        List of transcript segments (normalized dicts), or None if
        unavailable.
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        api = YouTubeTranscriptApi()
        # Reason: try the configured language filter first.
        try:
            fetched = api.fetch(video_id, languages=list(languages))
            return _fetched_to_dicts(fetched) or None
        except Exception as lang_exc:
            # Reason: NoTranscriptFound means the video has captions but
            # none in the requested languages. Try fetching ANY available
            # transcript (first one from the list) before giving up.
            logger.debug(
                "Transcript fetch with languages=%s failed for %s: %s — trying any language",
                list(languages), video_id, lang_exc,
            )
            try:
                available = api.list(video_id)
                # Reason: pick the first transcript (manual preferred over
                # auto-generated, since list() returns manual first).
                for t in available:
                    fetched = t.fetch()
                    return _fetched_to_dicts(fetched) or None
            except Exception as any_exc:
                logger.debug("Any-language transcript fetch also failed for %s: %s", video_id, any_exc)
        return None
    except Exception as exc:
        logger.debug("Official transcript fetch failed for %s: %s", video_id, exc)
        return None


def _normalize_items(items: list[dict], max_gap_s: float = 2.0) -> list[dict]:
    """Merge short transcript segments that are close together.

    Args:
        items: Raw transcript segments with start, duration, text.
        max_gap_s: Maximum gap in seconds to merge adjacent segments.

    Returns:
        Merged transcript segments.
    """
    merged = []
    buf = None
    for it in items:
        text = it.get("text", "").replace("\n", " ")
        if not text:
            continue
        if buf is None:
            buf = {"start": it.get("start", 0.0), "duration": it.get("duration", 0.0), "text": text}
            continue
        gap = float(it.get("start", 0.0)) - (buf["start"] + buf["duration"])
        if gap <= max_gap_s:
            buf["text"] += " " + text
            buf["duration"] = (float(it.get("start", 0.0)) + float(it.get("duration", 0.0))) - buf["start"]
        else:
            merged.append(buf)
            buf = {"start": it.get("start", 0.0), "duration": it.get("duration", 0.0), "text": text}
    if buf is not None:
        merged.append(buf)
    return merged


def _transcript_from_yt_dlp_subtitles(video_id: str, languages: Sequence[str]) -> list[dict] | None:
    """Fetch subtitles via yt-dlp as a fallback when the official API fails.

    Reason: youtube-transcript-api makes unauthenticated HTTP calls to
    YouTube's timedtext endpoint. When YouTube rate-limits or blocks
    those calls, yt-dlp can reach the same endpoint using the configured
    cookie jar / PO-token bypass mode. The subtitle data is the SAME
    data the official API would return — no quality difference. This is
    only used when ``settings.use_yt_dlp_subtitles`` is True.

    Args:
        video_id: YouTube video ID.
        languages: Preferred language codes in priority order.

    Returns:
        List of transcript segments (normalized dicts), or None if
        unavailable.
    """
    if not settings.use_yt_dlp_subtitles:
        return None

    import tempfile
    import yt_dlp
    from streamdoc.core.downloader import _resolve_cookie_path

    tmpdir = tempfile.mkdtemp(prefix="ytdlp_subs_")
    # Reason: yt-dlp writes subtitle files to disk using the outtmpl.
    # We use a temp dir and read the json3 file back after download.
    opts: dict = {
        "quiet": True,
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": list(languages) + ["en"],
        "subtitlesformat": "json3",
        "outtmpl": f"{tmpdir}/{video_id}",
    }
    mode = settings.yt_dlp_bypass_mode
    if mode == "po_token":
        opts["extractor_args"] = {"youtube": {"player_client": ["default", "web"], "pot_provider": ["bgutil"]}}
    if mode == "web_embedded":
        opts["extractor_args"] = {"youtube": {"player_client": ["web_embedded"]}}
    cookie = _resolve_cookie_path()
    if cookie and mode == "cookie":
        opts["cookiefile"] = str(cookie)

    url = f"https://www.youtube.com/watch?v={video_id}"
    logger.debug("Fetching subtitles via yt-dlp for %s", video_id)
    try:
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
        except Exception as dl_exc:
            # Reason: yt-dlp raises if ANY requested language fails (e.g.
            # 429 Too Many Requests for ar/he). But it may still have
            # downloaded the en subtitle before failing. Check for files
            # on disk regardless of the download exception.
            logger.debug("yt-dlp subtitle download raised for %s: %s — checking for partial files", video_id, dl_exc)
        # Reason: find the downloaded json3 subtitle file. yt-dlp names
        # files as <video_id>.<lang>.<format> e.g. dQw4w9WgXcQ.en.json3
        import glob
        candidates = sorted(glob.glob(f"{tmpdir}/{video_id}.*.json3"))
        if not candidates:
            logger.debug("No json3 subtitle file found for %s", video_id)
            return None
        # Reason: prefer the file matching the first configured language,
        # else fall back to the first available file.
        for lang in languages:
            for c in candidates:
                if f".{lang}." in c:
                    return _parse_json3_file(c)
        # Reason: no language match — use the first file (usually en).
        return _parse_json3_file(candidates[0])
    except Exception as exc:
        logger.debug("yt-dlp subtitle fetch failed for %s: %s", video_id, exc)
        return None
    finally:
        # Reason: clean up temp files.
        import shutil
        try:
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass


def _parse_json3_file(path: str) -> list[dict] | None:
    """Parse a yt-dlp json3 subtitle file into transcript segments.

    Reason: the json3 format contains a JSON object with an 'events'
    array, each having 'tStartMs', 'dDurationMs', and 'segs'
    (text segments). We convert this to the dict format used internally.

    Args:
        path: Path to the .json3 subtitle file on disk.

    Returns:
        List of dicts with keys: text, start, duration. None if parsing
        fails or no text is found.
    """
    import json

    try:
        with open(path, "r", encoding="utf-8") as f:
            parsed = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.debug("Failed to parse json3 subtitle file %s: %s", path, exc)
        return None

    events = parsed.get("events") if isinstance(parsed, dict) else None
    if not events:
        return None

    out: list[dict] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        start_ms = ev.get("tStartMs", 0)
        dur_ms = ev.get("dDurationMs", 0)
        segs = ev.get("segs") or []
        text = "".join(s.get("utf8", "") for s in segs if isinstance(s, dict))
        text = text.strip()
        if not text:
            continue
        out.append({
            "text": text,
            "start": float(start_ms) / 1000.0,
            "duration": float(dur_ms) / 1000.0,
        })
    return out if out else None


def fetch_transcript(video_id: str) -> list[dict]:
    """Fetch transcript for a video, trying official API first.

    Reason: the fallback chain is:
    1. youtube-transcript-api (official timedtext endpoint, no auth)
    2. yt-dlp subtitles (same endpoint, with cookie/PO-token bypass) —
       only when ``settings.use_yt_dlp_subtitles`` is True
    3. (Whisper fallback is handled by the caller in fetch.py)

    Args:
        video_id: YouTube video ID.

    Returns:
        Normalized transcript segments, or empty list if unavailable.
    """
    langs = TRANSCRIPT_SUPPORTED_LANGUAGES
    official = _transcript_from_official(video_id, langs)
    if official is not None:
        return _normalize_items(official)
    # Reason: try yt-dlp subtitle fallback if enabled.
    ytdlp_subs = _transcript_from_yt_dlp_subtitles(video_id, langs)
    if ytdlp_subs is not None:
        logger.info("Fetched transcript via yt-dlp subtitles for video: %s (%d segments)", video_id, len(ytdlp_subs))
        return _normalize_items(ytdlp_subs)
    return []


def fallback_audio_to_wav(input_path: Path, output_path: Path) -> Path:
    """Convert audio/video to normalized WAV using ffmpeg.

    Args:
        input_path: Source media file.
        output_path: Destination WAV path.

    Returns:
        Path to the output WAV file.
    """
    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(input_path),
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
        str(output_path),
    ]
    subprocess.run(cmd, check=True, text=True, capture_output=True)
    return output_path


def transcribe_audio(wav_path: Path, languages: Sequence[str] | None = None) -> list[dict]:
    """Transcribe audio using faster-whisper with a configurable timeout.

    Reason: Whisper on CPU can be extremely slow for long videos (30+ min
    for a 20-minute video with the "small" model). Without a timeout, a
    single slow transcription blocks the entire preset job indefinitely,
    preventing any subsequent videos from being processed and any
    NotebookLM uploads from happening. The timeout runs the transcription
    in a daemon thread and returns an empty list if the deadline is
    exceeded, allowing the job to skip the video and continue.

    Args:
        wav_path: Path to the WAV audio file.
        languages: Optional language codes to prefer.

    Returns:
        List of transcript segments with start, duration, text.
    """
    import threading

    try:
        from faster_whisper import WhisperModel
    except Exception as exc:
        logger.debug("faster-whisper import failed: %s", exc)
        return []

    timeout = settings.whisper_timeout_seconds
    result: list[dict] = []
    error: Exception | None = None
    done = threading.Event()

    def _worker() -> None:
        """Run Whisper transcription in a background thread."""
        nonlocal result, error
        try:
            model = WhisperModel(settings.whisper_model, compute_type="int8")
            segments, _info = model.transcribe(str(wav_path), beam_size=5)
            out: list[dict] = []
            for seg in segments:
                text = seg.text.strip()
                if not text:
                    continue
                out.append({"start": float(seg.start), "duration": float(seg.end - seg.start), "text": text})
            result = out
        except Exception as exc:
            error = exc
        finally:
            done.set()

    # Reason: daemon thread so it doesn't block process exit if the main
    # thread has already moved on. The thread will continue running in the
    # background but won't prevent the job from progressing.
    thread = threading.Thread(target=_worker, name="whisper-transcribe", daemon=True)
    thread.start()

    if not done.wait(timeout=timeout if timeout > 0 else None):
        logger.warning(
            "Whisper transcription timed out after %ss for %s — skipping video",
            timeout, wav_path.name,
        )
        return []

    if error:
        raise error
    return result
