"""Guidelines Extractor - scrape posting rules from platform guidelines pages."""
import logging
from typing import Optional
from sqlalchemy.orm import Session

from src.infrastructure.scrapers.static_scraper import StaticScraper
from src.infrastructure.repositories.platform_config_repo import PlatformConfigRepository
from src.infrastructure.repositories.guidelines_repo import GuidelinesRepository

logger = logging.getLogger(__name__)


class GuidelinesExtractor:
    """
    Extracts posting guidelines from platform help pages.

    Flow:
    1. Look up guidelines_url from platform_config table
    2. Scrape the guidelines page using StaticScraper
    3. Store in guidelines_cache with staleness tracking
    """

    def __init__(self, session: Session):
        self._session = session
        self._scraper = StaticScraper(timeout=20)
        self._platform_repo = PlatformConfigRepository(session)
        self._guidelines_repo = GuidelinesRepository(session)

    def extract_guidelines(self, domain: str, force_refresh: bool = False) -> Optional[str]:
        """
        Get guidelines for a domain.

        - If cached and fresh: return cached version
        - If stale or missing: scrape and cache

        Args:
            domain: The domain to get guidelines for
            force_refresh: Force re-scrape even if fresh

        Returns:
            Guidelines text or None if not available
        """
        # Check cache first (unless forced)
        if not force_refresh:
            cached = self._guidelines_repo.get_fresh_guidelines(domain, max_age_days=7)
            if cached:
                logger.info(f"Using cached guidelines for {domain} (scraped {cached.scraped_at})")
                return cached.content

        # Get guidelines URL from platform config
        config = self._platform_repo.get_by_domain(domain)
        if not config or not config.guidelines_url:
            logger.warning(f"No guidelines_url configured for {domain}")
            return None

        # Scrape the guidelines page
        logger.info(f"Scraping guidelines from {config.guidelines_url}")
        try:
            content = self._scraper.scrape(config.guidelines_url)

            if content.is_empty:
                logger.warning(f"Guidelines page returned empty content for {domain}")
                return None

            # Store in cache
            saved = self._guidelines_repo.save_guidelines(
                domain=domain,
                content=content.body,
                scraper_type_used="static",
                expires_days=7,
            )
            logger.info(f"Saved guidelines for {domain} ({len(content.body)} chars)")
            return saved.content

        except Exception as e:
            logger.error(f"Failed to scrape guidelines for {domain}: {e}")
            return None

    def extract_all_platforms(self, force_refresh: bool = False) -> dict:
        """
        Extract guidelines for all configured platforms.

        Returns:
            Dict of {domain: guidelines_text_or_None}
        """
        results = {}
        configs = self._platform_repo.get_all()

        for config in configs:
            if config.guidelines_url:
                guidelines = self.extract_guidelines(config.domain, force_refresh)
                results[config.domain] = guidelines
            else:
                logger.info(f"Skipping {config.domain} (no guidelines_url)")
                results[config.domain] = None

        return results

    def is_stale(self, domain: str) -> bool:
        """Check if guidelines for a domain need refresh."""
        return self._guidelines_repo.is_stale(domain, max_age_days=7)
