"""Guidelines Cache Manager - check freshness, get guidelines for drafter."""
import logging
from typing import Optional
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session

from src.infrastructure.repositories.guidelines_repo import GuidelinesRepository

logger = logging.getLogger(__name__)


class GuidelinesCacheManager:
    """
    Manages guidelines cache for the drafter agent.

    Provides:
    - Get guidelines by domain (fresh check)
    - Check if guidelines are stale
    - Get staleness info for monitoring
    """

    def __init__(self, session: Session, max_age_days: int = 7):
        self._session = session
        self._repo = GuidelinesRepository(session)
        self._max_age_days = max_age_days

    def get_guidelines(self, domain: str) -> Optional[str]:
        """
        Get fresh guidelines for a domain.

        Returns:
            Guidelines text if fresh, None if stale or missing
        """
        cached = self._repo.get_fresh_guidelines(domain, self._max_age_days)
        if cached:
            logger.info(f"Guidelines for {domain}: fresh (scraped {cached.scraped_at})")
            return cached.content
        logger.info(f"Guidelines for {domain}: stale or missing")
        return None

    def get_guidelines_any(self, domain: str) -> Optional[str]:
        """
        Get guidelines for a domain (even if stale).

        Returns:
            Most recent guidelines text or None
        """
        cached = self._repo.get_by_domain(domain)
        if cached:
            return cached.content
        return None

    def is_stale(self, domain: str) -> bool:
        """Check if guidelines need refresh."""
        return self._repo.is_stale(domain, self._max_age_days)

    def get_staleness_info(self, domain: str) -> dict:
        """
        Get detailed staleness info for a domain.

        Returns:
            Dict with domain, is_stale, scraped_at, expires_at, age_days
        """
        cached = self._repo.get_by_domain(domain)
        if not cached:
            return {
                "domain": domain,
                "is_stale": True,
                "scraped_at": None,
                "expires_at": None,
                "age_days": None,
            }

        now = datetime.now(timezone.utc)
        age = now - cached.scraped_at
        is_stale = age.days >= self._max_age_days

        return {
            "domain": domain,
            "is_stale": is_stale,
            "scraped_at": cached.scraped_at.isoformat(),
            "expires_at": cached.expires_at.isoformat() if cached.expires_at else None,
            "age_days": age.days,
        }

    def get_all_staleness(self) -> list:
        """Get staleness info for all cached guidelines."""
        from src.infrastructure.repositories.platform_config_repo import PlatformConfigRepository
        platform_repo = PlatformConfigRepository(self._session)

        results = []
        for config in platform_repo.get_all():
            if config.guidelines_url:
                info = self.get_staleness_info(config.domain)
                results.append(info)

        return results
