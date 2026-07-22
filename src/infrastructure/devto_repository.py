import logging
import json
from typing import Optional
from datetime import datetime

import requests

from src.domain.entities import Article
from src.domain.interfaces import ArticleRepository

logger = logging.getLogger(__name__)


def _sanitize_tag(tag: str) -> str:
    return "".join(ch for ch in tag if ch.isalnum()).lower()


class DevtoArticleRepository(ArticleRepository):
    BASE_URL = "https://dev.to/api"

    def __init__(self, api_key: str):
        self._api_key = api_key
        self._session = requests.Session()
        self._session.headers.update({
            "api-key": self._api_key,
            "Accept": "application/vnd.forem.api-v1+json",
            "Content-Type": "application/json",
        })

    def create(self, article: Article) -> Article:
        payload = {
            "article": {
                "title": article.title,
                "body_markdown": article.full_markdown,
                "published": article.published,
            }
        }

        if article.tags:
            sanitized = [_sanitize_tag(t) for t in article.tags[:4]]
            payload["article"]["tags"] = ",".join(sanitized)[:125]
        if article.description:
            payload["article"]["description"] = article.description
        if article.canonical_url:
            payload["article"]["canonical_url"] = article.canonical_url
        if article.series:
            payload["article"]["series"] = article.series

        logger.info(f"Creating article: {article.title}")
        logger.info(f"Payload tags: {payload['article'].get('tags', 'NONE')}")
        resp = self._session.post(f"{self.BASE_URL}/articles", json=payload)
        if not resp.ok:
            logger.error(f"API error {resp.status_code}: {resp.text[:1000]}")
        resp.raise_for_status()
        data = resp.json()

        return self._parse_response(data)

    def update(self, article_id: int, article: Article) -> Article:
        payload = {
            "article": {
                "title": article.title,
                "body_markdown": article.full_markdown,
                "published": article.published,
            }
        }

        if article.tags:
            sanitized = [_sanitize_tag(t) for t in article.tags[:4]]
            payload["article"]["tags"] = ",".join(sanitized)[:125]
        if article.description:
            payload["article"]["description"] = article.description

        logger.info(f"Updating article {article_id}: {article.title}")
        resp = self._session.put(f"{self.BASE_URL}/articles/{article_id}", json=payload)
        resp.raise_for_status()
        data = resp.json()

        return self._parse_response(data)

    def get_my_articles(self) -> list[Article]:
        logger.info("Fetching user articles...")
        resp = self._session.get(f"{self.BASE_URL}/articles/me/all")
        resp.raise_for_status()
        data = resp.json()

        articles = []
        for item in data:
            article = self._parse_response(item)
            articles.append(article)

        return articles

    def delete(self, article_id: int) -> bool:
        logger.info(f"Deleting article {article_id}...")
        resp = self._session.delete(f"{self.BASE_URL}/articles/{article_id}")
        return resp.status_code == 204

    def _parse_response(self, data: dict) -> Article:
        published_at = None
        if data.get("published_at"):
            try:
                published_at = datetime.fromisoformat(data["published_at"].replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        tags = []
        if data.get("tag_list"):
            tags = data["tag_list"]

        return Article(
            id=data.get("id"),
            title=data.get("title", ""),
            body_markdown=data.get("body_markdown", ""),
            description=data.get("description", ""),
            tags=tags,
            published=data.get("published", False),
            canonical_url=data.get("canonical_url", ""),
            url=data.get("url"),
            published_at=published_at,
        )
