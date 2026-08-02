"""Extract search keywords from gaper.io pages for discovery."""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, ".")

import logging
from typing import List, Optional
from urllib.parse import urljoin
import httpx
from xml.etree import ElementTree
from src.infrastructure.gemini_service import GeminiLLMService
from src.infrastructure.scrapers.static_scraper import StaticScraper
from src.config import GEMINI_API_KEY

logger = logging.getLogger(__name__)

GAPER_BASE = "https://gaper.io"
GAPER_SITEMAP = "https://gaper.io/sitemap.xml"

GAPER_PAGES = [
    "https://gaper.io/",
    "https://gaper.io/ai-agents-for-business",
    "https://gaper.io/build-vs-buy-ai-agents",
    "https://gaper.io/ai-agents-vs-chatbots",
    "https://gaper.io/ai-agent-development-cost",
    "https://gaper.io/deploy-ai-agents",
    "https://gaper.io/ai-agents-for-customer-support",
    "https://gaper.io/ai-agent-use-cases",
]


def get_sitemap_urls() -> List[str]:
    urls = []
    try:
        resp = httpx.get(GAPER_SITEMAP, timeout=10, follow_redirects=True)
        resp.raise_for_status()
        root = ElementTree.fromstring(resp.text)
        ns = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        for loc in root.iterfind(".//ns:loc", ns):
            url = loc.text.strip()
            if url.startswith(GAPER_BASE) and url not in urls:
                urls.append(url)
        logger.info(f"Discovered {len(urls)} URLs from sitemap")
    except Exception as e:
        logger.warning(f"Failed to fetch sitemap: {e}")
    return urls

KEYWORD_PROMPT = """Based on this content from gaper.io (an AI agent platform for businesses), extract 20-30 search keywords that someone might use when looking for help with the topics gaper.io covers.

These should be search queries people type into Google when they need help with:
- AI agents
- Chatbots
- Customer support automation
- Deploying AI
- Building AI-powered apps
- LLM integration

FORMAT: Return ONLY a comma-separated list of keywords, nothing else.
Example: deploy ai agents, build chatbot, ai customer support, llm api integration

Content:
{content}"""


def get_all_gaper_pages() -> List[str]:
    pages = list(GAPER_PAGES)
    sitemap_urls = get_sitemap_urls()
    for u in sitemap_urls:
        if u not in pages:
            pages.append(u)
    return pages


def extract_keywords_from_gaper(max_pages: int = 25) -> List[str]:
    """Scrape gaper.io and extract search keywords using LLM."""
    scraper = StaticScraper(timeout=20)
    llm = GeminiLLMService(api_key=GEMINI_API_KEY)

    all_content = []
    pages = get_all_gaper_pages()[:max_pages]
    for url in pages:
        try:
            result = scraper.scrape(url)
            if not result.is_empty and len(result.body) > 100:
                all_content.append(f"Page: {url}\n{result.body[:2000]}")
        except Exception as e:
            logger.warning(f"Failed to scrape {url}: {e}")

    if not all_content:
        return get_fallback_keywords()

    combined = "\n\n".join(all_content)
    prompt = KEYWORD_PROMPT.format(content=combined[:8000])

    try:
        response = llm.generate(prompt=prompt, temperature=0.3)
        keywords = [kw.strip().strip('"').strip("'") for kw in response.split(",") if kw.strip()]
        # Remove empty and very short keywords
        keywords = [kw for kw in keywords if len(kw) > 3]
        # Deduplicate while preserving order
        seen = set()
        unique_keywords = []
        for kw in keywords:
            kw_lower = kw.lower()
            if kw_lower not in seen:
                seen.add(kw_lower)
                unique_keywords.append(kw)
        keywords = unique_keywords
        logger.info(f"Extracted {len(keywords)} unique keywords from gaper.io")
        return keywords[:30]
    except Exception as e:
        logger.error(f"Keyword extraction failed: {e}")
        return get_fallback_keywords()


def get_fallback_keywords() -> List[str]:
    """Fallback keywords if extraction fails."""
    return [
        "deploy ai agents",
        "build chatbot no code",
        "ai agent platform",
        "llm deployment",
        "automate customer support",
        "ai agent for customer service",
        "build ai chatbot",
        "no code ai agent builder",
        "deploy llm app",
        "ai customer support automation",
        "create ai assistant",
        "ai agent hosting platform",
        "deploy gpt chatbot",
        "ai workflow automation",
        "no code ai platform",
        "build conversational ai",
        "ai agent sdk",
        "llm api integration",
        "custom ai agent",
        "ai support bot",
        "enterprise ai agents",
        "ai agent deployment service",
        "build ai-powered apps",
        "chatbot as a service",
        "ai agent for saas",
    ]


if __name__ == "__main__":
    keywords = extract_keywords_from_gaper()
    print(f"\nExtracted {len(keywords)} keywords:")
    for kw in keywords:
        print(f"  - {kw}")
