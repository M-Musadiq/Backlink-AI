"""Platform posting module — all sites use unified generic poster."""
from src.infrastructure.posting.base_poster import BasePlatformPoster, PostResult
from src.infrastructure.posting.generic_poster import GenericPoster


def get_poster(domain: str) -> BasePlatformPoster:
    """Get the unified generic poster for all domains."""
    return GenericPoster()


__all__ = [
    "BasePlatformPoster",
    "PostResult",
    "GenericPoster",
    "get_poster",
]

