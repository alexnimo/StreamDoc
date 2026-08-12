"""Unit tests for the configurable multi-stage frame deduplication pipeline.

Tests each stage in isolation and in combination using synthetic frames
so no real video is required.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from streamdoc.config import Settings, settings
from streamdoc.core.frames import (
    _frame_variance,
    _hash_frame,
    _hist_correlation,
    _motion_score,
    _ssim_score,
    dedup_frames,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_image(size: tuple[int, int] = (320, 240), color: tuple[int, int, int] = (128, 128, 128)) -> Image.Image:
    """Create a solid-color PIL image."""
    return Image.new("RGB", size, color)


def _save_image(img: Image.Image, path: Path) -> Path:
    img.save(path, "JPEG", quality=85)
    return path


def _make_noisy_image(size: tuple[int, int] = (320, 240), base_color: tuple[int, int, int] = (128, 128, 128), noise: int = 5) -> Image.Image:
    """Create an image with slight per-pixel noise."""
    arr = np.ones((*size[::-1], 3), dtype=np.uint8) * np.array(base_color, dtype=np.uint8)
    arr = arr.astype(np.int16)
    arr += np.random.randint(-noise, noise + 1, arr.shape)
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    return Image.fromarray(arr)


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture(autouse=True)
def _patch_settings(monkeypatch):
    """Provide isolated settings for each test."""
    # Copy current settings so we can mutate safely
    s = Settings()
    monkeypatch.setattr("streamdoc.core.frames.settings", s)
    yield s


# ---------------------------------------------------------------------------
# Individual stage tests
# ---------------------------------------------------------------------------

class TestMotionScore:
    def test_identical_images_zero_diff(self, temp_dir: Path) -> None:
        p = temp_dir / "a.jpg"
        _save_image(_make_image(), p)
        assert _motion_score(p, p) < 1.0

    def test_different_images_high_diff(self, temp_dir: Path) -> None:
        a = temp_dir / "a.jpg"
        b = temp_dir / "b.jpg"
        _save_image(_make_image(color=(0, 0, 0)), a)
        _save_image(_make_image(color=(255, 255, 255)), b)
        assert _motion_score(a, b) > 200.0

    def test_noisy_similar_images_low_diff(self, temp_dir: Path) -> None:
        a = temp_dir / "a.jpg"
        b = temp_dir / "b.jpg"
        _save_image(_make_noisy_image(noise=2), a)
        _save_image(_make_noisy_image(noise=2), b)
        score = _motion_score(a, b)
        # Two noisy images of the same base color should have low diff
        assert score < 50.0


class TestSSIMScore:
    def test_identical_images_ssim_one(self, temp_dir: Path) -> None:
        p = temp_dir / "a.jpg"
        _save_image(_make_image(), p)
        assert _ssim_score(p, p) > 0.99

    def test_different_images_ssim_low(self, temp_dir: Path) -> None:
        a = temp_dir / "a.jpg"
        b = temp_dir / "b.jpg"
        _save_image(_make_image(color=(0, 0, 0)), a)
        _save_image(_make_image(color=(255, 255, 255)), b)
        assert _ssim_score(a, b) < 0.3

    def test_noisy_similar_images_ssim_high(self, temp_dir: Path) -> None:
        a = temp_dir / "a.jpg"
        b = temp_dir / "b.jpg"
        _save_image(_make_noisy_image(noise=3), a)
        _save_image(_make_noisy_image(noise=3), b)
        assert _ssim_score(a, b) > 0.85


class TestHistCorrelation:
    def test_identical_histograms(self, temp_dir: Path) -> None:
        p = temp_dir / "a.jpg"
        _save_image(_make_image(), p)
        assert _hist_correlation(p, p) > 0.99

    def test_different_histograms(self, temp_dir: Path) -> None:
        a = temp_dir / "a.jpg"
        b = temp_dir / "b.jpg"
        _save_image(_make_image(color=(0, 0, 0)), a)
        _save_image(_make_image(color=(255, 255, 255)), b)
        assert _hist_correlation(a, b) < 0.5


class TestFrameVariance:
    def test_uniform_image_low_variance(self, temp_dir: Path) -> None:
        p = temp_dir / "a.jpg"
        _save_image(_make_image(), p)
        assert _frame_variance(p) < 50.0

    def test_noisy_image_high_variance(self, temp_dir: Path) -> None:
        p = temp_dir / "a.jpg"
        _save_image(_make_noisy_image(noise=40), p)
        assert _frame_variance(p) > 200.0


class TestHashFrame:
    def test_same_image_same_hash(self, temp_dir: Path) -> None:
        p = temp_dir / "a.jpg"
        _save_image(_make_image(), p)
        h1 = _hash_frame(p, "phash")
        h2 = _hash_frame(p, "phash")
        assert h1 == h2

    def test_different_image_different_hash(self, temp_dir: Path) -> None:
        a = temp_dir / "a.jpg"
        b = temp_dir / "b.jpg"
        _save_image(_make_image(color=(0, 0, 0)), a)
        _save_image(_make_image(color=(255, 255, 255)), b)
        h1 = _hash_frame(a, "phash")
        h2 = _hash_frame(b, "phash")
        assert h1 != h2


# ---------------------------------------------------------------------------
# Pipeline integration tests
# ---------------------------------------------------------------------------

class TestDedupPipeline:
    def test_phash_only_keeps_all_unique(self, temp_dir: Path, _patch_settings: Settings) -> None:
        """With visually distinct images phash should keep all of them."""
        _patch_settings.frame_dedup_pipeline = "phash"
        _patch_settings.frame_hash_threshold = 8
        paths: list[Path] = []
        for i in range(5):
            p = temp_dir / f"f{i}.jpg"
            # Use distinct geometric patterns instead of solid colors
            img = Image.new("RGB", (320, 240), (255, 255, 255))
            px = img.load()
            for x in range(320):
                for y in range(240):
                    val = (x * (i + 1) + y * (i + 3)) % 256
                    px[x, y] = (val, 255 - val, val // 2)
            _save_image(img, p)
            paths.append(p)
        kept = dedup_frames(paths)
        assert len(kept) == 5

    def test_phash_removes_exact_duplicates(self, temp_dir: Path, _patch_settings: Settings) -> None:
        _patch_settings.frame_dedup_pipeline = "phash"
        _patch_settings.frame_hash_threshold = 8
        a = temp_dir / "a.jpg"
        b = temp_dir / "b.jpg"
        _save_image(_make_image(), a)
        _save_image(_make_image(), b)
        kept = dedup_frames([a, b])
        assert len(kept) == 1

    def test_motion_gate_skips_similar(self, temp_dir: Path, _patch_settings: Settings) -> None:
        """Motion gate should skip frames with very low pixel diff."""
        _patch_settings.frame_dedup_pipeline = "motion"
        _patch_settings.frame_motion_threshold = 5.0
        a = temp_dir / "a.jpg"
        b = temp_dir / "b.jpg"
        _save_image(_make_image(), a)
        _save_image(_make_image(), b)  # identical
        kept = dedup_frames([a, b])
        assert len(kept) == 1

    def test_ssim_catches_near_duplicates(self, temp_dir: Path, _patch_settings: Settings) -> None:
        """SSIM stage should catch near-duplicates that phash might miss."""
        _patch_settings.frame_dedup_pipeline = "ssim"
        _patch_settings.frame_ssim_threshold = 0.90
        a = temp_dir / "a.jpg"
        b = temp_dir / "b.jpg"
        _save_image(_make_noisy_image(noise=2), a)
        _save_image(_make_noisy_image(noise=2), b)
        kept = dedup_frames([a, b])
        # Two very similar noisy images should be caught by SSIM
        assert len(kept) == 1

    def test_combined_pipeline_reduces_more(self, temp_dir: Path, _patch_settings: Settings) -> None:
        """Combined pipeline should be stricter than any single stage."""
        _patch_settings.frame_dedup_pipeline = "motion,phash,ssim,hist,variance"
        _patch_settings.frame_motion_threshold = 5.0
        _patch_settings.frame_hash_threshold = 8
        _patch_settings.frame_ssim_threshold = 0.90
        _patch_settings.frame_hist_threshold = 0.95

        paths: list[Path] = []
        for i in range(10):
            p = temp_dir / f"f{i}.jpg"
            if i % 2 == 0:
                _save_image(_make_image(color=(128, 128, 128)), p)
            else:
                _save_image(_make_noisy_image(base_color=(128, 128, 128), noise=2), p)
            paths.append(p)

        kept = dedup_frames(paths)
        # Should reduce duplicates significantly
        assert len(kept) < len(paths)

    def test_variance_prune_talk_head(self, temp_dir: Path, _patch_settings: Settings) -> None:
        """Variance prune should kick in for many low-variance frames."""
        _patch_settings.frame_dedup_pipeline = "variance"
        # Create 30 nearly identical low-variance frames
        paths: list[Path] = []
        for i in range(30):
            p = temp_dir / f"f{i}.jpg"
            _save_image(_make_image(color=(120 + i, 120 + i, 120 + i)), p)
            paths.append(p)

        # With only variance stage, nothing is deduped by the pipeline itself,
        # but the post-filter variance prune should reduce them.
        # However variance prune only fires if avg_var < 500 AND len > 20.
        # Solid color images have very low variance.
        kept = dedup_frames(paths)
        assert len(kept) < len(paths)
        assert len(kept) >= 8  # prune keeps at least 8

    def test_custom_pipeline_order(self, temp_dir: Path, _patch_settings: Settings) -> None:
        """Reordering stages should still produce valid results."""
        _patch_settings.frame_dedup_pipeline = "hist,phash"
        _patch_settings.frame_hash_threshold = 8
        _patch_settings.frame_hist_threshold = 0.95
        a = temp_dir / "a.jpg"
        b = temp_dir / "b.jpg"
        _save_image(_make_image(), a)
        _save_image(_make_image(), b)
        kept = dedup_frames([a, b])
        assert len(kept) == 1

    def test_empty_paths(self, _patch_settings: Settings) -> None:
        _patch_settings.frame_dedup_pipeline = "motion,phash,ssim,variance"
        kept = dedup_frames([])
        assert kept == []
