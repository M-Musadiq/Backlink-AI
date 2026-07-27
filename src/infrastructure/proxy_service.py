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

    def get_proxy_with_session(self, session_id: str, country: str = None) -> Optional[dict]:
        """Get proxy with a session ID for IP rotation via 2Captcha.

        2Captcha supports session_id in the username to get a different IP per session.
        Format: username-session-<session_id>-country-<country>
        """
        proxy_host = os.getenv("PROXY_HOST")
        proxy_port = os.getenv("PROXY_PORT")
        proxy_user = os.getenv("PROXY_USER")
        proxy_pass = os.getenv("PROXY_PASS")
        proxy_country = country or os.getenv("PROXY_COUNTRY", "us")

        if proxy_host and proxy_port:
            server = f"http://{proxy_host}:{proxy_port}"
            result = {"server": server}
            if proxy_user:
                result["username"] = f"{proxy_user}-session-{session_id}-country-{proxy_country}"
            if proxy_pass:
                result["password"] = proxy_pass
            logger.info(f"ProxyService: session proxy {server} session={session_id} country={proxy_country}")
            return result

        return self.get_proxy(proxy_country)

    def _build_proxy_url(self, proxy: dict) -> str:
        """Build proxy URL with auth: http://user:pass@host:port"""
        server = proxy["server"]
        username = proxy.get("username")
        password = proxy.get("password", "")
        if username:
            auth = f"{username}:{password}@"
            return server.replace("http://", f"http://{auth}")
        return server

    def verify_proxy(self, proxy: dict, test_url: str = "https://www.reddit.com") -> bool:
        """Test if proxy can reach the target site. Returns True if reachable."""
        try:
            proxy_url = self._build_proxy_url(proxy)
            resp = httpx.get(test_url, proxy=proxy_url, timeout=15, follow_redirects=True)
            logger.info(f"ProxyService: verify status={resp.status_code} url={resp.url}")
            return resp.status_code < 500
        except Exception as e:
            logger.warning(f"ProxyService: verify failed: {e}")
            return False

    def get_outbound_ip_via_proxy(self, proxy: dict) -> Optional[str]:
        """Get the outgoing IP address through the proxy."""
        try:
            proxy_url = self._build_proxy_url(proxy)
            resp = httpx.get("https://api.ipify.org?format=json", proxy=proxy_url, timeout=10)
            ip = resp.json().get("ip")
            logger.info(f"ProxyService: outbound IP via proxy is {ip}")
            return ip
        except Exception as e:
            logger.warning(f"ProxyService: failed to get IP via proxy: {e}")
            return None

    def get_playwright_proxy(self, country: str = "us") -> Optional[dict]:
        """Return Playwright proxy dict or None."""
        return self.get_proxy(country)


proxy_service = ProxyService()
