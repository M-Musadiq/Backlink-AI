from typing import Optional
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from src.infrastructure.models import GuidelinesCache
from src.infrastructure.repositories.base import BaseRepository


class GuidelinesRepository(BaseRepository[GuidelinesCache]):
    def __init__(self, session: Session):
        super().__init__(session, GuidelinesCache)

    def get_by_domain(self, domain: str) -> Optional[GuidelinesCache]:
        return (
            self._session.query(GuidelinesCache)
            .filter(GuidelinesCache.domain == domain)
            .order_by(GuidelinesCache.scraped_at.desc())
            .first()
        )

    def get_fresh_guidelines(self, domain: str, max_age_days: int = 7) -> Optional[GuidelinesCache]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        return (
            self._session.query(GuidelinesCache)
            .filter(GuidelinesCache.domain == domain)
            .filter(GuidelinesCache.scraped_at >= cutoff)
            .order_by(GuidelinesCache.scraped_at.desc())
            .first()
        )

    def is_stale(self, domain: str, max_age_days: int = 7) -> bool:
        guidelines = self.get_by_domain(domain)
        if not guidelines:
            return True
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        return guidelines.scraped_at < cutoff

    def save_guidelines(self, domain: str, content: str, scraper_type_used: str = "", expires_days: int = 7) -> GuidelinesCache:
        existing = self.get_by_domain(domain)
        if existing:
            existing.content = content
            existing.scraped_at = datetime.now(timezone.utc)
            existing.expires_at = datetime.now(timezone.utc) + timedelta(days=expires_days)
            existing.scraper_type_used = scraper_type_used
            self._session.commit()
            self._session.refresh(existing)
            return existing
        else:
            new_entry = GuidelinesCache(
                domain=domain,
                content=content,
                scraped_at=datetime.now(timezone.utc),
                expires_at=datetime.now(timezone.utc) + timedelta(days=expires_days),
                scraper_type_used=scraper_type_used,
            )
            self._session.add(new_entry)
            self._session.commit()
            self._session.refresh(new_entry)
            return new_entry
