"""JSON-file-based Platform Config Store.

Stores per-domain scraper configurations in a local JSON file.
This is a lightweight stand-in until Phase 1 (Postgres) is built.
"""

import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from src.domain.interfaces import PlatformConfigStore
from src.domain.scraper_entities import PlatformConfig

logger = logging.getLogger(__name__)


class JsonPlatformConfigStore(PlatformConfigStore):
    """Reads/writes platform configs from a JSON file."""

    def __init__(self, filepath: str = "data/platform_configs.json"):
        self._filepath = Path(filepath)
        self._ensure_file()

    def _ensure_file(self) -> None:
        """Create the file and parent dirs if they don't exist."""
        self._filepath.parent.mkdir(parents=True, exist_ok=True)
        if not self._filepath.exists():
            self._filepath.write_text("{}", encoding="utf-8")
            logger.info(f"Created config store: {self._filepath}")

    def _load(self) -> dict:
        """Load all configs from the JSON file."""
        try:
            text = self._filepath.read_text(encoding="utf-8")
            return json.loads(text) if text.strip() else {}
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

    def _save_all(self, data: dict) -> None:
        """Write all configs back to the JSON file."""
        self._filepath.write_text(
            json.dumps(data, indent=2, default=str),
            encoding="utf-8",
        )

    def get(self, domain: str) -> Optional[PlatformConfig]:
        data = self._load()
        entry = data.get(domain)
        if not entry:
            return None

        return PlatformConfig(
            domain=domain,
            scraper_type=entry.get("scraper_type", "static"),
            requires_auth=entry.get("requires_auth", False),
            post_method=entry.get("post_method", "not_supported"),
            rate_limit_seconds=entry.get("rate_limit_seconds", 5),
            guidelines_url=entry.get("guidelines_url", ""),
            last_updated=datetime.fromisoformat(entry["last_updated"])
            if entry.get("last_updated")
            else datetime.now(timezone.utc),
        )

    def save(self, config: PlatformConfig) -> None:
        data = self._load()
        data[config.domain] = {
            "scraper_type": config.scraper_type,
            "requires_auth": config.requires_auth,
            "post_method": config.post_method,
            "rate_limit_seconds": config.rate_limit_seconds,
            "guidelines_url": config.guidelines_url,
            "last_updated": config.last_updated.isoformat()
            if config.last_updated
            else datetime.now(timezone.utc).isoformat(),
        }
        self._save_all(data)
        logger.debug(f"Saved config for {config.domain}")

    def get_all(self) -> list[PlatformConfig]:
        data = self._load()
        configs = []
        for domain, entry in data.items():
            configs.append(
                PlatformConfig(
                    domain=domain,
                    scraper_type=entry.get("scraper_type", "static"),
                    requires_auth=entry.get("requires_auth", False),
                    post_method=entry.get("post_method", "not_supported"),
                    rate_limit_seconds=entry.get("rate_limit_seconds", 5),
                    guidelines_url=entry.get("guidelines_url", ""),
                    last_updated=datetime.fromisoformat(entry["last_updated"])
                    if entry.get("last_updated")
                    else datetime.now(timezone.utc),
                )
            )
        return configs
