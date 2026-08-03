"""Discovery tasks - find new URLs to track."""
import logging
from src.infrastructure.celery_app import app
from src.infrastructure.database import SessionLocal

logger = logging.getLogger(__name__)


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
