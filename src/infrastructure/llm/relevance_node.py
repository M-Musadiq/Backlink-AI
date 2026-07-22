"""Relevance Node - LLM decides if a thread is relevant for a Gaper.io backlink."""
import logging
import json
from typing import Dict, Optional
from sqlalchemy.orm import Session

from src.infrastructure.llm_factory import get_llm
from src.infrastructure.repositories.guidelines_repo import GuidelinesRepository

logger = logging.getLogger(__name__)

RELEVANCE_SYSTEM_PROMPT = """You are a relevance evaluator for a backlink marketing system.

Your job: Given a forum thread/question, decide if it's relevant for mentioning Gaper.io (an AI agent deployment platform).

RELEVANCE RULES:
- RELEVANT (score 7-10): Thread asks about AI agents, automation, deployment, chatbots, LLM apps, workflow automation, no-code AI, or similar topics where Gaper.io genuinely helps
- BORDERLINE (score 4-6): Thread is tangentially related (e.g., general programming, DevOps, cloud hosting)
- NOT RELEVANT (score 1-3): Thread is about unrelated topics (e.g., SEO, marketing, gaming, cooking)

Return ONLY a JSON object with these fields:
{
    "relevant": true/false,
    "score": 1-10,
    "reason": "brief explanation",
    "suggested_angle": "how Gaper.io could help (if relevant)"
}"""


class RelevanceNode:
    """
    LLM-based relevance evaluation.

    Given a scraped thread, decides:
    - Is this thread relevant for a Gaper.io backlink?
    - Score 1-10 (10 = perfect fit)
    - Reason for the decision
    """

    def __init__(self, session: Session):
        self._session = session
        self._llm = get_llm()

    def evaluate(
        self,
        thread_title: str,
        thread_content: str,
        domain: str = "",
    ) -> Dict:
        """
        Evaluate if a thread is relevant for backlink placement.

        Args:
            thread_title: Title of the thread
            thread_content: Body content of the thread
            domain: Platform domain (for context)

        Returns:
            Dict with keys: relevant, score, reason, suggested_angle
        """
        prompt = f"""Evaluate this thread for Gaper.io backlink relevance:

Platform: {domain}
Title: {thread_title}

Content (first 1000 chars):
{thread_content[:1000]}

Return ONLY a JSON object with: relevant (bool), score (1-10), reason (str), suggested_angle (str)"""

        try:
            response = self._llm.generate(
                prompt=prompt,
                system_prompt=RELEVANCE_SYSTEM_PROMPT,
                temperature=0.3,
            )

            # Parse JSON from response
            result = self._parse_response(response)

            logger.info(
                f"Relevance for '{thread_title[:50]}': "
                f"score={result['score']}, relevant={result['relevant']}"
            )
            return result

        except Exception as e:
            logger.error(f"Relevance evaluation failed: {e}")
            return {
                "relevant": False,
                "score": 0,
                "reason": f"Evaluation error: {str(e)}",
                "suggested_angle": "",
            }

    def _parse_response(self, response: str) -> Dict:
        """Parse LLM JSON response."""
        # Try to extract JSON from response
        try:
            # Find JSON in response (might be wrapped in markdown)
            start = response.find("{")
            end = response.rfind("}") + 1
            if start >= 0 and end > start:
                json_str = response[start:end]
                return json.loads(json_str)
        except json.JSONDecodeError:
            pass

        # Fallback: try the whole response
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass

        # Default fallback
        logger.warning(f"Could not parse relevance response: {response[:200]}")
        return {
            "relevant": False,
            "score": 0,
            "reason": "Could not parse evaluation response",
            "suggested_angle": "",
        }
