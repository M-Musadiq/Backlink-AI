"""HackerNews platform poster - browser-use with pre-imported cookies."""
import json
import logging
import asyncio
import tempfile
import os
from src.infrastructure.posting.base_poster import BasePlatformPoster, PostResult

logger = logging.getLogger(__name__)


class HackerNewsPoster(BasePlatformPoster):
    @property
    def platform_name(self) -> str:
        return "news.ycombinator.com"

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
            logger.info(f"HN: saved {len(storage_data['cookies'])} cookies to storage_state")

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

Your task is to post this comment on the Hacker News thread:

---
{content}
---

Hacker News layout:
- Each comment has a small "reply" link at the TOP of the comment (right below the username/timestamp)
- The page is plain HTML, no JavaScript frameworks
- Look for links with text "reply" — they appear after each comment's metadata line
- The "reply" link is an <a> tag with href containing "reply"

Steps:
1. Go to the URL
2. Check if you are logged in: look for a "logout" link in the top-right area. If you see "login" instead, report NOT_LOGGED_IN
3. Check if the thread is archived: scroll down and look for ANY "reply" links. If there are zero "reply" links on the entire page, the thread is archived. Report POST_FAILED with reason "thread archived - no reply links found"
4. To post a top-level comment (not replying to anyone): scroll to the VERY BOTTOM of the page. There should be a textarea with id="text" and a submit button labeled "add comment"
5. If posting a reply to a specific comment: find the "reply" link under that comment and click it. A form with a textarea (id="text") will appear below it
6. Click the textarea and type the comment exactly as shown above
7. Click the submit button (it says "add comment" or "reply")
8. Wait 5 seconds, then check if your comment appears on the page
9. Report POST_SUCCESS if your comment appeared, or POST_FAILED with reason

CRITICAL: Your final message MUST start with exactly one of these markers:
- POST_SUCCESS — comment was confirmed posted
- POST_FAILED — comment was NOT posted (explain why)
- NOT_LOGGED_IN — not logged in

Important:
- HN is plain HTML — no React, no Vue, no complex JavaScript
- "reply" links look like: <a href="reply?id=...">reply</a>
- The textarea has id="text" and name="text"
- The submit button is <input type="submit" value="add comment">
- If you cannot find any textarea or reply links at all, report POST_FAILED
"""

        try:
            agent = Agent(
                task=task,
                llm=llm,
                browser=browser,
            )

            result = await agent.run(max_steps=30)
            final_result = result.final_result() if hasattr(result, 'final_result') else str(result)
            logger.info(f"HN browser-use result: {final_result}")

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
            logger.error(f"HN posting failed: {e}")
            return PostResult(success=False, error=str(e), platform=self.platform_name)
        finally:
            await browser.close()
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
