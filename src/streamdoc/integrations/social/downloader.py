"""Safe media download helpers for social source collectors."""
from __future__ import annotations

import ipaddress
import logging
import re
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request

logger = logging.getLogger(__name__)

# Reason: hard cap to avoid memory exhaustion from a malicious or broken URL.
_MAX_IMAGE_BYTES = 50 * 1024 * 1024


_ALLOWED_IMAGE_SCHEMES = frozenset({"http", "https"})


def _is_safe_image_url(url: str) -> bool:
    """Return True when ``url`` is a public HTTP(S) image URL we are willing to fetch.

    Rejects file://, ftp://, private/reserved IP literals, and loopback hosts.
    Domain names are not resolved here to keep the check synchronous and cheap;
    the redirect landing point is validated after the request.
    """
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_IMAGE_SCHEMES:
        return False
    if not parsed.hostname:
        return False
    if parsed.hostname.lower() in {"localhost", "0.0.0.0", "::"}:
        return False
    try:
        ip = ipaddress.ip_address(parsed.hostname)
        if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_multicast:
            return False
    except ValueError:
        pass  # hostname is a domain, not an IP literal
    return True


def safe_dir_name(name: str) -> str:
    """Sanitize a user-supplied label for use as a directory name.

    Replaces path separators and other filesystem-unsafe characters with an
    underscore and collapses leading dots to prevent directory traversal.
    """
    safe = re.sub(r'[\\/*?:"<>|\x00-\x1f]', "_", name.strip())
    safe = re.sub(r"\.{2,}", "_", safe)
    safe = safe.lstrip(".")
    if not safe:
        safe = "unknown"
    return safe


def _image_dest_for_data(dest: Path, data: bytes) -> Path:
    """Return a destination path whose extension matches the image content."""
    if data.startswith(b"\xff\xd8\xff"):
        ext = ".jpg"
    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
        ext = ".png"
    elif data.startswith((b"GIF87a", b"GIF89a")):
        ext = ".gif"
    elif data.startswith(b"RIFF"):
        ext = ".webp"
    else:
        ext = dest.suffix
    if dest.suffix.lower() == ext.lower():
        return dest
    return dest.with_suffix(ext)


def download_image(url: str, dest: Path, headers: dict[str, str], timeout: int = 30) -> bool:
    """Download a single image from ``url`` into ``dest`` safely.

    Returns True on success and False on any validation or network failure.
    Logs a warning for unsafe/oversized URLs.

    Args:
        url: Public image URL.
        dest: Local file path to write.
        headers: HTTP request headers (e.g. User-Agent and Accept).
        timeout: Network timeout in seconds.
    """
    if not _is_safe_image_url(url):
        logger.warning("Refusing to download unsafe image URL: %s", url)
        return False

    try:
        request = Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            final_url = response.geturl()
            if isinstance(final_url, str) and not _is_safe_image_url(final_url):
                logger.warning("Image redirect landed on unsafe URL: %s", final_url)
                return False

            content_length = response.headers.get("Content-Length")
            size: int | None = None
            if isinstance(content_length, int):
                size = content_length
            elif isinstance(content_length, str):
                try:
                    size = int(content_length)
                except ValueError:
                    size = None
            if size is not None and size > _MAX_IMAGE_BYTES:
                logger.warning("Image Content-Length %s exceeds limit, skipping %s", size, url)
                return False

            data = response.read(_MAX_IMAGE_BYTES + 1)
            if not isinstance(data, bytes):
                logger.warning("Image response for %s did not return bytes", url)
                return False
            if len(data) > _MAX_IMAGE_BYTES:
                logger.warning("Image body exceeds %s bytes, skipping %s", _MAX_IMAGE_BYTES, url)
                return False

            # Reason: Content-Type is the first line of defense against a video
            # or other non-image payload; it is more reliable than URL suffix.
            content_type = response.headers.get("Content-Type", "")
            if isinstance(content_type, str):
                main_type = content_type.split(";", 1)[0].strip().lower()
                if main_type and not main_type.startswith("image/"):
                    logger.warning("Non-image Content-Type %r for %s, skipping", content_type, url)
                    return False

            # Reason: derive the real image extension from content so a video
            # saved as .jpg does not poison downstream PDF/MD builders.
            dest = _image_dest_for_data(dest, data)
            dest.write_bytes(data)
        return True
    except (urllib.error.URLError, OSError, ValueError, TypeError) as exc:
        logger.warning("Failed to download image %s: %s", url, exc)
        return False
