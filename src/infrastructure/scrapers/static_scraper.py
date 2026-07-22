"""Type 2: Static HTML Scraper.

For server-rendered pages (blogs, forums, documentation).
Uses requests + BeautifulSoup to fetch and parse HTML without a browser.
"""

import logging
from typing import Optional

import requests
from bs4 import BeautifulSoup

from src.domain.interfaces import Scraper
from src.domain.scraper_entities import ScrapedContent
from src.infrastructure.scrapers.base import (
    extract_domain,
    clean_html_to_markdown,
    extract_main_content,
    extract_metadata,
    is_js_rendered_page,
    DEFAULT_HEADERS,
    STRIP_TAGS,
    STRIP_SELECTORS,
)

logger = logging.getLogger(__name__)


class ScraperError(Exception):
    """Raised when scraping fails in a way that suggests escalation."""

    def __init__(self, message: str, should_escalate: bool = False):
        super().__init__(message)
        self.should_escalate = should_escalate


class StaticScraper(Scraper):
    """Scrapes server-rendered HTML pages using requests + BeautifulSoup."""

    def __init__(self, timeout: int = 15):
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(DEFAULT_HEADERS)

    def can_handle(self, url: str) -> bool:
        # Static scraper is the default fallback — it can try any URL
        return True

    def scrape(self, url: str) -> ScrapedContent:
        domain = extract_domain(url)
        logger.info(f"[Static Scraper] Scraping: {url}")

        try:
            resp = self._session.get(url, timeout=self._timeout, allow_redirects=True)
        except requests.exceptions.ConnectionError as e:
            raise ScraperError(f"Connection failed: {e}", should_escalate=False)
        except requests.exceptions.Timeout:
            raise ScraperError(f"Request timed out after {self._timeout}s", should_escalate=False)

        # Check for HTTP errors that suggest escalation
        if resp.status_code == 403:
            raise ScraperError(
                f"HTTP 403 Forbidden — site may block bots",
                should_escalate=True,
            )
        if resp.status_code == 429:
            raise ScraperError(
                f"HTTP 429 Too Many Requests — rate limited",
                should_escalate=False,
            )
        if resp.status_code >= 400:
            raise ScraperError(
                f"HTTP {resp.status_code} error",
                should_escalate=resp.status_code in (403, 406, 451),
            )

        raw_html = resp.text

        # Check if the page needs JS rendering
        if is_js_rendered_page(raw_html):
            raise ScraperError(
                "Page appears to require JavaScript rendering",
                should_escalate=True,
            )

        # Parse the HTML
        soup = BeautifulSoup(raw_html, "html.parser")

        # Extract metadata
        meta = extract_metadata(soup)

        # Find main content
        main_el = extract_main_content(soup)

        if main_el:
            # Clean the main content element
            for tag_name in STRIP_TAGS:
                for tag in main_el.find_all(tag_name):
                    tag.decompose()
            for selector in STRIP_SELECTORS:
                for el in main_el.select(selector):
                    el.decompose()

            body = clean_html_to_markdown(str(main_el))
        else:
            # Fallback: clean the entire page
            body = clean_html_to_markdown(raw_html)

        if not body or len(body.strip()) < 50:
            raise ScraperError(
                "Extracted content is too short — page may need JS rendering",
                should_escalate=True,
            )

        return ScrapedContent(
            url=url,
            domain=domain,
            title=meta.get("title", ""),
            body=body,
            author=meta.get("author", ""),
            published_at=meta.get("published_at", ""),
            scraper_type="static",
            metadata={k: v for k, v in meta.items() if k not in ("title", "author", "published_at")},
        )
