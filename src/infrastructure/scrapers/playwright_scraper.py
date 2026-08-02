"""Type 3: Playwright Dynamic Scraper.

For JavaScript-heavy pages (SPAs, Medium, modern forums) where
static HTML fetch returns empty or loading-spinner content.
Uses a headless Chromium browser to render the page fully.
"""

import logging
from typing import Optional

from src.domain.interfaces import Scraper
from src.domain.scraper_entities import ScrapedContent
from src.infrastructure.scrapers.base import (
    extract_domain,
    clean_html_to_markdown,
    extract_main_content,
    extract_metadata,
    STRIP_TAGS,
    STRIP_SELECTORS,
)

logger = logging.getLogger(__name__)


class PlaywrightScraper(Scraper):
    """Scrapes JS-rendered pages using a stealth headless Chromium browser."""

    def __init__(self, timeout: int = 20, headless: bool = True):
        self._timeout = timeout * 1000  # Playwright uses ms
        self._headless = headless
        self._browser = None
        self._playwright = None

    def can_handle(self, url: str) -> bool:
        # Playwright can handle any URL
        return True

    def _ensure_browser(self):
        """Lazily start the stealth browser only when first needed."""
        if self._browser is None:
            from playwright.sync_api import sync_playwright

            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(
                headless=self._headless,
                channel="chrome",
                args=[
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            logger.info("[Playwright Scraper] Stealth browser launched")

    def scrape(self, url: str) -> ScrapedContent:
        domain = extract_domain(url)
        logger.info(f"[Playwright Scraper] Scraping: {url}")

        self._ensure_browser()

        # Create a fresh stealth context per scrape to avoid cookie bleed
        context = self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()
        # Mask navigator.webdriver to bypass bot-detection (Cloudflare, Quora, etc.)
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        try:
            # Navigate and wait for content to load
            page.goto(url, wait_until="networkidle", timeout=self._timeout)

            # Extra wait for late-loading content
            page.wait_for_timeout(2000)

            # Get the fully rendered HTML
            raw_html = page.content()

        except Exception as e:
            logger.error(f"[Playwright Scraper] Navigation failed: {e}")
            raise
        finally:
            page.close()
            context.close()

        # Parse with BeautifulSoup (same logic as static scraper)
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(raw_html, "html.parser")

        # Extract metadata
        meta = extract_metadata(soup, url=url)

        # Find main content
        main_el = extract_main_content(soup)

        if main_el:
            for tag_name in STRIP_TAGS:
                for tag in main_el.find_all(tag_name):
                    tag.decompose()
            for selector in STRIP_SELECTORS:
                for el in main_el.select(selector):
                    el.decompose()

            body = clean_html_to_markdown(str(main_el))
        else:
            body = clean_html_to_markdown(raw_html)

        if not body or len(body.strip()) < 50:
            raise ValueError(
                f"Playwright rendered page but extracted content is too short ({len(body)} chars)"
            )

        return ScrapedContent(
            url=url,
            domain=domain,
            title=meta.get("title", ""),
            body=body,
            author=meta.get("author", ""),
            published_at=meta.get("published_at", ""),
            scraper_type="playwright",
            metadata={k: v for k, v in meta.items() if k not in ("title", "author", "published_at")},
        )

    def close(self):
        """Shut down the browser and Playwright."""
        try:
            if self._browser:
                self._browser.close()
                self._browser = None
            if self._playwright:
                self._playwright.stop()
                self._playwright = None
                logger.info("[Playwright Scraper] Browser closed")
        except Exception:
            self._browser = None
            self._playwright = None

    def __del__(self):
        self.close()
