"""Website classification service — uses LLM to classify unknown sites."""
import logging
import json
from typing import Optional
import src.config as config
from src.infrastructure.gemini_service import GeminiLLMService

logger = logging.getLogger(__name__)

SITE_TYPES = [
    "Forum",
    "Listing Site",
    "Directory",
    "Community",
    "Blog",
    "Q&A",
    "Documentation",
    "Knowledge Base",
    "Resource Page",
    "SaaS",
    "Marketplace",
    "Social Network",
    "News",
    "E-commerce",
    "Other",
]

CLASSIFICATION_PROMPT = """You are a website classifier. Given a URL and a page title/description, classify the website.

Respond with a JSON object. Do NOT include markdown or backticks.

Rules:
- If it's a forum or discussion board, type is "Forum"
- If it lists companies, products, or services, type is "Listing Site"
- If it's a categorized collection of links/resources, type is "Directory"
- If it's a community platform (Slack, Discord, Facebook Group), type is "Community"
- If it's primarily articles/posts, type is "Blog"
- If it's a question-answer site (StackOverflow, Quora), type is "Q&A"
- If it's technical documentation, type is "Documentation"
- If it's a knowledge base or wiki, type is "Knowledge Base"
- If it's a curated list of resources, type is "Resource Page"
- If it's a software/service platform, type is "SaaS"
- If none of the above fit, type is "Other"

JSON format:
{
  "type": "<one of the types above>",
  "confidence": <0.0-1.0>,
  "reasoning": "<brief reason for classification>",
  "login_required": <true/false>,
  "posting_capable": <true/false if users can post content>,
  "listing_capable": <true/false if company listings are accepted>,
  "has_api": <true/false if likely has a public API>
}
"""


CAPABILITY_PROMPT = """You analyze websites and return structured JSON.

Rules for site_type:
- Forum: discussion boards where users create threads and reply
- Listing Site: users submit company/product/service listings
- Directory: categorized collection of links/resources
- Community: Slack/Discord/Facebook Group
- Blog: primarily articles/posts
- Q&A: question-answer sites
- Documentation: technical docs
- Knowledge Base: wiki or knowledge base
- Resource Page: curated list of resources
- SaaS: software/service platform
- Other: none of the above

Capabilities (only what USERS can do, not admins):
- can_create_posts: can users create new discussion threads or topics?
- can_reply: can users reply to existing threads, comments, or discussions?
- can_submit_listings: can users submit company/product/service listings?
- can_publish_articles: can users contribute guest posts or articles?

login_required: true if a user account is needed.

Respond with ONLY valid JSON, no markdown, no backticks:
{
  "site_type": "<type>",
  "confidence": 0.0-1.0,
  "reasoning": "<brief reason>",
  "login_required": true/false,
  "can_create_posts": true/false,
  "can_reply": true/false,
  "can_submit_listings": true/false,
  "can_publish_articles": true/false,
  "has_api": true/false
}"""


class SiteClassificationService:
    def __init__(self, llm: Optional[GeminiLLMService] = None):
        self._llm = llm or GeminiLLMService(api_key=config.GEMINI_API_KEY)

    def classify(self, url: str, title: str = "", description: str = "") -> dict:
        prompt = f"URL: {url}\nTitle: {title}\nDescription: {description}\n\nClassify this website."
        try:
            raw = self._llm.generate(prompt, system_prompt=CLASSIFICATION_PROMPT, temperature=0.1)
            raw = raw.strip()
            if not raw:
                return self._default_classification()
            if raw.startswith("```"):
                raw = raw.strip("`").strip()
                if raw.startswith("json"):
                    raw = raw[4:].strip()
            result = json.loads(raw)
            if not isinstance(result, dict) or "type" not in result:
                return self._default_classification()
            return {
                "type": result.get("type", "Other"),
                "confidence": result.get("confidence", 0.0),
                "reasoning": result.get("reasoning", ""),
                "login_required": bool(result.get("login_required", False)),
                "posting_capable": bool(result.get("posting_capable", False)),
                "listing_capable": bool(result.get("listing_capable", False)),
                "has_api": bool(result.get("has_api", False)),
            }
        except Exception as e:
            logger.warning(f"Classification failed for {url}: {e}")
            return self._default_classification()

    def classify_with_content(self, url: str, title: str = "", page_content: str = "") -> dict:
        prompt = f"URL: {url}\nTitle: {title}\n\nPage content:\n{page_content[:5000]}"
        try:
            raw = self._llm.generate(prompt, system_prompt=CAPABILITY_PROMPT, temperature=0.1)
            raw = raw.strip()
            if not raw:
                return self._default_classification()
            if raw.startswith("```"):
                raw = raw.strip("`").strip()
                if raw.startswith("json"):
                    raw = raw[4:].strip()
            import json
            result = json.loads(raw)
            if not isinstance(result, dict) or "site_type" not in result:
                return self._default_classification()
            return {
                "type": result.get("site_type", "Other"),
                "confidence": result.get("confidence", 0.0),
                "reasoning": result.get("reasoning", ""),
                "login_required": bool(result.get("login_required", False)),
                "posting_capable": bool(result.get("can_create_posts", False)) or bool(result.get("can_reply", False)),
                "listing_capable": bool(result.get("can_submit_listings", False)),
                "article_capable": bool(result.get("can_publish_articles", False)),
                "has_api": bool(result.get("has_api", False)),
                "can_create_posts": bool(result.get("can_create_posts", False)),
                "can_reply": bool(result.get("can_reply", False)),
                "can_submit_listings": bool(result.get("can_submit_listings", False)),
                "can_publish_articles": bool(result.get("can_publish_articles", False)),
            }
        except Exception as e:
            logger.warning(f"Classification with content failed for {url}: {e}")
            return self._default_classification()

    def _default_classification(self) -> dict:
        return {
            "type": "Other",
            "confidence": 0.0,
            "reasoning": "Classification failed or unavailable",
            "login_required": False,
            "posting_capable": False,
            "listing_capable": False,
            "article_capable": False,
            "has_api": False,
            "can_create_posts": False,
            "can_reply": False,
            "can_submit_listings": False,
            "can_publish_articles": False,
        }
