"""Reddit platform poster - browser-use with pre-imported cookies and proxy rotation."""
import json
import logging
import asyncio
import tempfile
import os
import time
from src.infrastructure.posting.base_poster import BasePlatformPoster, PostResult

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BLOCKED_MARKERS = ("BLOCKED", "NETWORK SECURITY", "BLOCKED BY", "YOU'VE BEEN BLOCKED")


class RedditPoster(BasePlatformPoster):
    @property
    def platform_name(self) -> str:
        return "reddit.com"

    def post_reply(self, url: str, content: str, cookies: list = None) -> PostResult:
        try:
            return asyncio.get_event_loop().run_until_complete(
                self._post_reply_async(url, content, cookies)
            )
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(self._post_reply_async(url, content, cookies))
            finally:
                loop.close()

    def _build_storage_state(self, cookies: list) -> tuple:
        storage_data = {"cookies": [], "origins": []}
        for c in cookies:
            if c.get("name", "").startswith("__Host-"):
                continue
            ss = c.get("sameSite", "Lax")
            if ss is None or ss not in ("Strict", "Lax", "None"):
                ss = "Lax"
            cookie = {
                "name": c["name"],
                "value": c["value"],
                "domain": c["domain"],
                "path": c.get("path", "/"),
                "httpOnly": bool(c.get("httpOnly", False)),
                "secure": bool(c.get("secure", False)),
                "sameSite": ss,
            }
            if c.get("expires") and c["expires"] > 0:
                cookie["expires"] = c["expires"]
            storage_data["cookies"].append(cookie)

        tmp_path = tempfile.mktemp(suffix=".json")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(storage_data, f, ensure_ascii=False)
        logger.info(f"Reddit: saved {len(storage_data['cookies'])} cookies")
        return tmp_path

    def _build_task(self, url: str, content: str) -> str:
        return f"""Go to this URL: {url}

Your task is to post this comment on the Reddit thread:

---
{content}
---

Steps:
1. Check if you are logged in. If you see a login page or "Log In" button, report NOT_LOGGED_IN
2. If you see a page saying "You've been blocked" or "network security", report POST_FAILED - BLOCKED
3. Scroll down to find the comment/reply box
4. If there is a "reply" link or button, click it to open the reply box
5. Find the comment textarea (it may be named "text" or be a RichText editor)
6. Click on the textarea and type the comment exactly as shown above
7. Click the "Save" or "Comment" button to submit
8. Wait 5 seconds and verify the comment was posted
9. Report POST_SUCCESS if comment appeared, or POST_FAILED with reason

CRITICAL: Your final message MUST start with exactly one of these markers:
- POST_SUCCESS — comment was confirmed posted
- POST_FAILED — comment was NOT posted (explain why)
- NOT_LOGGED_IN — not logged in

Important:
- Reddit uses old.reddit.com or new.reddit.com - the layout may differ
- If you see "Log In" or are redirected to a login page, report NOT_LOGGED_IN
- The comment box may need you to click "reply" first
- If you see "blocked by network security", report POST_FAILED - BLOCKED
"""

    def _is_blocked(self, result: str) -> bool:
        upper = result.upper()
        return any(marker in upper for marker in BLOCKED_MARKERS)

    async def _try_post(self, url: str, content: str, storage_state: str, proxy_settings) -> tuple:
        """Attempt one post. Returns (success: bool, result: str, is_blocked: bool)."""
        from browser_use import Agent, Browser, BrowserProfile
        from browser_use.llm.google.chat import ChatGoogle
        import src.config as config

        import sys
        browser_kwargs = {
            "headless": sys.platform != "win32",
            "disable_security": True,
        }
        if storage_state:
            browser_kwargs["storage_state"] = storage_state
        else:
            browser_kwargs["user_data_dir"] = None

        if proxy_settings:
            browser_kwargs["proxy"] = proxy_settings

        browser_profile = BrowserProfile(**browser_kwargs)
        browser = Browser(browser_profile=browser_profile)

        llm = ChatGoogle(
            model="gemini-3.5-flash",
            api_key=config.GEMINI_API_KEY,
            temperature=0.1,
        )

        try:
            agent = Agent(
                task=self._build_task(url, content),
                llm=llm,
                browser=browser,
            )
            result = await agent.run(max_steps=30)
            final_result = result.final_result() if hasattr(result, 'final_result') else str(result)
            logger.info(f"Reddit browser-use result: {final_result}")

            if final_result and "POST_SUCCESS" in str(final_result).upper():
                return True, str(final_result), False

            blocked = self._is_blocked(str(final_result)) if final_result else False
            return False, str(final_result) if final_result else "Unknown result", blocked

        except Exception as e:
            logger.error(f"Reddit try_post error: {e}")
            return False, str(e), False
        finally:
            await browser.close()

    async def _post_reply_async(self, url: str, content: str, cookies: list = None) -> PostResult:
        storage_state = None
        tmp_path = None

        if cookies:
            tmp_path = self._build_storage_state(cookies)
            storage_state = tmp_path

        try:
            for attempt in range(1, MAX_RETRIES + 1):
                session_id = f"r{attempt}_{int(time.time())}"
                logger.info(f"Reddit: attempt {attempt}/{MAX_RETRIES} session={session_id}")

                from src.infrastructure.proxy_service import proxy_service
                proxy = proxy_service.get_proxy_with_session(session_id)

                if proxy:
                    outbound_ip = proxy_service.get_outbound_ip_via_proxy(proxy)
                    logger.info(f"Reddit: proxy outbound IP = {outbound_ip}")

                    if not proxy_service.verify_proxy(proxy):
                        logger.warning(f"Reddit: attempt {attempt} proxy failed verification, retrying...")
                        continue

                    from browser_use.browser.profile import ProxySettings
                    proxy_settings = ProxySettings(
                        server=proxy["server"],
                        username=proxy.get("username"),
                        password=proxy.get("password"),
                    )
                    logger.info(f"Reddit: attempt {attempt} using proxy {proxy['server']}")
                else:
                    logger.warning(f"Reddit: attempt {attempt} no proxy available, trying direct")
                    proxy_settings = None

                success, result, blocked = await self._try_post(url, content, storage_state, proxy_settings)

                if success:
                    return PostResult(success=True, post_url=url, platform=self.platform_name)

                if not blocked:
                    return PostResult(success=False, error=result, platform=self.platform_name)

                logger.warning(f"Reddit: attempt {attempt} blocked by Reddit network security")

            return PostResult(
                success=False,
                error=f"All {MAX_RETRIES} proxy attempts blocked by Reddit network security",
                platform=self.platform_name,
            )

        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
