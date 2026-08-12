from __future__ import annotations

from pathlib import Path
from typing import Iterable


def list_supported() -> list[str]:
    return ["mp4", "webm", "mkv", "mp3", "m4a", "wav", "flac"]


def unique_frames_filter(
    paths: Iterable[Path],
    *,
    size_fn=None,
    same_size_threshold: int = 0,
) -> list[Path]:
    """Filter likely-duplicate frames by filesize distance.

    - ``size_fn``: optional callable returning the byte size for a path.
      Defaults to ``Path.stat().st_size`` with missing-file fallback to -1.
    - ``same_size_threshold``: maximum allowed size difference to consider two
      frames duplicates. 0 keeps only the first path per exact size; choose a
      larger value for filesystem-rounded variants.
    """
    flat = list(paths)
    if not flat:
        return []

    def _default_size(p: Path) -> int:
        try:
            return p.stat().st_size
        except OSError:
            return -1

    resolve_size = size_fn or _default_size

    seen: list[tuple[int, Path]] = []
    out: list[Path] = []
    for p in flat:
        size = resolve_size(p)
        if any(abs(size - s) <= same_size_threshold for s, _ in seen):
            continue
        seen.append((size, p))
        out.append(p)
    return out

