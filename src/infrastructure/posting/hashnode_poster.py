"""Hashnode poster - posts comments via Playwright using imported cookies."""
import logging
import asyncio
from src.infrastructure.posting.base_poster import BasePlatformPoster, PostResult

logger = logging.getLogger(__name__)


class HashnodePoster(BasePlatformPoster):
    @property
    def platform_name(self) -> str:
        return "hashnode.com"

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
        import json, tempfile, os
        from playwright.async_api import async_playwright

        # Convert cookies to storage_state format (more reliable than add_cookies)
        storage_state = None
        tmp_path = None
        if cookies:
            storage_data = {"cookies": [], "origins": []}
            for c in cookies:
                domain = c.get("domain", "")
                # Fix domain for subdomains (hashnode blogs are on *.hashnode.com)
                if domain == "hashnode.com":
                    domain = ".hashnode.com"
                cookie = {
                    "name": c.get("name", ""),
                    "value": c.get("value", ""),
                    "domain": domain,
                    "path": c.get("path", "/"),
                    "httpOnly": c.get("httpOnly", False),
                    "secure": c.get("secure", False),
                    "sameSite": c.get("sameSite", "Lax"),
                }
                if c.get("expires") and c["expires"] > 0:
                    cookie["expires"] = c["expires"]
                # __Host- prefix cookies are auto-managed by browser, skip them
                if cookie["name"].startswith("__Host-"):
                    continue
                storage_data["cookies"].append(cookie)
            tmp_path = tempfile.mktemp(suffix=".json")
            with open(tmp_path, "w") as f:
                json.dump(storage_data, f)
            storage_state = tmp_path
            logger.info(f"Hashnode: loaded {len(cookies)} cookies via storage_state")

        async with async_playwright() as p:
            import sys as _sys
            browser = await p.chromium.launch(
                headless=_sys.platform != "win32",
                channel="chrome",
                args=["--no-first-run", "--no-default-browser-check"],
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                storage_state=storage_state,
            )

            page = await context.new_page()
            await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

            try:
                # First navigate to hashnode.com to validate session
                await page.goto("https://hashnode.com", wait_until="networkidle", timeout=30000)
                await page.wait_for_timeout(3000)

                # Check all cookies in browser to verify they loaded
                all_cookies = await context.cookies()
                hn_cookies = [c for c in all_cookies if "hashnode" in c.get("domain", "")]
                logger.info(f"Hashnode: browser has {len(hn_cookies)} hashnode cookies: {[(c['name'], c['domain']) for c in hn_cookies]}")

                # Check login status on main site
                logged_in = False
                for sel in [
                    "button[data-testid='user-menu']",
                    "img[data-testid='userAvatar']",
                    "[data-testid='dashboard-tab']",
                    "a[href*='/dashboard']",
                    "a[href*='/new']",
                    "img[alt*='avatar']",
                ]:
                    if await page.locator(sel).count() > 0:
                        logged_in = True
                        logger.info(f"Hashnode: logged in on main site ({sel})")
                        break

                if not logged_in:
                    page_text = await page.evaluate("document.body.innerText.substring(0, 500)")
                    logger.warning(f"Hashnode: NOT logged in on main site. Text: {page_text[:300]}")
                    # Still try the prospect URL in case it works there

                # Now navigate to the actual prospect URL
                logger.info(f"Hashnode: navigating to {url}")
                await page.goto(url, wait_until="networkidle", timeout=30000)
                await page.wait_for_timeout(4000)

                # Check login status on prospect page
                logged_in = False
                for sel in [
                    "button[data-testid='user-menu']",
                    "img[data-testid='userAvatar']",
                    "[data-testid='dashboard-tab']",
                    "a[href*='/dashboard']",
                    "a[href*='/new']",
                    "img[alt*='avatar']",
                    "a:has-text('Write')",
                    "a:has-text('Drafts')",
                    "a:has-text('Submissions')",
                    "button:has-text('Write')",
                ]:
                    if await page.locator(sel).count() > 0:
                        logged_in = True
                        logger.info(f"Hashnode: logged in on post page ({sel})")
                        break

                if not logged_in:
                    page_text = await page.evaluate("document.body.innerText.substring(0, 300)")
                    logger.warning(f"Hashnode: not logged in. Page: {page_text[:200]}")
                    return PostResult(success=False, error="Not logged in - re-import cookies from Cookie Editor", platform=self.platform_name)

                # Scroll to comments
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(2000)

                # Find comment box
                comment_box = None
                for sel in [
                    "textarea[placeholder*='comment']",
                    "textarea[placeholder*='Comment']",
                    "textarea[placeholder*='Write']",
                    "textarea[placeholder*='Share']",
                    "div[contenteditable='true'][data-placeholder]",
                    "div[contenteditable='true']",
                ]:
                    if await page.locator(sel).count() > 0:
                        comment_box = page.locator(sel).first
                        logger.info(f"Hashnode: found comment box ({sel})")
                        break

                if not comment_box:
                    # Try clicking write comment button
                    for btn_sel in [
                        "button:has-text('Write a comment')",
                        "button:has-text('Add a comment')",
                        "button:has-text('Respond')",
                        "[data-testid='write-comment-button']",
                    ]:
                        btn = page.locator(btn_sel)
                        if await btn.count() > 0:
                            await btn.first.click()
                            await page.wait_for_timeout(2000)
                            for sel in ["textarea", "div[contenteditable='true']"]:
                                if await page.locator(sel).count() > 0:
                                    comment_box = page.locator(sel).first
                                    break
                        if comment_box:
                            break

                if not comment_box:
                    return PostResult(success=False, error="Comment box not found", platform=self.platform_name)

                # Type comment
                await comment_box.click()
                await page.wait_for_timeout(500)
                try:
                    await comment_box.fill(content)
                except Exception:
                    await comment_box.type(content, delay=10)
                await page.wait_for_timeout(1000)

                # Submit
                submit_btn = None
                for sel in [
                    "button[type='submit']:has-text('Submit')",
                    "button[type='submit']:has-text('Post')",
                    "button:has-text('Submit')",
                    "button:has-text('Post')",
                    "form button[type='submit']",
                ]:
                    btn = page.locator(sel)
                    if await btn.count() > 0:
                        submit_btn = btn.first
                        break

                if not submit_btn:
                    return PostResult(success=False, error="Submit button not found", platform=self.platform_name)

                await submit_btn.click()
                await page.wait_for_timeout(3000)

                return PostResult(success=True, post_url=url, platform=self.platform_name)

            except Exception as e:
                logger.error(f"Hashnode posting failed: {e}")
                return PostResult(success=False, error=str(e), platform=self.platform_name)
            finally:
                await browser.close()
                if tmp_path and os.path.exists(tmp_path):
                    os.remove(tmp_path)
