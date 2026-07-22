"""Solve CAPTCHAs using 2Captcha - Turnstile and reCAPTCHA."""
import os
import httpx

TWOCAPTCHA_API_KEY = os.getenv("TWOCAPTCHA_API_KEY", "")
API_BASE = "https://api.2captcha.com"


async def solve_turnstile(sitekey: str, page_url: str) -> str | None:
    """Solve a Cloudflare Turnstile CAPTCHA. Returns the token or None on failure."""
    if not TWOCAPTCHA_API_KEY or TWOCAPTCHA_API_KEY.startswith("PASTE"):
        return None

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{API_BASE}/createTask",
                json={
                    "clientKey": TWOCAPTCHA_API_KEY,
                    "task": {
                        "type": "TurnstileTaskProxyless",
                        "websiteURL": page_url,
                        "websiteKey": sitekey,
                    },
                },
            )
            data = resp.json()
            if data.get("errorId", 0) != 0:
                print(f"2Captcha Turnstile error: {data.get('errorDescription', data)}")
                return None

            task_id = data["taskId"]
            print(f"2Captcha Turnstile task created: {task_id}")

            for attempt in range(45):
                await _async_sleep(2)
                resp = await client.post(
                    f"{API_BASE}/getTaskResult",
                    json={"clientKey": TWOCAPTCHA_API_KEY, "taskId": task_id},
                )
                result = resp.json()

                if result.get("status") == "ready":
                    token = result["solution"]["token"]
                    print(f"2Captcha Turnstile solved in {attempt * 2}s")
                    return token

                if result.get("errorId", 0) != 0:
                    print(f"2Captcha Turnstile solve error: {result.get('errorDescription')}")
                    return None

            print("2Captcha Turnstile solve timeout")
            return None
    except Exception as e:
        print(f"2Captcha Turnstile error: {e}")
        return None


async def solve_recaptcha_v2(sitekey: str, page_url: str) -> str | None:
    """Solve a reCAPTCHA v2 interactive challenge. Returns the g-recaptcha-response token or None."""
    if not TWOCAPTCHA_API_KEY or TWOCAPTCHA_API_KEY.startswith("PASTE"):
        return None

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{API_BASE}/createTask",
                json={
                    "clientKey": TWOCAPTCHA_API_KEY,
                    "task": {
                        "type": "RecaptchaV2TaskProxyless",
                        "websiteURL": page_url,
                        "websiteKey": sitekey,
                    },
                },
            )
            data = resp.json()
            if data.get("errorId", 0) != 0:
                print(f"2Captcha reCAPTCHA v2 error: {data.get('errorDescription', data)}")
                return None

            task_id = data["taskId"]
            print(f"2Captcha reCAPTCHA v2 task created: {task_id}")

            for attempt in range(60):
                await _async_sleep(2)
                resp = await client.post(
                    f"{API_BASE}/getTaskResult",
                    json={"clientKey": TWOCAPTCHA_API_KEY, "taskId": task_id},
                )
                result = resp.json()

                if result.get("status") == "ready":
                    token = result["solution"]["gRecaptchaResponse"]
                    print(f"2Captcha reCAPTCHA v2 solved in {attempt * 2}s")
                    return token

                if result.get("errorId", 0) != 0:
                    print(f"2Captcha reCAPTCHA v2 solve error: {result.get('errorDescription')}")
                    return None

            print("2Captcha reCAPTCHA v2 solve timeout")
            return None
    except Exception as e:
        print(f"2Captcha reCAPTCHA v2 error: {e}")
        return None


async def solve_recaptcha_v3_enterprise(sitekey: str, page_url: str, action: str = "", min_score: float = 0.9) -> str | None:
    """Solve reCAPTCHA v3 Enterprise (score-based). Returns the token or None."""
    if not TWOCAPTCHA_API_KEY or TWOCAPTCHA_API_KEY.startswith("PASTE"):
        return None

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{API_BASE}/createTask",
                json={
                    "clientKey": TWOCAPTCHA_API_KEY,
                    "task": {
                        "type": "RecaptchaV3TaskProxyless",
                        "websiteURL": page_url,
                        "websiteKey": sitekey,
                        "minScore": min_score,
                        "pageAction": action,
                        "isEnterprise": True,
                    },
                },
            )
            data = resp.json()
            if data.get("errorId", 0) != 0:
                print(f"2Captcha reCAPTCHA v3 Enterprise error: {data.get('errorDescription', data)}")
                return None

            task_id = data["taskId"]
            print(f"2Captcha reCAPTCHA v3 Enterprise task created: {task_id}")

            for attempt in range(60):
                await _async_sleep(2)
                resp = await client.post(
                    f"{API_BASE}/getTaskResult",
                    json={"clientKey": TWOCAPTCHA_API_KEY, "taskId": task_id},
                )
                result = resp.json()

                if result.get("status") == "ready":
                    token = result["solution"]["gRecaptchaResponse"]
                    print(f"2Captcha reCAPTCHA v3 Enterprise solved in {attempt * 2}s")
                    return token

                if result.get("errorId", 0) != 0:
                    print(f"2Captcha reCAPTCHA v3 Enterprise error: {result.get('errorDescription')}")
                    return None

            print("2Captcha reCAPTCHA v3 Enterprise solve timeout")
            return None
    except Exception as e:
        print(f"2Captcha reCAPTCHA v3 Enterprise error: {e}")
        return None


async def _async_sleep(seconds: float):
    import asyncio
    await asyncio.sleep(seconds)
