"""Medium platform poster - Playwright + 2Captcha reCAPTCHA v3 Enterprise solving."""
import json
import logging
import asyncio
import re
import tempfile
import os
from src.infrastructure.posting.base_poster import BasePlatformPoster, PostResult
from src.infrastructure.posting.captcha_solver import solve_recaptcha_v3_enterprise

logger = logging.getLogger(__name__)

MEDIUM_RECAPTCHA_SITEKEY = "6Le-uGgpAAAAAPprRaokM8AKthQ9KNGdoxaGUvVp"
MEDIUM_RECAPTCHA_ACTION = "respond"


class MediumPoster(BasePlatformPoster):
    @property
    def platform_name(self) -> str:
        return "medium.com"

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

        # Build storage_state from cookies
        storage_state = None
        tmp_path = None
        if cookies:
            storage_data = {"cookies": [], "origins": []}
            for c in cookies:
                if c.get("name", "").startswith("__Host-"):
                    continue
                domain = c.get("domain", "")
                ss = c.get("sameSite", "Lax")
                if ss is None or ss not in ("Strict", "Lax", "None"):
                    ss = "Lax"
                cookie = {
                    "name": c["name"],
                    "value": c["value"],
                    "domain": domain,
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
            logger.info(f"Medium: saved {len(storage_data['cookies'])} cookies")

        # Pre-solve reCAPTCHA v3 Enterprise via 2Captcha
        logger.info(f"Medium: pre-solving reCAPTCHA v3 Enterprise (action={MEDIUM_RECAPTCHA_ACTION})")
        recaptcha_token = await solve_recaptcha_v3_enterprise(
            MEDIUM_RECAPTCHA_SITEKEY, url, action=MEDIUM_RECAPTCHA_ACTION, min_score=0.9
        )
        if recaptcha_token:
            logger.info(f"Medium: reCAPTCHA v3 Enterprise solved! Token length={len(recaptcha_token)}")
        else:
            logger.warning("Medium: reCAPTCHA v3 Enterprise pre-solve FAILED")

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
                # Inject reCAPTCHA interceptor BEFORE page load
                if recaptcha_token:
                    safe_token = json.dumps(recaptcha_token)
                    await page.add_init_script(f"""
                        (function() {{
                            var token = {safe_token};

                            // Override grecaptcha.enterprise.execute
                            Object.defineProperty(window, 'grecaptcha', {{
                                get: function() {{
                                    return {{
                                        enterprise: {{
                                            execute: function() {{
                                                return Promise.resolve(token);
                                            }}
                                        }}
                                    }};
                                }},
                                configurable: true
                            }});

                            // Intercept fetch
                            var origFetch = window.fetch;
                            window.fetch = function(url, opts) {{
                                if (opts && opts.body) {{
                                    try {{
                                        var body = String(opts.body);
                                        if (body.indexOf('recaptcha') !== -1) {{
                                            body = body.replace(/g-recaptcha-response=[^&]*/, 'g-recaptcha-response=' + encodeURIComponent(token));
                                            opts.body = body;
                                        }}
                                    }} catch(e) {{}}
                                }}
                                return origFetch.call(this, url, opts);
                            }};

                            // Intercept XMLHttpRequest
                            var origOpen = XMLHttpRequest.prototype.open;
                            var origSend = XMLHttpRequest.prototype.send;
                            XMLHttpRequest.prototype.open = function(method, url) {{
                                this._url = url;
                                return origOpen.apply(this, arguments);
                            }};
                            XMLHttpRequest.prototype.send = function(data) {{
                                if (data && typeof data === 'string' && data.indexOf('recaptcha') !== -1) {{
                                    data = data.replace(/g-recaptcha-response=[^&]*/, 'g-recaptcha-response=' + encodeURIComponent(token));
                                }}
                                return origSend.call(this, data);
                            }};
                        }})()
                    """)
                    logger.info("Medium: reCAPTCHA interceptor injected via add_init_script")

                # Navigate to article
                logger.info(f"Medium: navigating to {url}")
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(5000)

                # Check login status
                logged_in = False
                for sel in [
                    "button[aria-label='responses']",
                    "a[href*='/settings']",
                    "img[data-testid='userAvatar']",
                    "button[aria-label='home']",
                    "div[data-testid='headerUserMenu']",
                ]:
                    if await page.locator(sel).count() > 0:
                        logged_in = True
                        logger.info(f"Medium: logged in (found {sel})")
                        break

                if not logged_in:
                    # Check page text for login indicators
                    page_text = await page.evaluate("document.body.innerText.substring(0, 500)")
                    if "Sign in" in page_text or "Log in" in page_text:
                        await page.screenshot(path="debug_medium_login.png")
                        return PostResult(success=False, error="Not logged in. Re-import cookies via Sessions page.", platform=self.platform_name)

                # Scroll down to find responses section
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(2000)

                # Click "Responses" button to open comment panel
                responses_btn = page.locator("button[aria-label='responses']")
                if await responses_btn.count() > 0:
                    await responses_btn.first.click()
                    logger.info("Medium: clicked responses button")
                    await page.wait_for_timeout(3000)
                else:
                    logger.warning("Medium: responses button not found, trying alternative")
                    # Try alternative selectors
                    for alt_sel in [
                        "button:has-text('Respond')",
                        "button:has-text('Responses')",
                        "a:has-text('Respond')",
                    ]:
                        btn = page.locator(alt_sel)
                        if await btn.count() > 0:
                            await btn.first.click()
                            await page.wait_for_timeout(2000)
                            break

                # Find the contenteditable textbox
                textbox = None
                for sel in [
                    'div[role="textbox"][contenteditable="true"]',
                    'div[contenteditable="true"]',
                    'textarea:not(.g-recaptcha-response)',
                ]:
                    el = page.locator(sel)
                    count = await el.count()
                    logger.info(f"Medium: textbox selector '{sel}' — count={count}")
                    if count > 0:
                        textbox = el.first
                        logger.info(f"Medium: found textbox ({sel})")
                        break

                if not textbox:
                    await page.screenshot(path="debug_medium_no_textbox.png")
                    page_html = await page.content()
                    with open("debug_medium_page.html", "w", encoding="utf-8") as f:
                        f.write(page_html)
                    logger.info("Medium: saved debug_medium_page.html for analysis")
                    return PostResult(success=False, error="Comment textbox not found. Check debug_medium_page.html", platform=self.platform_name)

                # Click textbox to focus
                await textbox.click()
                await page.wait_for_timeout(500)

                # Clean content: convert "Name (URL)" to bare URL
                clean_content = re.sub(
                    r'(?:Gaper\.io|gaper\.io)\s*\(?(https?://gaper\.io/?\)?+)\)?',
                    r'https://gaper.io/',
                    content
                )
                if clean_content != content:
                    logger.info("Medium: cleaned backlink format to bare URL")

                # Find URL to hyperlink
                url_match = re.search(r'(https?://[^\s]+)', clean_content)

                if url_match:
                    url = url_match.group(1)
                    url_start = url_match.start()
                    url_end = url_match.end()
                    text_before = clean_content[:url_start]
                    text_after = clean_content[url_end:]

                    # Type text BEFORE the URL
                    if text_before:
                        await page.keyboard.type(text_before, delay=8)
                        await page.wait_for_timeout(500)

                    # Click the link button in toolbar
                    link_btn = None
                    for sel in [
                        'button[aria-label="link"]',
                        'button[aria-label="Link"]',
                        'button[aria-label="insert link"]',
                        'button[aria-label="Insert link"]',
                        'button[aria-label="hyperlink"]',
                        'button[aria-label="Hyperlink"]',
                    ]:
                        btn = page.locator(sel)
                        if await btn.count() > 0:
                            link_btn = btn.first
                            logger.info(f"Medium: found link button ({sel})")
                            break

                    if not link_btn:
                        buttons = page.locator('button')
                        count = await buttons.count()
                        for i in range(count):
                            btn = buttons.nth(i)
                            label = await btn.get_attribute("aria-label") or ""
                            if "link" in label.lower():
                                link_btn = btn
                                logger.info(f"Medium: found link button (aria-label={label})")
                                break

                    if link_btn:
                        await link_btn.click()
                        await page.wait_for_timeout(1500)

                        # Find the link URL input field
                        link_input = None
                        for sel in [
                            'input[placeholder*="link" i]',
                            'input[placeholder*="url" i]',
                            'input[placeholder*="URL" i]',
                            'input[placeholder*="Paste" i]',
                            'input[placeholder*="paste" i]',
                            'input[type="url"]',
                            'input[type="text"]',
                        ]:
                            inp = page.locator(sel)
                            if await inp.count() > 0:
                                link_input = inp.first
                                logger.info(f"Medium: found link input ({sel})")
                                break

                        if link_input:
                            await link_input.click()
                            await page.wait_for_timeout(300)
                            await link_input.fill(url)
                            await page.wait_for_timeout(500)
                            await page.keyboard.press("Enter")
                            await page.wait_for_timeout(1000)
                            logger.info(f"Medium: created hyperlink to {url}")
                        else:
                            logger.warning("Medium: link input dialog not found")
                    else:
                        logger.warning("Medium: link toolbar button not found")

                    # Type text AFTER the URL
                    if text_after:
                        await page.keyboard.type(text_after, delay=8)
                        await page.wait_for_timeout(500)
                else:
                    # No URL found, just type the whole thing
                    await page.keyboard.type(clean_content, delay=8)
                    await page.wait_for_timeout(1000)

                # Dispatch input events to ensure React state is updated
                await page.evaluate("""() => {
                    const textbox = document.querySelector('div[role="textbox"][contenteditable="true"]');
                    if (textbox) {
                        textbox.focus();
                        textbox.dispatchEvent(new Event('input', { bubbles: true }));
                        textbox.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                }""")
                await page.wait_for_timeout(1000)

                # Screenshot before submit
                await page.screenshot(path="debug_medium_before_submit.png")
                logger.info("Medium: saved debug_medium_before_submit.png")

                # Find and click Respond button
                respond_btn = None
                for sel in [
                    'button:has-text("Respond")',
                    'button[data-testid="respond-button"]',
                    'button[type="submit"]:has-text("Respond")',
                ]:
                    btn = page.locator(sel)
                    if await btn.count() > 0:
                        respond_btn = btn.first
                        break

                if not respond_btn:
                    # Try to find any enabled submit-like button in the responses panel
                    buttons = page.locator('button')
                    count = await buttons.count()
                    for i in range(count):
                        btn = buttons.nth(i)
                        text = await btn.inner_text()
                        if "respond" in text.lower() or "submit" in text.lower():
                            respond_btn = btn
                            break

                if not respond_btn:
                    await page.screenshot(path="debug_medium_no_respond_btn.png")
                    return PostResult(success=False, error="Respond button not found.", platform=self.platform_name)

                # Check if button is disabled
                is_disabled = await respond_btn.get_attribute("disabled")
                aria_disabled = await respond_btn.get_attribute("aria-disabled")
                logger.info(f"Medium: Respond button disabled={is_disabled}, aria-disabled={aria_disabled}")

                if is_disabled is not None or aria_disabled == "true":
                    # Try harder: clear and retype with keyboard
                    logger.info("Medium: Respond button disabled, trying harder...")
                    await textbox.click()
                    await page.wait_for_timeout(300)

                    # Select all and delete
                    await page.keyboard.press("Control+A")
                    await page.wait_for_timeout(100)
                    await page.keyboard.press("Backspace")
                    await page.wait_for_timeout(500)

                    # Clear and re-fill
                    await textbox.fill("")
                    await page.wait_for_timeout(300)
                    await textbox.fill(clean_content)
                    await textbox.dispatch_event("input")
                    await page.wait_for_timeout(2000)

                    # Fire more events
                    await page.evaluate("""() => {
                        const textbox = document.querySelector('div[role="textbox"][contenteditable="true"]');
                        if (textbox) {
                            textbox.focus();
                            ['input', 'change', 'keyup', 'keydown', 'keypress'].forEach(evt => {
                                textbox.dispatchEvent(new Event(evt, { bubbles: true }));
                            });
                            // Also try React's internal handler
                            const tracker = textbox._valueTracker;
                            if (tracker) {
                                tracker.setValue({toString: () => ''});
                            }
                            textbox.dispatchEvent(new Event('input', { bubbles: true }));
                        }
                    }""")
                    await page.wait_for_timeout(1500)

                    # Recheck
                    is_disabled = await respond_btn.get_attribute("disabled")
                    aria_disabled = await respond_btn.get_attribute("aria-disabled")
                    logger.info(f"Medium: After retry, disabled={is_disabled}, aria-disabled={aria_disabled}")

                    await page.screenshot(path="debug_medium_before_submit_2.png")

                # Force click even if disabled (some buttons are visually enabled but attribute is stale)
                try:
                    await respond_btn.click(force=True)
                    logger.info("Medium: clicked Respond button (force=True)")
                except Exception:
                    await respond_btn.click()
                    logger.info("Medium: clicked Respond button")

                await page.wait_for_timeout(8000)

                # Screenshot after submit
                await page.screenshot(path="debug_medium_after_submit.png")
                logger.info("Medium: saved debug_medium_after_submit.png")

                # Verify comment was posted
                page_text = await page.evaluate("document.body.innerText")
                first_line = content.split("\n")[0].strip()[:60]
                if first_line and first_line in page_text:
                    logger.info("Medium: verified comment text on page")
                    return PostResult(success=True, post_url=url, platform=self.platform_name)

                # Check if textbox is still visible with content (means not submitted)
                still_visible = False
                for sel in ['div[role="textbox"][contenteditable="true"]']:
                    el = page.locator(sel)
                    if await el.count() > 0:
                        text = await el.inner_text()
                        if first_line[:20] in text:
                            still_visible = True
                            break

                if still_visible:
                    logger.warning("Medium: comment still in textbox after clicking Respond")
                    return PostResult(success=False, error="Comment not posted - Respond button may require manual CAPTCHA verification", platform=self.platform_name)

                return PostResult(success=True, post_url=url, platform=self.platform_name)

            except Exception as e:
                logger.error(f"Medium posting failed: {e}")
                return PostResult(success=False, error=str(e), platform=self.platform_name)
            finally:
                await browser.close()
                if tmp_path and os.path.exists(tmp_path):
                    os.remove(tmp_path)
