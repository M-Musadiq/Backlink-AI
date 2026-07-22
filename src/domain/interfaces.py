from abc import ABC, abstractmethod
from typing import Optional
from src.domain.entities import Article, Topic


class ArticleRepository(ABC):
    @abstractmethod
    def create(self, article: Article) -> Article:
        ...

    @abstractmethod
    def update(self, article_id: int, article: Article) -> Article:
        ...

    @abstractmethod
    def get_my_articles(self) -> list[Article]:
        ...

    @abstractmethod
    def delete(self, article_id: int) -> bool:
        ...


class ContentGenerator(ABC):
    @abstractmethod
    def generate(self, topic: Topic) -> Article:
        ...

    @abstractmethod
    def review(self, article: Article) -> Article:
        ...


class LLMService(ABC):
    @abstractmethod
    def generate(self, prompt: str, system_prompt: Optional[str] = None, temperature: float = 0.7) -> str:
        ...


class Scraper(ABC):
    """Base interface for all scraper types."""

    @abstractmethod
    def can_handle(self, url: str) -> bool:
        """Check if this scraper can handle the given URL."""
        ...

    @abstractmethod
    def scrape(self, url: str) -> "ScrapedContent":
        """Scrape the URL and return cleaned content."""
        ...


class PlatformConfigStore(ABC):
    """Interface for storing/retrieving per-domain scraper configurations."""

    @abstractmethod
    def get(self, domain: str) -> Optional["PlatformConfig"]:
        ...

    @abstractmethod
    def save(self, config: "PlatformConfig") -> None:
        ...

    @abstractmethod
    def get_all(self) -> list["PlatformConfig"]:
        ...
