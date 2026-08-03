"""Legacy Celery task: scheduled/queued discovery. Discovery now runs inline via the dashboard."""
import logging
from src.infrastructure.celery_app import app
from src.infrastructure.database import SessionLocal
from src.infrastructure.discovery.discovery_node import DiscoveryNode
from src.infrastructure.repositories.prospect_repo import ProspectRepository
from src.infrastructure.models import Prospect

logger = logging.getLogger(__name__)


@app.task(bind=True, max_retries=3)
def run_discovery(self, keywords: list = None, num_per_platform: int = 10, generic: bool = False):
    """Run discovery pipeline and create prospects for new URLs."""
    session = SessionLocal()
    try:
        node = DiscoveryNode(session)
        if generic:
            stats = node.discover_generic()
        else:
            stats = node.discover(
                keywords=keywords or [],
                num_per_platform=num_per_platform,
            )
        logger.info(f"Discovery complete: {stats}")

        from src.infrastructure.repositories.tracked_url_repo import TrackedURLRepository
        tracked_repo = TrackedURLRepository(session)
        new_urls = tracked_repo.get_new_urls(limit=50)

        prospect_repo = ProspectRepository(session)
        created = 0
        for url_entity in new_urls:
            existing = prospect_repo.get_by_url(url_entity.url)
            if not existing:
                prospect_repo.add(Prospect(
                    tracked_url_id=url_entity.id,
                    url=url_entity.url,
                    domain=url_entity.domain,
                    title=url_entity.title,
                    status="discovered",
                ))
                created += 1

        logger.info(f"Created {created} new prospects")
        return {"discovered": stats, "prospects_created": created}

    except Exception as e:
        logger.error(f"Discovery task failed: {e}")
        raise self.retry(exc=e, countdown=60)
    finally:
        session.close()
