"""Platform configuration service - single source of truth for all platforms."""
import json
import os
import logging
from typing import List, Dict, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "platform_configs.json")


class PlatformConfigService:
    """Reads and writes platform configs from data/platform_configs.json."""

    def __init__(self, config_path: str = None):
        self._path = config_path or CONFIG_PATH

    def _load(self) -> Dict:
        with open(self._path, "r") as f:
            return json.load(f)

    def _save(self, data: Dict):
        with open(self._path, "w") as f:
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
