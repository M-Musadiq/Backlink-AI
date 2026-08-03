"""2Captcha proxy helper for bypassing bot detection."""
import os
import httpx

TWOCAPTCHA_API_KEY = os.getenv("TWOCAPTCHA_API_KEY", "")


async def get_proxy() -> dict | None:
    """Fetch a fresh proxy from 2Captcha. Returns proxy dict for Playwright or None."""
    if not TWOCAPTCHA_API_KEY or TWOCAPTCHA_API_KEY.startswith("PASTE"):
        return None

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # Get a fresh proxy from 2Captcha
            resp = await client.post(
                "https://api.2captcha.com/api/proxy.php",
                data={
                    "api_key": TWOCAPTCHA_API_KEY,
                    "type": "https",
                    "count": 1,
                    "protocol": "http",
                },
            )
            text = resp.text.strip()
            if text.startswith("OK:"):
                proxy_addr = text[3:]  # e.g. "1.2.3.4:8080"
                return {
                    "server": f"http://{proxy_addr}",
                    "username": TWOCAPTCHA_API_KEY,
                    "password": "2captcha",
                }
            else:
                print(f"2Captcha proxy error: {text}")
                return None
    except Exception as e:
        print(f"2Captcha proxy fetch failed: {e}")
        return None
