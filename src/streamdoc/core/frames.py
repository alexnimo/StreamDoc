from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Sequence

import numpy as np
from PIL import Image

from streamdoc.config import settings

logger = logging.getLogger(__name__)


def _frames_dir(video_path: Path) -> Path:
    return video_path.parent / "frames"


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _probe_duration_seconds(video_path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    try:
        out = subprocess.run(cmd, check=True, text=True, capture_output=True)
        return float(out.stdout.strip())
    except Exception as exc:
        logger.debug("ffprobe failed for duration; assuming 0: %s", exc)
        return 0.0


def extract_frames(video_path: Path, max_count: int | None = None, min_interval_s: float | None = None) -> list[Path]:
    if not video_path.exists():
        return []
    max_count = max_count if max_count is not None else settings.frame_max_count
    min_interval_s = min_interval_s if min_interval_s is not None else settings.frame_min_interval_s
    duration = _probe_duration_seconds(video_path)
    if duration <= 0:
        return []
    interval = max(float(min_interval_s), duration / max_count)
    count = max(1, min(max_count, int(duration / interval)))
    out_dir = _frames_dir(video_path)
    _ensure_dir(out_dir)
    paths: list[Path] = []
    for i in range(count):
        ts = i * interval
        if ts >= duration:
            break
        out_path = out_dir / f"frame_{i:04d}.jpg"
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            f"{ts:.3f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-q:v",
            str(max(1, 101 - settings.frame_jpeg_quality)),
            str(out_path),
        ]
        try:
            subprocess.run(cmd, check=True, text=True, capture_output=True)
        except Exception as exc:
            logger.debug("ffmpeg frame extraction failed: %s", exc)
            continue
        if out_path.exists():
            paths.append(out_path)
    return paths


def _hash_frame(path: Path, algo: str):
    import imagehash

    with Image.open(path) as img:
        img = img.convert("RGB")
        if algo == "dhash":
            return imagehash.dhash(img)
        if algo == "ahash":
            return imagehash.average_hash(img)
        return imagehash.phash(img)


def _load_gray_array(path: Path, size: tuple[int, int] = (128, 128)) -> np.ndarray:
    """Load image as a normalized grayscale numpy array."""
    with Image.open(path) as img:
        return np.array(img.convert("L").resize(size, Image.Resampling.LANCZOS), dtype=np.float32) / 255.0


def _motion_score(path_a: Path, path_b: Path) -> float:
    """Mean absolute pixel difference between two frames (0-255 scale).

    Returns:
        float: Average absolute difference. 0 = identical, 255 = completely different.
    """
    try:
        a = _load_gray_array(path_a)
        b = _load_gray_array(path_b)
        return float(np.mean(np.abs(a - b)) * 255.0)
    except Exception as exc:
        logger.debug("motion score failed: %s", exc)
        return 255.0


def _ssim_score(path_a: Path, path_b: Path, window_size: int = 7) -> float:
    """Compute simplified SSIM between two frames.

    Uses a single pooled-window estimate for speed rather than a full
    sliding-window map.  Returns a value in [-1, 1]; 1.0 = identical.

    Args:
        path_a: First frame path.
        path_b: Second frame path.
        window_size: Size of the local window for stats (must be odd).

    Returns:
        SSIM index.  Higher = more similar.
    """
    try:
        a = _load_gray_array(path_a)
        b = _load_gray_array(path_b)

        if a.shape != b.shape:
            # Resize smaller to match
            h, w = min(a.shape[0], b.shape[0]), min(a.shape[1], b.shape[1])
            a = np.array(Image.fromarray((a * 255).astype(np.uint8)).resize((w, h), Image.Resampling.LANCZOS), dtype=np.float32) / 255.0
            b = np.array(Image.fromarray((b * 255).astype(np.uint8)).resize((w, h), Image.Resampling.LANCZOS), dtype=np.float32) / 255.0

        # Pad to ensure window fits
        pad = window_size // 2
        a_pad = np.pad(a, pad, mode="reflect")
        b_pad = np.pad(b, pad, mode="reflect")

        # Collect local windows
        windows_a = []
        windows_b = []
        for i in range(a.shape[0]):
            for j in range(a.shape[1]):
                wa = a_pad[i:i + window_size, j:j + window_size]
                wb = b_pad[i:i + window_size, j:j + window_size]
                windows_a.append(wa)
                windows_b.append(wb)

        # Convert to arrays for vectorised computation
        wa = np.stack(windows_a)  # (N, ws, ws)
        wb = np.stack(windows_b)

        mu_a = wa.mean(axis=(1, 2))
        mu_b = wb.mean(axis=(1, 2))
        sigma_a = wa.var(axis=(1, 2))
        sigma_b = wb.var(axis=(1, 2))
        sigma_ab = ((wa - mu_a[:, None, None]) * (wb - mu_b[:, None, None])).mean(axis=(1, 2))

        c1 = (0.01) ** 2
        c2 = (0.03) ** 2

        ssim_vals = ((2 * mu_a * mu_b + c1) * (2 * sigma_ab + c2)) / (
            (mu_a ** 2 + mu_b ** 2 + c1) * (sigma_a + sigma_b + c2)
        )
        return float(np.mean(ssim_vals))
    except Exception as exc:
        logger.debug("ssim score failed: %s", exc)
        return -1.0


def _hist_correlation(path_a: Path, path_b: Path) -> float:
    """Compute grayscale histogram correlation between two frames.

    Returns a Pearson-like correlation in [-1, 1].
    1.0 = identical histograms, 0.0 = uncorrelated.
    """
    try:
        with Image.open(path_a) as img_a, Image.open(path_b) as img_b:
            ha = np.array(img_a.convert("L").histogram(), dtype=np.float32)
            hb = np.array(img_b.convert("L").histogram(), dtype=np.float32)

        # Normalise
        ha = ha / (ha.sum() + 1e-8)
        hb = hb / (hb.sum() + 1e-8)

        mean_a = ha.mean()
        mean_b = hb.mean()
        num = np.sum((ha - mean_a) * (hb - mean_b))
        den = np.sqrt(np.sum((ha - mean_a) ** 2) * np.sum((hb - mean_b) ** 2)) + 1e-8
        return float(num / den)
    except Exception as exc:
        logger.debug("hist correlation failed: %s", exc)
        return 0.0


def _frame_variance(path: Path) -> float:
    """Compute pixel variance as a proxy for visual activity / scene change.

    Low variance = mostly uniform (talking head with static background).
    High variance = more visual changes (charts, screen shares, scene cuts).
    """
    from PIL import Image
    import numpy as np

    try:
        with Image.open(path) as img:
            arr = np.array(img.convert("L"), dtype=np.float32)
            return float(np.var(arr))
    except Exception as exc:
        logger.debug("variance compute failed for %s: %s", path, exc)
        return 0.0


def dedup_frames(
    paths: Sequence[Path],
    algo: str | None = None,
    threshold: int | None = None,
) -> list[Path]:
    """De-duplicate frames via a configurable multi-stage pipeline.

    The pipeline is controlled by ``settings.frame_dedup_pipeline`` (comma-
    separated stage names).  Stages run left-to-right; a frame rejected by
    any stage is discarded.

    Available stages
    ----------------
    **motion** — Compare candidate to the *last extracted* frame using mean
    absolute pixel difference.  If the difference is below
    ``frame_motion_threshold`` the frame is skipped.  This is extremely fast
    and catches static-background talking-head micro-movements.

    **phash** / **dhash** / **ahash** — Perceptual hash compared against
    previously *kept* frames.  Controlled by ``frame_hash_algo``,
    ``frame_hash_threshold``, and ``frame_dedup_mode`` (global/window).

    **ssim** — Structural Similarity Index compared against the last N
    *kept* frames (``frame_dedup_ssim_window``).  If SSIM >
    ``frame_ssim_threshold`` the frame is a near-duplicate and is skipped.
    More precise than phash for gradual changes.

    **hist** — Grayscale histogram correlation against last N kept frames.
    If correlation > ``frame_hist_threshold`` the frame is skipped.
    Good for catching identical scenes with minor blur or compression
    differences.

    **variance** — Post-filter.  If >20 frames remain and average variance
    is very low (<500), keep only the top 60%% highest-variance frames.
    Prevents repetitive talking-head shot floods.

    Args:
        paths: Sequence of frame image paths.
        algo: Hash algorithm override (phash, dhash, ahash).
        threshold: Hamming distance threshold override.

    Returns:
        List of kept frame paths in original order.
    """
    algo = algo or settings.frame_hash_algo
    threshold = threshold if threshold is not None else settings.frame_hash_threshold
    mode = settings.frame_dedup_mode
    window_size = settings.frame_dedup_window

    stages = [s.strip().lower() for s in settings.frame_dedup_pipeline.split(",") if s.strip()]
    if not stages:
        stages = ["phash"]

    use_motion = "motion" in stages
    use_hash = any(s in stages for s in ("phash", "dhash", "ahash"))
    use_ssim = "ssim" in stages
    use_hist = "hist" in stages
    use_variance = "variance" in stages

    # Resolve hash algo if a stage name is the algo itself
    if not use_hash:
        for s in stages:
            if s in ("phash", "dhash", "ahash"):
                use_hash = True
                algo = s
                break

    kept: list[Path] = []
    hashes: list[object] = []
    last_extracted: Path | None = None
    ssim_window = settings.frame_dedup_ssim_window
    hist_window = settings.frame_dedup_window  # reuse hash window for hist

    sorted_paths = sorted(paths)

    for p in sorted_paths:
        # ------------------------------------------------------------------
        # Stage 0: Motion Gating
        # ------------------------------------------------------------------
        if use_motion and last_extracted is not None:
            try:
                mscore = _motion_score(p, last_extracted)
            except Exception:
                mscore = 255.0
            if mscore < settings.frame_motion_threshold:
                logger.debug("Motion gate skipped %s (diff=%.2f)", p.name, mscore)
                last_extracted = p
                continue
        last_extracted = p

        # ------------------------------------------------------------------
        # Stage 1: Perceptual Hash
        # ------------------------------------------------------------------
        if use_hash:
            try:
                h = _hash_frame(p, algo)
            except Exception as exc:
                logger.debug("hash failed for %s: %s", p, exc)
                kept.append(p)
                if use_ssim or use_hist:
                    hashes.append(None)
                continue

            compare_against = hashes if mode == "global" else hashes[-window_size:]
            is_duplicate = False
            for hs in compare_against:
                if hs is not None and (h - hs) <= threshold:
                    is_duplicate = True
                    break
            if is_duplicate:
                continue

            hashes.append(h)
        else:
            hashes.append(None)

        # ------------------------------------------------------------------
        # Stage 2: SSIM
        # ------------------------------------------------------------------
        if use_ssim:
            ssim_targets = kept[-ssim_window:] if ssim_window > 0 else kept
            is_duplicate = False
            for target in ssim_targets:
                score = _ssim_score(p, target)
                if score >= settings.frame_ssim_threshold:
                    logger.debug("SSIM skipped %s (score=%.3f vs %s)", p.name, score, target.name)
                    is_duplicate = True
                    break
            if is_duplicate:
                # Roll back hash append if we did one
                if use_hash and hashes and hashes[-1] is not None:
                    hashes.pop()
                elif not use_hash and hashes:
                    hashes.pop()
                continue

        # ------------------------------------------------------------------
        # Stage 3: Histogram Correlation
        # ------------------------------------------------------------------
        if use_hist:
            hist_targets = kept[-hist_window:] if hist_window > 0 else kept
            is_duplicate = False
            for target in hist_targets:
                corr = _hist_correlation(p, target)
                if corr >= settings.frame_hist_threshold:
                    logger.debug("Hist skipped %s (corr=%.3f vs %s)", p.name, corr, target.name)
                    is_duplicate = True
                    break
            if is_duplicate:
                if use_hash and hashes and hashes[-1] is not None:
                    hashes.pop()
                elif not use_hash and hashes:
                    hashes.pop()
                continue

        kept.append(p)

    # ------------------------------------------------------------------
    # Stage 4: Variance Prune
    # ------------------------------------------------------------------
    if use_variance and len(kept) > 20:
        variances = [(p, _frame_variance(p)) for p in kept]
        avg_var = sum(v for _, v in variances) / len(variances)
        if avg_var < 500:
            logger.info(
                "Low-variance video detected (avg=%.1f); pruning repetitive frames", avg_var
            )
            variances.sort(key=lambda x: x[1], reverse=True)
            keep_count = max(8, int(len(kept) * 0.6))
            pruned = [p for p, _ in variances[:keep_count]]
            kept_set = set(str(p) for p in pruned)
            kept = [p for p in kept if str(p) in kept_set]

    logger.info(
        "Deduped %d frames down to %d (pipeline=%s)",
        len(paths),
        len(kept),
        ",".join(stages),
    )
    return kept


def extract_and_dedup(video_path: Path) -> list[Path]:
    raw = extract_frames(video_path)
    return dedup_frames(raw)
