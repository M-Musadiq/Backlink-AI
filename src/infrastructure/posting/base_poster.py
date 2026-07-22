"""Base poster interface for all platforms."""
import logging
from abc import ABC, abstractmethod
from typing import Dict, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PostResult:
    success: bool
    post_id: str = ""
    post_url: str = ""
    error: str = ""
    platform: str = ""

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "post_id": self.post_id,
            "post_url": self.post_url,
            "error": self.error,
            "platform": self.platform,
        }


class BasePlatformPoster(ABC):
    """Base class for all platform posters using Playwright."""

    def __init__(self):
        self._browser = None
        self._context = None

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Platform identifier (e.g., 'reddit.com', 'dev.to')."""
        pass

    @abstractmethod
    def post_reply(self, url: str, content: str, cookies: list = None) -> PostResult:
        """Post a reply/comment to the given URL (sync version)."""
        pass

    async def post_reply_async(self, url: str, content: str, cookies: list = None) -> PostResult:
        """Post a reply/comment to the given URL (async version)."""
        return await self._post_reply_async(url, content, cookies)

    @abstractmethod
    async def _post_reply_async(self, url: str, content: str, cookies: list = None) -> PostResult:
        """Internal async implementation."""
        pass

    async def _get_browser(self):
        """Get or create a Playwright browser instance."""
        if self._browser is None:
            from playwright.async_api import async_playwright
            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(
                headless=True,
                channel="chrome",
                args=["--no-first-run", "--no-default-browser-check"],
            )
        return self._browser

    async def _create_context(self, cookies: list = None):
        """Create a browser context with optional cookies."""
        browser = await self._get_browser()
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        if cookies:
            await context.add_cookies(cookies)
        return context

    async def close(self):
        """Clean up browser resources."""
        if self._browser:
            await self._browser.close()
        if hasattr(self, '_pw') and self._pw:
            await self._pw.stop()
