"""Type 4: LLM Parser Fallback Scraper.

Last resort for pages with unpredictable HTML structures.
Fetches raw HTML and sends it to the LLM to extract structured content.
This is the most expensive type (1 LLM call per page).
"""

import logging
import json
import re
from typing import Optional

import requests

from src.domain.interfaces import Scraper, LLMService
from src.domain.scraper_entities import ScrapedContent
from src.infrastructure.scrapers.base import extract_domain, DEFAULT_HEADERS

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """Extract the main content from the following HTML page.

Return a JSON object with these fields:
- "title": The page/article title
- "author": The author's name (empty string if unknown)
- "published_at": The publication date (empty string if unknown)
- "body": The main content converted to clean markdown. Include all important text, code blocks, and formatting. Remove navigation, ads, sidebars, and footers.

Return ONLY valid JSON, no other text.

HTML content (truncated):
"""

MAX_HTML_CHARS = 12000  # Limit HTML sent to LLM to control token usage


class LLMScraper(Scraper):
    """Scrapes pages by sending raw HTML to an LLM for content extraction."""

    def __init__(self, llm_service: LLMService, timeout: int = 15):
        self._llm = llm_service
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(DEFAULT_HEADERS)

    def can_handle(self, url: str) -> bool:
        # LLM scraper can attempt any URL
        return True

    def scrape(self, url: str) -> ScrapedContent:
        domain = extract_domain(url)
        logger.info(f"[LLM Scraper] Scraping: {url}")

        # First, try fetching the raw HTML
        html = self._fetch_html(url)

        if not html:
            raise ValueError(f"Could not fetch any HTML from: {url}")

        # Truncate to stay within LLM context limits
        truncated = html[:MAX_HTML_CHARS]
        if len(html) > MAX_HTML_CHARS:
            truncated += "\n\n[... HTML truncated ...]"

        # Send to LLM for extraction
        prompt = EXTRACTION_PROMPT + truncated

        logger.info(f"[LLM Scraper] Sending {len(truncated)} chars to LLM for extraction")
        raw_response = self._llm.generate(
            prompt=prompt,
            system_prompt=(
                "You are an expert HTML content extractor. "
                "Extract the main content and return valid JSON only."
            ),
            temperature=0.1,  # Low temperature for consistent extraction
        )

        # Parse the LLM response
        parsed = self._parse_response(raw_response)

        return ScrapedContent(
            url=url,
            domain=domain,
            title=parsed.get("title", ""),
            body=parsed.get("body", ""),
            author=parsed.get("author", ""),
            published_at=parsed.get("published_at", ""),
            scraper_type="llm",
            metadata={"raw_html_length": len(html)},
        )

    def _fetch_html(self, url: str) -> str:
        """Fetch raw HTML. Try static first, fallback to Playwright if available."""
        try:
            resp = self._session.get(url, timeout=self._timeout, allow_redirects=True)
            if resp.ok:
                return resp.text
        except Exception as e:
            logger.warning(f"[LLM Scraper] Static fetch failed: {e}")

        # Try Playwright as HTML fetcher (not for content extraction, just raw HTML)
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(url, wait_until="networkidle", timeout=self._timeout * 1000)
                page.wait_for_timeout(2000)
                html = page.content()
                page.close()
                browser.close()
                return html
        except Exception as e:
            logger.warning(f"[LLM Scraper] Playwright fetch also failed: {e}")

        return ""

    def _parse_response(self, raw: str) -> dict:
        """Parse the LLM JSON response, handling common formatting issues."""
        # Try direct JSON parse
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # Try extracting JSON from markdown code block
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try finding any JSON object in the response
        brace_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass

        # Last resort: treat the entire response as the body
        logger.warning("[LLM Scraper] Could not parse JSON — using raw response as body")
        return {"title": "", "body": raw, "author": "", "published_at": ""}
