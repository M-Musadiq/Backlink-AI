"""Session Manager - handles encryption/decryption of platform sessions."""
import json
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict
from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from src.infrastructure.repositories.session_vault_repo import SessionVaultRepository
from src.config import VAULT_ENCRYPTION_KEY

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages encrypted platform sessions for Playwright posting."""

    def __init__(self, db_session: Session):
        self._db = db_session
        self._vault = SessionVaultRepository(db_session)
        self._fernet = Fernet(VAULT_ENCRYPTION_KEY.encode() if isinstance(VAULT_ENCRYPTION_KEY, str) else VAULT_ENCRYPTION_KEY)

    def save_cookies(self, domain: str, cookies: List[Dict], expires_at: Optional[datetime] = None) -> None:
        """Save browser cookies for a platform.
        
        Args:
            domain: Platform domain (e.g., 'reddit.com')
            cookies: List of cookie dicts [{name, value, domain, path, ...}]
            expires_at: Optional expiration time
        """
        payload = json.dumps({"cookies": cookies, "saved_at": datetime.now(timezone.utc).isoformat()})
        encrypted = self._fernet.encrypt(payload.encode()).decode()
        self._vault.save_session(domain, encrypted, expires_at)
        logger.info(f"Saved session for {domain} ({len(cookies)} cookies)")

    def get_cookies(self, domain: str) -> List[Dict]:
        """Load browser cookies for a platform.
        
        Returns:
            List of cookie dicts for Playwright context.add_cookies()
        """
        session = self._vault.get_by_domain(domain)
        if not session:
            return []

        try:
            decrypted = self._fernet.decrypt(session.session_data_encrypted.encode()).decode()
            payload = json.loads(decrypted)
            return payload.get("cookies", [])
        except Exception as e:
            logger.error(f"Failed to decrypt session for {domain}: {e}")
            return []

    def is_session_valid(self, domain: str) -> bool:
        """Check if a valid session exists for the domain."""
        return self._vault.is_valid(domain)

    def invalidate_session(self, domain: str) -> None:
        """Mark a session as expired (needs re-login)."""
        self._vault.flag_for_reauth(domain)
        logger.info(f"Invalidated session for {domain}")

    def get_all_sessions(self) -> Dict[str, dict]:
        """Get status of all platform sessions."""
        all_sessions = self._vault.get_all()
        result = {}
        for s in all_sessions:
            result[s.domain] = {
                "valid": self.is_session_valid(s.domain),
                "last_used": s.last_used.isoformat() if s.last_used else None,
                "expires_at": s.expires_at.isoformat() if s.expires_at else None,
            }
        return result
