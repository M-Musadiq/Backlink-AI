"""Scrape Orchestrator — the escalation engine.

Given any URL, auto-detects the best scraper type, tries it,
and escalates to the next type on failure. Caches the winning
scraper type per domain in the PlatformConfigStore.
"""

import logging
from typing import Optional
from datetime import datetime, timezone

from src.domain.interfaces import Scraper, LLMService, PlatformConfigStore
from src.domain.scraper_entities import ScrapedContent, PlatformConfig
from src.infrastructure.scrapers.base import extract_domain
from src.infrastructure.scrapers.api_scraper import APIScraper
from src.infrastructure.scrapers.static_scraper import StaticScraper, ScraperError
from src.infrastructure.scrapers.playwright_scraper import PlaywrightScraper
from src.infrastructure.scrapers.llm_scraper import LLMScraper

logger = logging.getLogger(__name__)

# Scraper type names in escalation order (cheapest → most expensive)
SCRAPER_ORDER = ["api", "static", "playwright", "llm"]


class ScrapeOrchestrator:
    """Routes URLs to the right scraper and handles escalation on failure."""

    def __init__(
        self,
        config_store: PlatformConfigStore,
        llm_service: Optional[LLMService] = None,
        timeout: int = 15,
    ):
        self._config_store = config_store
        self._timeout = timeout

        # Initialize all scraper types
        self._scrapers: dict[str, Scraper] = {
            "api": APIScraper(timeout=timeout),
            "static": StaticScraper(timeout=timeout),
            "playwright": PlaywrightScraper(timeout=timeout),
        }

        # LLM scraper only available if an LLM service is provided
        if llm_service:
            self._scrapers["llm"] = LLMScraper(llm_service=llm_service, timeout=timeout)

    def scrape(self, url: str, force_type: Optional[str] = None) -> ScrapedContent:
        """
        Scrape a URL with auto-detection and escalation.

        Args:
            url: The URL to scrape.
            force_type: Force a specific scraper type (skip auto-detect).

        Returns:
            ScrapedContent with the extracted page content.

        Raises:
            ValueError: If all scraper types fail.
        """
        domain = extract_domain(url)

        if force_type:
            # User explicitly chose a scraper type
            return self._try_scraper(force_type, url)

        # Check if we have a cached config for this domain
        config = self._config_store.get(domain)

        # Build the ordered list of scrapers to try
        attempt_order = self._build_attempt_order(url, config)

        logger.info(f"Scrape plan for {domain}: {' → '.join(attempt_order)}")

        errors = []
        for scraper_type in attempt_order:
            if scraper_type not in self._scrapers:
                logger.debug(f"Skipping {scraper_type} (not available)")
                continue

            try:
                result = self._try_scraper(scraper_type, url)

                # Success — cache this scraper type for the domain
                self._cache_success(domain, scraper_type)

                logger.info(
                    f"Successfully scraped {url} with {scraper_type} scraper "
                    f"({len(result.body)} chars)"
                )
                return result

            except ScraperError as e:
                errors.append(f"{scraper_type}: {e}")
                if e.should_escalate:
                    logger.warning(f"[{scraper_type}] Failed with escalation: {e}")
                    continue  # Try next scraper
                else:
                    logger.warning(f"[{scraper_type}] Failed (no escalation): {e}")
                    continue  # Still try next for robustness

            except Exception as e:
                errors.append(f"{scraper_type}: {e}")
                logger.warning(f"[{scraper_type}] Unexpected error: {e}")
                continue

        # All scrapers failed
        error_summary = "\n  ".join(errors)
        raise ValueError(
            f"All scraper types failed for {url}:\n  {error_summary}"
        )

    def _build_attempt_order(
        self, url: str, config: Optional[PlatformConfig]
    ) -> list[str]:
        """Determine which scrapers to try and in what order."""
        domain = extract_domain(url)

        # If we have a cached config, start with that type
        if config and config.scraper_type in self._scrapers:
            cached_type = config.scraper_type
            # Put cached type first, then the rest in standard order
            order = [cached_type]
            for t in SCRAPER_ORDER:
                if t != cached_type:
                    order.append(t)
            return order

        # No cached config — use auto-detection
        # Check if API scraper can handle this URL natively
        api_scraper = self._scrapers.get("api")
        if api_scraper and api_scraper.can_handle(url):
            return ["api", "static", "playwright", "llm"]

        # Default: start with static (cheapest), then escalate
        return ["static", "playwright", "llm"]

    def _try_scraper(self, scraper_type: str, url: str) -> ScrapedContent:
        """Try a specific scraper type."""
        scraper = self._scrapers.get(scraper_type)
        if not scraper:
            raise ValueError(f"Scraper type '{scraper_type}' is not available")

        logger.info(f"Trying {scraper_type} scraper for: {url}")
        return scraper.scrape(url)

    def _cache_success(self, domain: str, scraper_type: str) -> None:
        """Save the successful scraper type for this domain."""
        existing = self._config_store.get(domain)

        if existing:
            # Update only if the type changed
            if existing.scraper_type != scraper_type:
                existing.scraper_type = scraper_type
                existing.last_updated = datetime.now(timezone.utc)
                self._config_store.save(existing)
                logger.info(f"Updated config for {domain}: scraper_type={scraper_type}")
        else:
            # Create new config
            new_config = PlatformConfig(
                domain=domain,
                scraper_type=scraper_type,
                last_updated=datetime.now(timezone.utc),
            )
            self._config_store.save(new_config)
            logger.info(f"Cached new config for {domain}: scraper_type={scraper_type}")

    def close(self):
        """Clean up resources (browser instances, etc.)."""
        pw_scraper = self._scrapers.get("playwright")
        if pw_scraper and hasattr(pw_scraper, "close"):
            pw_scraper.close()
