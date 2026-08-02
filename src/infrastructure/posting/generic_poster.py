"""Generic poster — 3-phase Scout → Plan → Execute.

Scout:     navigate, screenshot + DOM snapshot, LLM builds a SiteProfile (cached per domain).
Plan:      SiteProfile → ordered PostingStep recipe (drawer → focus → type → events → submit → verify).
Execute:   run the recipe, screenshot at key steps, ask LLM to adapt failing steps (up to 2 retries).
"""
import json
import logging
import asyncio
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial
from urllib.parse import urlparse

from src.infrastructure.posting.base_poster import BasePlatformPoster, PostResult
from src.infrastructure.gemini_service import GeminiLLMService
from src.infrastructure.posting.captcha_solver import solve_turnstile, solve_recaptcha_v2
from src.infrastructure.posting.site_profile import SiteProfile, SiteProfileCache, EDITOR_PROMPTS
import src.config as config

logger = logging.getLogger(__name__)

DEBUG_DIR = "debug_posting"

TEXTBOX_FALLBACK_SELECTORS = [
    'div[role="textbox"][contenteditable="true"]',
    'div[contenteditable="true"]',
    'textarea:not(.g-recaptcha-response)',
    'textarea',
    'input[type="text"]',
    'input[type="email"]',
]

SUBMIT_FALLBACK_SELECTORS = [
    'button[type="submit"]',
    'button:has-text("Respond")',
    'button:has-text("Reply")',
    'button:has-text("Comment")',
    'button:has-text("Submit")',
    'button:has-text("Post")',
    'button:has-text("Publish")',
    'button:has-text("Send")',
    'input[type="submit"]',
]

URL_PATTERN = re.compile(r"https?://[^\s<>()\[\]]+")

NATURAL_ANCHORS = {"here", "this"}


class PostingStepError(Exception):
    """Raised when a recipe step cannot be completed; the executor may ask the LLM to adapt."""


@dataclass
class PostingStep:
    action: str  # open_drawer | focus_editor | type_content | dispatch_events | submit | verify
    selector: str = ""
    params: dict = field(default_factory=dict)
    screenshot: str = ""


class GenericPoster(BasePlatformPoster):
    @property
    def platform_name(self) -> str:
        return "generic"

    def __init__(self):
        super().__init__()
        self._cache = SiteProfileCache()

    def _get_llm(self):
        return GeminiLLMService(api_key=config.GEMINI_API_KEY)

    # ------------------------------------------------------------------ sync entry
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

    # ------------------------------------------------------------------ main flow
    async def _post_reply_async(self, url: str, content: str, cookies: list = None) -> PostResult:
        from playwright.async_api import async_playwright

        os.makedirs(DEBUG_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        domain_slug = url.replace("https://", "").replace("http://", "").split("/")[0].replace(".", "_")
        domain = urlparse(url).hostname or domain_slug

        storage_state, tmp_path = self._build_storage_state(cookies)

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=sys.platform != "win32",
                channel="chrome",
                args=[
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                storage_state=storage_state,
                viewport={"width": 1280, "height": 800},
            )
            page = await context.new_page()
            await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

            try:
                logger.info(f"GenericPoster: Navigating to {url}")
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(5000)
                await page.screenshot(path=f"{DEBUG_DIR}/{ts}_{domain_slug}_initial.png")

                await self._solve_captcha_if_present(page, url)
                llm = self._get_llm()

                # ---- Phase 1: Scout (with per-domain cache) ----
                logger.info("GenericPoster: ▶ Phase 1/3 — Scouting the site (analyzing editor, selectors, URL handling)...")
                profile = self._cache.load(domain)
                if profile is None:
                    logger.info(f"GenericPoster: No cached profile for {domain}, scouting site...")
                    profile = await self._scout_site(page, url, content, llm)
                    if profile:
                        self._cache.save(profile)
                    else:
                        profile = SiteProfile(domain=domain)
                        logger.warning("GenericPoster: Scout failed, using default profile (type_raw / unknown editor)")
                else:
                    logger.info(
                        f"GenericPoster: Using cached profile for {domain}: "
                        f"editor={profile.editor_type}, url_strategy={profile.url_strategy}, "
                        f"submit_method={profile.submit_method}, drawer={profile.drawer_needed}"
                    )

                if not profile.login_detected:
                    logger.warning("GenericPoster: LLM thinks the user is not logged in. Proceeding anyway.")

                # ---- Phase 2: Plan ----
                logger.info("GenericPoster: ▶ Phase 2/3 — Planning the posting recipe...")
                recipe = self._build_recipe(profile, content)
                logger.info(f"GenericPoster: Built recipe: {[s.action for s in recipe]}")

                # ---- Phase 3: Execute ----
                logger.info("GenericPoster: ▶ Phase 3/3 — Executing (screenshots saved to debug_posting/)...")
                ctx = {"textbox": None, "ts": ts, "domain_slug": domain_slug, "url": url}
                return await self._execute_recipe(page, recipe, llm, ctx)

            except Exception as e:
                logger.error(f"GenericPoster failed: {e}")
                try:
                    await page.screenshot(path=f"{DEBUG_DIR}/{ts}_{domain_slug}_error.png")
                except Exception:
                    pass
                return PostResult(success=False, error=str(e), platform=self.platform_name)
            finally:
                await browser.close()
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass

    # ------------------------------------------------------------------ Phase 1: Scout
    async def _scout_site(self, page, url: str, content: str, llm) -> SiteProfile:
        """Screenshot + structured DOM snapshot → LLM → SiteProfile."""
        simplified = await self._capture_dom(page)
        screenshot_bytes = await page.screenshot()
        page_title = ""
        try:
            page_title = await page.title()
        except Exception:
            pass
        domain = urlparse(url).hostname or url

        editor_hints = "; ".join(f"{k}: {v}" for k, v in EDITOR_PROMPTS.items())
        prompt = f"""You are analyzing a webpage to build a "site profile" for posting a comment/reply.

Page URL: {url}
Page title: {page_title}
Reply draft (first 400 chars): {content[:400]}
Draft contains a URL: {bool(URL_PATTERN.search(content))}

The comment input may be hidden behind a drawer/sidebar that must be clicked open first.

Editor types — {editor_hints}
URL strategies:
- type_raw: no toolbar, just type the URL as plain text
- toolbar_link: rich-text toolbar has a link button (or Ctrl+K) — select anchor text, click button, fill URL
- markdown_syntax: editor accepts markdown — wrap URL as [anchor](url)
- paste_and_enter: editor expects pasted URL into a URL/prompt input followed by Enter
- not_supported: links cannot be inserted — type the URL as plain text

Submit methods:
- click: a Submit/Reply/Post button exists
- ctrl_enter: press Ctrl+Enter to submit
- tab_enter: press Tab then Enter to submit

Interactive elements found on the page:
{simplified[:6000]}

Examine the screenshot image for visual clues (toolbars, editor chrome, comment section).

Return ONLY a valid JSON block (no markdown fences):
{{
  "editor_type": "plain_textarea|contenteditable|quill|prosemirror|markdown|unknown",
  "url_strategy": "type_raw|toolbar_link|markdown_syntax|paste_and_enter|not_supported",
  "drawer_needed": true|false,
  "drawer_selector": "css_selector|none",
  "textbox_selector": "css_selector|not_found",
  "submit_selector": "css_selector|not_found",
  "submit_method": "click|ctrl_enter|tab_enter",
  "login_detected": true|false,
  "notes": "brief explanation"
}}

Use robust, specific CSS selectors (prefer id, data-testid, aria-label, tag+class). Do not guess. If not found, set "not_found".
IMPORTANT — ambiguous selectors:
- Many pages have MULTIPLE textboxes (search box, login field, comment box). Make the textbox_selector as specific as possible to the COMMENT box (use placeholder/aria-label/name hints like comment, reply, respond, discuss, join the conversation).
- If only a generic selector is possible (e.g. div[role="textbox"]), it is OK — the poster re-scores all matches at runtime to find the comment box.
- Never select search bars or login/sign-in/email fields."""
        try:
            response = await self._ask_llm(llm, prompt, screenshot_bytes=screenshot_bytes)
            logger.info(f"Gemini scout raw response: {response}")
            data = self._parse_json_response(response)
            if data is None:
                return None
            profile = SiteProfile.from_dict({"domain": domain, **data})
            logger.info(
                f"GenericPoster: Scouted {domain} → editor={profile.editor_type}, "
                f"url_strategy={profile.url_strategy}, textbox={profile.textbox_selector}, "
                f"submit={profile.submit_selector}, drawer={profile.drawer_needed} ({profile.drawer_selector}), "
                f"submit_method={profile.submit_method}, notes={profile.notes[:120]}"
            )
            return profile
        except Exception as e:
            logger.warning(f"Scout failed: {e}")
            return None

    # ------------------------------------------------------------------ Phase 2: Plan
    def _build_recipe(self, profile: SiteProfile, content: str) -> list:
        clean = self._clean_content(content)
        segments = self._split_content(clean)

        recipe = []
        if profile.drawer_needed and profile.drawer_selector and profile.drawer_selector != "none":
            recipe.append(PostingStep(action="open_drawer", selector=profile.drawer_selector, screenshot="drawer_open"))
        recipe.append(PostingStep(action="focus_editor", selector=profile.textbox_selector))
        recipe.append(PostingStep(
            action="type_content",
            params={"segments": segments, "strategy": profile.url_strategy},
            screenshot="filled",
        ))
        recipe.append(PostingStep(action="dispatch_events"))
        recipe.append(PostingStep(
            action="submit",
            selector=profile.submit_selector,
            params={"method": profile.submit_method},
        ))
        recipe.append(PostingStep(action="verify", params={"content": clean}, screenshot="submitted"))
        return recipe

    @staticmethod
    def _clean_content(content: str) -> str:
        return re.sub(
            r'(?:Gaper\.io|gaper\.io)\s*\(?(https?://gaper\.io/?\)?+)\)?',
            r'https://gaper.io/',
            content,
        )

    @staticmethod
    def _split_content(content: str) -> list:
        """Split content into text/url segments so URL handling can be strategy-aware."""
        segments = []
        pos = 0
        for m in URL_PATTERN.finditer(content):
            if m.start() > pos:
                segments.append({"type": "text", "text": content[pos:m.start()]})
            url = m.group(0).rstrip(".,;:!?")
            anchor = None
            word_match = re.search(r"(\w+)\s+$", content[:m.start()])
            if word_match and word_match.group(1).lower() in NATURAL_ANCHORS:
                anchor = word_match.group(1)
            segments.append({"type": "url", "url": url, "anchor": anchor})
            pos = m.end()
        if pos < len(content):
            segments.append({"type": "text", "text": content[pos:]})
        return segments

    # ------------------------------------------------------------------ Phase 3: Execute
    async def _execute_recipe(self, page, recipe: list, llm, ctx: dict) -> PostResult:
        step_names = {
            "open_drawer": "Opening the comment section/drawer",
            "focus_editor": "Focusing the comment editor",
            "type_content": "Typing the reply content",
            "dispatch_events": "Notifying the page that text was entered",
            "submit": "Submitting the comment",
            "verify": "Verifying the comment was posted",
        }
        for idx, step in enumerate(recipe, 1):
            logger.info(f"GenericPoster: ▶ Step {idx}/{len(recipe)} — {step_names.get(step.action, step.action)}")
            attempt = 0
            step_result = None
            while True:
                try:
                    step_result = await self._run_step(page, step, llm, ctx)
                    break
                except Exception as e:
                    if not isinstance(e, PostingStepError):
                        logger.warning(f"GenericPoster: Step '{step.action}' raised unhandled error: {e}")
                        e = PostingStepError(str(e))
                    attempt += 1
                    if attempt > 2:
                        logger.error(f"GenericPoster: Step '{step.action}' failed after retries: {e}")
                        return PostResult(
                            success=False,
                            error=f"Step '{step.action}' failed: {e}",
                            platform=self.platform_name,
                        )
                    logger.warning(f"GenericPoster: Step '{step.action}' failed (retry {attempt}/2): {e}. Adapting...")
                    adapted = await self._adapt_step(page, step, str(e), llm, ctx)
                    if adapted is None:
                        return PostResult(
                            success=False,
                            error=f"Step '{step.action}' failed and could not be adapted: {e}",
                            platform=self.platform_name,
                        )
                    step = adapted
            if step.screenshot:
                try:
                    await page.screenshot(path=f"{DEBUG_DIR}/{ctx['ts']}_{ctx['domain_slug']}_{step.screenshot}.png")
                except Exception:
                    pass
            if step_result is not None:
                return step_result
        return PostResult(success=True, post_url=ctx["url"], platform=self.platform_name)

    async def _run_step(self, page, step: PostingStep, llm, ctx: dict):
        action = step.action
        if action == "open_drawer":
            await self._click_drawer(page, step.selector)
        elif action == "focus_editor":
            textbox = await self._locate_textbox(page, step.selector, llm, ctx)
            if textbox is None:
                raise PostingStepError("Could not locate the comment/reply input field")
            await self._focus_textbox(page, textbox)
            ctx["textbox"] = textbox
        elif action == "type_content":
            textbox = ctx.get("textbox")
            if textbox is None:
                textbox = await self._locate_textbox(page, "not_found", llm, ctx)
            if textbox is None:
                raise PostingStepError("No comment input available for typing")
            if not await self._is_active(page, textbox):
                logger.warning("GenericPoster: Comment editor lost focus; re-focusing before typing...")
                await self._focus_textbox(page, textbox)
                ctx["textbox"] = textbox
            await self._type_segments(
                page, textbox,
                step.params.get("segments", []),
                step.params.get("strategy", "type_raw"),
            )
        elif action == "dispatch_events":
            await self._dispatch_input_events(page)
        elif action == "submit":
            await self._submit(page, step.selector, step.params.get("method", "click"), ctx.get("textbox"))
        elif action == "verify":
            return await self._verify_post(page, step.params.get("content", ""), ctx)
        else:
            raise PostingStepError(f"Unknown step action: {action}")
        return None

    # --------------------------------------------------------------- step helpers
    @staticmethod
    async def _capture_dom(page) -> str:
        try:
            return await page.evaluate("""() => {
                const clone = document.body.cloneNode(true);
                clone.querySelectorAll('script, style, noscript, svg, iframe').forEach(el => el.remove());
                clone.querySelectorAll('[hidden], [style*="display:none"], [style*="display: none"]').forEach(el => el.remove());
                const elements = [];
                clone.querySelectorAll('textarea, [contenteditable="true"], button, input[type="submit"], input[type="text"], [role="textbox"], [role="button"], a').forEach(el => {
                    const tag = el.tagName.toLowerCase();
                    const attrs = {};
                    ['id','class','name','placeholder','aria-label','role','data-testid','type','value','href'].forEach(a => {
                        const v = el.getAttribute(a);
                        if (v) attrs[a] = v.length > 80 ? v.substring(0,80) : v;
                    });
                    const text = (el.innerText || el.value || '').trim().substring(0, 100);
                    const rect = el.getBoundingClientRect();
                    elements.push({tag, attrs, text, visible: rect.width > 0 || rect.height > 0});
                });
                return JSON.stringify(elements.slice(0, 80));
            }""")
        except Exception as e:
            logger.warning(f"DOM capture failed: {e}")
            return "{}"

    async def _ask_llm(self, llm, prompt: str, screenshot_bytes: bytes = None) -> str:
        loop = asyncio.get_event_loop()
        if screenshot_bytes:
            try:
                return await loop.run_in_executor(
                    None, partial(llm.generate_with_images, prompt=prompt, images=[(screenshot_bytes, "image/png")], temperature=0.1)
                )
            except Exception as e:
                logger.warning(f"Vision LLM call failed ({e}), retrying text-only")
        return await loop.run_in_executor(None, partial(llm.generate, prompt=prompt, temperature=0.1))

    @staticmethod
    def _parse_json_response(response: str):
        try:
            match = re.search(r'\{[\s\S]*\}', response or "")
            if not match:
                return None
            return json.loads(match.group())
        except Exception:
            return None

    async def _click_drawer(self, page, selector: str):
        el = page.locator(selector)
        if await el.count() == 0:
            raise PostingStepError(f"Drawer/comments trigger '{selector}' not found")
        logger.info(f"GenericPoster: Clicking drawer/comments trigger: {selector}")
        await el.first.evaluate("e => e.scrollIntoView({block:'center', behavior:'smooth'})")
        await page.wait_for_timeout(500)
        try:
            await el.first.click(timeout=8000)
        except Exception:
            await el.first.evaluate("e => e.click()")
        await page.wait_for_timeout(3000)

    async def _locate_textbox(self, page, preferred: str, llm, ctx: dict):
        """Locate the comment/reply input by LIVE scoring every candidate element.

        Broad selectors like div[role="textbox"] match search boxes, login fields etc.,
        so instead of blindly taking the first match we score each candidate by
        visibility, comment-related hints (placeholder/aria-label/name), editor type,
        and penalties for search/login fields — and pick the best.
        """
        selectors = []
        if preferred and preferred != "not_found":
            selectors.append(preferred)
        selectors.extend(TEXTBOX_FALLBACK_SELECTORS)

        scored = []
        seen = set()
        for sel in selectors:
            try:
                locator = page.locator(sel)
                count = await locator.count()
            except Exception:
                continue
            for i in range(min(count, 10)):
                key = (sel, i)
                if key in seen:
                    continue
                seen.add(key)
                try:
                    el = locator.nth(i)
                    info = await el.evaluate("""el => {
                        const r = el.getBoundingClientRect();
                        return {
                            tag: el.tagName.toLowerCase(),
                            visible: (r.width > 0 || r.height > 0),
                            placeholder: el.getAttribute('placeholder') || el.getAttribute('aria-placeholder') || '',
                            aria: el.getAttribute('aria-label') || '',
                            name: el.getAttribute('name') || '',
                            id: el.id || '',
                            cls: typeof el.className === 'string' ? el.className : '',
                            contenteditable: el.isContentEditable,
                            role: el.getAttribute('role') || '',
                            type: el.getAttribute('type') || '',
                        };
                    }""")
                    visible = await el.is_visible()
                except Exception:
                    continue
                score = self._score_textbox(info, visible)
                if score <= 0:
                    continue
                scored.append((score, sel, i, info, visible))

        if scored:
            scored.sort(key=lambda c: c[0], reverse=True)
            score, sel, i, info, visible = scored[0]
            logger.info(
                f"GenericPoster: Picked comment input → {sel} [#{i}] (score={score}, "
                f"<{info['tag']}> visible={visible}, placeholder='{info['placeholder']}', "
                f"aria='{info['aria']}', name='{info['name']}')"
            )
            if len(scored) > 1:
                logger.info(
                    f"GenericPoster:   other candidates: "
                    + "; ".join(f"{s[1]}[#{s[2]}] score={s[0]}" for s in scored[1:4])
                )
            return page.locator(sel).nth(i)

        # LLM re-scout with fresh DOM (drawer may have opened since the profile was built)
        logger.info("GenericPoster: No good candidate found by scoring; asking LLM for the textbox selector...")
        simplified = await self._capture_dom(page)
        prompt = f"""You are analyzing a webpage to find the comment/reply input field.
Page URL: {ctx['url']}
Interactive elements:
{simplified[:6000]}
Return ONLY a valid JSON block:
{{
  "textbox_selector": "css_selector|not_found",
  "notes": "brief explanation"
}}
Prefer the comment/reply box (placeholder/aria-label hints like comment, reply, respond, discuss, write).
Avoid search boxes, login/sign-in fields, and email fields. Do not guess. If not found, set "not_found"."""
        try:
            response = await self._ask_llm(llm, prompt)
            data = self._parse_json_response(response)
            sel = (data or {}).get("textbox_selector")
            if sel and sel != "not_found":
                el = page.locator(sel)
                if await el.count() > 0:
                    logger.info(f"GenericPoster: LLM re-scout found textbox: {sel}")
                    return el.first
        except Exception as e:
            logger.warning(f"LLM textbox re-scout failed: {e}")
        return None

    @staticmethod
    def _score_textbox(info: dict, visible: bool) -> int:
        """Score a candidate comment-input element. <=0 means 'not a comment input'."""
        score = 0
        if visible:
            score += 50
        hay = f"{info.get('placeholder', '')} {info.get('aria', '')} {info.get('name', '')} {info.get('id', '')} {info.get('cls', '')}".lower()
        for kw in ("comment", "reply", "respond", "discuss", "write", "feedback", "join the conversation", "conversation"):
            if kw in hay:
                score += 30
        if info.get("contenteditable"):
            score += 10
        if info.get("role") == "textbox":
            score += 5
        if info.get("tag") == "textarea":
            score += 5
        if info.get("type") == "email":
            score -= 40
        for kw in ("search", "login", "signin", "sign-in", "password", "username", "email"):
            if kw in hay:
                score -= 60
        return score

    @staticmethod
    async def _is_active(page, textbox) -> bool:
        """Check the browser's document.activeElement actually points at the textbox."""
        try:
            return await textbox.evaluate(
                "el => { const a = document.activeElement; return a === el || (a && el.contains(a)); }"
            )
        except Exception:
            return False

    async def _focus_textbox(self, page, textbox):
        focused = False
        # Strategy 1: scroll into view + click
        try:
            await textbox.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'smooth'})")
            await page.wait_for_timeout(600)
            await textbox.click(timeout=8000)
            focused = await self._is_active(page, textbox)
            logger.info(f"GenericPoster: scroll+click → active={focused}")
        except Exception as e1:
            logger.warning(f"GenericPoster: scroll+click failed: {e1}")
        # Strategy 2: JS focus + click
        if not focused:
            try:
                await textbox.evaluate("el => { el.scrollIntoView({block:'center'}); el.focus(); el.click(); }")
                await page.wait_for_timeout(500)
                focused = await self._is_active(page, textbox)
                logger.info(f"GenericPoster: JS focus+click → active={focused}")
            except Exception as e2:
                logger.warning(f"GenericPoster: JS focus+click failed: {e2}")
        # Strategy 3: force click
        if not focused:
            try:
                await textbox.click(force=True, timeout=8000)
                await page.wait_for_timeout(500)
                focused = await self._is_active(page, textbox)
                logger.info(f"GenericPoster: force click → active={focused}")
            except Exception as e3:
                logger.warning(f"GenericPoster: force click failed: {e3}")
        # Strategy 4: Escape to dismiss overlays, then retry
        if not focused:
            try:
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(500)
                await textbox.evaluate("el => el.scrollIntoView({block:'center'})")
                await page.wait_for_timeout(400)
                await textbox.click(timeout=8000)
                focused = await self._is_active(page, textbox)
                logger.info(f"GenericPoster: Escape+retry → active={focused}")
            except Exception as e4:
                logger.warning(f"GenericPoster: Escape+retry failed: {e4}")
        # Strategy 5: Tab-navigate from body
        if not focused:
            try:
                await page.evaluate("document.body.focus()")
                await page.wait_for_timeout(200)
                for _ in range(20):
                    await page.keyboard.press("Tab")
                    await page.wait_for_timeout(100)
                    active_tag = await page.evaluate(
                        "() => { const el = document.activeElement; return (el.getAttribute('role') || el.tagName || '').toLowerCase(); }"
                    )
                    if active_tag in ("textbox", "textarea"):
                        focused = True
                        break
                if focused:
                    logger.info("GenericPoster: Focused textbox via Tab navigation")
                else:
                    logger.warning("GenericPoster: Tab navigation could not find textbox focus")
            except Exception as e5:
                logger.warning(f"GenericPoster: Tab navigation failed: {e5}")
        # Strategy 6: trusted mouse click at the element's bounding-box center.
        # JS el.click() produces untrusted events which collapsed composers (Reddit-style)
        # ignore — a CDP-driven mouse click at coordinates is a trusted event.
        if not focused:
            try:
                box = await textbox.evaluate(
                    "el => { const r = el.getBoundingClientRect(); return {x: r.x, y: r.y, w: r.width, h: r.height}; }"
                )
                if box and (box["w"] > 0 or box["h"] > 0):
                    await page.mouse.click(box["x"] + max(box["w"], 1) / 2, box["y"] + max(box["h"], 1) / 2)
                    await page.wait_for_timeout(800)
                    focused = await self._is_active(page, textbox)
                    logger.info(f"GenericPoster: trusted mouse click at coordinates → active={focused}")
            except Exception as e6:
                logger.warning(f"GenericPoster: trusted mouse click failed: {e6}")
        if not focused:
            raise PostingStepError("Could not focus the comment input. It may be inside an iframe or behind an undetected overlay.")
        logger.info("GenericPoster: ✓ Comment editor is focused and ready for typing")
        await page.wait_for_timeout(300)

    async def _type_segments(self, page, textbox, segments: list, strategy: str):
        total_urls = sum(1 for s in segments if s["type"] == "url")
        logger.info(
            f"GenericPoster: Simulating physical keyboard typing (url_strategy={strategy}, "
            f"{len(segments)} segments, {total_urls} URL(s))..."
        )
        for idx, seg in enumerate(segments, 1):
            if seg["type"] == "text":
                logger.info(f"GenericPoster:   [{idx}/{len(segments)}] typing text ({len(seg['text'])} chars)...")
                if seg["text"]:
                    await page.keyboard.type(seg["text"], delay=15)
            else:
                logger.info(
                    f"GenericPoster:   [{idx}/{len(segments)}] inserting URL {seg['url']} "
                    f"(strategy={strategy}, anchor={seg.get('anchor') or 'none'})..."
                )
                await self._handle_url_in_content(page, textbox, seg["url"], seg.get("anchor"), strategy)
        await page.wait_for_timeout(1000)

    async def _handle_url_in_content(self, page, textbox, url_str: str, anchor, strategy: str):
        """Insert the URL part of the content according to the site's url_strategy."""
        if strategy == "markdown_syntax" and anchor:
            logger.info(f"GenericPoster: URL strategy=markdown_syntax → typing [{anchor}]({url_str})")
            await page.keyboard.type(f"[{anchor}]({url_str})", delay=15)
        elif strategy == "toolbar_link" and anchor:
            await self._toolbar_link_flow(page, url_str, anchor)
        elif strategy == "paste_and_enter":
            await self._paste_and_enter_flow(page, url_str)
        else:
            # type_raw, not_supported, or no natural anchor text → plain text
            logger.info(f"GenericPoster: URL strategy={strategy} → typing URL raw")
            await page.keyboard.type(url_str, delay=15)
        await page.wait_for_timeout(300)

    async def _toolbar_link_flow(self, page, url_str: str, anchor: str):
        logger.info("GenericPoster: URL strategy=toolbar_link → anchor + link button")
        await page.keyboard.type(anchor, delay=15)
        await page.wait_for_timeout(200)
        await page.keyboard.press("Control+Shift+ArrowLeft")
        await page.wait_for_timeout(300)
        link_btn = await self._find_link_toolbar_button(page)
        if link_btn is None:
            logger.warning("GenericPoster: No link toolbar button found; typing raw URL")
            await page.keyboard.type(url_str, delay=15)
            return
        await link_btn.click()
        await page.wait_for_timeout(1000)
        link_input = await self._find_link_input(page)
        if link_input is None:
            logger.warning("GenericPoster: No link URL input found; typing raw URL")
            await page.keyboard.type(url_str, delay=15)
            return
        await link_input.click()
        await page.wait_for_timeout(200)
        await link_input.fill(url_str)
        await page.wait_for_timeout(300)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(1000)

    @staticmethod
    async def _find_link_toolbar_button(page):
        for sel in [
            'button[aria-label="link"]', 'button[aria-label="Link"]',
            'button[aria-label="insert link"]', 'button[aria-label="Insert link"]',
            'button[aria-label="hyperlink"]', 'button[aria-label="Hyperlink"]',
        ]:
            btn = page.locator(sel)
            if await btn.count() > 0:
                return btn.first
        btns = page.locator('button')
        for i in range(await btns.count()):
            label = await btns.nth(i).get_attribute("aria-label") or ""
            text_inner = await btns.nth(i).inner_text() or ""
            if "link" in label.lower() or "link" in text_inner.lower():
                return btns.nth(i)
        return None

    @staticmethod
    async def _find_link_input(page):
        for sel in [
            'input[placeholder*="link" i]', 'input[placeholder*="url" i]',
            'input[placeholder*="URL" i]', 'input[placeholder*="Paste" i]',
            'input[placeholder*="paste" i]', 'input[type="url"]',
            'input[type="text"]',
        ]:
            inp = page.locator(sel)
            if await inp.count() > 0:
                return inp.first
        return None

    @staticmethod
    async def _paste_and_enter_flow(page, url_str: str):
        logger.info("GenericPoster: URL strategy=paste_and_enter → clipboard paste + Enter")
        try:
            await page.evaluate(
                """(url) => { navigator.clipboard.writeText(url).catch(() => {}); }""", url_str
            )
        except Exception:
            pass
        await page.keyboard.press("Control+v")
        await page.wait_for_timeout(500)
        await page.keyboard.press("Enter")

    @staticmethod
    async def _dispatch_input_events(page):
        await page.evaluate("""() => {
            const el = document.activeElement;
            if (el) {
                ['input', 'change', 'keyup', 'keydown', 'keypress'].forEach(evtName => {
                    el.dispatchEvent(new Event(evtName, { bubbles: true }));
                });
                const tracker = el._valueTracker;
                if (tracker) {
                    tracker.setValue({toString: () => ''});
                }
                el.dispatchEvent(new Event('input', { bubbles: true }));
            }
        }""")
        await page.wait_for_timeout(1500)

    async def _submit(self, page, submit_sel: str, method: str, textbox):
        logger.info(f"GenericPoster: Submitting (method={method})...")
        if method == "ctrl_enter":
            await page.keyboard.press("Control+Enter")
            await page.wait_for_timeout(1000)
            return
        if method == "tab_enter":
            await page.keyboard.press("Tab")
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(1000)
            return
        btn = await self._find_submit_button(page, submit_sel)
        if btn is None and textbox is not None:
            # The submit button may only mount after a trusted click opens the composer
            # (Reddit-style collapsed comment composers ignore untrusted JS clicks).
            logger.info("GenericPoster: Submit button not found; trusted-clicking textbox to open composer...")
            try:
                await textbox.evaluate("el => el.scrollIntoView({block:'center', behavior:'smooth'})")
                await page.wait_for_timeout(400)
                box = await textbox.evaluate(
                    "el => { const r = el.getBoundingClientRect(); return {x: r.x + r.width / 2, y: r.y + r.height / 2}; }"
                )
                if box:
                    await page.mouse.click(max(box["x"], 1), max(box["y"], 1))
                    await page.wait_for_timeout(1500)
            except Exception as ex:
                logger.warning(f"GenericPoster: textbox trusted re-click failed: {ex}")
            btn = await self._find_submit_button(page, submit_sel)
        if btn is None:
            raise PostingStepError("Could not locate a visible submit button")
        try:
            if not await btn.is_visible():
                raise PostingStepError(f"Submit button '{submit_sel}' exists but is not visible")
        except PostingStepError:
            raise
        except Exception:
            pass
        is_disabled = await btn.get_attribute("disabled")
        aria_disabled = await btn.get_attribute("aria-disabled")
        logger.info(f"GenericPoster: Submit button disabled state: disabled={is_disabled}, aria-disabled={aria_disabled}")
        if is_disabled is not None or aria_disabled == "true":
            logger.info("GenericPoster: Submit button is disabled, trying blur-focus trick...")
            await page.mouse.click(10, 10)
            await page.wait_for_timeout(500)
            if textbox:
                await textbox.click()
                await page.wait_for_timeout(500)
        try:
            await btn.click(force=True, timeout=15000)
        except Exception as click_err:
            logger.warning(f"Submit button click failed: {click_err}")
            raise PostingStepError(f"Could not click submit button: {click_err}")
        await page.wait_for_timeout(3000)

    async def _find_submit_button(self, page, preferred: str):
        """Locate the submit button by LIVE scoring of visible candidates.

        Scores visible buttons by how comment-like they are (text/aria-label contains
        comment/reply/respond/post...), so a hidden or unrelated button[type=submit]
        (e.g. Reddit's "Apply filters") is never picked over the real submit button.
        """
        selectors = []
        if preferred and preferred != "not_found":
            selectors.append(preferred)
        selectors.extend(SUBMIT_FALLBACK_SELECTORS)

        scored = []
        seen = set()
        for sel in selectors:
            try:
                locator = page.locator(sel)
                count = await locator.count()
            except Exception:
                continue
            for i in range(min(count, 8)):
                key = (sel, i)
                if key in seen:
                    continue
                seen.add(key)
                try:
                    el = locator.nth(i)
                    if not await el.is_visible():
                        continue
                    info = await el.evaluate("""el => {
                        return {
                            text: (el.innerText || el.value || '').trim().slice(0, 50),
                            aria: el.getAttribute('aria-label') || '',
                            tag: el.tagName.toLowerCase(),
                            disabled: el.disabled || el.getAttribute('aria-disabled') === 'true',
                        };
                    }""")
                except Exception:
                    continue
                score = self._score_submit_button(info)
                scored.append((score, sel, i, info))

        if scored:
            scored.sort(key=lambda c: c[0], reverse=True)
            score, sel, i, info = scored[0]
            logger.info(
                f"GenericPoster: Picked submit button → {sel} [#{i}] (score={score}, "
                f"text='{info['text']}', aria='{info['aria']}', disabled={info['disabled']})"
            )
            if len(scored) > 1:
                logger.info(
                    f"GenericPoster:   other candidates: "
                    + "; ".join(f"{s[1]}[#{s[2]}] score={s[0]} ('{s[3]['text']}')" for s in scored[1:4])
                )
            return page.locator(sel).nth(i)
        return None

    @staticmethod
    def _score_submit_button(info: dict) -> int:
        score = 0
        hay = f"{info.get('text', '')} {info.get('aria', '')}".lower()
        for kw in ("comment", "reply", "respond", "submit", "post", "publish", "send", "discuss"):
            if kw in hay:
                score += 30
        if info.get("tag") in ("button", "input"):
            score += 5
        if info.get("disabled"):
            score -= 20
        for kw in ("filter", "search", "cancel", "close"):
            if kw in hay:
                score -= 50
        return score

    async def _verify_post(self, page, content: str, ctx: dict) -> PostResult:
        logger.info("GenericPoster: Verifying — waiting for the comment to appear...")
        await page.wait_for_timeout(8000)
        page_text = await page.evaluate("document.body.innerText")
        first_line = content.strip().split("\n")[0][:50]
        if first_line and first_line in page_text:
            logger.info("GenericPoster: Successfully verified post content on the page!")
            return PostResult(success=True, post_url=ctx["url"], platform=self.platform_name)
        still_has_text = False
        textbox = ctx.get("textbox")
        if textbox:
            try:
                text_val = await textbox.evaluate(
                    "el => el.tagName === 'TEXTAREA' || el.tagName === 'INPUT' ? el.value : el.innerText"
                )
                if first_line[:20] in text_val:
                    still_has_text = True
            except Exception:
                pass
        if still_has_text:
            return PostResult(
                success=False,
                error="Draft text is still present in the input box. Submission likely failed due to form validation, CAPTCHA block, or rate limit.",
                platform=self.platform_name,
            )
        logger.info("GenericPoster: Text input is no longer present or has been cleared. Assuming success.")
        return PostResult(success=True, post_url=ctx["url"], platform=self.platform_name)

    # --------------------------------------------------------------- adaptation
    async def _adapt_step(self, page, step: PostingStep, error: str, llm, ctx: dict):
        """Ask the LLM for a corrected step after a failure (up to 2 retries per step)."""
        try:
            simplified = await self._capture_dom(page)
            screenshot_bytes = await page.screenshot()
            prompt = f"""A posting step failed while posting a comment on this page.
Page URL: {ctx['url']}
Failed step: {json.dumps({"action": step.action, "selector": step.selector, "params": step.params}, ensure_ascii=False)}
Error: {error}

Current interactive elements:
{simplified[:6000]}

Examine the screenshot for visual clues. Return ONLY a valid JSON block describing the corrected step:
{{
  "action": "open_drawer|focus_editor|type_content|dispatch_events|submit|verify",
  "selector": "css_selector|none",
  "params": {{}}
}}
If the step cannot be salvaged, return {{"action": "abort"}}."""
            response = await self._ask_llm(llm, prompt, screenshot_bytes=screenshot_bytes)
            data = self._parse_json_response(response)
            if not data:
                return None
            action = data.get("action")
            if action in (None, "abort") or action not in (
                "open_drawer", "focus_editor", "type_content", "dispatch_events", "submit", "verify",
            ):
                return None
            params = data.get("params") or {}
            if action in ("type_content", "verify") and not params:
                params = step.params
            adapted = PostingStep(
                action=action,
                selector=data.get("selector") or step.selector,
                params=params,
                screenshot=step.screenshot,
            )
            logger.info(f"GenericPoster: LLM adapted step → action={adapted.action}, selector={adapted.selector}")
            return adapted
        except Exception as e:
            logger.warning(f"Step adaptation failed: {e}")
            return None

    # --------------------------------------------------------------- setup helpers
    @staticmethod
    def _build_storage_state(cookies: list):
        storage_state = None
        tmp_path = None
        if not cookies:
            return None, None
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
        logger.info(f"GenericPoster: saved {len(storage_data['cookies'])} cookies for cookie injection")
        return tmp_path, tmp_path

    @staticmethod
    async def _solve_captcha_if_present(page, url: str):
        captcha_sitekey = None
        captcha_type = None

        turnstile_el = page.locator(".cf-turnstile, iframe[src*='challenges.cloudflare.com']")
        if await turnstile_el.count() > 0:
            captcha_type = "turnstile"
            for i in range(await turnstile_el.count()):
                el = turnstile_el.nth(i)
                sk = await el.get_attribute("data-sitekey")
                if sk:
                    captcha_sitekey = sk
                    break
                src = await el.get_attribute("src")
                if src:
                    match = re.search(r"/#key=([^&]+)", src)
                    if match:
                        captcha_sitekey = match.group(1)
                        break
            logger.info(f"GenericPoster: Cloudflare Turnstile detected! Sitekey: {captcha_sitekey}")

        if not captcha_sitekey:
            recaptcha_el = page.locator(".g-recaptcha, iframe[src*='google.com/recaptcha']")
            if await recaptcha_el.count() > 0:
                captcha_type = "recaptcha"
                for i in range(await recaptcha_el.count()):
                    el = recaptcha_el.nth(i)
                    sk = await el.get_attribute("data-sitekey")
                    if sk:
                        captcha_sitekey = sk
                        break
                    src = await el.get_attribute("src")
                    if src:
                        match = re.search(r"k=([^&]+)", src)
                        if match:
                            captcha_sitekey = match.group(1)
                            break
                logger.info(f"GenericPoster: reCAPTCHA detected! Sitekey: {captcha_sitekey}")

        if captcha_sitekey and os.getenv("TWOCAPTCHA_API_KEY"):
            logger.info(f"GenericPoster: Solving {captcha_type} with sitekey={captcha_sitekey}")
            if captcha_type == "turnstile":
                captcha_token = await solve_turnstile(captcha_sitekey, url)
            else:
                captcha_token = await solve_recaptcha_v2(captcha_sitekey, url)
            if captcha_token:
                logger.info("GenericPoster: CAPTCHA solved! Injecting solution...")
                await page.evaluate(f"""(token) => {{
                    const inputs = document.querySelectorAll('[name="g-recaptcha-response"], [name="cf-turnstile-response"]');
                    inputs.forEach(el => el.value = token);
                    inputs.forEach(el => el.dispatchEvent(new Event('input', {{bubbles: true}})));
                }}""", captcha_token)
            else:
                logger.warning("GenericPoster: CAPTCHA solving returned no token.")
