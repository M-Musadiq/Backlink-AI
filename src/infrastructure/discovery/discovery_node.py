"""Discovery Node - merge SERP + RSS sources, dedup, populate tracked_urls."""
import logging
import os
from typing import List, Dict, Optional
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from src.infrastructure.discovery.serp_client import SERPClient
from src.infrastructure.discovery.rss_discovery import RSSDiscovery
from src.infrastructure.discovery.dedup import Deduplicator, extract_domain
from src.infrastructure.repositories.tracked_url_repo import TrackedURLRepository
from src.infrastructure.models import TrackedURL

logger = logging.getLogger(__name__)


class DiscoveryNode:
    """
    Orchestrates URL discovery from multiple sources.

    Flow:
    1. Search SERP (Serper.dev if API key set, otherwise DuckDuckGo)
    2. Discover RSS feeds from target platforms
    3. Merge + normalize results
    4. Deduplicate against DB
    5. Insert new URLs into tracked_urls
    """

    def __init__(self, session: Session):
        self._session = session
        self._serp = SERPClient(serper_api_key=os.getenv("SERPER_API_KEY"))
        self._rss = RSSDiscovery()
        self._tracked_repo = TrackedURLRepository(session)
        self._dedup = Deduplicator(tracked_url_repo=self._tracked_repo)

    def discover(
        self,
        keywords: List[str],
        platforms: List[str] = None,
        num_per_platform: int = 10,
        rss_feeds: List[str] = None,
    ) -> Dict:
        """
        Run full discovery pipeline.

        Args:
            keywords: Search keywords
            platforms: Site filters for SERP (e.g., ["site:reddit.com"])
            num_per_platform: Results per platform from SERP
            rss_feeds: Direct RSS feed URLs to parse

        Returns:
            Dict with stats: {new_count, skipped_count, errors}
        """
        all_results = []

        # Step 1: SERP discovery
        logger.info(f"Discovery starting with {len(keywords)} keywords: {keywords}")
        for i, keyword in enumerate(keywords, 1):
            logger.info(f"[{i}/{len(keywords)}] Searching SERP for: {keyword}")
            serp_results = self._serp.search_platforms(
                query=keyword,
                platforms=platforms,
                num_per_platform=num_per_platform,
            )
            logger.info(f"[{i}/{len(keywords)}] Got {len(serp_results)} results for: {keyword}")
            all_results.extend(serp_results)

        # Step 2: RSS discovery
        if rss_feeds:
            for feed_url in rss_feeds:
                logger.info(f"Parsing RSS feed: {feed_url}")
                rss_results = self._rss.parse_feed(feed_url)
                all_results.extend(rss_results)

        # Step 3: Normalize URLs
        for result in all_results:
            if result.get("url"):
                result["domain"] = extract_domain(result["url"])

        # Step 4: Deduplicate within results
        unique_results, internal_dups = self._dedup.deduplicate_results(all_results)
        logger.info(f"After internal dedup: {len(unique_results)} unique ({internal_dups} duplicates)")

        # Step 5: Deduplicate against DB
        new_results, existing_dups = self._dedup.deduplicate_with_db(unique_results)
        logger.info(f"After DB dedup: {len(new_results)} new URLs ({existing_dups} already tracked)")

        # Step 6: Insert new URLs
        inserted = 0
        errors = 0
        inserted_entities = []
        for result in new_results:
            try:
                url = result.get("url", "")
                domain = result.get("domain", extract_domain(url))
                title = result.get("title", "")

                entity = TrackedURL(
                    url=url,
                    domain=domain,
                    title=title,
                    source="serper" if "snippet" in result else "rss",
                    status="discovered",
                    discovered_at=datetime.now(timezone.utc),
                )
                self._tracked_repo.add(entity)
                inserted += 1
                inserted_entities.append(entity)
            except Exception as e:
                errors += 1
                logger.error(f"Failed to insert {result.get('url')}: {e}")

        stats = {
            "total_found": len(all_results),
            "after_internal_dedup": len(unique_results),
            "new_count": inserted,
            "skipped_count": existing_dups + internal_dups,
            "errors": errors,
            "inserted_entities": inserted_entities,
        }

        logger.info(
            f"Discovery complete: {stats['new_count']} new URLs added, "
            f"{stats['skipped_count']} skipped, {stats['errors']} errors"
        )

        return stats

    def discover_from_rss(self, feeds: List[str]) -> Dict:
        """Quick discovery from RSS feeds only."""
        return self.discover(keywords=[], rss_feeds=feeds)

    def discover_from_search(self, keywords: List[str], platforms: List[str] = None) -> Dict:
        """Quick discovery from search only."""
        return self.discover(keywords=keywords, platforms=platforms)
