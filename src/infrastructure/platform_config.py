"""Platform configuration service - single source of truth for all platforms."""
import json
import os
import shutil
import logging
from typing import List, Dict, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "platform_configs.json")
_CONTAINER_CONFIG = "/tmp/platform_configs.json"

_DEFAULT_CONFIG = {
    "platforms": {
        "reddit.com": {"enabled": True, "search_enabled": False, "post_enabled": True, "scraper_type": "api", "requires_auth": True, "post_method": "api", "rate_limit_seconds": 10, "guidelines_url": "", "serp_site_filter": "site:reddit.com"},
        "news.ycombinator.com": {"enabled": True, "search_enabled": True, "post_enabled": False, "scraper_type": "api", "requires_auth": True, "post_method": "form_submit", "rate_limit_seconds": 30, "guidelines_url": "", "serp_site_filter": "site:news.ycombinator.com", "time_filter": "qdr:m"},
    }
}


class PlatformConfigService:
    """Reads and writes platform configs from data/platform_configs.json."""

    def __init__(self, config_path: str = None):
        self._path = config_path or CONFIG_PATH
        self._container_path = _CONTAINER_CONFIG
        self._ensure_config()

    def _ensure_config(self):
        """Copy bundled config to /tmp on first access (Cloud Run read-only FS)."""
        if os.path.exists(self._container_path):
            return
        if os.path.exists(self._path):
            shutil.copy2(self._path, self._container_path)
            logger.info("Copied platform_configs.json to /tmp")
        else:
            with open(self._container_path, "w") as f:
                json.dump(_DEFAULT_CONFIG, f, indent=2)
            logger.warning("platform_configs.json not found, using defaults in /tmp")

    def _load(self) -> Dict:
        path = self._container_path if os.path.exists(self._container_path) else self._path
        with open(path, "r") as f:
            return json.load(f)

    def _save(self, data: Dict):
        with open(self._container_path, "w") as f:
            json.dump(data, f, indent=2)

    def get_all(self) -> Dict[str, Dict]:
        """Return all platform configs."""
        return self._load().get("platforms", {})

    def get(self, domain: str) -> Optional[Dict]:
        """Get config for a single platform."""
        return self._load().get("platforms", {}).get(domain)

    def get_search_platforms(self) -> List[str]:
        """Return list of serp_site_filter values for platforms with search_enabled=true."""
        platforms = self._load().get("platforms", {})
        return [
            cfg["serp_site_filter"]
            for cfg in platforms.values()
            if cfg.get("search_enabled", True) and cfg.get("enabled", True)
        ]

    def get_search_platforms_with_time_filter(self) -> List[Dict]:
        """Return list of {site_filter, time_filter} for platforms with search_enabled=true."""
        platforms = self._load().get("platforms", {})
        return [
            {
                "site_filter": cfg["serp_site_filter"],
                "time_filter": cfg.get("time_filter", ""),
            }
            for cfg in platforms.values()
            if cfg.get("search_enabled", True) and cfg.get("enabled", True)
        ]

    def get_post_enabled_domains(self) -> List[str]:
        """Return list of domains where posting is allowed."""
        platforms = self._load().get("platforms", {})
        return [
            domain for domain, cfg in platforms.items()
            if cfg.get("post_enabled", True) and cfg.get("enabled", True)
        ]

    def is_post_enabled(self, domain: str) -> bool:
        """Check if posting is enabled for a domain."""
        cfg = self.get(domain)
        if not cfg:
            return False
        return cfg.get("post_enabled", True) and cfg.get("enabled", True)

    def toggle_search(self, domain: str, enabled: bool) -> bool:
        """Toggle search_enabled for a platform."""
        data = self._load()
        platforms = data.get("platforms", {})
        if domain not in platforms:
            return False
        platforms[domain]["search_enabled"] = enabled
        platforms[domain]["last_updated"] = datetime.now(timezone.utc).isoformat()
        self._save(data)
        return True

    def toggle_post(self, domain: str, enabled: bool) -> bool:
        """Toggle post_enabled for a platform."""
        data = self._load()
        platforms = data.get("platforms", {})
        if domain not in platforms:
            return False
        platforms[domain]["post_enabled"] = enabled
        platforms[domain]["last_updated"] = datetime.now(timezone.utc).isoformat()
        self._save(data)
        return True

    def toggle_enabled(self, domain: str, enabled: bool) -> bool:
        """Toggle enabled for a platform."""
        data = self._load()
        platforms = data.get("platforms", {})
        if domain not in platforms:
            return False
        platforms[domain]["enabled"] = enabled
        platforms[domain]["last_updated"] = datetime.now(timezone.utc).isoformat()
        self._save(data)
        return True

    def add_platform(self, domain: str, config: Dict) -> bool:
        """Add a new platform."""
        data = self._load()
        platforms = data.get("platforms", {})
        if domain in platforms:
            return False
        defaults = {
            "enabled": True,
            "search_enabled": True,
            "post_enabled": True,
            "scraper_type": "static",
            "requires_auth": False,
            "post_method": "not_supported",
            "rate_limit_seconds": 5,
            "guidelines_url": "",
            "serp_site_filter": f"site:{domain}",
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
        defaults.update(config)
        platforms[domain] = defaults
        data["platforms"] = platforms
        self._save(data)
        return True

    def remove_platform(self, domain: str) -> bool:
        """Remove a platform."""
        data = self._load()
        platforms = data.get("platforms", {})
        if domain not in platforms:
            return False
        del platforms[domain]
        data["platforms"] = platforms
        self._save(data)
        return True
