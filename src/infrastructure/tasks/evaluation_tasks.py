"""Evaluation tasks - relevance check, drafting, guidelines refresh."""
import logging
from src.infrastructure.celery_app import app
from src.infrastructure.database import SessionLocal
from src.infrastructure.repositories.prospect_repo import ProspectRepository
from src.infrastructure.repositories.audit_log_repo import AuditLogRepository

logger = logging.getLogger(__name__)


@app.task(bind=True, max_retries=3)
def evaluate_relevance(self, prospect_id: int):
    """Evaluate if a scraped prospect is relevant for backlink."""
    session = SessionLocal()
    try:
        prospect_repo = ProspectRepository(session)
        prospect = prospect_repo.get_by_id(prospect_id)

        if not prospect:
            return {"error": "Prospect not found"}

        from src.infrastructure.llm.relevance_node import RelevanceNode
        evaluator = RelevanceNode(session)

        result = evaluator.evaluate(
            thread_title=prospect.title,
            thread_content=prospect.body_preview,
            domain=prospect.domain,
        )

        # Update prospect
        prospect.relevance_score = result["score"]
        if result["relevant"]:
            prospect.status = "relevant"
        else:
            prospect.status = "archived"
        from datetime import datetime as _dt, timezone
        prospect.updated_at = _dt.now(timezone.utc)
        session.commit()

        # Audit log
        audit_repo = AuditLogRepository(session)
        audit_repo.log_action(
            action="evaluated",
            details=f"Score: {result['score']}, Relevant: {result['relevant']}, Reason: {result['reason']}",
            prospect_id=prospect_id,
        )

        logger.info(f"Evaluated prospect {prospect_id}: score={result['score']}")
        return result

    except Exception as e:
        logger.error(f"Relevance evaluation failed: {e}")
        raise self.retry(exc=e, countdown=60)
    finally:
        session.close()


@app.task(bind=True, max_retries=3)
def draft_reply(self, prospect_id: int):
    """Draft a reply for a relevant prospect."""
    session = SessionLocal()
    try:
        prospect_repo = ProspectRepository(session)
        prospect = prospect_repo.get_by_id(prospect_id)

        if not prospect:
            return {"error": "Prospect not found"}

        from src.infrastructure.llm.drafter_agent import DrafterAgent
        drafter = DrafterAgent(session)

        result = drafter.draft(
            thread_title=prospect.title,
            thread_content=prospect.body_preview,
            domain=prospect.domain,
        )

        # Update prospect with draft
        prospect_repo.save_draft(prospect_id, result["draft"])

        # Audit log
        audit_repo = AuditLogRepository(session)
        audit_repo.log_action(
            action="drafted",
            details=f"Tone: {result['tone']}, Backlink: {result['backlink_included']}",
            prospect_id=prospect_id,
        )

        logger.info(f"Drafted reply for prospect {prospect_id}: {len(result['draft'])} chars")
        return result

    except Exception as e:
        logger.error(f"Drafting failed: {e}")
        raise self.retry(exc=e, countdown=60)
    finally:
        session.close()


@app.task
def refresh_guidelines():
    """Refresh stale guidelines for all platforms."""
    session = SessionLocal()
    try:
        from src.infrastructure.guidelines.guidelines_extractor import GuidelinesExtractor
        extractor = GuidelinesExtractor(session)

        results = extractor.extract_all_platforms(force_refresh=False)
        refreshed = sum(1 for v in results.values() if v is not None)
        logger.info(f"Guidelines refresh: {refreshed} updated")
        return {"refreshed": refreshed, "total": len(results)}

    except Exception as e:
        logger.error(f"Guidelines refresh failed: {e}")
        return {"error": str(e)}
    finally:
        session.close()
