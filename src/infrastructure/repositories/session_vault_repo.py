from typing import Optional
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from src.infrastructure.models import PlatformSession
from src.infrastructure.repositories.base import BaseRepository


class SessionVaultRepository(BaseRepository[PlatformSession]):
    def __init__(self, session: Session):
        super().__init__(session, PlatformSession)

    def get_by_domain(self, domain: str) -> Optional[PlatformSession]:
        # Try exact match first
        session = self._session.query(PlatformSession).filter(PlatformSession.domain == domain).first()
        if session:
            return session
        # Fallback: try parent domains (e.g. dsvgroup.medium.com -> medium.com)
        parts = domain.split(".")
        for i in range(1, len(parts) - 1):
            parent = ".".join(parts[i:])
            session = self._session.query(PlatformSession).filter(PlatformSession.domain == parent).first()
            if session:
                return session
        return None

    def save_session(self, domain: str, encrypted_data: str, expires_at: Optional[datetime] = None) -> PlatformSession:
        existing = self.get_by_domain(domain)
        if existing:
            existing.session_data_encrypted = encrypted_data
            existing.expires_at = expires_at
            existing.last_used = datetime.now(timezone.utc)
            self._session.commit()
            self._session.refresh(existing)
            return existing
        else:
            new_session = PlatformSession(
                domain=domain,
                session_data_encrypted=encrypted_data,
                expires_at=expires_at,
                last_used=datetime.now(timezone.utc),
            )
            self._session.add(new_session)
            self._session.commit()
            self._session.refresh(new_session)
            return new_session

    def is_valid(self, domain: str) -> bool:
        session = self.get_by_domain(domain)
        if not session:
            return False
        if session.expires_at:
            expires = session.expires_at.replace(tzinfo=timezone.utc) if session.expires_at.tzinfo is None else session.expires_at
            if expires < datetime.now(timezone.utc):
                return False
        return True

    def flag_for_reauth(self, domain: str) -> None:
        session = self.get_by_domain(domain)
        if session:
            session.expires_at = datetime.now(timezone.utc)
            self._session.commit()
