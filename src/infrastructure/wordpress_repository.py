import logging
from typing import Optional
from datetime import datetime

import requests
import markdown

from src.domain.entities import Article
from src.domain.interfaces import ArticleRepository

logger = logging.getLogger(__name__)


class WordPressArticleRepository(ArticleRepository):
    BASE_URL = "https://public-api.wordpress.com/wp/v2"

    def __init__(self, access_token: str, site_id: str):
        self._access_token = access_token
        self._site_id = site_id
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        })

    def _resolve_tag_ids(self, tag_names: list[str]) -> list[int]:
        tag_ids = []
        for name in tag_names[:10]:
            resp = self._session.get(
                f"{self.BASE_URL}/sites/{self._site_id}/tags",
                params={"search": name, "per_page": 5},
            )
            if resp.ok:
                for tag in resp.json():
                    if tag.get("name", "").lower() == name.lower():
                        tag_ids.append(tag["id"])
                        break
                else:
                    create_resp = self._session.post(
                        f"{self.BASE_URL}/sites/{self._site_id}/tags",
                        json={"name": name},
                    )
                    if create_resp.ok:
                        tag_ids.append(create_resp.json()["id"])
        return tag_ids

    def create(self, article: Article) -> Article:
        html_content = markdown.markdown(
            article.body_markdown,
            extensions=["fenced_code", "tables", "nl2br"],
        )

        payload = {
            "title": article.title,
            "content": html_content,
            "status": "publish" if article.published else "draft",
        }

        if article.tags:
            tag_ids = self._resolve_tag_ids(article.tags)
            if tag_ids:
                payload["tags"] = tag_ids
        if article.description:
            payload["excerpt"] = article.description

        logger.info(f"Creating WordPress post: {article.title}")
        resp = self._session.post(
            f"{self.BASE_URL}/sites/{self._site_id}/posts",
            json=payload,
        )
        if not resp.ok:
            logger.error(f"API error {resp.status_code}: {resp.text[:1000]}")
        resp.raise_for_status()
        data = resp.json()

        return self._parse_response(data)

    def update(self, article_id: int, article: Article) -> Article:
        html_content = markdown.markdown(
            article.body_markdown,
            extensions=["fenced_code", "tables", "nl2br"],
        )

        payload = {
            "title": article.title,
            "content": html_content,
            "status": "publish" if article.published else "draft",
        }

        if article.tags:
            tag_ids = self._resolve_tag_ids(article.tags)
            if tag_ids:
                payload["tags"] = tag_ids
        if article.description:
            payload["excerpt"] = article.description

        logger.info(f"Updating WordPress post {article_id}: {article.title}")
        resp = self._session.post(
            f"{self.BASE_URL}/sites/{self._site_id}/posts/{article_id}",
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

        return self._parse_response(data)

    def get_my_articles(self) -> list[Article]:
        logger.info("Fetching WordPress articles...")
        articles = []
        page = 1

        while True:
            resp = self._session.get(
                f"{self.BASE_URL}/sites/{self._site_id}/posts",
                params={"page": page, "per_page": 20, "status": "publish,draft,private"},
            )
            resp.raise_for_status()
            data = resp.json()

            if not data:
                break

            for item in data:
                articles.append(self._parse_response(item))

            if len(data) < 20:
                break
            page += 1

        return articles

    def delete(self, article_id: int) -> bool:
        logger.info(f"Deleting WordPress post {article_id}...")
        resp = self._session.post(
            f"{self.BASE_URL}/sites/{self._site_id}/posts/{article_id}",
            json={"status": "trash"},
        )
        if resp.ok:
            resp = self._session.delete(
                f"{self.BASE_URL}/sites/{self._site_id}/posts/{article_id}",
                params={"force": True},
            )
        return resp.ok

    def _parse_response(self, data: dict) -> Article:
        published_at = None
        if data.get("date"):
            try:
                published_at = datetime.fromisoformat(data["date"].replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        tags = []
        if data.get("tag_names"):
            tags = data["tag_names"]

        url = data.get("link", "")

        return Article(
            id=data.get("id"),
            title=data.get("title", {}).get("raw", ""),
            body_markdown=data.get("content", {}).get("raw", ""),
            description=data.get("excerpt", {}).get("raw", ""),
            tags=tags,
            published=data.get("status") == "publish",
            canonical_url=data.get("canonical_url", ""),
            url=url,
            published_at=published_at,
        )
