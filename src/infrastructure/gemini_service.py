import logging
import base64
from typing import Optional
import requests

from src.domain.interfaces import LLMService

logger = logging.getLogger(__name__)

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiLLMService(LLMService):
    def __init__(self, api_key: str, model: str = "gemini-flash-latest"):
        self._api_key = api_key
        self._model = model
        self._url = GEMINI_API_URL.format(model=self._model)

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
    ) -> str:
        contents = []

        if system_prompt:
            contents.append({"role": "user", "parts": [{"text": system_prompt}]})
            contents.append({"role": "model", "parts": [{"text": "Understood. I will follow these instructions."}]})

        contents.append({"role": "user", "parts": [{"text": prompt}]})

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": 8192,
            },
        }

        logger.debug(f"Gemini request: model={self._model}, prompt_len={len(prompt)}")

        resp = requests.post(
            self._url,
            params={"key": self._api_key},
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()

        candidates = data.get("candidates", [])
        if not candidates:
            logger.error(f"Gemini returned no candidates: {data}")
            return ""

        parts = candidates[0].get("content", {}).get("parts", [])
        result = "".join(p.get("text", "") for p in parts).strip()

        logger.debug(f"Gemini response: len={len(result)}")
        return result

    def generate_with_image(
        self,
        prompt: str,
        image_bytes: bytes,
        image_mime: str = "image/png",
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
    ) -> str:
        """Send a prompt + screenshot image to Gemini Vision."""
        b64_image = base64.b64encode(image_bytes).decode("utf-8")

        contents = []

        if system_prompt:
            contents.append({"role": "user", "parts": [{"text": system_prompt}]})
            contents.append({"role": "model", "parts": [{"text": "Understood."}]})

        contents.append({
            "role": "user",
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": image_mime, "data": b64_image}},
            ],
        })

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": 4096,
            },
        }

        resp = requests.post(
            self._url,
            params={"key": self._api_key},
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()

        candidates = data.get("candidates", [])
        if not candidates:
            logger.error(f"Gemini vision returned no candidates: {data}")
            return ""

        parts = candidates[0].get("content", {}).get("parts", [])
        result = "".join(p.get("text", "") for p in parts).strip()

        logger.debug(f"Gemini vision response: len={len(result)}")
        return result

    def generate_with_images(
        self,
        prompt: str,
        images: list,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
    ) -> str:
        """Send a prompt + multiple screenshot images (history) to Gemini Vision."""
        contents = []

        if system_prompt:
            contents.append({"role": "user", "parts": [{"text": system_prompt}]})
            contents.append({"role": "model", "parts": [{"text": "Understood."}]})

        user_parts = [{"text": prompt}]
        for img_bytes, mime in images:
            b64 = base64.b64encode(img_bytes).decode("utf-8")
            user_parts.append({"inline_data": {"mime_type": mime, "data": b64}})

        contents.append({"role": "user", "parts": user_parts})

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": 4096,
            },
        }

        resp = requests.post(
            self._url,
            params={"key": self._api_key},
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()

        candidates = data.get("candidates", [])
        if not candidates:
            return ""

        parts = candidates[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts).strip()
