import logging
from typing import Optional
from src.domain.entities import Topic, Article
from src.domain.interfaces import ArticleRepository, ContentGenerator

logger = logging.getLogger(__name__)


class GenerateAndPublishUseCase:
    def __init__(self, content_generator: ContentGenerator, article_repository: ArticleRepository):
        self._content_generator = content_generator
        self._article_repository = article_repository

    def execute(
        self,
        topic: Topic,
        publish: bool = False,
        dry_run: bool = False,
    ) -> Article:
        logger.info(f"Generating article for topic: {topic.name}")

        article = self._content_generator.generate(topic)
        logger.info(f"Generated article: {article.title}")

        article.published = publish

        if dry_run:
            logger.info("Dry run mode — article not published.")
            return article

        created = self._article_repository.create(article)
        logger.info(f"Article published to dev.to: {created.url}")
        return created

    def generate_and_review(
        self,
        topic: Topic,
        publish: bool = False,
    ) -> Article:
        logger.info(f"Generating and reviewing article for topic: {topic.name}")

        article = self._content_generator.generate(topic)
        logger.info(f"Initial draft: {article.title}")

        article = self._content_generator.review(article)
        logger.info(f"Reviewed draft: {article.title}")

        article.published = publish

        if publish:
            created = self._article_repository.create(article)
            logger.info(f"Published to dev.to: {created.url}")
            return created

        return article
