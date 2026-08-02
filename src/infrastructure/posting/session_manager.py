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
        
        Falls back to a session whose cookies cover this domain, so that a
        single login (e.g. cookies scoped to `.substack.com`) is reused for
        every subdomain (`blog.substack.com`, `other.substack.com`, ...).
        
        Returns:
            List of cookie dicts for Playwright context.add_cookies()
        """
        session = self._vault.get_by_domain(domain)
        resolved_from = None
        if not session:
            session, resolved_from = self._find_fallback_session(domain)
        if not session:
            return []

        try:
            decrypted = self._fernet.decrypt(session.session_data_encrypted.encode()).decode()
            payload = json.loads(decrypted)
            cookies = payload.get("cookies", [])
            if resolved_from:
                logger.info(
                    f"Session: no session for '{domain}', using '{resolved_from}' "
                    f"(cookie scope covers target host)"
                )
            return cookies
        except Exception as e:
            logger.error(f"Failed to decrypt session for {domain}: {e}")
            return []

    def is_session_valid(self, domain: str) -> bool:
        """Check if a valid session exists for the domain or any scoped-cookie session covers it."""
        if self._vault.is_valid(domain):
            return True
        session, _ = self._find_fallback_session(domain)
        if not session:
            return False
        return self._is_not_expired(session)

    def invalidate_session(self, domain: str) -> None:
        """Mark a session as expired (needs re-login)."""
        self._vault.flag_for_reauth(domain)
        resolved = self._find_fallback_session(domain)[0]
        if resolved and resolved.domain != domain:
            self._vault.flag_for_reauth(resolved.domain)
            logger.info(f"Invalidated session for {domain} and its covering session '{resolved.domain}'")
        else:
            logger.info(f"Invalidated session for {domain}")

    def _find_fallback_session(self, domain: str):
        """Find a stored session whose cookie scope covers the target host.

        Fallback precedence:
        1. Cookie-scope match — any saved cookie whose RFC 6265 scope covers the
           host (e.g. ``.substack.com`` covers ``blog.substack.com``).
        2. Platform-root match — derived from the registered domain of every
           saved session, so ``substack.custom.com`` reuses the ``substack.com``
           session the same way ``foo.medium.com`` reuses ``medium.com``.

        Returns ``(PlatformSession, stored_domain)`` or ``(None, None)``.
        """
        host = domain.strip().lower().lstrip("www.")
        best = None
        best_scope = None
        best_domain = None
        platform_index = self._build_platform_index()
        platform_root = self._resolve_platform_root(host, platform_index)
        for stored in self._vault.get_all():
            if not self._is_not_expired(stored):
                continue
            try:
                decrypted = self._fernet.decrypt(stored.session_data_encrypted.encode()).decode()
                payload = json.loads(decrypted)
            except Exception:
                continue
            cookies = payload.get("cookies", [])
            stored_root = _registrable_domain(stored.domain)
            if platform_root and stored_root == platform_root:
                return stored, stored.domain
            for c in cookies:
                scope = c.get("domain", "")
                if self._covers(scope, host) and (best_scope is None or len(scope) > len(best_scope)):
                    best = stored
                    best_scope = scope
                    best_domain = stored.domain
        if best is not None:
            return best, best_domain
        return None, None

    def _build_platform_index(self) -> dict:
        """Map platform label -> registrable root domain for every saved session.

        e.g. a session for ``substack.com`` registers the label ``substack``,
        so any host containing that label (``foo.substack.com``,
        ``substack.custom.com``) is later mapped back to that session.
        """
        index = {}
        for stored in self._vault.get_all():
            if not self._is_not_expired(stored):
                continue
            root = _registrable_domain(stored.domain)
            if not root:
                continue
            label = root.split(".")[0]
            if len(label) > 2:
                index.setdefault(label, root)
        return index

    def _resolve_platform_root(self, host: str, platform_index: dict):
        """Match a host's labels against known platform labels.

        The most specific (longest) known label wins, so ``medium.com`` is
        preferred over ``com`` if both were somehow indexed.
        """
        labels = host.split(".")
        candidates = [(label, root) for label, root in platform_index.items() if label in labels]
        if not candidates:
            return None
        return max(candidates, key=lambda item: len(item[0]))[1]

    @staticmethod
    def _covers(scope: str, host: str) -> bool:
        """True when a cookie set for *scope* is sent to `host` (RFC 6265)."""
        domain = scope.strip().lstrip(".").lower()
        if not domain:
            return False
        host = host.lower()
        return host == domain or host.endswith("." + domain)

    def _is_not_expired(self, session) -> bool:
        if not session.expires_at:
            return True
        expires = session.expires_at
        if expires.tzinfo is None:
            from datetime import timezone
            expires = expires.replace(tzinfo=timezone.utc)
        return expires >= datetime.now(timezone.utc)

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


def _registrable_domain(host: str):
    """Best-effort registrable (eTLD+1) root for a host.

    e.g. ``blog.substack.com`` -> ``substack.com``,
    ``substack.jurgenappelo.com`` -> ``jurgenappelo.com`` (only used to derive
    platform labels; real matching happens via cookie scope / platform label).
    """
    parts = (host or "").strip().lower().lstrip("www.").split(".")
    if len(parts) <= 2:
        return ".".join(parts) if parts else None
    if parts[-1] in ("uk", "au", "ca", "jp") and len(parts) >= 3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])
