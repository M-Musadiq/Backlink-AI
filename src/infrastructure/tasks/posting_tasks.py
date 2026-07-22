"""Posting tasks - execute approved replies across platforms."""
import logging
from datetime import datetime, timezone
from src.infrastructure.celery_app import app
from src.infrastructure.database import SessionLocal
from src.infrastructure.repositories.prospect_repo import ProspectRepository
from src.infrastructure.repositories.audit_log_repo import AuditLogRepository
from src.infrastructure.posting.session_manager import SessionManager
from src.infrastructure.posting import get_poster

logger = logging.getLogger(__name__)


@app.task(bind=True, max_retries=3)
def execute_post(self, prospect_id: int):
    """
    Execute a post for an approved prospect.
    Routes to the appropriate Playwright-based platform handler.
    """
    session = SessionLocal()
    try:
        prospect_repo = ProspectRepository(session)
        prospect = prospect_repo.get_by_id(prospect_id)

        if not prospect:
            return {"error": "Prospect not found"}

        if prospect.status != "approved":
            return {"error": f"Prospect status is '{prospect.status}', expected 'approved'"}

        result = _route_to_platform(prospect, session)

        if result.get("success"):
            prospect.status = "posted"
            prospect.posted_at = datetime.now(timezone.utc)
            prospect.platform_post_id = result.get("post_id", "")
            prospect.posted_url = result.get("post_url", "")
        else:
            prospect.status = "post_failed"
            prospect.updated_at = datetime.now(timezone.utc)

        session.commit()

        audit_repo = AuditLogRepository(session)
        audit_repo.log_action(
            action="posted" if result.get("success") else "post_failed",
            details=str(result),
            prospect_id=prospect_id,
        )

        logger.info(f"Post result for prospect {prospect_id}: {result}")
        return result

    except Exception as e:
        logger.error(f"Posting failed: {e}")
        raise self.retry(exc=e, countdown=120)
    finally:
        session.close()


def _route_to_platform(prospect, session) -> dict:
    """Route to the appropriate platform posting handler."""
    domain = prospect.domain.lower()

    # Load session cookies
    sm = SessionManager(session)
    cookies = sm.get_cookies(domain)

    if not cookies:
        return {
            "success": False,
            "error": f"No saved session for {domain}. Please log in first.",
        }

    # Get the right poster
    try:
        poster = get_poster(domain)
    except ValueError:
        return {"success": False, "error": f"Unknown platform: {domain}"}

    # Execute the post
    try:
        result = poster.post_reply(
            url=prospect.url,
            content=prospect.draft_content,
            cookies=cookies,
        )
        return result.to_dict()
    except Exception as e:
        logger.error(f"Posting to {domain} failed: {e}")
        return {"success": False, "error": str(e)}
