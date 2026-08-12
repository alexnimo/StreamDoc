"""Social sentiment collector integration package."""
from streamdoc.integrations.social.base import SocialPost, SocialSource
from streamdoc.integrations.social.store import SocialPostStore

__all__ = ["SocialPost", "SocialPostStore", "SocialSource", "register", "get_collector"]

_REGISTRY: dict[str, type[SocialSource]] = {}


def register(platform: str, collector_class: type[SocialSource]) -> None:
    """Register a collector class for a platform identifier."""
    _REGISTRY[platform] = collector_class


def get_collector(platform: str) -> type[SocialSource] | None:
    """Return the registered collector class for a platform, if any."""
    return _REGISTRY.get(platform)


# Register built-in collectors.
from streamdoc.integrations.social.reddit import RedditSource  # noqa: E402
from streamdoc.integrations.social.stocktwits import StocktwitsSource  # noqa: E402
from streamdoc.integrations.social.x import XSource  # noqa: E402

register("reddit", RedditSource)
register("stocktwits", StocktwitsSource)
register("x", XSource)
