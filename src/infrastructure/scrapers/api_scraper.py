"""Type 1: API/RSS Native Scraper.

Handles platforms with public APIs or RSS feeds:
- Dev.to: /api/articles by path
- Reddit: append .json to thread URL
- Hacker News: Firebase API
- RSS/Atom feeds: feedparser
"""

import re
import logging
from typing import Optional
from datetime import datetime
from urllib.parse import urlparse

import requests
import feedparser

from src.domain.interfaces import Scraper
from src.domain.scraper_entities import ScrapedContent
from src.infrastructure.scrapers.base import extract_domain, DEFAULT_HEADERS

logger = logging.getLogger(__name__)

# Domains this scraper natively supports
API_DOMAINS = {
    "dev.to",
    "reddit.com",
    "old.reddit.com",
    "news.ycombinator.com",
}


class APIScraper(Scraper):
    """Scrapes content using platform-native APIs and RSS feeds."""

    def __init__(self, timeout: int = 15):
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(DEFAULT_HEADERS)

    def can_handle(self, url: str) -> bool:
        domain = extract_domain(url)
        # Check known API domains
        if domain in API_DOMAINS:
            return True
        # Check if URL points to an RSS/Atom feed
        if any(hint in url.lower() for hint in ["/rss", "/feed", "/atom", ".xml"]):
            return True
        return False

    def scrape(self, url: str) -> ScrapedContent:
        domain = extract_domain(url)
        logger.info(f"[API Scraper] Scraping: {url}")

        if domain == "dev.to":
            return self._scrape_devto(url)
        elif domain in ("reddit.com", "old.reddit.com"):
            return self._scrape_reddit(url)
        elif domain == "news.ycombinator.com":
            return self._scrape_hackernews(url)
        else:
            return self._scrape_rss(url)

    # ----- Dev.to -----

    def _scrape_devto(self, url: str) -> ScrapedContent:
        """Scrape Dev.to article using their public API."""
        # Extract the article path: /username/slug
        parsed = urlparse(url)
        path = parsed.path.strip("/")

        # Try fetching by path
        api_url = f"https://dev.to/api/articles/{path}"
        resp = self._session.get(api_url, timeout=self._timeout)
        resp.raise_for_status()
        data = resp.json()

        return ScrapedContent(
            url=url,
            domain="dev.to",
            title=data.get("title", ""),
            body=data.get("body_markdown", "") or data.get("body_html", ""),
            author=data.get("user", {}).get("username", ""),
            published_at=data.get("published_at", ""),
            scraper_type="api",
            metadata={
                "tags": data.get("tag_list", []),
                "reactions": data.get("positive_reactions_count", 0),
                "comments": data.get("comments_count", 0),
                "reading_time": data.get("reading_time_minutes", 0),
            },
        )

    # ----- Reddit -----

    def _scrape_reddit(self, url: str) -> ScrapedContent:
        """Scrape Reddit thread using old.reddit.com (server-rendered)."""
        # Convert to old.reddit.com for server-rendered HTML
        old_url = url.replace("www.reddit.com", "old.reddit.com").split("?")[0].rstrip("/")
        resp = self._session.get(
            old_url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; BacklinkBot/1.0)"},
            timeout=self._timeout,
        )
        resp.raise_for_status()

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")

        # Extract title
        title_el = soup.find("a", class_="title")
        title = title_el.get_text(strip=True) if title_el else ""

        # Extract post body
        body_parts = []
        selftext = soup.find("div", class_="usertext-body")
        if selftext:
            body_parts.append(selftext.get_text(strip=True))

        # Extract top-level comments
        comments = soup.find_all("div", class_="comment", limit=10)
        for comment in comments:
            author_el = comment.find("a", class_="author")
            body_el = comment.find("div", class_="md")
            if author_el and body_el:
                author = author_el.get_text(strip=True)
                c_body = body_el.get_text(strip=True)[:500]
                body_parts.append(f"\n---\n**{author}**:\n{c_body}")

        body = "\n\n".join(body_parts)
        if not body or len(body) < 50:
            raise ValueError(f"Reddit page content too short ({len(body)} chars)")

        return ScrapedContent(
            url=url,
            domain="reddit.com",
            title=title,
            body=body,
            author="",
            published_at="",
            scraper_type="api",
            metadata={},
        )

    # ----- Hacker News -----

    def _scrape_hackernews(self, url: str) -> ScrapedContent:
        """Scrape Hacker News item using Firebase API."""
        # Extract item ID from URL
        match = re.search(r"id=(\d+)", url)
        if not match:
            raise ValueError(f"Cannot extract HN item ID from: {url}")

        item_id = match.group(1)
        api_url = f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json"
        resp = self._session.get(api_url, timeout=self._timeout)
        resp.raise_for_status()
        data = resp.json()

        if not data:
            raise ValueError(f"HN item not found: {item_id}")

        if data.get("dead"):
            raise ValueError(f"HN thread archived/dead: {item_id}")

        # Build body from the story text + top comments
        body_parts = []
        story_text = data.get("text", "")
        if story_text:
            body_parts.append(story_text)

        # Fetch top comments (first 10 kids)
        kids = data.get("kids", [])[:10]
        for kid_id in kids:
            try:
                kid_url = f"https://hacker-news.firebaseio.com/v0/item/{kid_id}.json"
                kid_resp = self._session.get(kid_url, timeout=self._timeout)
                kid_data = kid_resp.json()
                if kid_data and kid_data.get("text"):
                    author = kid_data.get("by", "anon")
                    body_parts.append(f"\n---\n**{author}**:\n{kid_data['text']}")
            except Exception:
                continue

        return ScrapedContent(
            url=url,
            domain="news.ycombinator.com",
            title=data.get("title", ""),
            body="\n\n".join(body_parts) if body_parts else data.get("url", ""),
            author=data.get("by", ""),
            published_at=str(data.get("time", "")),
            scraper_type="api",
            metadata={
                "score": data.get("score", 0),
                "descendants": data.get("descendants", 0),
                "type": data.get("type", ""),
                "linked_url": data.get("url", ""),
            },
        )

    # ----- RSS / Atom -----

    def _scrape_rss(self, url: str) -> ScrapedContent:
        """Scrape content from an RSS or Atom feed URL."""
        feed = feedparser.parse(url)

        if feed.bozo and not feed.entries:
            raise ValueError(f"Failed to parse RSS feed: {url} — {feed.bozo_exception}")

        if not feed.entries:
            raise ValueError(f"RSS feed has no entries: {url}")

        # Take the first (most recent) entry
        entry = feed.entries[0]

        body = ""
        if hasattr(entry, "content") and entry.content:
            body = entry.content[0].get("value", "")
        elif hasattr(entry, "summary"):
            body = entry.summary or ""
        elif hasattr(entry, "description"):
            body = entry.description or ""

        return ScrapedContent(
            url=entry.get("link", url),
            domain=extract_domain(url),
            title=entry.get("title", ""),
            body=body,
            author=entry.get("author", ""),
            published_at=entry.get("published", ""),
            scraper_type="api",
            metadata={
                "feed_title": feed.feed.get("title", ""),
                "feed_url": url,
                "entry_count": len(feed.entries),
            },
        )
