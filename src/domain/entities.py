from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Topic:
    name: str
    description: str = ""
    keywords: list[str] = field(default_factory=list)


@dataclass
class Author:
    name: str
    username: str
    website_url: str = ""


@dataclass
class Article:
    title: str
    body_markdown: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    published: bool = False
    canonical_url: str = ""
    series: str = ""
    id: Optional[int] = None
    url: Optional[str] = None
    published_at: Optional[datetime] = None

    @property
    def front_matter(self) -> str:
        lines = ["---"]
        lines.append(f"title: {self.title}")
        lines.append(f"published: {str(self.published).lower()}")
        if self.description:
            lines.append(f"description: {self.description}")
        if self.canonical_url:
            lines.append(f"canonical_url: {self.canonical_url}")
        if self.series:
            lines.append(f"series: {self.series}")
        lines.append("---")
        return "\n".join(lines)

    @property
    def full_markdown(self) -> str:
        return f"{self.front_matter}\n\n{self.body_markdown}"
