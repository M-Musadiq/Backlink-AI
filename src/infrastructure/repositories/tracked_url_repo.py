from typing import Optional, List
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from src.infrastructure.models import TrackedURL
from src.infrastructure.repositories.base import BaseRepository


class TrackedURLRepository(BaseRepository[TrackedURL]):
    def __init__(self, session: Session):
        super().__init__(session, TrackedURL)

    def get_by_url(self, url: str) -> Optional[TrackedURL]:
        return self._session.query(TrackedURL).filter(TrackedURL.url == url).first()

    def get_by_domain(self, domain: str) -> List[TrackedURL]:
        return self._session.query(TrackedURL).filter(TrackedURL.domain == domain).all()

    def get_by_status(self, status: str) -> List[TrackedURL]:
        return self._session.query(TrackedURL).filter(TrackedURL.status == status).all()

    def get_new_urls(self, limit: int = 100) -> List[TrackedURL]:
        return (
            self._session.query(TrackedURL)
            .filter(TrackedURL.status == "discovered")
            .order_by(TrackedURL.discovered_at.desc())
            .limit(limit)
            .all()
        )

    def mark_scraped(self, url_id: int) -> None:
        tracked = self.get_by_id(url_id)
        if tracked:
            tracked.status = "scraped"
            tracked.last_checked = datetime.now(timezone.utc)
            self._session.commit()

    def url_exists(self, url: str) -> bool:
        return self._session.query(TrackedURL).filter(TrackedURL.url == url).first() is not None
