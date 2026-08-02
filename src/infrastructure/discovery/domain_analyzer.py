"""Domain analyzer — scrape homepage + LLM classify for capabilities."""
import logging
from typing import Optional
from dataclasses import dataclass, field
from src.domain.interfaces import Scraper
from src.infrastructure.gemini_service import GeminiLLMService
from src.infrastructure.scrapers.static_scraper import StaticScraper
import src.config as config

logger = logging.getLogger(__name__)

SITE_TYPES = [
    "Forum", "Listing Site", "Directory", "Community", "Blog",
    "Q&A", "Documentation", "Knowledge Base", "Resource Page",
    "SaaS", "Marketplace", "Social Network", "News", "E-commerce", "Other",
]

ANALYSIS_PROMPT = """You analyze websites and return structured JSON about what users can do.

Rules for site_type:
- Forum: discussion boards where users create threads and reply
- Listing Site: users submit company/product/service listings
- Directory: categorized collection of links/resources
- Community: Slack/Discord/Facebook Group
- Blog: primarily articles/posts
- Q&A: question-answer sites (StackOverflow, Quora)
- Documentation: technical docs
- Knowledge Base: wiki or knowledge base
- Resource Page: curated list of resources
- SaaS: software/service platform
- Other: none of the above

Rules for capabilities (only consider what USERS can do, not admins):
- can_create_posts: can users create new discussion threads or topics?
- can_reply: can users reply to existing threads, comments, or discussions?
- can_submit_listings: can users submit company/product/service listings?
- can_publish_articles: can users contribute guest posts or articles?

login_required: true if a user account/login is needed to do any of the above.

Respond with ONLY valid JSON, no markdown, no backticks:
{
  "site_type": "<type>",
  "confidence": 0.0-1.0,
  "reasoning": "<brief reason>",
  "login_required": true/false,
  "can_create_posts": true/false,
  "can_reply": true/false,
  "can_submit_listings": true/false,
  "can_publish_articles": true/false
}"""


@dataclass
class DomainAnalysis:
    site_type: str = "Other"
    confidence: float = 0.0
    reasoning: str = ""
    login_required: bool = False
    can_create_posts: bool = False
    can_reply: bool = False
    can_submit_listings: bool = False
    can_publish_articles: bool = False
    error: Optional[str] = None
    homepage_content: str = ""


class DomainAnalyzer:
    def __init__(self, llm: Optional[GeminiLLMService] = None, scraper: Optional[Scraper] = None):
        self._llm = llm or GeminiLLMService(api_key=config.GEMINI_API_KEY)
        # Accept any scraper implementation; default to StaticScraper for backwards compat
        self._scraper = scraper or StaticScraper(timeout=15)

    def analyze(self, url: str, title: str = "") -> DomainAnalysis:
        """Scrape homepage + LLM class"""
        try:
            result = self._scraper.scrape(url)
            content = result.body if not result.is_empty else ""
            if not content or len(content.strip()) < 50:
                return DomainAnalysis(
                    error=f"Homepage too short or empty ({len(content or '')} chars)"
                )
        except Exception as e:
            logger.warning(f"Failed to scrape {url}: {e}")
            return DomainAnalysis(error=f"Scrape failed: {e}")

        prompt = f"URL: {url}\nTitle: {title}\n\nHomepage content:\n{content[:5000]}"
        try:
            raw = self._llm.generate(prompt, system_prompt=ANALYSIS_PROMPT, temperature=0.1)
            raw = raw.strip()
            if not raw:
                return DomainAnalysis(error="Empty LLM response")
            if raw.startswith("```"):
                raw = raw.strip("`").strip()
                if raw.startswith("json"):
                    raw = raw[4:].strip()
            import json
            data = json.loads(raw)
            if not isinstance(data, dict):
                return DomainAnalysis(error="Invalid LLM response format")
            return DomainAnalysis(
                site_type=data.get("site_type", "Other"),
                confidence=data.get("confidence", 0.0),
                reasoning=data.get("reasoning", ""),
                login_required=bool(data.get("login_required", False)),
                can_create_posts=bool(data.get("can_create_posts", False)),
                can_reply=bool(data.get("can_reply", False)),
                can_submit_listings=bool(data.get("can_submit_listings", False)),
                can_publish_articles=bool(data.get("can_publish_articles", False)),
                homepage_content=content[:2000],
            )
        except Exception as e:
            logger.warning(f"Analysis LLM failed for {url}: {e}")
            return DomainAnalysis(error=f"LLM analysis failed: {e}")
