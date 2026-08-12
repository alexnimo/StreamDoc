import json
from unittest.mock import MagicMock, patch

from streamdoc.core.youtube_api import fetch_upload_dates, fetch_video_metadata


def test_fetch_video_metadata_parses_duration():
    """Should parse ISO 8601 duration and return seconds."""
    api_response = {
        "items": [
            {
                "id": "a",
                "snippet": {"publishedAt": "2026-07-14T01:00:00Z", "title": "A"},
                "contentDetails": {"duration": "PT1M30S"},
            },
            {
                "id": "b",
                "snippet": {"publishedAt": "2026-07-13T02:00:00Z", "title": "B"},
                "contentDetails": {"duration": "PT60S"},
            },
        ]
    }

    def mock_urlopen(req, **kwargs):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(api_response).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        return mock_resp

    with patch("streamdoc.core.youtube_api.urllib.request.urlopen", side_effect=mock_urlopen) as m:
        result = fetch_video_metadata(["a", "b"], "test-key")

    assert result["a"]["published_at"] == "2026-07-14T01:00:00Z"
    assert result["a"]["duration_seconds"] == 90
    assert result["b"]["duration_seconds"] == 60
    # Verify the request asks for contentDetails so we get duration.
    assert "part=snippet%2CcontentDetails" in m.call_args[0][0].full_url


def test_fetch_upload_dates_empty_input():
    """Empty inputs should return an empty dict."""
    assert fetch_upload_dates([], "key") == {}
    assert fetch_upload_dates(["abc"], "") == {}


def test_fetch_upload_dates_batches_ids():
    """Should call the Data API with batched IDs and return parsed dates."""
    video_ids = ["a", "b"]
    api_response = {
        "items": [
            {"id": "a", "snippet": {"publishedAt": "2026-07-14T01:00:00Z"}},
            {"id": "b", "snippet": {"publishedAt": "2026-07-13T02:00:00Z"}},
        ]
    }

    def mock_urlopen(req, **kwargs):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(api_response).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        return mock_resp

    with patch("streamdoc.core.youtube_api.urllib.request.urlopen", side_effect=mock_urlopen) as m:
        result = fetch_upload_dates(video_ids, "test-key")

    assert result == {
        "a": "2026-07-14T01:00:00Z",
        "b": "2026-07-13T02:00:00Z",
    }
    # Verify the call URL contains the batched IDs and key.
    call_args = m.call_args
    assert "id=a%2Cb" in call_args[0][0].full_url
    assert "key=test-key" in call_args[0][0].full_url


def test_fetch_upload_dates_partial_response():
    """Should return only the IDs the API returned."""
    api_response = {
        "items": [
            {"id": "a", "snippet": {"publishedAt": "2026-07-14T01:00:00Z"}},
        ]
    }

    def mock_urlopen(req, **kwargs):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(api_response).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        return mock_resp

    with patch("streamdoc.core.youtube_api.urllib.request.urlopen", side_effect=mock_urlopen):
        result = fetch_upload_dates(["a", "missing"], "test-key")

    assert result == {"a": "2026-07-14T01:00:00Z"}


def test_fetch_upload_dates_api_error_returns_partial():
    """API errors should return any partial data and not crash."""
    with patch("streamdoc.core.youtube_api.urllib.request.urlopen", side_effect=Exception("network")):
        result = fetch_upload_dates(["a"], "test-key")

    assert result == {}
