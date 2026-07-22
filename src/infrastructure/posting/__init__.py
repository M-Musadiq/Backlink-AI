"""Platform posting module."""
from src.infrastructure.posting.base_poster import BasePlatformPoster, PostResult
from src.infrastructure.posting.devto_poster import DevToPoster
from src.infrastructure.posting.reddit_poster import RedditPoster
from src.infrastructure.posting.stackoverflow_poster import StackOverflowPoster
from src.infrastructure.posting.hackernews_poster import HackerNewsPoster
from src.infrastructure.posting.hashnode_poster import HashnodePoster
from src.infrastructure.posting.medium_poster import MediumPoster
from src.infrastructure.posting.ai_poster import BrowserUsePoster

PLATFORM_POSTERS = {
    "reddit.com": RedditPoster,
    "stackoverflow.com": StackOverflowPoster,  # Playwright + 2Captcha Turnstile
    "news.ycombinator.com": HackerNewsPoster,
    "hashnode.com": BrowserUsePoster,
    "medium.com": MediumPoster,  # Playwright + 2Captcha reCAPTCHA
}


def get_poster(domain: str) -> BasePlatformPoster:
    """Get the appropriate poster for a domain.
    Uses platform-specific poster if available, otherwise falls back to AI-powered poster.
    """
    domain = domain.lower()
    for key, poster_cls in PLATFORM_POSTERS.items():
        if key in domain:
            return poster_cls()
    # Unknown platform — use AI poster
    return BrowserUsePoster()


__all__ = [
    "BasePlatformPoster",
    "PostResult",
    "BrowserUsePoster",
    "PLATFORM_POSTERS",
    "get_poster",
]
