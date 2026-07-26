"""Medium platform poster - browser-use + 2Captcha reCAPTCHA v3 Enterprise solving."""
import json
import logging
import asyncio
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
        from browser_use import Agent, Browser, BrowserProfile
        from browser_use.llm.google.chat import ChatGoogle
        import src.config as config

        llm = ChatGoogle(
            model="gemini-3.5-flash",
            api_key=config.GEMINI_API_KEY,
            temperature=0.1,
        )

        # Save cookies to storage_state
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

        import sys
        browser_kwargs = {
            "headless": sys.platform != "win32",
            "disable_security": True,
        }
        if storage_state:
            browser_kwargs["storage_state"] = storage_state
        else:
            browser_kwargs["user_data_dir"] = None

        browser_profile = BrowserProfile(**browser_kwargs)
        browser = Browser(browser_profile=browser_profile)

        # Build the injection script that runs BEFORE page load
        inject_script = ""
        if recaptcha_token:
            # Escape token for JS
            safe_token = json.dumps(recaptcha_token)
            inject_script = f"""
Before navigating to the page, inject this script via evaluate:

(function() {{
  var token = {safe_token};

  // 1. Override grecaptcha.enterprise.execute to return our token
  if (window.grecaptcha && window.grecaptcha.enterprise) {{
    window.grecaptcha.enterprise.execute = function() {{
      return Promise.resolve(token);
    }};
  }}

  // 2. Intercept fetch to inject token into requests
  var origFetch = window.fetch;
  window.fetch = function(url, opts) {{
    if (opts && opts.body) {{
      try {{
        var body = opts.body;
        if (typeof body === 'string' && body.indexOf('recaptcha') !== -1) {{
          body = body.replace(/g-recaptcha-response=[^&]*/, 'g-recaptcha-response=' + encodeURIComponent(token));
          opts.body = body;
        }}
      }} catch(e) {{}}
    }}
    return origFetch.call(this, url, opts);
  }};

  // 3. Intercept XMLHttpRequest
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

  return 'interceptors_installed';
}})()
"""

        task = f"""Go to this URL: {url}

Your task is to post this comment on the page:

---
{content}
---

IMPORTANT: Before doing anything else, inject the reCAPTCHA interceptor by running this evaluate:

(function() {{
  var token = '{recaptcha_token if recaptcha_token else ""}';
  if (window.grecaptcha && window.grecaptcha.enterprise) {{
    window.grecaptcha.enterprise.execute = function() {{
      return Promise.resolve(token);
    }};
  }}
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
  return 'interceptors_installed';
}})()

Steps:
1. If you see a login page, report NOT_LOGGED_IN
2. Scroll down to find the Responses section
3. Click "Responses" or "Respond" to open the comment editor
4. Find the contenteditable textbox and click on it
5. Type the comment text exactly as shown above
6. Click the "Respond" button to submit
7. Wait 5 seconds and check if the comment was posted
8. Report POST_SUCCESS if comment appeared, or POST_FAILED with reason

CRITICAL: Your final message MUST start with exactly one of these markers:
- POST_SUCCESS — comment was confirmed posted
- POST_FAILED — comment was NOT posted (explain why)
- NOT_LOGGED_IN — not logged in

Important:
- If login page appears, report NOT_LOGGED_IN immediately
- On Medium the response editor is a contenteditable div
- You may need to scroll down to see the Responses section
- The Respond button may be disabled until you type in the textbox
"""

        try:
            agent = Agent(
                task=task,
                llm=llm,
                browser=browser,
            )

            result = await agent.run(max_steps=30)
            final_result = result.final_result() if hasattr(result, 'final_result') else str(result)
            logger.info(f"Medium browser-use result: {final_result}")

            if final_result and "POST_SUCCESS" in str(final_result).upper():
                return PostResult(success=True, post_url=url, platform=self.platform_name)

            if final_result and ("NOT_LOGGED_IN" in str(final_result).upper() or "POST_FAILED" in str(final_result).upper()):
                return PostResult(success=False, error=str(final_result), platform=self.platform_name)

            # Fallback: treat unknown as failure
            return PostResult(success=False, error=str(final_result) if final_result else "Unknown result from agent", platform=self.platform_name)

        except Exception as e:
            logger.error(f"Medium posting failed: {e}")
            return PostResult(success=False, error=str(e), platform=self.platform_name)
        finally:
            await browser.close()
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
