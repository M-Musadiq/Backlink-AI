"""RSS Feed Discovery - find and parse RSS feeds from target domains."""
import logging
from typing import List, Dict, Optional
from urllib.parse import urljoin
import feedparser
import httpx

logger = logging.getLogger(__name__)

# Common RSS feed paths to check
COMMON_FEED_PATHS = [
    "/feed",
    "/rss",
    "/feed.xml",
    "/rss.xml",
    "/atom.xml",
    "/index.xml",
    "/blog/feed",
    "/blog/rss",
    "/blog/feed.xml",
    "/blog/rss.xml",
    "/news/feed",
    "/news/rss",
    "/.rss",
]

# Known platform feeds
PLATFORM_FEEDS = {
    "reddit.com": "https://www.reddit.com/r/{subreddit}/.rss",
    "dev.to": "https://dev.to/feed",
    "hashnode.com": "https://hashnode.com/feed",
    "news.ycombinator.com": "https://hnrss.org/frontpage",
    "medium.com": "https://medium.com/feed",
}


class RSSDiscovery:
    """Discover and parse RSS feeds from target domains."""

    def __init__(self, timeout: int = 10):
        self._timeout = timeout

    def discover_feeds(self, domain: str) -> List[str]:
        """
        Discover RSS feed URLs for a domain.

        Args:
            domain: The domain to search (e.g., "example.com")

        Returns:
            List of feed URLs found
        """
        feeds = []

        # Check known platform feeds first
        for platform, feed_url in PLATFORM_FEEDS.items():
            if platform in domain:
                feeds.append(feed_url)
                logger.info(f"Found known feed for {domain}: {feed_url}")

        # Check common feed paths
        base_url = f"https://{domain}"
        for path in COMMON_FEED_PATHS:
            feed_url = urljoin(base_url, path)
            if self._is_feed(feed_url):
                feeds.append(feed_url)
                logger.info(f"Discovered feed: {feed_url}")

        return list(set(feeds))

    def parse_feed(self, feed_url: str, max_entries: int = 20) -> List[Dict]:
        """
        Parse an RSS feed and extract entries.

        Args:
            feed_url: URL of the RSS feed
            max_entries: Maximum number of entries to return

        Returns:
            List of dicts with keys: url, title, published, summary
        """
        results = []

        try:
            feed = feedparser.parse(feed_url)

            if feed.bozo and not feed.entries:
                logger.warning(f"Feed parse error for {feed_url}: {feed.bozo_exception}")
                return results

            for entry in feed.entries[:max_entries]:
                result = {
                    "url": entry.get("link", ""),
                    "title": entry.get("title", ""),
                    "published": entry.get("published", ""),
                    "summary": entry.get("summary", "")[:500],
                }
                if result["url"]:
                    results.append(result)

            logger.info(f"Parsed feed {feed_url}: {len(results)} entries")
        except Exception as e:
            logger.error(f"Failed to parse feed {feed_url}: {e}")

        return results

    def parse_known_feed(self, platform: str, subreddit: str = "") -> List[Dict]:
        """
        Parse a known platform feed.

        Args:
            platform: Platform name (e.g., "reddit.com")
            subreddit: Optional subreddit for Reddit

        Returns:
            List of parsed entries
        """
        feed_url = PLATFORM_FEEDS.get(platform)
        if not feed_url:
            return []

        if "{subreddit}" in feed_url:
            feed_url = feed_url.format(subreddit=subreddit)

        return self.parse_feed(feed_url)

    def _is_feed(self, url: str) -> bool:
        """Check if a URL is a valid RSS/Atom feed."""
        try:
            response = httpx.get(url, timeout=self._timeout, follow_redirects=True)
            if response.status_code != 200:
                return False

            content_type = response.headers.get("content-type", "").lower()
            if any(t in content_type for t in ["xml", "rss", "atom"]):
                return True

            # Check if content looks like XML
            text = response.text[:500].strip()
            if text.startswith("<?xml") or "<rss" in text or "<feed" in text:
                return True

            return False
        except Exception:
            return False
