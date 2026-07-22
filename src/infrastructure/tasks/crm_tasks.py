"""CRM tasks - follow-up tracking, status updates, reporting."""
import logging
from datetime import datetime, timedelta, timezone
from src.infrastructure.celery_app import app
from src.infrastructure.database import SessionLocal
from src.infrastructure.repositories.prospect_repo import ProspectRepository
from src.infrastructure.repositories.audit_log_repo import AuditLogRepository

logger = logging.getLogger(__name__)


@app.task
def follow_up_check():
    """
    Check for prospects that need follow-up.
    - Posted prospects older than 3 days: check for responses
    - Prospects stuck in 'scraped' > 24h: re-evaluate or archive
    """
    session = SessionLocal()
    try:
        prospect_repo = ProspectRepository(session)
        audit_repo = AuditLogRepository(session)

        # Check posted prospects for responses
        posted = prospect_repo.get_by_status("posted")
        for p in posted:
            if p.posted_at and (datetime.now(timezone.utc) - p.posted_at).days > 3:
                audit_repo.log_action(
                    action="follow_up_needed",
                    details=f"Posted {p.posted_at}, checking for responses",
                    prospect_id=p.id,
                )
                logger.info(f"Follow-up needed for prospect {p.id}")

        # Archive old scraped prospects
        stale = prospect_repo.get_by_status("scraped")
        for p in stale:
            if p.created_at and (datetime.now(timezone.utc) - p.created_at).total_seconds() > 86400:
                prospect_repo.archive(p.id)
                logger.info(f"Archived stale prospect {p.id}")

        return {"follow_ups": len(posted), "archived": len(stale)}

    except Exception as e:
        logger.error(f"Follow-up check failed: {e}")
        return {"error": str(e)}
    finally:
        session.close()


@app.task
def update_prospect_status(prospect_id: int, new_status: str):
    """Update prospect status (called from dashboard UI)."""
    session = SessionLocal()
    try:
        prospect_repo = ProspectRepository(session)
        prospect = prospect_repo.get_by_id(prospect_id)

        if not prospect:
            return {"error": "Prospect not found"}

        old_status = prospect.status
        prospect.status = new_status
        prospect.updated_at = datetime.now(timezone.utc)
        session.commit()

        audit_repo = AuditLogRepository(session)
        audit_repo.log_action(
            action="status_changed",
            details=f"Status: {old_status} -> {new_status}",
            prospect_id=prospect_id,
        )

        return {"success": True, "old_status": old_status, "new_status": new_status}

    except Exception as e:
        logger.error(f"Status update failed: {e}")
        return {"error": str(e)}
    finally:
        session.close()


@app.task
def generate_daily_report():
    """Generate daily stats for the dashboard."""
    session = SessionLocal()
    try:
        prospect_repo = ProspectRepository(session)

        today = datetime.now(timezone.utc).date()
        stats = {
            "date": str(today),
            "discovered": len(prospect_repo.get_by_status("discovered")),
            "relevant": len(prospect_repo.get_by_status("relevant")),
            "drafted": len(prospect_repo.get_by_status("drafted")),
            "approved": len(prospect_repo.get_by_status("approved")),
            "posted": len(prospect_repo.get_by_status("posted")),
            "archived": len(prospect_repo.get_by_status("archived")),
        }

        logger.info(f"Daily report: {stats}")
        return stats

    except Exception as e:
        logger.error(f"Report generation failed: {e}")
        return {"error": str(e)}
    finally:
        session.close()
