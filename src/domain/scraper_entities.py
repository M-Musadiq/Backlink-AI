from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class ScrapedContent:
    """Represents the cleaned, extracted content from a scraped URL."""

    url: str
    domain: str
    title: str
    body: str  # Clean markdown text
    author: str = ""
    published_at: str = ""
    scraper_type: str = ""  # Which scraper succeeded: api, static, playwright, llm
    scraped_at: datetime = field(default_factory=datetime.utcnow)
    metadata: dict = field(default_factory=dict)  # Extra fields (tags, votes, etc.)

    @property
    def is_empty(self) -> bool:
        return not self.body or len(self.body.strip()) < 50

    @property
    def preview(self) -> str:
        text = self.body[:300].replace("\n", " ").strip()
        return f"{text}..." if len(self.body) > 300 else text


@dataclass
class PlatformConfig:
    """Per-domain configuration for scraping and posting."""

    domain: str
    scraper_type: str = "static"  # api, static, playwright, llm
    requires_auth: bool = False
    post_method: str = "not_supported"  # api, form_submit, playwright, not_supported
    rate_limit_seconds: int = 5
    guidelines_url: str = ""
    last_updated: datetime = field(default_factory=datetime.utcnow)
