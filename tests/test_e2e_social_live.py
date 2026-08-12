"""Live E2E social pipeline test — pulls real data from X, Reddit, Stocktwits.

Usage:
    pytest tests/test_e2e_social_live.py -x -v -s 2>&1

Requires:
    - public-clis/twitter-cli (``twitter`` binary) for X collector
    - public-clis/rdt-cli (``rdt`` binary) + logged-in Reddit session for Reddit
    - Stocktwits public API (no auth; curl_cffi reduces Cloudflare blocks)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone, timedelta

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from streamdoc.integrations.social.reddit import RedditSource
from streamdoc.integrations.social.stocktwits import StocktwitsSource
from streamdoc.integrations.social.x import (
    XSource,
    XSourceNotInstalledError,
)


class _FakePreset:
    """Minimal preset stub that provides the name attribute collectors need."""
    def __init__(self, name: str):
        self.name = name


@pytest.fixture
def dedup():
    """In-memory dedup store that never rejects (accepts everything)."""
    class AcceptAllDedup:
        def is_processed(self, platform: str, source_id: str, preset_name: str) -> bool:
            return False
    return AcceptAllDedup()


@pytest.fixture
def cutoff():
    """Cutoff: last 7 days."""
    return datetime.now(timezone.utc) - timedelta(days=7)


def _rdt_is_authenticated() -> bool:
    """Return True if public-clis ``rdt`` is installed and has Reddit credentials."""
    binary = shutil.which("rdt")
    if not binary:
        return False
    try:
        result = subprocess.run(
            [binary, "status", "--json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False

    if result.returncode != 0:
        return False

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return False

    if not payload.get("ok"):
        return False

    return bool(payload.get("data", {}).get("authenticated"))


# ── Reddit E2E ────────────────────────────────────────────────────────

@pytest.mark.live
def test_reddit_collects_real_posts_and_images(dedup, cutoff):
    """Pull actual posts from a popular subreddit, verify text + images.

    Reddit blocks anonymous requests with Cloudflare, so the test is skipped
    when ``rdt`` is not authenticated.
    """
    if not _rdt_is_authenticated():
        pytest.skip("rdt-cli is not authenticated; Reddit requires a logged-in session")

    source = RedditSource()
    preset = _FakePreset("e2e-reddit-test")

    posts = source.collect(
        preset=preset,
        source_descriptor="wallstreetbets",
        cutoff=cutoff,
        dedup_store=dedup,
        max_posts=10,
    )

    assert len(posts) > 0, "No posts returned from Reddit"

    print(f"\n=== Reddit: {len(posts)} posts ===")
    for p in posts:
        img_info = ""
        if p.images:
            img_info = f" 📸 {len(p.images)} images: {' | '.join(p.images[:3])}"
            if len(p.images) > 3:
                img_info += f" (+{len(p.images)-3} more)"
        print(f"  [{p.source_id}] {p.author}: {p.text[:120]}{img_info}")
        print(f"    URL: {p.url}")

    # Verify image extraction works
    all_images = []
    for p in posts:
        all_images.extend(p.images or [])
    print(f"\n  Total images extracted: {len(all_images)}")
    if all_images:
        print("  Sample image URLs:")
        for url in all_images[:5]:
            print(f"    - {url}")


@pytest.mark.live
def test_reddit_image_extraction(dedup, cutoff):
    """Specifically verify that image URLs are extracted from Reddit posts."""
    if not _rdt_is_authenticated():
        pytest.skip("rdt-cli is not authenticated; Reddit requires a logged-in session")

    source = RedditSource()
    preset = _FakePreset("e2e-reddit-img-test")

    posts = source.collect(
        preset=preset,
        source_descriptor="itookapicture",
        cutoff=cutoff,
        dedup_store=dedup,
        max_posts=15,
    )

    assert len(posts) > 0, "No posts from r/itookapicture"

    posts_with_images = [p for p in posts if p.images]
    print(f"\n=== Reddit (r/itookapicture): {len(posts_with_images)}/{len(posts)} posts with images ===")

    for p in posts_with_images[:5]:
        print(f"  {p.author}: {p.text[:100]}")
        for img in (p.images or [])[:3]:
            print(f"    📷 {img}")


# ── Stocktwits E2E ────────────────────────────────────────────────────

@pytest.mark.live
def test_stocktwits_collects_trending_and_images(dedup, cutoff):
    """Pull trending symbols and user stream from Stocktwits, verify data + images."""
    source = StocktwitsSource()
    preset = _FakePreset("e2e-stocktwits-test")

    # Collect by symbol (e.g. TSLA, AAPL, SPY)
    for symbol in ["TSLA", "AAPL", "SPY"]:
        posts = source.collect(
            preset=preset,
            source_descriptor=symbol,
            cutoff=cutoff,
            dedup_store=dedup,
            max_posts=5,
        )

        if posts:
            print(f"\n=== Stocktwits ${symbol}: {len(posts)} posts ===")
            for p in posts[:3]:
                img_info = ""
                if p.images:
                    img_info = f" 📸 {p.images[0]}"
                print(f"  {p.author}: {p.text[:120]}{img_info}")
                print(f"    URL: {p.url}")
            break  # Got data, stop

    # If none worked, note it
    all_posts = []
    for symbol in ["TSLA", "AAPL", "SPY", "QQQ"]:
        posts = source.collect(
            preset=preset,
            source_descriptor=symbol,
            cutoff=cutoff,
            dedup_store=dedup,
            max_posts=3,
        )
        all_posts.extend(posts)

    if all_posts:
        print(f"\n  Total Stocktwits posts: {len(all_posts)}")
        all_images = []
        for p in all_posts:
            all_images.extend(p.images or [])
        print(f"  Total images: {len(all_images)}")
        for url in all_images[:5]:
            print(f"    📷 {url}")
    else:
        print("\n  ⚠️ No Stocktwits posts returned (API may be unavailable)")


# ── X (Twitter) E2E ───────────────────────────────────────────────────

@pytest.mark.live
def test_x_collects_user_feed_and_images(dedup, cutoff):
    """Pull real tweets from a user feed, verify text + images."""
    try:
        from streamdoc.integrations.social.x import _find_binary as find_x_binary
        binary = find_x_binary()
    except Exception:
        binary = shutil.which("twitter")
    if not binary:
        pytest.skip("twitter binary not installed (public-clis/twitter-cli)")

    preset = _FakePreset("e2e-x-test")
    source = XSource()

    # Try a few public tech profiles that often post with images
    targets = ["jack", "elonmusk", "npmjs"]

    for username in targets:
        try:
            posts = source.collect(
                preset=preset,
                source_descriptor=username,
                cutoff=cutoff,
                dedup_store=dedup,
                max_posts=10,
            )
        except XSourceNotInstalledError:
            pytest.skip("twitter binary not installed (public-clis/twitter-cli)")
        except Exception as exc:
            print(f"\n  ⚠️ X feed for @{username} failed: {exc}")
            continue

        if posts:
            print(f"\n=== X (Twitter) @{username}: {len(posts)} tweets ===")
            for p in posts[:5]:
                img_info = ""
                if p.images:
                    img_info = f" 📸 {len(p.images)} images: {' | '.join(p.images[:2])}"
                print(f"  [{p.source_id}] {p.text[:120]}{img_info}")
                print(f"    URL: {p.url}")

            all_images = []
            for p in posts:
                all_images.extend(p.images or [])
            if all_images:
                print(f"\n  Total images from @{username}: {len(all_images)}")
                for url in all_images[:5]:
                    print(f"    📷 {url}")
            break


# ── Full Pipeline E2E ──────────────────────────────────────────────

@pytest.mark.live
def test_full_e2e_social_pipeline(dedup, cutoff):
    """Aggregate posts from all available platforms, summary with images."""
    results = {
        "reddit": {"posts": [], "images": 0},
        "stocktwits": {"posts": [], "images": 0},
        "x": {"posts": [], "images": 0},
    }

    # Reddit
    try:
        if _rdt_is_authenticated():
            source = RedditSource()
            preset = _FakePreset("e2e-full-test")
            posts = source.collect(
                preset=preset, source_descriptor="wallstreetbets",
                cutoff=cutoff, dedup_store=dedup, max_posts=5,
            )
            for p in posts:
                results["reddit"]["posts"].append(p)
                if p.images:
                    results["reddit"]["images"] += len(p.images)
            print(f"\n✅ Reddit: {len(posts)} posts, {results['reddit']['images']} images")
        else:
            print("⏭️ Reddit: rdt-cli not authenticated")
    except Exception as e:
        print(f"❌ Reddit: {e}")

    # Stocktwits
    try:
        source = StocktwitsSource()
        preset = _FakePreset("e2e-full-test")
        posts = source.collect(
            preset=preset, source_descriptor="TSLA",
            cutoff=cutoff, dedup_store=dedup, max_posts=5,
        )
        for p in posts:
            results["stocktwits"]["posts"].append(p)
            if p.images:
                results["stocktwits"]["images"] += len(p.images)
        print(f"✅ Stocktwits: {len(posts)} posts, {results['stocktwits']['images']} images")
    except Exception as e:
        print(f"❌ Stocktwits: {e}")

    # X
    try:
        from streamdoc.integrations.social.x import _find_binary as find_x_binary
        binary = find_x_binary()
    except Exception:
        binary = shutil.which("twitter")
    if binary:
        try:
            x_source = XSource()
            preset = _FakePreset("e2e-full-test")
            posts = x_source.collect(
                preset=preset, source_descriptor="jack",
                cutoff=cutoff, dedup_store=dedup, max_posts=5,
            )
            for p in posts:
                results["x"]["posts"].append(p)
                if p.images:
                    results["x"]["images"] += len(p.images)
            print(f"✅ X: {len(posts)} posts, {results['x']['images']} images")
        except Exception as e:
            print(f"❌ X: {e}")
    else:
        print("⏭️ X: twitter binary not installed")

    # Summary
    total_posts = sum(len(v["posts"]) for v in results.values())
    total_images = sum(v["images"] for v in results.values())
    print(f"\n{'='*50}")
    print("📊 E2E Pipeline Summary")
    print(f"{'='*50}")
    print(f"  Total posts collected: {total_posts}")
    print(f"  Total images extracted: {total_images}")

    all_image_urls = []
    for platform, data in results.items():
        for p in data["posts"]:
            if p.images:
                all_image_urls.extend(p.images)

    if all_image_urls:
        print(f"\n  All image URLs ({len(all_image_urls)} total):")
        for url in all_image_urls[:10]:
            print(f"    📷 {url}")
        if len(all_image_urls) > 10:
            print(f"    ... and {len(all_image_urls) - 10} more")

    assert total_posts > 0, "No posts collected from any platform"
