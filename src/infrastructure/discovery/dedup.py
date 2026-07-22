"""URL Deduplication - normalize URLs and check against database."""
import logging
import re
from typing import List, Dict, Tuple
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

logger = logging.getLogger(__name__)


def normalize_url(url: str) -> str:
    """
    Normalize a URL for comparison.

    - Remove www. prefix
    - Remove trailing slash
    - Remove query parameters
    - Remove fragments
    - Lowercase scheme and domain
    """
    try:
        parsed = urlparse(url.lower().strip())

        # Remove www. from domain
        hostname = parsed.hostname or ""
        if hostname.startswith("www."):
            hostname = hostname[4:]

        # Reconstruct without query params and fragment
        normalized = urlunparse((
            parsed.scheme,
            hostname,
            parsed.path.rstrip("/") or "/",
            "",  # params
            "",  # query
            "",  # fragment
        ))

        return normalized
    except Exception:
        return url.lower().strip()


def extract_domain(url: str) -> str:
    """Extract domain from URL."""
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        if hostname.startswith("www."):
            hostname = hostname[4:]
        return hostname
    except Exception:
        return ""


EXCLUDED_DOMAINS = {"agents.stackoverflow.com"}


def similarity_score(title1: str, title2: str) -> float:
    """
    Calculate similarity between two titles using simple word overlap.
    Returns 0.0 to 1.0 (1.0 = identical).
    """
    if not title1 or not title2:
        return 0.0

    words1 = set(re.findall(r'\w+', title1.lower()))
    words2 = set(re.findall(r'\w+', title2.lower()))

    if not words1 or not words2:
        return 0.0

    intersection = words1 & words2
    union = words1 | words2

    return len(intersection) / len(union) if union else 0.0


class Deduplicator:
    """Deduplicate URLs against database and within result sets."""

    def __init__(self, tracked_url_repo=None):
        """
        Args:
            tracked_url_repo: TrackedURLRepository instance for DB checks
        """
        self._repo = tracked_url_repo

    def is_duplicate(self, url: str) -> bool:
        """Check if URL already exists in database."""
        if not self._repo:
            return False
        return self._repo.url_exists(url)

    def deduplicate_results(
        self,
        results: List[Dict],
        title_similarity_threshold: float = 0.85,
    ) -> Tuple[List[Dict], int]:
        """
        Deduplicate a list of results.

        - Removes exact URL duplicates
        - Removes near-duplicate titles (similarity > threshold)

        Returns:
            Tuple of (deduplicated results, number of duplicates removed)
        """
        seen_urls = set()
        seen_titles = []
        unique = []
        duplicates = 0

        for result in results:
            url = result.get("url", "")
            title = result.get("title", "")
            normalized = normalize_url(url)

            # Skip empty URLs
            if not url:
                continue

            # Skip excluded domains
            domain = extract_domain(url)
            if domain in EXCLUDED_DOMAINS:
                duplicates += 1
                continue

            # Skip exact URL duplicates
            if normalized in seen_urls:
                duplicates += 1
                continue

            # Skip near-duplicate titles
            is_title_dup = False
            for seen_title in seen_titles:
                if similarity_score(title, seen_title) >= title_similarity_threshold:
                    is_title_dup = True
                    break

            if is_title_dup:
                duplicates += 1
                continue

            # New unique result
            seen_urls.add(normalized)
            seen_titles.append(title)
            unique.append(result)

        logger.info(f"Deduplication: {len(unique)} unique, {duplicates} duplicates removed")
        return unique, duplicates

    def deduplicate_with_db(
        self,
        results: List[Dict],
    ) -> Tuple[List[Dict], int]:
        """
        Remove results that already exist in the database.

        Returns:
            Tuple of (new results only, number of existing duplicates)
        """
        if not self._repo:
            return results, 0

        new_results = []
        existing = 0

        for result in results:
            url = result.get("url", "")
            if not url:
                continue

            # Skip excluded domains
            domain = extract_domain(url)
            if domain in EXCLUDED_DOMAINS:
                existing += 1
                continue

            if self.is_duplicate(url):
                existing += 1
                continue

            new_results.append(result)

        logger.info(f"DB deduplication: {len(new_results)} new, {existing} already tracked")
        return new_results, existing
