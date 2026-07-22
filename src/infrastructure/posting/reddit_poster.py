"""Reddit platform poster - browser-use with pre-imported cookies."""
import json
import logging
import asyncio
import tempfile
import os
from src.infrastructure.posting.base_poster import BasePlatformPoster, PostResult

logger = logging.getLogger(__name__)


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

    async def _post_reply_async(self, url: str, content: str, cookies: list = None) -> PostResult:
        from browser_use import Agent, Browser, BrowserProfile
        from browser_use.llm.google.chat import ChatGoogle
        import src.config as config

        llm = ChatGoogle(
            model="gemini-3.5-flash",
            api_key=config.GEMINI_API_KEY,
            temperature=0.1,
        )

        storage_state = None
        tmp_path = None
        if cookies:
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
            storage_state = tmp_path
            logger.info(f"Reddit: saved {len(storage_data['cookies'])} cookies to storage_state")

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

Your task is to post this comment on the Reddit thread:

---
{content}
---

Steps:
1. Check if you are logged in. If you see a login page or "Log In" button, report NOT_LOGGED_IN
2. Scroll down to find the comment/reply box
3. If there is a "reply" link or button, click it to open the reply box
4. Find the comment textarea (it may be named "text" or be a RichText editor)
5. Click on the textarea and type the comment exactly as shown above
6. Click the "Save" or "Comment" button to submit
7. Wait 5 seconds and verify the comment was posted
8. Report POST_SUCCESS if comment appeared, or POST_FAILED with reason

CRITICAL: Your final message MUST start with exactly one of these markers:
- POST_SUCCESS — comment was confirmed posted
- POST_FAILED — comment was NOT posted (explain why)
- NOT_LOGGED_IN — not logged in

Important:
- Reddit uses old.reddit.com or new.reddit.com - the layout may differ
- If you see "Log In" or are redirected to a login page, report NOT_LOGGED_IN
- The comment box may need you to click "reply" first
"""

        try:
            agent = Agent(
                task=task,
                llm=llm,
                browser=browser,
            )

            result = await agent.run(max_steps=30)
            final_result = result.final_result() if hasattr(result, 'final_result') else str(result)
            logger.info(f"Reddit browser-use result: {final_result}")

            if final_result and "POST_SUCCESS" in str(final_result).upper():
                return PostResult(success=True, post_url=url, platform=self.platform_name)

            if final_result and ("NOT_LOGGED_IN" in str(final_result).upper() or "POST_FAILED" in str(final_result).upper()):
                return PostResult(
                    success=False,
                    error=str(final_result),
                    platform=self.platform_name,
                )

            # Fallback: treat unknown as failure
            return PostResult(
                success=False,
                error=str(final_result) if final_result else "Unknown result from agent",
                platform=self.platform_name,
            )

        except Exception as e:
            logger.error(f"Reddit posting failed: {e}")
            return PostResult(success=False, error=str(e), platform=self.platform_name)
        finally:
            await browser.close()
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
