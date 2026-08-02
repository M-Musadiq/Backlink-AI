"""Site profile dataclass + disk cache for the 3-phase (Scout → Plan → Execute) generic poster."""
import json
import logging
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

CACHE_ROOT = os.path.join(os.path.expanduser("~"), ".backlink_site_profiles")
CACHE_TTL_DAYS = 7

EDITOR_TYPES = ("plain_textarea", "contenteditable", "quill", "prosemirror", "markdown", "unknown")
URL_STRATEGIES = ("type_raw", "toolbar_link", "markdown_syntax", "paste_and_enter", "not_supported")
SUBMIT_METHODS = ("click", "ctrl_enter", "tab_enter")

EDITOR_PROMPTS = {
    "plain_textarea": "Plain <textarea>/<input>. Type content directly; URLs are typed as plain text.",
    "contenteditable": "contenteditable div (Medium-style). Click to focus and type; URLs are typically plain text.",
    "quill": "Quill rich-text editor. Type via keyboard; URLs should use the toolbar link button or Ctrl+K.",
    "prosemirror": "ProseMirror rich-text editor. Type via keyboard; URLs use the toolbar link button or Ctrl+K.",
    "markdown": "Markdown editor. Type markdown directly; URLs are wrapped as [anchor](url).",
    "unknown": "Unknown editor — generic typing with runtime adaptation on failure.",
}


@dataclass
class SiteProfile:
    domain: str
    editor_type: str = "unknown"
    url_strategy: str = "type_raw"
    drawer_needed: bool = False
    drawer_selector: str = "none"
    textbox_selector: str = "not_found"
    submit_selector: str = "not_found"
    submit_method: str = "click"
    login_detected: bool = False
    notes: str = ""
    created_at: str = ""

    def __post_init__(self):
        if self.editor_type not in EDITOR_TYPES:
            self.editor_type = "unknown"
        if self.url_strategy not in URL_STRATEGIES:
            self.url_strategy = "type_raw"
        if self.submit_method not in SUBMIT_METHODS:
            self.submit_method = "click"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SiteProfile":
        defaults = {f.name: f.default for f in cls.__dataclass_fields__.values()}
        payload = {**defaults, **{k: v for k, v in data.items() if k in defaults}}
        return cls(**payload)


class SiteProfileCache:
    """Disk-based SiteProfile cache: ~/.backlink_site_profiles/<domain>.json, expires after 7 days."""

    def __init__(self, root: str = CACHE_ROOT, ttl_days: int = CACHE_TTL_DAYS):
        self._root = Path(root)
        self._ttl = timedelta(days=ttl_days)

    def _path(self, domain: str) -> Path:
        safe = re.sub(r"[^a-z0-9.-]", "_", domain.lower())
        return self._root / f"{safe}.json"

    def load(self, domain: str):
        path = self._path(domain)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            profile = SiteProfile.from_dict(data)
            if not profile.created_at:
                return None
            created = datetime.fromisoformat(profile.created_at)
            if created.tzinfo is None:
                created = created.replace(tzinfo=datetime.now().astimezone().tzinfo)
            if datetime.now(created.tzinfo) - created > self._ttl:
                logger.info(f"SiteProfile for {domain} expired, will re-scout")
                return None
            return profile
        except Exception as e:
            logger.warning(f"Failed to load site profile for {domain}: {e}")
            return None

    def save(self, profile: SiteProfile):
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            profile.created_at = datetime.now().astimezone().isoformat()
            self._path(profile.domain).write_text(
                json.dumps(profile.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info(f"Saved site profile for {profile.domain}")
        except Exception as e:
            logger.warning(f"Failed to save site profile: {e}")

    def clear(self, domain: str = None):
        if domain:
            path = self._path(domain)
            if path.exists():
                path.unlink()
                logger.info(f"Cleared site profile for {domain}")
        elif self._root.exists():
            for f in self._root.iterdir():
                if f.is_file() and f.suffix == ".json":
                    f.unlink()
            logger.info(f"Cleared all site profiles under {self._root}")
