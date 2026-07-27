import os
import json
import logging
import httpx
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_CACHE_PATH = Path("/tmp/proxy_cache.json") if os.name != "nt" else Path("data/proxy_cache.json")


class ProxyService:
    """Provides proxy settings for browser-use and Playwright via 2Captcha residential proxy."""

    def __init__(self):
        self._cache = None
        self._load_cache()

    def _load_cache(self):
        try:
            if _CACHE_PATH.exists():
                data = json.loads(_CACHE_PATH.read_text())
                if data.get("ip"):
                    self._cache = data
                    logger.info(f"ProxyService: loaded cached proxy {data['ip']}")
        except Exception:
            pass

    def _save_cache(self):
        try:
            _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            _CACHE_PATH.write_text(json.dumps(self._cache))
        except Exception:
            pass

    def _get_outbound_ip(self) -> Optional[str]:
        try:
            resp = httpx.get("https://api.ipify.org?format=json", timeout=5)
            return resp.json().get("ip")
        except Exception as e:
            logger.warning(f"ProxyService: failed to get outbound IP: {e}")
            return None

    def _generate_connections(self, api_key: str, ip: str, country: str = "us") -> Optional[list]:
        try:
            resp = httpx.get(
                "https://api.2captcha.com/proxy/generate_white_list_connections",
                params={
                    "key": api_key,
                    "country": country,
                    "protocol": "http",
                    "connection_count": 5,
                    "ip": ip,
                },
                timeout=10,
            )
            data = resp.json()
            if data.get("status") == "OK":
                return data.get("data", [])
            else:
                logger.warning(f"ProxyService: API error: {data}")
                return None
        except Exception as e:
            logger.warning(f"ProxyService: failed to generate connections: {e}")
            return None

    def get_proxy(self, country: str = "us") -> Optional[dict]:
        """Return proxy dict for browser-use (ProxySettings) or Playwright.

        Format: {"server": "http://ip:port"} — no auth needed for whitelisted connections.
        Returns None if no proxy is available.
        """
        from src.config import TWOCAPTCHA_API_KEY

        # 1. Check env var override (admin-configured proxy)
        proxy_host = os.getenv("PROXY_HOST")
        proxy_port = os.getenv("PROXY_PORT")
        proxy_user = os.getenv("PROXY_USER")
        proxy_pass = os.getenv("PROXY_PASS")

        if proxy_host and proxy_port:
            server = f"http://{proxy_host}:{proxy_port}"
            result = {"server": server}
            if proxy_user:
                result["username"] = proxy_user
            if proxy_pass:
                result["password"] = proxy_pass
            logger.info(f"ProxyService: using env var proxy {server}")
            return result

        # 2. Check cache (valid for this Cloud Run instance lifetime)
        if self._cache and self._cache.get("ip"):
            cached_ip = self._cache["ip"]
            logger.info(f"ProxyService: using cached proxy {cached_ip}")
            return {"server": f"http://{cached_ip}"}

        # 3. Fetch fresh from 2Captcha API
        if not TWOCAPTCHA_API_KEY:
            logger.info("ProxyService: no API key, no proxy available")
            return None

        outbound_ip = self._get_outbound_ip()
        if not outbound_ip:
            return None

        logger.info(f"ProxyService: outbound IP is {outbound_ip} — must be whitelisted at https://2captcha.com/proxy/ip-whitelist")

        connections = self._generate_connections(TWOCAPTCHA_API_KEY, outbound_ip, country)
        if connections:
            proxy_ip = connections[0]
            self._cache = {"ip": proxy_ip, "all": connections}
            self._save_cache()
            logger.info(f"ProxyService: got proxy {proxy_ip} from 2Captcha")
            return {"server": f"http://{proxy_ip}"}

        logger.info("ProxyService: could not get proxy, proceeding without")
        return None

    def get_browser_use_proxy_settings(self, country: str = "us"):
        """Return browser-use ProxySettings object or None."""
        proxy = self.get_proxy(country)
        if not proxy:
            return None
        try:
            from browser_use.browser.profile import ProxySettings
            return ProxySettings(
                server=proxy["server"],
                username=proxy.get("username"),
                password=proxy.get("password"),
            )
        except Exception as e:
            logger.warning(f"ProxyService: failed to create ProxySettings: {e}")
            return None

    def get_playwright_proxy(self, country: str = "us") -> Optional[dict]:
        """Return Playwright proxy dict or None."""
        return self.get_proxy(country)


proxy_service = ProxyService()
