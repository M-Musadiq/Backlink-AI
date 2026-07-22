"""StackOverflow poster - Playwright + 2Captcha Turnstile solving."""
import json
import logging
import asyncio
import tempfile
import os
from src.infrastructure.posting.base_poster import BasePlatformPoster, PostResult
from src.infrastructure.posting.captcha_solver import solve_turnstile

logger = logging.getLogger(__name__)


class StackOverflowPoster(BasePlatformPoster):
    @property
    def platform_name(self) -> str:
        return "stackoverflow.com"

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
        from playwright.async_api import async_playwright

        tmp_path = None
        browser = None
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=False,
                    channel="chrome",
                    args=["--no-first-run", "--no-default-browser-check"],
                )

                storage_state = None
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
                    logger.info(f"SO: saved {len(storage_data['cookies'])} cookies to storage_state")

                context = await browser.new_context(
                    storage_state=storage_state,
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                )
                await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
                page = await context.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(3000)

                # Check logged in via cookies
                all_cookies = await context.cookies()
                cookie_names = {c["name"] for c in all_cookies}
                logger.info(f"SO: loaded cookies: {cookie_names}")
                if "acct" not in cookie_names:
                    await browser.close()
                    return PostResult(success=False, error="Not logged in to StackOverflow (no acct cookie)", platform=self.platform_name)

                logger.info("SO: logged in, looking for comment link...")

                # Click "add a comment" link
                comment_link = page.locator("a:has-text('add a comment'), a.js-add-link, button:has-text('Add a comment')")
                if await comment_link.count() == 0:
                    await page.evaluate("window.scrollBy(0, 800)")
                    await page.wait_for_timeout(1000)
                    comment_link = page.locator("a:has-text('add a comment'), a.js-add-link, button:has-text('Add a comment')")

                if await comment_link.count() > 0:
                    await comment_link.first.click()
                    logger.info("SO: clicked 'add a comment'")
                    await page.wait_for_timeout(3000)

                    # Solve Turnstile if present
                    for attempt in range(3):
                        solved = await self._solve_turnstile(page, url)
                        if solved:
                            logger.info("SO: Turnstile solved!")
                            break
                        logger.info(f"SO: Turnstile attempt {attempt+1} failed, retrying...")
                        await page.wait_for_timeout(2000)

                # Find comment textarea
                textarea = page.locator("textarea#add-comment, textarea[name='comment'], textarea.js-comment-textbox, textarea[placeholder*='comment'], textarea[placeholder*='Comment']")
                if await textarea.count() == 0:
                    textarea = page.locator("div[contenteditable='true'], textarea#comment-text")
                if await textarea.count() == 0:
                    textarea = page.locator("textarea")

                if await textarea.count() == 0:
                    await browser.close()
                    return PostResult(success=False, error="Comment box not found", platform=self.platform_name)

                logger.info("SO: typing comment...")
                await textarea.first.click()
                await textarea.first.fill(content)
                await page.wait_for_timeout(1000)

                # Submit comment
                submit = page.locator("button:has-text('Add Comment'), input[value='Add Comment'], button.js-comment-submit")
                if await submit.count() == 0:
                    logger.info("SO: no submit button, trying Enter key")
                    await textarea.first.press("Enter")
                else:
                    await submit.first.click()

                await page.wait_for_timeout(5000)

                # Check for errors
                error = page.locator(".error, .validation-error, .js-error-message, .captcha-error")
                if await error.count() > 0:
                    error_text = await error.first.text_content()
                    await browser.close()
                    return PostResult(success=False, error=f"SO error: {error_text}", platform=self.platform_name)

                await browser.close()
                return PostResult(success=True, post_url=url, platform=self.platform_name)

        except Exception as e:
            logger.error(f"StackOverflow posting failed: {e}")
            return PostResult(success=False, error=str(e), platform=self.platform_name)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass

    async def _solve_turnstile(self, page, page_url: str) -> bool:
        """Detect and solve Turnstile CAPTCHA if present."""
        try:
            turnstile = page.locator("iframe[src*='turnstile'], iframe[src*='challenges.cloudflare.com'], div.cf-turnstile")
            if await turnstile.count() == 0:
                return True  # No Turnstile present

            # Get sitekey
            sitekey = None
            # Try from iframe src
            if await turnstile.first.locator("xpath=..").count() > 0:
                src = await turnstile.first.get_attribute("src") or ""
                import re
                match = re.search(r'sitekey[=/]([A-Za-z0-9_-]+)', src)
                if match:
                    sitekey = match.group(1)

            # Try from data-sitekey
            if not sitekey:
                div = page.locator("div[data-sitekey]")
                if await div.count() > 0:
                    sitekey = await div.first.get_attribute("data-sitekey")

            if not sitekey:
                # Try from the Turnstile widget directly
                sitekey = await page.evaluate("""
                    () => {
                        const el = document.querySelector('[data-sitekey]');
                        return el ? el.getAttribute('data-sitekey') : null;
                    }
                """)

            if not sitekey:
                logger.warning("SO: Turnstile found but no sitekey")
                return False

            logger.info(f"SO: solving Turnstile (sitekey={sitekey[:20]}...)")
            token = await solve_turnstile(sitekey, page_url)
            if not token:
                logger.error("SO: 2Captcha failed to solve Turnstile")
                return False

            # Inject token
            await page.evaluate(f"""
                () => {{
                    const inputs = document.querySelectorAll('input[name="cf-turnstile-response"], textarea[name="cf-turnstile-response"]');
                    inputs.forEach(i => i.value = '{token}');
                    // Also try to trigger the callback
                    if (window.turnstile) {{
                        try {{ window.turnstile.execute(); }} catch(e) {{}}
                    }}
                }}
            """)
            await page.wait_for_timeout(2000)
            logger.info("SO: Turnstile token injected")
            return True

        except Exception as e:
            logger.error(f"SO: Turnstile error: {e}")
            return False
