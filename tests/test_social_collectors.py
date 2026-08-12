"""Tests for social source collectors."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from streamdoc.integrations.social import (
    RedditSource,
    SocialPost,
    StocktwitsSource,
    XSource,
)
from streamdoc.integrations.social.x import XSourceNotInstalledError


def _reddit_json(posts: list[dict]) -> dict:
    """Wrap raw post dicts in Reddit's public JSON envelope."""
    return {"data": {"children": [{"data": p} for p in posts]}}


def _fake_urlopen_factory(response_json: dict):
    """Return a fake urlopen that serves JSON for Reddit and bytes for images."""

    def fake_urlopen(url, *args, **kwargs):
        # Reason: urlopen may receive a Request object or a plain URL string.
        if isinstance(url, str):
            url_str = url
        else:
            url_str = getattr(url, "full_url", "")
        response = MagicMock()
        if "reddit.com" in url_str:
            response.read.return_value = json.dumps(response_json).encode("utf-8")
        else:
            response.read.return_value = b"fake-image-bytes"
        response.__enter__ = MagicMock(return_value=response)
        response.__exit__ = MagicMock(return_value=False)
        return response

    return fake_urlopen


def test_reddit_source_collects_recent_posts_and_skips_old_ones(tmp_path, monkeypatch):
    """RedditSource returns posts inside the cutoff and drops older posts."""
    monkeypatch.setattr("streamdoc.config.settings.media_root", str(tmp_path / "media"))

    now_ts = datetime.now(timezone.utc).timestamp()
    posts = [
        {
            "id": "abc123",
            "title": "Recent post",
            "selftext": "Body text",
            "author": "user1",
            "created_utc": now_ts - 300,
            "url": "https://example.com",
            "permalink": "/r/test/comments/abc123/recent_post/",
            "thumbnail": "https://i.redd.it/thumb.jpg",
            "preview": {
                "images": [{"source": {"url": "https://i.redd.it/img.jpg"}}]
            },
        },
        {
            "id": "old456",
            "title": "Old post",
            "selftext": "",
            "author": "user2",
            "created_utc": now_ts - 86400,
            "url": "https://old.example.com",
            "permalink": "/r/test/comments/old456/old_post/",
            "thumbnail": "default",
            "preview": {},
        },
    ]
    fake_urlopen = _fake_urlopen_factory(_reddit_json(posts))

    dedup = MagicMock()
    dedup.is_processed.return_value = False

    preset = MagicMock()
    preset.name = "test-preset"

    source = RedditSource()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = source.collect(preset, "testsub", cutoff, dedup, max_posts=10)

    assert len(result) == 1
    post = result[0]
    assert isinstance(post, SocialPost)
    assert post.platform == "reddit"
    assert post.source_id == "abc123"
    assert post.author == "user1"
    assert "Recent post" in post.text
    assert "Body text" in post.text
    assert post.url.endswith("/r/test/comments/abc123/recent_post/")
    assert post.images
    img_path = Path(post.images[0])
    assert img_path.exists()

    dedup.is_processed.assert_called()


def test_reddit_source_respects_max_posts(tmp_path, monkeypatch):
    """RedditSource caps the number of returned posts at max_posts."""
    monkeypatch.setattr("streamdoc.config.settings.media_root", str(tmp_path / "media"))

    now_ts = datetime.now(timezone.utc).timestamp()
    posts = [
        {
            "id": f"p{i}",
            "title": f"Post {i}",
            "selftext": "",
            "author": "u",
            "created_utc": now_ts - i * 60,
            "url": f"https://example.com/{i}",
            "permalink": f"/r/test/comments/p{i}/",
            "thumbnail": "default",
            "preview": {},
        }
        for i in range(5)
    ]
    fake_urlopen = _fake_urlopen_factory(_reddit_json(posts))

    dedup = MagicMock()
    dedup.is_processed.return_value = False

    preset = MagicMock()
    preset.name = "test-preset"

    source = RedditSource()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = source.collect(preset, "testsub", cutoff, dedup, max_posts=2)

    assert len(result) == 2
    assert result[0].source_id == "p0"
    assert result[1].source_id == "p1"


def test_reddit_source_skips_already_processed_posts(tmp_path, monkeypatch):
    """RedditSource skips posts that the dedup store reports as processed."""
    monkeypatch.setattr("streamdoc.config.settings.media_root", str(tmp_path / "media"))

    now_ts = datetime.now(timezone.utc).timestamp()
    posts = [
        {
            "id": "abc123",
            "title": "Post",
            "selftext": "Body",
            "author": "u1",
            "created_utc": now_ts - 300,
            "url": "https://example.com",
            "permalink": "/r/test/comments/abc123/",
            "thumbnail": "default",
            "preview": {},
        }
    ]
    fake_urlopen = _fake_urlopen_factory(_reddit_json(posts))

    dedup = MagicMock()
    dedup.is_processed.return_value = True

    preset = MagicMock()
    preset.name = "test-preset"

    source = RedditSource()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = source.collect(preset, "testsub", cutoff, dedup, max_posts=10)

    assert len(result) == 0


def _stocktwits_message(
    message_id: int,
    body: str,
    created_at: str,
    sentiment: str | None,
    username: str = "trader123",
    avatar: str = "https://avatars.stocktwits.com/u/avatar.jpg",
) -> dict:
    """Build a single Stocktwits message dict."""
    return {
        "id": message_id,
        "body": body,
        "created_at": created_at,
        "user": {
            "id": 98765,
            "username": username,
            "avatar_url_ssl": avatar,
        },
        "entities": {
            "sentiment": {"basic": sentiment},
            "symbols": [{"symbol": "AAPL", "title": "Apple Inc."}],
        },
        "likes": {"total": 42},
    }


def _fake_stocktwits_urlopen_factory(symbol_response: dict, trending_response: dict | None = None):
    """Return a fake urlopen that serves Stocktwits JSON and bytes for images."""

    def fake_urlopen(url, *args, **kwargs):
        if isinstance(url, str):
            url_str = url
        else:
            url_str = getattr(url, "full_url", "")
        response = MagicMock()
        if "trending/symbols.json" in url_str:
            response.read.return_value = json.dumps(
                trending_response or {"symbols": []}
            ).encode("utf-8")
        elif "api.stocktwits.com" in url_str:
            response.read.return_value = json.dumps(symbol_response).encode("utf-8")
        else:
            response.read.return_value = b"fake-image-bytes"
        response.__enter__ = MagicMock(return_value=response)
        response.__exit__ = MagicMock(return_value=False)
        return response

    return fake_urlopen


def test_stocktwits_source_collects_recent_posts_and_skips_old_ones(tmp_path, monkeypatch):
    """StocktwitsSource returns posts inside the cutoff and drops older posts."""
    monkeypatch.setattr("streamdoc.config.settings.media_root", str(tmp_path / "media"))

    recent = datetime.now(timezone.utc) - timedelta(minutes=30)
    old = datetime.now(timezone.utc) - timedelta(days=1)
    messages = [
        _stocktwits_message(
            111,
            "AAPL looking bullish here https://img.example.com/chart.png $AAPL",
            recent.isoformat().replace("+00:00", "Z"),
            "Bullish",
        ),
        _stocktwits_message(
            222,
            "Old bearish take",
            old.isoformat().replace("+00:00", "Z"),
            "Bearish",
        ),
    ]
    symbol_response = {"messages": messages}
    fake_urlopen = _fake_stocktwits_urlopen_factory(symbol_response)

    dedup = MagicMock()
    dedup.is_processed.return_value = False

    preset = MagicMock()
    preset.name = "test-preset"

    source = StocktwitsSource()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = source.collect(preset, "AAPL", cutoff, dedup, max_posts=10)

    assert len(result) == 1
    post = result[0]
    assert isinstance(post, SocialPost)
    assert post.platform == "stocktwits"
    assert post.source_id == "111"
    assert post.author == "trader123"
    assert "bullish" in post.text.lower()
    assert "AAPL looking bullish" in post.text
    assert post.url == "https://stocktwits.com/message/111"
    assert post.images
    img_path = Path(post.images[0])
    assert img_path.exists()

    dedup.is_processed.assert_called_with("stocktwits", "111", "test-preset")


def test_stocktwits_source_respects_max_posts(tmp_path, monkeypatch):
    """StocktwitsSource caps the number of returned posts at max_posts."""
    monkeypatch.setattr("streamdoc.config.settings.media_root", str(tmp_path / "media"))

    now = datetime.now(timezone.utc) - timedelta(minutes=10)
    messages = [
        _stocktwits_message(
            i,
            f"Post {i}",
            (now - timedelta(minutes=i)).isoformat().replace("+00:00", "Z"),
            None,
        )
        for i in range(5)
    ]
    symbol_response = {"messages": messages}
    fake_urlopen = _fake_stocktwits_urlopen_factory(symbol_response)

    dedup = MagicMock()
    dedup.is_processed.return_value = False

    preset = MagicMock()
    preset.name = "test-preset"

    source = StocktwitsSource()
    cutoff = now - timedelta(hours=1)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = source.collect(preset, "AAPL", cutoff, dedup, max_posts=2)

    assert len(result) == 2
    assert result[0].source_id == "0"
    assert result[1].source_id == "1"


def test_stocktwits_source_skips_already_processed_posts(tmp_path, monkeypatch):
    """StocktwitsSource skips posts that the dedup store reports as processed."""
    monkeypatch.setattr("streamdoc.config.settings.media_root", str(tmp_path / "media"))

    now = datetime.now(timezone.utc)
    messages = [
        _stocktwits_message(
            333,
            "Post",
            now.isoformat().replace("+00:00", "Z"),
            "Bullish",
        )
    ]
    symbol_response = {"messages": messages}
    fake_urlopen = _fake_stocktwits_urlopen_factory(symbol_response)

    dedup = MagicMock()
    dedup.is_processed.return_value = True

    preset = MagicMock()
    preset.name = "test-preset"

    source = StocktwitsSource()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = source.collect(preset, "AAPL", cutoff, dedup, max_posts=10)

    assert len(result) == 0


def test_stocktwits_source_handles_trending_descriptor(tmp_path, monkeypatch):
    """StocktwitsSource expands 'trending' into trending symbols and fetches posts."""
    monkeypatch.setattr("streamdoc.config.settings.media_root", str(tmp_path / "media"))

    now = datetime.now(timezone.utc)
    trending_response = {"symbols": [{"symbol": "TSLA", "title": "Tesla, Inc."}]}
    messages = [
        _stocktwits_message(
            444,
            "TSLA trending",
            now.isoformat().replace("+00:00", "Z"),
            "Bullish",
        )
    ]
    symbol_response = {"messages": messages}
    fake_urlopen = _fake_stocktwits_urlopen_factory(symbol_response, trending_response)

    dedup = MagicMock()
    dedup.is_processed.return_value = False

    preset = MagicMock()
    preset.name = "test-preset"

    source = StocktwitsSource()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = source.collect(preset, "trending", cutoff, dedup, max_posts=10)

    assert len(result) == 1
    assert result[0].source_id == "444"
    assert "TSLA trending" in result[0].text


def test_stocktwits_source_handles_username_descriptor(tmp_path, monkeypatch):
    """StocktwitsSource fetches user streams for descriptors prefixed with '@'."""
    monkeypatch.setattr("streamdoc.config.settings.media_root", str(tmp_path / "media"))

    now = datetime.now(timezone.utc)
    messages = [
        _stocktwits_message(
            555,
            "My user post",
            now.isoformat().replace("+00:00", "Z"),
            "Bearish",
            username="trader123",
        )
    ]
    symbol_response = {"messages": messages}
    fake_urlopen = _fake_stocktwits_urlopen_factory(symbol_response)

    dedup = MagicMock()
    dedup.is_processed.return_value = False

    preset = MagicMock()
    preset.name = "test-preset"

    source = StocktwitsSource()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = source.collect(preset, "@trader123", cutoff, dedup, max_posts=10)

    assert len(result) == 1
    assert result[0].source_id == "555"
    assert result[0].author == "trader123"
    assert "bearish" in result[0].text.lower()


def test_stocktwits_source_maps_sentiment_and_downloads_avatar(tmp_path, monkeypatch):
    """StocktwitsSource maps sentiment labels and downloads the user avatar."""
    monkeypatch.setattr("streamdoc.config.settings.media_root", str(tmp_path / "media"))

    now = datetime.now(timezone.utc)
    messages = [
        _stocktwits_message(
            666,
            "No image in body",
            now.isoformat().replace("+00:00", "Z"),
            "Bullish",
            avatar="https://avatars.stocktwits.com/u/666.jpg",
        )
    ]
    symbol_response = {"messages": messages}
    fake_urlopen = _fake_stocktwits_urlopen_factory(symbol_response)

    dedup = MagicMock()
    dedup.is_processed.return_value = False

    preset = MagicMock()
    preset.name = "test-preset"

    source = StocktwitsSource()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = source.collect(preset, "AAPL", cutoff, dedup, max_posts=10)

    assert len(result) == 1
    post = result[0]
    assert "[bullish]" in post.text
    assert post.images
    assert "stocktwits" in post.images[0] and "AAPL" in post.images[0]


# ── X / Twitter collector tests ────────────────────────────────────────


def _x_tweet(
    tweet_id: str,
    text: str,
    created_at: str,
    screen_name: str = "user1",
    images: list[str] | None = None,
) -> dict:
    """Build a mock tweet dict matching public-clis/twitter-cli JSON output."""
    media_list = []
    legacy_media_list = []
    if images:
        for url in images:
            media_list.append({"type": "photo", "url": url, "width": 100, "height": 100})
            legacy_media_list.append({
                "type": "photo",
                "media_url_https": url,
                "media_url": url,
            })

    return {
        "id": tweet_id,
        "text": text,
        "createdAt": created_at,
        "author": {"screenName": screen_name, "id": "999"},
        "media": media_list,
        "entities": {"media": legacy_media_list},
        "extended_entities": {"media": legacy_media_list},
    }


def test_x_source_collects_recent_tweets_and_skips_old_ones(tmp_path, monkeypatch):
    """XSource returns tweets inside the cutoff and drops older tweets."""
    monkeypatch.setattr("streamdoc.config.settings.media_root", str(tmp_path / "media"))

    import datetime as dt

    now_str = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)).strftime(
        "%a %b %d %H:%M:%S %z %Y"
    )
    old_str = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)).strftime(
        "%a %b %d %H:%M:%S %z %Y"
    )

    tweets = [
        _x_tweet("1001", "Recent tweet about $AAPL", now_str, "trader42"),
        _x_tweet("1002", "Old tweet not in window", old_str, "old_user"),
    ]
    stdout_data = json.dumps(tweets)

    dedup = MagicMock()
    dedup.is_processed.return_value = False

    preset = MagicMock()
    preset.name = "test-x-preset"

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = stdout_data
    mock_result.stderr = ""

    source = XSource()
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)

    with patch("shutil.which", return_value="twitter"), patch(
        "subprocess.run", return_value=mock_result
    ):
        result = source.collect(preset, "trader42", cutoff, dedup, max_posts=10)

    assert len(result) == 1
    assert result[0].source_id == "1001"
    assert result[0].author == "trader42"
    assert "$AAPL" in result[0].text


def test_x_source_deduplication(tmp_path, monkeypatch):
    """XSource skips tweets already processed via dedup store."""
    monkeypatch.setattr("streamdoc.config.settings.media_root", str(tmp_path / "media"))

    import datetime as dt

    now_str = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)).strftime(
        "%a %b %d %H:%M:%S %z %Y"
    )

    tweets = [
        _x_tweet("2001", "Already processed tweet", now_str, "user1"),
        _x_tweet("2002", "New tweet", now_str, "user1"),
    ]
    stdout_data = json.dumps(tweets)

    dedup = MagicMock()
    dedup.is_processed.side_effect = lambda platform, sid, pname: sid == "2001"

    preset = MagicMock()
    preset.name = "test-x-preset"

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = stdout_data
    mock_result.stderr = ""

    source = XSource()
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)

    with patch("shutil.which", return_value="twitter"), patch(
        "subprocess.run", return_value=mock_result
    ):
        result = source.collect(preset, "user1", cutoff, dedup, max_posts=10)

    assert len(result) == 1
    assert result[0].source_id == "2002"


def test_x_source_paginates_list_and_respects_cutoff(tmp_path, monkeypatch):
    """XSource follows list cursors until the lookback window is exhausted."""
    monkeypatch.setattr("streamdoc.config.settings.media_root", str(tmp_path / "media"))

    import datetime as dt

    recent = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)
    old = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2)

    page1 = [
        _x_tweet("3001", "Recent list tweet", recent.strftime("%Y-%m-%dT%H:%M:%SZ"), "trader1"),
        _x_tweet("3002", "Older list tweet", old.strftime("%Y-%m-%dT%H:%M:%SZ"), "trader1"),
    ]
    page2 = [_x_tweet("3003", "Even older", old.strftime("%Y-%m-%dT%H:%M:%SZ"), "trader1")]

    calls: list[list[str]] = []

    def fake_subprocess(args, **kwargs):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""
        calls.append(args)
        if "--cursor" not in args:
            mock_result.stdout = json.dumps({"data": page1, "pagination": {"nextCursor": "cursor1"}})
        else:
            mock_result.stdout = json.dumps({"data": page2, "pagination": {}})
        return mock_result

    dedup = MagicMock()
    dedup.is_processed.return_value = False

    preset = MagicMock()
    preset.name = "test-x-preset"

    source = XSource()
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)

    with patch("shutil.which", return_value="twitter"), patch(
        "subprocess.run", side_effect=fake_subprocess
    ):
        result = source.collect(preset, "list/123456", cutoff, dedup, max_posts=100)

    # Only the first tweet is within the cutoff; the second is older, so the
    # paginator should stop after the first page once the oldest tweet is before cutoff.
    assert len(result) == 1
    assert result[0].source_id == "3001"
    # It should request at least the first list page and may request a second.
    assert len(calls) >= 1
    assert calls[0][1] == "list"
    assert calls[0][2] == "123456"


def test_x_source_respects_max_posts_as_target(tmp_path, monkeypatch):
    """XSource treats max_posts as a target cap across pages."""
    monkeypatch.setattr("streamdoc.config.settings.media_root", str(tmp_path / "media"))

    import datetime as dt

    recent = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)
    tweets = [
        _x_tweet(f"400{i}", f"Tweet {i}", recent.strftime("%Y-%m-%dT%H:%M:%SZ"), "trader1")
        for i in range(3)
    ]
    stdout_data = json.dumps(tweets)

    dedup = MagicMock()
    dedup.is_processed.return_value = False

    preset = MagicMock()
    preset.name = "test-x-preset"

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = stdout_data
    mock_result.stderr = ""

    source = XSource()
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)

    with patch("shutil.which", return_value="twitter"), patch(
        "subprocess.run", return_value=mock_result
    ):
        result = source.collect(preset, "trader1", cutoff, dedup, max_posts=2)

    assert len(result) == 2
    assert result[0].source_id == "4000"
    assert result[1].source_id == "4001"


def test_x_source_not_installed_raises_error(tmp_path, monkeypatch):
    """XSource raises XSourceNotInstalledError when twitter-cli is missing."""
    monkeypatch.setattr("streamdoc.config.settings.media_root", str(tmp_path / "media"))

    dedup = MagicMock()
    preset = MagicMock()
    preset.name = "test-x-preset"

    source = XSource()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)

    # Patch binary discovery to return empty so the source acts as not installed.
    with patch("streamdoc.integrations.social.x._find_binary", return_value=""):
        with pytest.raises(XSourceNotInstalledError):
            source.collect(preset, "elonmusk", cutoff, dedup, max_posts=10)

