from typing import Optional, List
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from src.infrastructure.models import AuditLog
from src.infrastructure.repositories.base import BaseRepository


class AuditLogRepository(BaseRepository[AuditLog]):
    def __init__(self, session: Session):
        super().__init__(session, AuditLog)

    def log_action(self, action: str, details: str = "", prospect_id: Optional[int] = None) -> AuditLog:
        log_entry = AuditLog(
            prospect_id=prospect_id,
            action=action,
            details=details,
            created_at=datetime.now(timezone.utc),
        )
        self._session.add(log_entry)
        self._session.commit()
        self._session.refresh(log_entry)
        return log_entry

    def get_prospect_history(self, prospect_id: int) -> List[AuditLog]:
        return (
            self._session.query(AuditLog)
            .filter(AuditLog.prospect_id == prospect_id)
            .order_by(AuditLog.created_at.desc())
            .all()
        )

    def get_recent(self, limit: int = 50) -> List[AuditLog]:
        return (
            self._session.query(AuditLog)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
            .all()
        )
