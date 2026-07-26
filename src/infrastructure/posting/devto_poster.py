"""Dev.to platform poster - posts comments via Playwright."""
import logging
import asyncio
from src.infrastructure.posting.base_poster import BasePlatformPoster, PostResult

logger = logging.getLogger(__name__)


class DevToPoster(BasePlatformPoster):
    @property
    def platform_name(self) -> str:
        return "dev.to"

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

        async with async_playwright() as p:
            import sys as _sys
        browser = await p.chromium.launch(headless=_sys.platform != "win32")
            try:
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                if cookies:
                    await context.add_cookies(cookies)

                page = await context.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(6000)

                # Scroll to comment section
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(3000)

                # Check login
                logged_in = await page.locator("header a[href='/dashboard'], a.profile-preview-card__trigger, img.profile-preview-card__trigger").count() > 0
                if not logged_in:
                    return PostResult(success=False, error="Not logged in. Re-login via Sessions page.", platform=self.platform_name)

                # Find the textarea
                textarea = page.locator("#text-area, textarea[name='comment[body_markdown]'], textarea.comment-textarea")
                if await textarea.count() == 0:
                    await page.screenshot(path="debug_no_editor.png")
                    return PostResult(success=False, error="Comment textarea not found.", platform=self.platform_name)

                logger.info("Found comment textarea #text-area")

                # Fill the textarea
                await textarea.first.click()
                await page.wait_for_timeout(300)
                await textarea.first.fill(content)
                logger.info("Filled textarea with content")

                # Fire input/keyup events to enable the Submit button (dev.to disables it until input)
                await page.evaluate("""() => {
                    const ta = document.querySelector('#text-area, textarea[name="comment[body_markdown]"]');
                    if (ta) {
                        ta.dispatchEvent(new Event('input', { bubbles: true }));
                        ta.dispatchEvent(new Event('keyup', { bubbles: true }));
                        ta.dispatchEvent(new Event('change', { bubbles: true }));
                        // Also call the global handlers dev.to expects
                        if (typeof handleKeyUp === 'function') handleKeyUp({ target: ta });
                        if (typeof handleChange === 'function') handleChange({ target: ta });
                    }
                }""")
                logger.info("Fired input events to enable Submit button")
                await page.wait_for_timeout(1500)

                # Screenshot before submit
                await page.screenshot(path="debug_before_submit.png")
                logger.info("Saved debug_before_submit.png")

                # Wait for Submit button to become enabled
                submit_btn = page.locator("button[type='submit']:has-text('Submit')")
                if await submit_btn.count() == 0:
                    return PostResult(success=False, error="Submit button not found", platform=self.platform_name)

                # Check if disabled
                is_disabled = await submit_btn.first.get_attribute("disabled")
                logger.info(f"Submit button disabled: {is_disabled}")

                # If still disabled, try typing character by character instead of fill
                if is_disabled is not None:
                    logger.info("Submit still disabled after fill, trying keyboard.type()")
                    await textarea.first.click()
                    await page.wait_for_timeout(200)
                    # Clear and retype
                    await textarea.first.fill("")
                    await page.wait_for_timeout(200)
                    await page.keyboard.type(content, delay=10)
                    await page.wait_for_timeout(1500)
                    is_disabled = await submit_btn.first.get_attribute("disabled")
                    logger.info(f"After keyboard.type, disabled: {is_disabled}")
                    await page.screenshot(path="debug_before_submit_2.png")

                # Click submit
                await submit_btn.first.click()
                logger.info("Clicked Submit")
                await page.wait_for_timeout(8000)

                # Screenshot after submit
                await page.screenshot(path="debug_after_submit.png")
                logger.info("Saved debug_after_submit.png")

                # Verify
                page_text = await page.inner_text("body")
                first_line = content.split("\n")[0].strip()[:60]
                if first_line and first_line in page_text:
                    logger.info("Verified: comment content found on page")
                else:
                    logger.warning(f"Could not verify comment text '{first_line}' on page")

                return PostResult(success=True, post_url=url, platform=self.platform_name)

            except Exception as e:
                logger.error(f"Dev.to posting failed: {e}")
                return PostResult(success=False, error=str(e), platform=self.platform_name)
            finally:
                await browser.close()
