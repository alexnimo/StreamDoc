import pytest


from streamdoc.core.media import list_supported, unique_frames_filter


def test_list_supported_contains_expected():
    supported = list_supported()
    for ext in ["mp4", "wav", "flac"]:
        assert ext in supported


def test_unique_frames_filter_deduplicates_by_size():
    p1 = type("P", (), {"exists": lambda self: True, "stat": lambda self: type("S", (), {"st_size": 1000})()})()
    p2 = type("P", (), {"exists": lambda self: True, "stat": lambda self: type("S", (), {"st_size": 1000})()})()
    p3 = type("P", (), {"exists": lambda self: True, "stat": lambda self: type("S", (), {"st_size": 1500})()})()

    out = unique_frames_filter([p1, p2, p3], same_size_threshold=0)
    assert len(out) == 2
    assert out == [p1, p3]


def test_unique_frames_filter_empty_input():
    assert unique_frames_filter([]) == []

