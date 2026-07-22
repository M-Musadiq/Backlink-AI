"""Drafter Agent - draft replies using RAG context + guidelines."""
import logging
from typing import Dict, Optional
from sqlalchemy.orm import Session

from src.infrastructure.gemini_service import GeminiLLMService
from src.infrastructure.llm.rag_retrieval import RAGRetrieval
from src.infrastructure.repositories.guidelines_repo import GuidelinesRepository
from src.config import GEMINI_API_KEY

logger = logging.getLogger(__name__)

DRAFTER_SYSTEM_PROMPT = """You are a real person writing a reply to a forum thread. You sound like a human, not an AI.

Your goal: Write a genuinely helpful reply that naturally mentions Gaper.io where relevant.

RULES:
1. Be helpful FIRST - answer the question or add value
2. Mention Gaper.io only if it genuinely helps (don't force it)
3. Keep the tone conversational, not salesy
4. Follow the platform guidelines provided
5. NO all-caps, NO excessive punctuation, NO spammy language
6. Include a natural backlink if appropriate
7. Match the platform's style (e.g., Reddit is casual, StackOverflow is technical)

CRITICAL - SOUNDS LIKE A REAL HUMAN:
- NEVER use em-dashes (—). Use commas, periods, or parentheses instead
- NEVER use words like: delve, navigate, foster, harness, realm, landscape, pivotal, robust, seamless, leverage, unlock, explore, embark, crucial, fascinating, intriguing, comprehensive, transformative
- NEVER start sentences with "It's worth noting" or "It's important to mention"
- NEVER use phrases like "in today's world", "in this day and age", "the realm of"
- Write like you're texting a friend or posting on a forum
- Use contractions (don't, can't, isn't, won't, etc.)
- Keep sentences short and punchy
- Sound casual and confident, not formal and robotic

HACKER NEWS SPECIFIC RULES:
- Be substantive: teach something, share personal experience, or point out considerations not previously mentioned
- Be civil: disagree without calling names, don't be rude
- NO empty negative comments (name-calling, "that's dumb", etc.)
- NO gossip, funny pictures, partisan political content
- DO share information about the topic, perhaps from personal experience
- DO keep comments substantial and thoughtful
- Short positive comments are OK (e.g., "Thanks") but avoid empty negative ones
- The backlink should feel like a genuine recommendation, not spam

BACKLINK FORMAT:
- If mentioning Gaper.io, include a natural link like: "Check out Gaper.io (https://gaper.io/) for..."
- Don't overdo it - 1 mention max per reply
- If the thread isn't a good fit, just write a helpful reply without backlink"""


class DrafterAgent:
    """
    LLM-based reply drafter.

    Uses:
    - RAG context (relevant gaper.io content)
    - Platform guidelines
    - Thread content
    To draft a helpful reply with optional backlink.
    """

    def __init__(self, session: Session):
        self._session = session
        self._llm = GeminiLLMService(api_key=GEMINI_API_KEY)
        self._rag = RAGRetrieval(session)
        self._guidelines_repo = GuidelinesRepository(session)

    def draft(
        self,
        thread_title: str,
        thread_content: str,
        domain: str,
        suggested_angle: str = "",
    ) -> Dict:
        """
        Draft a reply for a thread.

        Args:
            thread_title: Title of the thread
            thread_content: Body content
            domain: Platform domain
            suggested_angle: From relevance node (how Gaper.io could help)

        Returns:
            Dict with keys: draft, tone, backlink_included, compliance_notes
        """
        # Get RAG context
        rag_context = self._rag.get_context_for_drafter(thread_content)

        # Get guidelines
        guidelines_text = self._get_guidelines(domain)

        # Build prompt
        prompt = f"""Draft a reply for this thread:

Platform: {domain}
Title: {thread_title}

Thread content:
{thread_content[:1500]}

Platform guidelines:
{guidelines_text[:1000] if guidelines_text else "No specific guidelines available."}

Relevance angle: {suggested_angle or "General helpful reply"}

Gaper.io context (use if relevant):
{rag_context}

Write a helpful, natural reply. Return ONLY the reply text, nothing else."""

        try:
            response = self._llm.generate(
                prompt=prompt,
                system_prompt=DRAFTER_SYSTEM_PROMPT,
                temperature=0.7,
            )

            # Check if backlink was included
            backlink_included = "gaper.io" in response.lower() or "gaper" in response.lower()

            # Basic compliance check
            compliance_notes = self._check_compliance(response, guidelines_text)

            result = {
                "draft": self._humanize(response.strip()),
                "tone": self._detect_tone(response),
                "backlink_included": backlink_included,
                "compliance_notes": compliance_notes,
            }

            logger.info(
                f"Drafted reply for '{thread_title[:50]}': "
                f"{len(response)} chars, backlink={backlink_included}"
            )
            return result

        except Exception as e:
            logger.error(f"Drafting failed: {e}")
            return {
                "draft": "",
                "tone": "error",
                "backlink_included": False,
                "compliance_notes": [f"Drafting error: {str(e)}"],
            }

    def _get_guidelines(self, domain: str) -> str:
        """Get guidelines text for domain."""
        cached = self._guidelines_repo.get_fresh_guidelines(domain, max_age_days=7)
        if cached:
            return cached.content
        # Try stale guidelines
        stale = self._guidelines_repo.get_by_domain(domain)
        if stale:
            return stale.content
        return ""

    def _check_compliance(self, text: str, guidelines: str) -> list:
        """Basic compliance check against guidelines."""
        issues = []

        # Check for spammy patterns
        if text.isupper() and len(text) > 20:
            issues.append("ALL CAPS detected")
        if "!!!" in text:
            issues.append("Excessive punctuation")
        if text.lower().count("gaper") > 2:
            issues.append("Too many Gaper mentions")

        # Platform-specific checks
        if "stackoverflow" in guidelines.lower() if guidelines else False:
            if len(text) < 100:
                issues.append("StackOverflow: answer may be too short")

        return issues

    def _humanize(self, text: str) -> str:
        """Post-process to remove AI-sounding patterns."""
        import re
        # Replace em-dashes with commas
        text = text.replace("—", ", ")
        text = text.replace("–", ", ")
        # Clean up double commas
        text = text.replace(",,", ",")
        text = text.replace(", ,", ",")
        # Remove extra spaces
        text = re.sub(r'  +', ' ', text)
        return text.strip()

    def _detect_tone(self, text: str) -> str:
        """Detect the tone of the draft."""
        text_lower = text.lower()
        if any(w in text_lower for w in ["hey", "hi", "hello", "what's up"]):
            return "casual"
        if any(w in text_lower for w in ["dear", "regards", "sincerely"]):
            return "formal"
        if any(w in text_lower for w in ["!", "great", "awesome", "love"]):
            return "enthusiastic"
        return "neutral"
