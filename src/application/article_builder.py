from typing import Optional
from src.domain.entities import Article


class ArticleBuilder:
    def __init__(self):
        self._title = ""
        self._body_markdown = ""
        self._description = ""
        self._tags: list[str] = []
        self._published = False
        self._canonical_url = ""
        self._series = ""

    def with_title(self, title: str) -> "ArticleBuilder":
        self._title = title
        return self

    def with_body(self, body: str) -> "ArticleBuilder":
        self._body_markdown = body
        return self

    def with_description(self, description: str) -> "ArticleBuilder":
        self._description = description
        return self

    def with_tags(self, tags: list[str]) -> "ArticleBuilder":
        self._tags = tags
        return self

    def as_published(self, published: bool = True) -> "ArticleBuilder":
        self._published = published
        return self

    def with_canonical_url(self, url: str) -> "ArticleBuilder":
        self._canonical_url = url
        return self

    def with_series(self, series: str) -> "ArticleBuilder":
        self._series = series
        return self

    def build(self) -> Article:
        return Article(
            title=self._title,
            body_markdown=self._body_markdown,
            description=self._description,
            tags=self._tags,
            published=self._published,
            canonical_url=self._canonical_url,
            series=self._series,
        )

    def reset(self) -> "ArticleBuilder":
        self.__init__()
        return self
