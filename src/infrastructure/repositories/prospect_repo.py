from typing import Optional, List
from datetime import datetime, timezone
from sqlalchemy.orm import Session, joinedload
from src.infrastructure.models import Prospect
from src.infrastructure.repositories.base import BaseRepository


class ProspectRepository(BaseRepository[Prospect]):
    def __init__(self, session: Session):
        super().__init__(session, Prospect)

    def get_by_url(self, url: str) -> Optional[Prospect]:
        return self._session.query(Prospect).options(joinedload(Prospect.tracked_url)).filter(Prospect.url == url).first()

    def get_by_domain(self, domain: str) -> List[Prospect]:
        return self._session.query(Prospect).options(joinedload(Prospect.tracked_url)).filter(Prospect.domain == domain).all()

    def get_by_status(self, status: str) -> List[Prospect]:
        return self._session.query(Prospect).options(joinedload(Prospect.tracked_url)).filter(Prospect.status == status).order_by(Prospect.id.asc()).all()

    def get_by_statuses(self, statuses: List[str]) -> List[Prospect]:
        return self._session.query(Prospect).options(joinedload(Prospect.tracked_url)).filter(Prospect.status.in_(statuses)).order_by(Prospect.id.asc()).all()

    def get_pending_drafts(self) -> List[Prospect]:
        return self._session.query(Prospect).options(joinedload(Prospect.tracked_url)).filter(Prospect.status == "drafted").order_by(Prospect.id.asc()).all()

    def get_approved(self) -> List[Prospect]:
        return self._session.query(Prospect).options(joinedload(Prospect.tracked_url)).filter(Prospect.status == "approved").order_by(Prospect.id.asc()).all()

    def count_by_domain(self, domain: str) -> int:
        return self._session.query(Prospect).filter(Prospect.domain == domain).count()

    def get_all(self) -> List[Prospect]:
        return self._session.query(Prospect).options(joinedload(Prospect.tracked_url)).order_by(Prospect.id.asc()).all()

    def update_status(self, prospect_id: int, new_status: str) -> None:
        prospect = self.get_by_id(prospect_id)
        if prospect:
            prospect.status = new_status
            prospect.updated_at = datetime.now(timezone.utc)
            self._session.commit()

    def advance_waiting_login_to_discovered(self, domain: str) -> int:
        """Move all waiting_for_login prospects for a domain to discovered (cookies now available)."""
        from sqlalchemy import update
        domains = [domain]
        if domain.startswith("www."):
            domains.append(domain.removeprefix("www."))
        else:
            domains.append(f"www.{domain}")
        count = self._session.execute(
            update(Prospect)
            .where(Prospect.domain.in_(domains), Prospect.status == "waiting_for_login")
            .values(status="discovered", updated_at=datetime.now(timezone.utc))
        ).rowcount
        self._session.commit()
        return count

    def save_draft(self, prospect_id: int, draft_content: str) -> None:
        prospect = self.get_by_id(prospect_id)
        if prospect:
            prospect.draft_content = draft_content
            prospect.status = "drafted"
            prospect.updated_at = datetime.now(timezone.utc)
            self._session.commit()

    def save_feedback(self, prospect_id: int, feedback: str) -> None:
        prospect = self.get_by_id(prospect_id)
        if prospect:
            prospect.feedback_notes = feedback
            prospect.updated_at = datetime.now(timezone.utc)
            self._session.commit()

    def archive(self, prospect_id: int) -> None:
        prospect = self.get_by_id(prospect_id)
        if prospect:
            prospect.status = "archived"
            prospect.updated_at = datetime.now(timezone.utc)
            self._session.commit()
