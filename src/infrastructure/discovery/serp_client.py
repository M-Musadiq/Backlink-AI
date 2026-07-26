"""SERP Search clients - DuckDuckGo (free) and Serper.dev (2,500 free credits)."""
import logging
import os
import requests
from typing import List, Dict, Optional
from duckduckgo_search import DDGS
from src.infrastructure.platform_config import PlatformConfigService

logger = logging.getLogger(__name__)

_platform_config = PlatformConfigService()


class DuckDuckGoSearch:
    """Search DuckDuckGo for relevant threads and discussions."""

    def __init__(self):
        self._ddgs = DDGS()

    def search(
        self,
        query: str,
        num_results: int = 20,
        region: str = "wt",
        site_filter: str = "",
    ) -> List[Dict]:
        """
        Search DuckDuckGo and return results.

        Args:
            query: Search query
            num_results: Number of results to return
            region: Region code (wt = worldwide)
            site_filter: Optional site filter (e.g., "site:reddit.com")

        Returns:
            List of dicts with keys: url, title, snippet
        """
        full_query = f"{query} {site_filter}".strip()
        results = []

        try:
            search_results = self._ddgs.text(full_query, region=region, max_results=num_results)
            for r in search_results:
                url = r.get("href", "")
                if "agents.stackoverflow.com" in url:
                    continue
                results.append({
                    "url": url,
                    "title": r.get("title", ""),
                    "snippet": r.get("body", ""),
                    "source": "duckduckgo",
                })
            logger.info(f"DuckDuckGo search for '{full_query}': {len(results)} results")
        except Exception as e:
            logger.error(f"DuckDuckGo search failed: {e}")

        return results

    def search_platforms(
        self,
        query: str,
        platforms: List[str] = None,
        num_per_platform: int = 10,
    ) -> List[Dict]:
        """
        Search across multiple platforms.

        Args:
            query: Base search query
            platforms: List of site filters (e.g., ["site:reddit.com", "site:dev.to"])
            num_per_platform: Results per platform

        Returns:
            Combined and deduplicated results
        """
        if platforms is None:
            platforms = _platform_config.get_search_platforms()

        all_results = []
        for platform in platforms:
            results = self.search(query, num_results=num_per_platform, site_filter=platform)
            all_results.extend(results)

        logger.info(f"DuckDuckGo multi-platform search: {len(all_results)} total results from {len(platforms)} platforms")
        return all_results


class SerperDevSearch:
    """
    Search Google via Serper.dev API.
    
    Free tier: 2,500 credits, no credit card required.
    Sign up at: https://serper.dev
    """

    BASE_URL = "https://google.serper.dev/search"

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize Serper.dev client.

        Args:
            api_key: Serper.dev API key. If not provided, reads from SERPER_API_KEY env var.
        """
        self.api_key = api_key or os.getenv("SERPER_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Serper.dev API key required. Set SERPER_API_KEY env var or pass api_key parameter.\n"
                "Get free 2,500 credits at: https://serper.dev"
            )

    def search(
        self,
        query: str,
        num_results: int = 20,
        country: str = "us",
        language: str = "en",
        site_filter: str = "",
        time_filter: str = "",
    ) -> List[Dict]:
        """
        Search Google via Serper.dev.

        Args:
            query: Search query
            num_results: Number of results (max 100)
            country: Country code (us, uk, de, etc.)
            language: Language code (en, es, etc.)
            site_filter: Optional site filter (e.g., "site:reddit.com")
            time_filter: Optional time filter (e.g., "qdr:m" for last month, "qdr:w" for last week, "qdr:d" for last day)

        Returns:
            List of dicts with keys: url, title, snippet, position, date
        """
        full_query = f"{query} {site_filter}".strip()
        results = []

        headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json",
        }

        payload = {
            "q": full_query,
            "gl": country,
            "hl": language,
            "num": min(num_results, 100),
        }
        if time_filter:
            payload["tbs"] = time_filter

        try:
            response = requests.post(
                self.BASE_URL,
                headers=headers,
                json=payload,
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()

            # Extract organic results
            for r in data.get("organic", []):
                url = r.get("link", "")
                if "agents.stackoverflow.com" in url:
                    continue
                results.append({
                    "url": url,
                    "title": r.get("title", ""),
                    "snippet": r.get("snippet", ""),
                    "position": r.get("position", 0),
                    "date": r.get("date", ""),
                    "source": "serper",
                })

            logger.info(f"Serper.dev search for '{full_query}': {len(results)} results")

        except requests.exceptions.RequestException as e:
            logger.error(f"Serper.dev search failed: {e}")

        return results

    def search_platforms(
        self,
        query: str,
        platforms: List[str] = None,
        num_per_platform: int = 10,
    ) -> List[Dict]:
        """
        Search across multiple platforms.

        Args:
            query: Base search query
            platforms: List of site filters
            num_per_platform: Results per platform

        Returns:
            Combined and deduplicated results
        """
        if platforms is None:
            platforms = _platform_config.get_search_platforms()

        all_results = []
        for platform in platforms:
            results = self.search(query, num_results=num_per_platform, site_filter=platform)
            all_results.extend(results)

        logger.info(f"Serper multi-platform search: {len(all_results)} total results from {len(platforms)} platforms")
        return all_results

    def search_platforms_with_time(
        self,
        query: str,
        platforms_with_time: List[Dict] = None,
        num_per_platform: int = 10,
    ) -> List[Dict]:
        """Search across platforms with per-platform time filters."""
        if platforms_with_time is None:
            platforms_with_time = _platform_config.get_search_platforms_with_time_filter()

        all_results = []
        for pt in platforms_with_time:
            results = self.search(
                query,
                num_results=num_per_platform,
                site_filter=pt["site_filter"],
                time_filter=pt.get("time_filter", ""),
            )
            all_results.extend(results)

        logger.info(f"Serper multi-platform search (with time): {len(all_results)} total results")
        return all_results


class SERPClient:
    """
    Unified SERP client that tries Serper.dev first, falls back to DuckDuckGo.
    
    This gives you:
    - Better Google results when SERPER_API_KEY is set (free 2,500 credits)
    - Unlimited DuckDuckGo results as fallback
    """

    def __init__(self, serper_api_key: Optional[str] = None):
        """
        Initialize the SERP client.

        Args:
            serper_api_key: Optional Serper.dev API key
        """
        self._serper = None
        self._duckduckgo = None

        # Try to initialize Serper.dev
        api_key = serper_api_key or os.getenv("SERPER_API_KEY")
        if api_key:
            try:
                self._serper = SerperDevSearch(api_key=api_key)
                logger.info("Using Serper.dev (Google results)")
            except Exception as e:
                logger.warning(f"Failed to initialize Serper.dev: {e}")

        # Always have DuckDuckGo as fallback
        self._duckduckgo = DuckDuckGoSearch()
        if not self._serper:
            logger.info("Using DuckDuckGo (free, unlimited)")

    def search(
        self,
        query: str,
        num_results: int = 20,
        site_filter: str = "",
    ) -> List[Dict]:
        """
        Search using the best available provider.

        Args:
            query: Search query
            num_results: Number of results
            site_filter: Optional site filter

        Returns:
            List of search results
        """
        # Try Serper.dev first (better Google results)
        if self._serper:
            try:
                results = self._serper.search(
                    query=query,
                    num_results=num_results,
                    site_filter=site_filter,
                )
                if results:
                    return results
            except Exception as e:
                logger.warning(f"Serper.dev failed, falling back to DuckDuckGo: {e}")

        # Fallback to DuckDuckGo
        return self._duckduckgo.search(
            query=query,
            num_results=num_results,
            site_filter=site_filter,
        )

    def search_platforms(
        self,
        query: str,
        platforms: List[str] = None,
        num_per_platform: int = 10,
    ) -> List[Dict]:
        """Search across platforms."""
        # Try Serper.dev first with time filters
        if self._serper:
            try:
                platforms_with_time = _platform_config.get_search_platforms_with_time_filter()
                if platforms_with_time:
                    results = self._serper.search_platforms_with_time(
                        query=query,
                        platforms_with_time=platforms_with_time,
                        num_per_platform=num_per_platform,
                    )
                    if results:
                        return results
                results = self._serper.search_platforms(
                    query=query,
                    platforms=platforms,
                    num_per_platform=num_per_platform,
                )
                if results:
                    return results
            except Exception as e:
                logger.warning(f"Serper.dev failed, falling back to DuckDuckGo: {e}")

        # Fallback to DuckDuckGo
        return self._duckduckgo.search_platforms(
            query=query,
            platforms=platforms,
            num_per_platform=num_per_platform,
        )
