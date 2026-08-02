"""Site Knowledge Service — manages the lifecycle of site knowledge entries."""
import logging
from typing import Optional
from urllib.parse import urlparse
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from src.infrastructure.repositories.site_knowledge_repo import SiteKnowledgeRepository
from src.infrastructure.site_knowledge.classification_service import SiteClassificationService
from src.infrastructure.scrapers.base import extract_domain
from src.infrastructure.gemini_service import GeminiLLMService
import src.config as config

logger = logging.getLogger(__name__)


class SiteKnowledgeService:
    def __init__(self, session: Session, llm: Optional[GeminiLLMService] = None):
        self._repo = SiteKnowledgeRepository(session)
        self._classifier = SiteClassificationService(llm=llm)

    def get_freshness(self, domain: str) -> Optional[int]:
        site = self._repo.get_by_domain(domain)
        if not site or not site.site_type:
            return None
        if not site.updated_at:
            return None
        updated = site.updated_at
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - updated
        return delta.days

    def is_fresh(self, domain: str, max_age_days: int = 30) -> Optional[bool]:
        days = self.get_freshness(domain)
        if days is None:
            return None
        return days < max_age_days

    def ensure_site(self, url: str, title: str = "", description: str = "") -> dict:
        domain = extract_domain(url) or (urlparse(url).hostname or url)
        existing = self._repo.get_by_domain(domain)
        if existing and existing.site_type:
            return {
                "domain": domain,
                "site_type": existing.site_type,
                "classified": True,
                "existed": True,
            }
        result = self._classifier.classify(url, title, description)
        self._repo.upsert(
            domain=domain,
            site_type=result["type"],
            title=title,
            description=description,
            login_required=result["login_required"],
            posting_capable=result["posting_capable"],
            listing_capable=result["listing_capable"],
            has_api=result["has_api"],
            classification_raw=result.get("reasoning", ""),
        )
        logger.info(f"Classified {domain} as {result['type']} (confidence={result['confidence']})")
        return {
            "domain": domain,
            "site_type": result["type"],
            "classified": True,
            "existed": False,
        }

    def ensure_site_with_content(self, url: str, title: str = "", page_content: str = "") -> dict:
        domain = extract_domain(url) or (urlparse(url).hostname or url)
        result = self._classifier.classify_with_content(url, title, page_content)
        self._repo.upsert(
            domain=domain,
            site_type=result["type"],
            title=title,
            description=page_content[:500] if page_content else "",
            login_required=result["login_required"],
            posting_capable=result.get("can_create_posts", False) or result.get("can_reply", False),
            listing_capable=result.get("can_submit_listings", False),
            has_api=result.get("has_api", False),
            classification_raw=result.get("reasoning", ""),
        )
        logger.info(f"Classified {domain} as {result['type']} (confidence={result['confidence']})")
        return {
            "domain": domain,
            "site_type": result["type"],
            "classified": True,
            "existed": False,
            "can_create_posts": result.get("can_create_posts", False),
            "can_reply": result.get("can_reply", False),
            "can_submit_listings": result.get("can_submit_listings", False),
            "can_publish_articles": result.get("can_publish_articles", False),
            "login_required": result["login_required"],
        }

    def get_summary(self) -> list[dict]:
        return self._repo.get_all_summary()

    def get_by_domain(self, domain: str) -> Optional[dict]:
        site = self._repo.get_by_domain(domain)
        if not site:
            return None
        return {
            "id": site.id,
            "domain": site.domain,
            "site_type": site.site_type or "unclassified",
            "title": site.title or "",
            "description": site.description or "",
            "login_url": site.login_url or "",
            "registration_url": site.registration_url or "",
            "submission_url": site.submission_url or "",
            "login_required": site.login_required,
            "posting_capable": site.posting_capable,
            "listing_capable": site.listing_capable,
            "has_api": site.has_api,
            "robots_summary": site.robots_summary or "",
            "posting_rules": site.posting_rules or "",
            "required_fields": site.required_fields or "",
            "last_visited": site.last_visited.isoformat() if site.last_visited else None,
            "visit_count": site.visit_count or 0,
            "success_rate": site.success_rate or 0.0,
            "last_error": site.last_error or "",
            "discovered_at": site.discovered_at.isoformat() if site.discovered_at else None,
        }

    def classify_unclassified(self, limit: int = 20) -> int:
        sites = self._repo.get_unclassified()
        count = 0
        for site in sites[:limit]:
            try:
                result = self._classifier.classify(
                    f"https://{site.domain}", site.title, site.description
                )
                self._repo.upsert(
                    domain=site.domain,
                    site_type=result["type"],
                    login_required=result["login_required"],
                    posting_capable=result["posting_capable"],
                    listing_capable=result["listing_capable"],
                    has_api=result["has_api"],
                    classification_raw=result.get("reasoning", ""),
                )
                count += 1
            except Exception as e:
                logger.warning(f"Failed to classify {site.domain}: {e}")
        return count
