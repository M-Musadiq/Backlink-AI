"""AI-powered platform poster using browser-use library."""
import json
import logging
import asyncio
import tempfile
import os
from src.infrastructure.posting.base_poster import BasePlatformPoster, PostResult

logger = logging.getLogger(__name__)


RECON_JS = """(...args) => {
  const result = {
    is_logged_in: false,
    login_detected: false,
    comment_input: null,
    comment_buttons: [],
    captcha_detected: false,
    sidebar_detected: false,
    page_title: document.title,
    url: location.href,
  };

  // Check login state
  const loginLinks = document.querySelectorAll('a[href*="sign-in"], a[href*="login"], a[href*="signin"]');
  const signInButtons = [...document.querySelectorAll('button')].filter(b =>
    /sign\\s*in|log\\s*in|login|signin/i.test(b.textContent)
  );
  const profileIcon = document.querySelector('[aria-label*="profile"], [aria-label*="account"], img[alt*="avatar"], [data-testid*="avatar"]');
  result.is_logged_in = !!profileIcon || (loginLinks.length === 0 && signInButtons.length === 0);
  result.login_detected = loginLinks.length > 0 || signInButtons.length > 0;

  // Find comment input fields — skip hidden and recaptcha elements
  const textareas = [...document.querySelectorAll('textarea')].filter(el =>
    el.offsetParent !== null && !(el.id || '').includes('g-recaptcha')
  );
  const contenteditables = [...document.querySelectorAll('[contenteditable="true"]')].filter(el =>
    el.offsetParent !== null
  );
  const commentInputs = [...document.querySelectorAll('input[type="text"], input:not([type])')].filter(el =>
    el.offsetParent !== null
  );

  // Prefer elements with comment-related attributes/classes
  const allInputs = [...contenteditables, ...textareas, ...commentInputs];
  const commentRelated = allInputs.filter(el =>
    /comment|response|reply|write|discuss|feedback/i.test(
      (el.id || '') + ' ' + (el.className || '') + ' ' + (el.placeholder || '') + ' ' + (el.getAttribute('aria-label') || '')
    )
  );
  const target = commentRelated[0] || allInputs[0];
  if (target) {
    result.comment_input = {
      tag: target.tagName.toLowerCase(),
      type: target.getAttribute('type') || (target.getAttribute('contenteditable') === 'true' ? 'contenteditable' : ''),
      id: target.id || null,
      placeholder: target.placeholder || null,
      aria_label: target.getAttribute('aria-label') || null,
      visible: target.offsetParent !== null,
    };
  }

  // Find submit/post buttons
  const allButtons = [...document.querySelectorAll('button, input[type="submit"], [role="button"]')];
  const submitRelated = allButtons.filter(el =>
    /submit|post|comment|respond|reply|send|publish|add\\s*comment/i.test(
      (el.textContent || '') + ' ' + (el.value || '') + ' ' + (el.getAttribute('aria-label') || '')
    )
  );
  result.comment_buttons = submitRelated.slice(0, 5).map(b => ({
    text: (b.textContent || b.value || '').trim().slice(0, 50),
    aria_label: b.getAttribute('aria-label') || null,
    id: b.id || null,
    disabled: b.disabled || b.classList.contains('disabled') || b.getAttribute('aria-disabled') === 'true',
  }));

  // Detect CAPTCHA
  const captchaFrames = [...document.querySelectorAll('iframe[src*="captcha"], iframe[src*="recaptcha"], iframe[src*="hcaptcha"], iframe[src*="turnstile"]')];
  const captchaDivs = [...document.querySelectorAll('[class*="captcha"], [class*="recaptcha"], [class*="hcaptcha"], [class*="turnstile"]')];
  const recaptchaBadge = document.querySelector('.grecaptcha-badge');
  result.captcha_detected = captchaFrames.length > 0 || captchaDivs.length > 0 || !!recaptchaBadge;

  // Detect sidebar/modal comment systems (Medium, Dev.to)
  const sidebarTriggers = [...document.querySelectorAll('[aria-label*="response"], [aria-label*="comment"], [aria-label*="reply"]')];
  const sidebars = [...document.querySelectorAll('[class*="sidebar"], [class*="panel"], [class*="drawer"], [role="dialog"], [aria-modal="true"]')];
  result.sidebar_detected = sidebarTriggers.length > 0 || sidebars.length > 0;
  result.sidebar_triggers = sidebarTriggers.slice(0, 5).map(b => ({
    text: (b.textContent || '').trim().slice(0, 50),
    aria_label: b.getAttribute('aria-label') || null,
  }));

  return result;
}
"""


def _build_task(url: str, content: str, recon: dict) -> str:
    """Build a targeted task prompt based on recon data."""
    parts = [f"Go to this URL: {url}"]
    parts.append("")
    parts.append("Your task is to post this comment on the page:")
    parts.append("")
    parts.append("---")
    parts.append(content)
    parts.append("---")
    parts.append("")

    s = 1
    instructions = []

    # Login check
    if recon.get("is_logged_in") is False:
        instructions.append(f"{s}. You see a login page or sign-in prompt — stop and report NOT_LOGGED_IN"); s += 1
    else:
        instructions.append(f"{s}. Verify you are logged in (look for profile icon/avatar). If you see a sign-in page, stop and report NOT_LOGGED_IN"); s += 1

    # Sidebar detection
    ci = recon.get("comment_input")
    sb = recon.get("sidebar_detected")
    st = recon.get("sidebar_triggers", [])
    cb = recon.get("comment_buttons", [])
    cd = recon.get("captcha_detected")

    if sb and not ci:
        trigger_desc = ""
        if st:
            labels = [t.get("aria_label") or t.get("text", "") for t in st if t.get("text") or t.get("aria_label")]
            if labels:
                trigger_desc = f" (labeled: {', '.join(labels[:3])})"
        instructions.append(f"{s}. The page uses a sidebar/panel for comments{trigger_desc}. Click the sidebar trigger button to open the comment panel, then wait 2 seconds"); s += 1
        instructions.append(f"{s}. After the sidebar opens, look for the comment input inside it. If still not visible, scroll to the bottom of the page"); s += 1
    else:
        instructions.append(f"{s}. Find the comment section — scroll down if needed"); s += 1

    # Comment input details
    if ci:
        tag = ci.get("tag", "")
        tip = ci.get("type", "")
        placeholder = ci.get("placeholder", "")
        aria = ci.get("aria_label", "")
        desc_parts = []
        if tag:
            desc_parts.append(f"<{tag}>")
        if placeholder:
            desc_parts.append(f'placeholder="{placeholder}"')
        if aria:
            desc_parts.append(f'aria-label="{aria}"')
        if tip == "contenteditable" or tag == "div":
            desc_parts.append("(contenteditable — click to focus first)")
        desc = " ".join(desc_parts) if desc_parts else "a text field"
        instructions.append(f"{s}. Click the comment input ({desc}) to focus it"); s += 1
    else:
        instructions.append(f"{s}. Find and click the comment input field (textarea, input, or contenteditable div)"); s += 1

    # CAPTCHA
    if cd:
        instructions.append(f"{s}. CAPTCHA detected on this page. If solving is required and doesn't auto-resolve after 10 seconds, report POST_FAILED with CAPTCHA reason"); s += 1
    else:
        instructions.append(f"{s}. If you see a captcha challenge, try clicking it; if stuck after 10 seconds, report POST_FAILED with CAPTCHA reason"); s += 1

    # Type content
    instructions.append(f"{s}. Type the comment content into the focused input field"); s += 1
    instructions.append(f"{s}. After typing, click somewhere else on the page to trigger blur/validation, wait 1 second"); s += 1
    instructions.append(f"{s}. If the submit button is still disabled, try Tab then Enter, or Ctrl+Enter"); s += 1
    instructions.append(f'{s}. If still disabled, dispatch input event: evaluate("document.activeElement.dispatchEvent(new Event(\'input\', {{bubbles:true}}))")'); s += 1

    # Submit button
    if cb:
        enabled = [b for b in cb if not b.get("disabled")]
        labels = list(dict.fromkeys(b.get("aria_label") or b.get("text") for b in (enabled or cb) if b.get("aria_label") or b.get("text")))
        hint = ", ".join(f'"{l}"' for l in labels[:3]) if labels else "Submit/Post/Respond"
        instructions.append(f"{s}. Find and click the submit button (candidates: {hint})"); s += 1
    else:
        instructions.append(f"{s}. Find and click the Submit/Post/Respond/Comment button"); s += 1

    instructions.append(f"{s}. Wait for the page to confirm the comment was posted"); s += 1
    instructions.append(f"{s}. Report POST_SUCCESS if the comment appeared, or POST_FAILED with reason")

    parts.append("\n".join(instructions))
    parts.append("")
    parts.append("CRITICAL: Your final message MUST start with exactly one of these markers:")
    parts.append("- POST_SUCCESS — comment was confirmed posted")
    parts.append("- POST_FAILED — comment was NOT posted (explain why, include if CAPTCHA was detected)")
    parts.append("- NOT_LOGGED_IN — not logged in")
    parts.append("")
    parts.append("Important:")
    parts.append("- If the submit button is disabled after typing, always try blur (click elsewhere) + wait before concluding it's stuck")
    parts.append("- If you see a captcha or the page says 'Verify you are human', note it in the POST_FAILED reason")
    parts.append("- Make sure the full comment text is entered before submitting")

    return "\n".join(parts)


def _ensure_cookie_storage(cookies: list) -> tuple:
    """Save cookies to temp file and return (storage_state_path, tmp_path)."""
    if not cookies:
        return None, None
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
    logger.info(f"Saved {len(cookies)} cookies to {tmp_path}")
    return tmp_path, tmp_path


def _make_browser_kwargs(storage_state: str | None) -> dict:
    import sys
    kwargs = {
        "headless": sys.platform != "win32",
        "disable_security": True,
    }
    if storage_state:
        kwargs["storage_state"] = storage_state
    else:
        kwargs["user_data_dir"] = None
    return kwargs


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

    async def _recon_page(self, browser, url: str) -> dict:
        """Quick reconnaissance: navigate and analyze page structure."""
        from browser_use.browser.views import BrowserError
        try:
            page = await browser.must_get_current_page()
            await page.goto(url)
            await asyncio.sleep(3)
            raw = await page.evaluate(RECON_JS)
            return json.loads(raw) if isinstance(raw, str) else raw
        except BrowserError:
            logger.warning("Browser error during recon, returning empty data")
            return {}
        except Exception as e:
            logger.warning(f"Recon failed: {e}, continuing with generic prompt")
            return {}

    async def _post_reply_async(self, url: str, content: str, cookies: list = None) -> PostResult:
        from browser_use import Browser as BrowserSession, BrowserProfile, Agent

        llm = self._get_llm()
        tmp_path, storage_state = _ensure_cookie_storage(cookies)

        browser_kwargs = _make_browser_kwargs(storage_state)
        browser_profile = BrowserProfile(**browser_kwargs)
        browser = BrowserSession(browser_profile=browser_profile)

        try:
            await browser.start()

            # Phase 1: Reconnaissance — understand page structure
            logger.info("Phase 1: Reconnaissance — analyzing page structure")
            recon = await self._recon_page(browser, url)
            logger.info(f"Recon result: logged_in={recon.get('is_logged_in')}, "
                        f"comment_input={recon.get('comment_input')}, "
                        f"buttons={len(recon.get('comment_buttons', []))}, "
                        f"sidebar={recon.get('sidebar_detected')}, "
                        f"captcha={recon.get('captcha_detected')}")

            # Phase 2: Build targeted task prompt
            logger.info("Phase 2: Building targeted task prompt")
            task = _build_task(url, content, recon)
            logger.debug(f"Task prompt:\n{task}")

            # Phase 3: Execute posting
            logger.info("Phase 3: Running posting agent")
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

            return PostResult(success=False, error=str(final_result) if final_result else "Unknown result from agent", platform=self.platform_name)

        except Exception as e:
            logger.error(f"browser-use failed: {e}")
            return PostResult(success=False, error=str(e), platform=self.platform_name)
        finally:
            await browser.close()
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
