import logging
from typing import Optional
import requests

from src.domain.interfaces import LLMService

logger = logging.getLogger(__name__)


class OpenRouterLLMService(LLMService):
    def __init__(self, api_key: str, model: str = "google/gemini-2.5-flash"):
        self._api_key = api_key
        self._model = model
        self._url = "https://openrouter.ai/api/v1/chat/completions"

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
    ) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 4096,
        }

        logger.debug(f"OpenRouter request: model={self._model}, prompt_len={len(prompt)}")

        resp = requests.post(
            self._url,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()

        result = data["choices"][0]["message"]["content"].strip()

        logger.debug(f"OpenRouter response: len={len(result)}")
        return result
