from typing import Optional, List
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from src.infrastructure.models import PlatformConfigDB
from src.infrastructure.repositories.base import BaseRepository
from src.domain.scraper_entities import PlatformConfig


class PlatformConfigRepository(BaseRepository[PlatformConfigDB]):
    def __init__(self, session: Session):
        super().__init__(session, PlatformConfigDB)

    def get_by_domain(self, domain: str) -> Optional[PlatformConfigDB]:
        return self._session.query(PlatformConfigDB).filter(PlatformConfigDB.domain == domain).first()

    def get(self, domain: str) -> Optional[PlatformConfig]:
        """Adapter: returns PlatformConfig domain entity for ScrapeOrchestrator."""
        db = self.get_by_domain(domain)
        if not db:
            return None
        return PlatformConfig(
            domain=db.domain,
            scraper_type=db.scraper_type,
            post_method=db.post_method,
            requires_auth=db.requires_auth,
            rate_limit_seconds=db.rate_limit_seconds,
            guidelines_url=db.guidelines_url,
            last_updated=db.last_updated,
        )

    def save(self, config: PlatformConfig) -> None:
        """Adapter: saves PlatformConfig domain entity for ScrapeOrchestrator."""
        self.upsert(
            domain=config.domain,
            scraper_type=config.scraper_type,
            post_method=config.post_method,
            requires_auth=config.requires_auth,
            rate_limit_seconds=config.rate_limit_seconds,
            guidelines_url=config.guidelines_url,
        )

    def upsert(self, domain: str, **kwargs) -> PlatformConfigDB:
        existing = self.get_by_domain(domain)
        if existing:
            for key, value in kwargs.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
            existing.last_updated = datetime.now(timezone.utc)
            self._session.commit()
            self._session.refresh(existing)
            return existing
        else:
            new_config = PlatformConfigDB(domain=domain, **kwargs)
            self._session.add(new_config)
            self._session.commit()
            self._session.refresh(new_config)
            return new_config

    def get_all_domains(self) -> List[str]:
        results = self._session.query(PlatformConfigDB.domain).all()
        return [r[0] for r in results]
