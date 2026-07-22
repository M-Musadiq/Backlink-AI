"""Discovery tasks - find new URLs to track."""
import logging
from src.infrastructure.celery_app import app
from src.infrastructure.database import SessionLocal
from src.infrastructure.discovery.discovery_node import DiscoveryNode
from src.infrastructure.repositories.prospect_repo import ProspectRepository
from src.infrastructure.models import Prospect

logger = logging.getLogger(__name__)


@app.task(bind=True, max_retries=3)
def run_discovery(self, keywords: list, num_per_platform: int = 10):
    """Run discovery pipeline and create prospects for new URLs."""
    session = SessionLocal()
    try:
        node = DiscoveryNode(session)
        stats = node.discover(
            keywords=keywords,
            num_per_platform=num_per_platform,
        )
        logger.info(f"Discovery complete: {stats}")

        # Create prospects for newly discovered URLs
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


@app.task(bind=True, max_retries=3)
def scrape_url(self, url_id: int):
    """Scrape a single URL and update its content."""
    session = SessionLocal()
    try:
        from src.infrastructure.repositories.tracked_url_repo import TrackedURLRepository
        from src.infrastructure.scrapers.scrape_orchestrator import ScrapeOrchestrator
        from src.infrastructure.repositories.platform_config_repo import PlatformConfigRepository

        tracked_repo = TrackedURLRepository(session)
        url_entity = tracked_repo.get_by_id(url_id)
        if not url_entity:
            return {"error": "URL not found"}

        config_repo = PlatformConfigRepository(session)
        orchestrator = ScrapeOrchestrator(config_store=config_repo)

        content = orchestrator.scrape(url_entity.url)

        # Update prospect with scraped content
        from src.infrastructure.repositories.prospect_repo import ProspectRepository
        prospect_repo = ProspectRepository(session)
        prospect = prospect_repo.get_by_url(url_entity.url)
        if prospect:
            prospect.body_preview = content.body[:500]
            prospect.title = content.title or prospect.title
            prospect.status = "scraped"
            session.commit()

        tracked_repo.mark_scraped(url_id)

        logger.info(f"Scraped {url_entity.url}: {len(content.body)} chars")
        return {"url": url_entity.url, "chars": len(content.body)}

    except Exception as e:
        logger.error(f"Scrape task failed: {e}")
        raise self.retry(exc=e, countdown=30)
    finally:
        session.close()
