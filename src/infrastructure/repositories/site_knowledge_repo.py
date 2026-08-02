from typing import Optional, List
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from src.infrastructure.models import SiteKnowledge
from src.infrastructure.repositories.base import BaseRepository


class SiteKnowledgeRepository(BaseRepository[SiteKnowledge]):
    def __init__(self, session: Session):
        super().__init__(session, SiteKnowledge)

    def get_by_domain(self, domain: str) -> Optional[SiteKnowledge]:
        return self._session.query(SiteKnowledge).filter(SiteKnowledge.domain == domain).first()

    def get_by_site_type(self, site_type: str) -> List[SiteKnowledge]:
        return self._session.query(SiteKnowledge).filter(SiteKnowledge.site_type == site_type).all()

    def get_unclassified(self) -> List[SiteKnowledge]:
        return self._session.query(SiteKnowledge).filter(SiteKnowledge.site_type == "").all()

    def upsert(self, domain: str, **kwargs) -> SiteKnowledge:
        existing = self.get_by_domain(domain)
        if existing:
            for k, v in kwargs.items():
                if hasattr(existing, k):
                    setattr(existing, k, v)
            existing.updated_at = datetime.now(timezone.utc)
            self._session.commit()
            self._session.refresh(existing)
            return existing
        else:
            obj = SiteKnowledge(domain=domain, **kwargs)
            self._session.add(obj)
            self._session.commit()
            self._session.refresh(obj)
            return obj

    def record_visit(self, domain: str, success: bool) -> None:
        site = self.get_by_domain(domain)
        if not site:
            site = self.upsert(domain=domain)
        site.visit_count = (site.visit_count or 0) + 1
        site.last_visited = datetime.now(timezone.utc)
        if success:
            site.success_count = (site.success_count or 0) + 1
        else:
            site.failure_count = (site.failure_count or 0) + 1
        total = (site.success_count or 0) + (site.failure_count or 0)
        site.success_rate = (site.success_count or 0) / total if total > 0 else 0.0
        site.updated_at = datetime.now(timezone.utc)
        self._session.commit()

    def record_error(self, domain: str, error: str) -> None:
        site = self.get_by_domain(domain)
        if not site:
            site = self.upsert(domain=domain)
        site.last_error = error[:500]
        site.updated_at = datetime.now(timezone.utc)
        self._session.commit()

    def search(self, query: str) -> List[SiteKnowledge]:
        q = f"%{query}%"
        return self._session.query(SiteKnowledge).filter(
            SiteKnowledge.domain.ilike(q) | SiteKnowledge.title.ilike(q) | SiteKnowledge.description.ilike(q)
        ).limit(50).all()

    def get_all_summary(self) -> List[dict]:
        rows = self._session.query(SiteKnowledge).order_by(SiteKnowledge.updated_at.desc().nullslast()).all()
        return [
            {
                "id": r.id,
                "domain": r.domain,
                "site_type": r.site_type or "unclassified",
                "title": r.title or "",
                "login_required": r.login_required,
                "posting_capable": r.posting_capable,
                "listing_capable": r.listing_capable,
                "visit_count": r.visit_count or 0,
                "success_rate": r.success_rate or 0.0,
                "last_visited": r.last_visited.isoformat() if r.last_visited else None,
                "last_error": r.last_error or "",
                "discovered_at": r.discovered_at.isoformat() if r.discovered_at else None,
            }
            for r in rows
        ]
