"""LLM factory - returns OpenRouter if available, falls back to Gemini."""
import logging
from src.config import GEMINI_API_KEY, OPENROUTER_API_KEY, OPENROUTER_MODEL
from src.domain.interfaces import LLMService

logger = logging.getLogger(__name__)


def get_llm() -> LLMService:
    if OPENROUTER_API_KEY:
        from src.infrastructure.openrouter_service import OpenRouterLLMService
        logger.info(f"Using OpenRouter ({OPENROUTER_MODEL})")
        return OpenRouterLLMService(api_key=OPENROUTER_API_KEY, model=OPENROUTER_MODEL)
    elif GEMINI_API_KEY:
        from src.infrastructure.gemini_service import GeminiLLMService
        logger.info("Using Gemini direct")
        return GeminiLLMService(api_key=GEMINI_API_KEY)
    else:
        raise RuntimeError("No LLM API key configured. Set OPENROUTER_API_KEY or GEMINI_API_KEY.")
