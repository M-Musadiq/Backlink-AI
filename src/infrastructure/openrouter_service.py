import logging
import base64
from typing import Optional
import requests

from src.domain.interfaces import LLMService

logger = logging.getLogger(__name__)


class OpenRouterLLMService(LLMService):
    def __init__(self, api_key: str, model: str = "google/gemini-2.5-flash"):
        self._api_key = api_key
        self._model = model
        self._url = "https://openrouter.ai/api/v1/chat/completions"

    def _call(self, messages: list, temperature: float = 0.7, max_tokens: int = 4096) -> str:
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

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
        return data["choices"][0]["message"]["content"].strip()

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

        logger.debug(f"OpenRouter request: model={self._model}, prompt_len={len(prompt)}")
        result = self._call(messages, temperature)
        logger.debug(f"OpenRouter response: len={len(result)}")
        return result

    def generate_with_image(
        self,
        prompt: str,
        image_bytes: bytes,
        image_mime: str = "image/png",
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
    ) -> str:
        b64_image = base64.b64encode(image_bytes).decode("utf-8")
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{image_mime};base64,{b64_image}"}},
            ],
        })
        return self._call(messages, temperature, max_tokens=4096)

    def generate_with_images(
        self,
        prompt: str,
        images: list,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
    ) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        content = [{"type": "text", "text": prompt}]
        for img_bytes, mime in images:
            b64 = base64.b64encode(img_bytes).decode("utf-8")
            content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
        messages.append({"role": "user", "content": content})
        return self._call(messages, temperature, max_tokens=4096)
