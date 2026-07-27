import logging
import re
from typing import Optional

from src.domain.entities import Topic, Article
from src.domain.interfaces import ContentGenerator, LLMService
from src.application.content_strategy import ContentGenerationStrategy, ContentStrategyFactory

logger = logging.getLogger(__name__)

def _clean_body(body: str) -> str:
    lines = body.split("\n")
    cleaned = [l for l in lines if l.strip() != "---"]
    return "\n".join(cleaned).strip()


def _strip_leading_heading(body: str) -> str:
    lines = body.split("\n")
    result = []
    skipped = False
    for line in lines:
        if not skipped:
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("**") and stripped.endswith("**"):
                skipped = True
                continue
        result.append(line)
    return "\n".join(result).strip()


def _humanize_body(body: str) -> str:
    """Post-process to remove em-dashes and AI-sounding patterns."""
    import re
    body = body.replace("\u2014", ",")  # em-dash
    body = body.replace("\u2013", ",")  # en-dash
    body = body.replace(" -- ", ", ")
    body = body.replace(" — ", ", ")
    body = re.sub(r"\s+,\s*", ", ", body)
    return body


BACKLINK_SENTENCE = (
    "\n\n---\n\n*Looking for a production-ready solution? "
    "Check out [Gaper](https://gaper.io), deploy AI agents that integrate "
    "with your real workflows, from support to finance to sales automation.*"
)

GAPER_LINKS = """Use these Gaper.io links naturally in the article where relevant:
- Homepage: https://gaper.io
- AI Agent Development: https://gaper.io/ai-agents
- AI Implementation / Consulting: https://gaper.io/ai-consulting
- AI for Healthcare: https://gaper.io/ai-healthcare
- AI for Legal: https://gaper.io/ai-legal
- AI for Accounting & Finance: https://gaper.io/ai-finance
- Workflow Automation: https://gaper.io/workflow-automation
- Founders Grit Podcast: https://gaper.io/founders-grit"""

HUMANIZATION_RULES = """CRITICAL WRITING RULES:
1. NEVER use em-dashes (--) or en-dashes (-). Use commas instead.
2. Write like a real human developer, not like AI. Use casual, conversational tone.
3. NO filler phrases like "in today's fast-paced world", "it's worth noting", "leveraging", "streamline".
4. Use short sentences. Mix sentence lengths. Be direct.
5. Include personal opinions and real experiences where possible.
6. Insert 2-3 natural backlinks to Gaper.io pages (from the link list above) where they genuinely fit the context. Do NOT force them. Place them where a reader would naturally want to learn more.
7. End with a brief, natural mention of Gaper, not a sales pitch."""


class LLMContentGenerator(ContentGenerator):
    def __init__(
        self,
        llm_service: LLMService,
        strategy_type: str = "tutorial",
        backlink_enabled: bool = True,
        target_audience: str = "developers",
    ):
        self._llm = llm_service
        self._backlink_enabled = backlink_enabled
        self._target_audience = target_audience
        self._strategy: ContentGenerationStrategy = ContentStrategyFactory.create(strategy_type)

    def set_strategy(self, strategy_type: str) -> None:
        self._strategy = ContentStrategyFactory.create(strategy_type)
        logger.info(f"Strategy switched to: {strategy_type}")

    def generate(self, topic: Topic) -> Article:
        logger.info(f"Generating content using {type(self._strategy).__name__}")

        base_prompt = self._strategy.build_user_prompt(topic)
        full_prompt = f"{base_prompt}\n\n{GAPER_LINKS}\n\n{HUMANIZATION_RULES}"

        body = self._llm.generate(
            prompt=full_prompt,
            system_prompt=self._strategy.build_system_prompt(),
            temperature=0.7,
        )

        body = _strip_leading_heading(body)
        body = _humanize_body(body)

        if self._backlink_enabled and "gaper.io" not in body.lower():
            body += BACKLINK_SENTENCE

        description = self._generate_description(topic, body)

        return Article(
            title=topic.name,
            body_markdown=body,
            description=description,
            tags=topic.keywords[:4],
            published=False,
        )

    def review(self, article: Article) -> Article:
        logger.info("Reviewing first section for grammar...")

        body = _clean_body(article.body_markdown)
        para_end = body.find("\n\n", 200)
        lead = body[:para_end] if para_end > 0 else body[:500]

        fixed = self._llm.generate(
            prompt=(
                f"Fix grammar and clarity in this text. "
                f"Return only the corrected text, nothing else:\n\n{lead}"
            ),
            temperature=0.2,
        )

        body = fixed + body[len(lead):]
        article.body_markdown = body
        return article

    def _generate_title(self, topic: Topic, body: str) -> str:
        prompt = (
            f"Based on the article body below, generate a compelling, SEO-friendly title "
            f"(max 80 chars, no quotes). Return ONLY the title, nothing else.\n\n"
            f"Topic: {topic.name}\n\n"
            f"Article:\n{body[:1000]}"
        )

        title = self._llm.generate(
            prompt=prompt,
            temperature=0.5,
        )

        title = title.strip().strip('"').strip("'")
        return title[:128] if title else topic.name

    def _generate_description(self, topic: Topic, body: str) -> str:
        prompt = (
            f"Write a 1-2 sentence description for this article (max 250 chars). "
            f"Return ONLY the description.\n\n"
            f"Title: {topic.name}\n\n"
            f"Article:\n{body[:500]}"
        )

        desc = self._llm.generate(
            prompt=prompt,
            temperature=0.4,
        )

        desc = desc.strip().strip('"').strip("'")
        return desc[:250] if desc else topic.description
