"""AI-powered platform poster using browser-use library."""
import json
import logging
import asyncio
import tempfile
import os
from src.infrastructure.posting.base_poster import BasePlatformPoster, PostResult

logger = logging.getLogger(__name__)


class BrowserUsePoster(BasePlatformPoster):
    """Uses browser-use library — AI agent autonomously navigates and posts."""

    @property
    def platform_name(self) -> str:
        return "browser_use"

    def _get_llm(self):
        from browser_use.llm.google.chat import ChatGoogle
        import src.config as config
        return ChatGoogle(
            model="gemini-3.5-flash",
            api_key=config.GEMINI_API_KEY,
            temperature=0.1,
        )

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

    async def _post_reply_async(self, url: str, content: str, cookies: list = None) -> PostResult:
        from browser_use import Agent, Browser, BrowserProfile

        llm = self._get_llm()

        # Save cookies to temp file in Playwright storage_state format
        storage_state = None
        tmp_path = None
        if cookies:
            storage_data = {
                "cookies": [],
                "origins": [],
            }
            for c in cookies:
                ss = c.get("sameSite", "Lax")
                if ss is None or ss not in ("Strict", "Lax", "None"):
                    ss = "Lax"
                cookie = {
                    "name": c.get("name", ""),
                    "value": c.get("value", ""),
                    "domain": c.get("domain", ""),
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
            storage_state = tmp_path
            logger.info(f"Saved {len(cookies)} cookies to {tmp_path}")
            logger.info(f"Cookie domains: {list(set(c.get('domain', '') for c in cookies))}")
            logger.info(f"Cookie names: {[c.get('name', '') for c in cookies[:10]]}")

        browser_kwargs = {
            "headless": False,
            "disable_security": True,
        }
        if storage_state:
            browser_kwargs["storage_state"] = storage_state
        else:
            browser_kwargs["user_data_dir"] = None

        browser_profile = BrowserProfile(**browser_kwargs)
        browser = Browser(browser_profile=browser_profile)

        task = f"""Go to this URL: {url}

Your task is to post this comment on the page:

---
{content}
---

Steps to follow:
1. If you are not logged in (you see a login page), stop and report "NOT_LOGGED_IN"
2. Scroll down to find the comment section
3. Click the "add a comment" link if present
4. If you see a Cloudflare Turnstile challenge (a checkbox saying "Verify you are human"), click inside the checkbox to solve it. Wait 5 seconds after clicking. If it shows a spinner, wait up to 10 seconds for it to complete.
5. Find the comment textarea / text box
6. Click on it and type the comment content exactly as shown above
7. Find and click the Submit button ("Add Comment")
8. Wait for the page to confirm the comment was posted
9. Report POST_SUCCESS if the comment appeared, or POST_FAILED with reason

CRITICAL: Your final message MUST start with exactly one of these markers:
- POST_SUCCESS — comment was confirmed posted
- POST_FAILED — comment was NOT posted (explain why)
- NOT_LOGGED_IN — not logged in

Important:
- If the submit button is disabled, try typing into the textarea to enable it
- If you see a login page, stop immediately and report NOT_LOGGED_IN
- If you see a Cloudflare "Verify you are human" checkbox or challenge, CLICK on it — it usually auto-resolves
- Make sure the full comment text is entered before submitting
"""

        try:
            agent = Agent(
                task=task,
                llm=llm,
                browser=browser,
            )

            result = await agent.run(max_steps=30)

            final_result = result.final_result() if hasattr(result, 'final_result') else str(result)
            logger.info(f"browser-use result: {final_result}")

            if final_result and "POST_SUCCESS" in str(final_result).upper():
                return PostResult(success=True, post_url=url, platform=self.platform_name)

            if final_result and ("NOT_LOGGED_IN" in str(final_result).upper() or "POST_FAILED" in str(final_result).upper()):
                return PostResult(success=False, error=str(final_result), platform=self.platform_name)

            # Fallback: treat unknown as failure
            return PostResult(success=False, error=str(final_result) if final_result else "Unknown result from agent", platform=self.platform_name)

        except Exception as e:
            logger.error(f"browser-use failed: {e}")
            return PostResult(success=False, error=str(e), platform=self.platform_name)
        finally:
            await browser.close()
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
