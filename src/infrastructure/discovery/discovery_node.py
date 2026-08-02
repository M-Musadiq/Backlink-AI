"""Discovery Node - merge SERP + RSS sources, dedup, populate tracked_urls."""
import json
import logging
import os
from typing import List, Dict, Optional
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from sqlalchemy.orm import Session

from src.infrastructure.discovery.serp_client import SERPClient
from src.infrastructure.discovery.rss_discovery import RSSDiscovery
from src.infrastructure.discovery.dedup import Deduplicator, extract_domain
from src.infrastructure.discovery.query_generator import generate_queries
from src.infrastructure.discovery.domain_analyzer import DomainAnalyzer
from src.infrastructure.discovery.gaper_keywords import extract_keywords_from_gaper, get_fallback_keywords
from src.infrastructure.repositories.tracked_url_repo import TrackedURLRepository
from src.infrastructure.repositories.platform_config_repo import PlatformConfigRepository
from src.infrastructure.models import TrackedURL
from src.infrastructure.scrapers.scrape_orchestrator import ScrapeOrchestrator
from src.infrastructure.gemini_service import GeminiLLMService
import src.config as config

PAGE_CLASSIFICATION_PROMPT = """You analyze a web page and determine if a user can interact on it (reply, comment, answer, submit).

Page types where interaction IS possible:
- forum_thread: discussion thread where users can reply
- blog_post: blog article where comments/replies are possible
- qa_question: a question page where users can post answers
- listing_submission: a page where users can submit a listing/entry

Page types where interaction is NOT possible:
- doc_page: documentation or wiki page (no user replies)
- product_page: product/service landing or SaaS page
- news_article: news article or press release
- other: anything else with no user interaction

Respond ONLY with valid JSON, no markdown, no backticks:
{
  "page_type": "<type>",
  "is_interactive": true/false,
  "reasoning": "<brief reason>"
}"""

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
    6. Optionally classify discovered sites in Site Knowledge Base
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
        classify_sites: bool = True,
    ) -> Dict:
        """
        Run full discovery pipeline.

        Args:
            keywords: Search keywords
            platforms: Site filters for SERP (e.g., ["site:reddit.com"])
            num_per_platform: Results per platform from SERP
            rss_feeds: Direct RSS feed URLs to parse
            classify_sites: If True, classify newly discovered sites into Site Knowledge Base

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

        # Step 7: Classify discovered sites in Site Knowledge Base
        classified_count = 0
        if classify_sites and inserted_entities:
            try:
                from src.infrastructure.site_knowledge.site_knowledge_service import SiteKnowledgeService
                svc = SiteKnowledgeService(self._session)
                seen_domains = set()
                for entity in inserted_entities:
                    if entity.domain not in seen_domains:
                        seen_domains.add(entity.domain)
                        svc.ensure_site(
                            url=entity.url,
                            title=entity.title or "",
                            description="",
                        )
                        classified_count += 1
                logger.info(f"Classified {classified_count} unique domains in Site Knowledge Base")
            except Exception as e:
                logger.warning(f"Site classification step failed (non-fatal): {e}")

        stats = {
            "total_found": len(all_results),
            "after_internal_dedup": len(unique_results),
            "new_count": inserted,
            "skipped_count": existing_dups + internal_dups,
            "errors": errors,
            "classified_count": classified_count,
            "inserted_entities": inserted_entities,
        }

        logger.info(
            f"Discovery complete: {stats['new_count']} new URLs added, "
            f"{stats['skipped_count']} skipped, {stats['errors']} errors, "
            f"{stats['classified_count']} sites classified"
        )

        return stats

    def discover_from_rss(self, feeds: List[str]) -> Dict:
        """Quick discovery from RSS feeds only."""
        return self.discover(keywords=[], rss_feeds=feeds)

    def discover_from_search(self, keywords: List[str], platforms: List[str] = None) -> Dict:
        """Quick discovery from search only."""
        return self.discover(keywords=keywords, platforms=platforms)

    def discover_generic(
        self,
        max_search_results: int = 30,
        classify_existing: bool = False,
        monitor: Optional[Dict] = None,
        keywords: Optional[List[str]] = None,
    ) -> Dict:
        logger.info("Starting generic discovery (no hardcoded platforms)")
        all_results = []

        if monitor is not None:
            monitor["status"] = "running"
            monitor["phase"] = "extracting_keywords"
            monitor["log"] = []
            monitor["keywords"] = []

        def log_msg(msg: str):
            logger.info(msg)
            if monitor is not None:
                monitor["log"].append(msg)

        if keywords:
            log_msg(f"Using {len(keywords)} user-provided keywords")
        else:
            log_msg("Extracting keywords from gaper.io")
            keywords = extract_keywords_from_gaper()
            if not keywords:
                keywords = get_fallback_keywords()
            log_msg(f"Using {len(keywords)} extracted keywords")

        if monitor is not None:
            monitor["keywords"] = keywords

        queries = generate_queries(keywords)
        log_msg(f"Searching {len(queries)} queries generically")

        if monitor is not None:
            monitor["phase"] = "searching"
            monitor["total_queries"] = len(queries)
            monitor["current_query"] = 0

        def search_query(query: str) -> List[Dict]:
            return self._serp.search_generic(query, num_results=max_search_results)

        search_workers = int(os.getenv("SEARCH_WORKERS", "5"))
        with ThreadPoolExecutor(max_workers=search_workers) as executor:
            futures = {executor.submit(search_query, q): q for q in queries}
            for future in as_completed(futures):
                query = futures[future]
                try:
                    results = future.result()
                    log_msg(f"Search '{query}': {len(results)} results")
                    all_results.extend(results)
                except Exception as e:
                    log_msg(f"Search '{query}' failed: {e}")
                if monitor is not None:
                    monitor["current_query"] = monitor.get("current_query", 0) + 1

        for r in all_results:
            if r.get("url"):
                r["domain"] = extract_domain(r["url"])

        unique_results, _ = self._dedup.deduplicate_results(all_results)

        unique_domains = {}
        domain_results: Dict[str, List[Dict]] = {}
        for r in unique_results:
            domain = r.get("domain", "")
            if not domain:
                continue
            if domain not in domain_results:
                domain_results[domain] = []
            domain_results[domain].append(r)
            if domain not in unique_domains:
                unique_domains[domain] = r
        log_msg(f"Unique domains found: {len(unique_domains)}")

        if monitor is not None:
            monitor["total_raw_results"] = len(all_results)
            monitor["unique_domains"] = len(unique_domains)

        from src.infrastructure.site_knowledge.site_knowledge_service import SiteKnowledgeService
        svc = SiteKnowledgeService(self._session)

        analyzed = 0
        new_analyzed = 0
        classified_count = 0
        actionable = 0
        errors = 0
        individual_urls_saved = 0

        domains_to_analyze = []
        for domain, result in unique_domains.items():
            freshness = svc.is_fresh(domain)
            if freshness is True and not classify_existing:
                analyzed += 1
                logger.debug(f"Skipping {domain} (fresh)")
                continue
            domains_to_analyze.append((domain, result, domain_results.get(domain, [])))

        log_msg(f"Analyzing {len(domains_to_analyze)} new domains in parallel")

        if monitor is not None:
            monitor["phase"] = "analyzing"
            monitor["domains_total"] = len(domains_to_analyze)
            monitor["domains_analyzed"] = 0

        def analyze_domain(domain: str, result: Dict) -> dict:
            """Worker: build a thread-isolated scrape orchestrator + analyzer."""
            from src.infrastructure.database import SessionLocal
            thread_session = SessionLocal()
            thread_config_repo = PlatformConfigRepository(thread_session)
            thread_orchestrator = ScrapeOrchestrator(
                config_store=thread_config_repo,
                timeout=20,
            )
            try:
                analyzer = DomainAnalyzer(scraper=thread_orchestrator)
                url = result.get("url", f"https://{domain}")
                analysis = analyzer.analyze(url, result.get("title", ""))
                return {
                    "domain": domain,
                    "url": url,
                    "title": result.get("title", ""),
                    "analysis": analysis,
                }
            finally:
                thread_orchestrator.close()
                thread_session.close()

        max_workers = int(os.getenv("DISCOVERY_WORKERS", "5"))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(analyze_domain, domain, result): (domain, urls)
                for domain, result, urls in domains_to_analyze
            }
            for future in as_completed(futures):
                domain, individual_urls = futures[future]
                try:
                    out = future.result()
                except Exception as e:
                    errors += 1
                    log_msg(f"Failed to process domain {domain}: {e}")
                    continue

                analyzed += 1
                new_analyzed += 1
                analysis = out["analysis"]

                if analysis.error:
                    errors += 1
                    log_msg(f"Skipping {domain}: {analysis.error}")
                    continue

                individual_inserted = 0
                is_actionable = any([
                    analysis.can_create_posts,
                    analysis.can_reply,
                    analysis.can_submit_listings,
                    analysis.can_publish_articles,
                ])
                if not is_actionable:
                    log_msg(f"Skipping {domain} ({analysis.site_type}) — not actionable")
                    continue

                saved = svc.ensure_site_with_content(
                    url=out["url"],
                    title=out["title"],
                    page_content=analysis.homepage_content,
                )
                classified_count += 1

                from src.infrastructure.repositories.prospect_repo import ProspectRepository
                from src.infrastructure.models import Prospect
                from src.infrastructure.posting.session_manager import SessionManager

                session_mgr = SessionManager(self._session)
                has_session = session_mgr.is_session_valid(domain)
                prospect_status = "waiting_for_login" if not has_session else "discovered"

                all_urls_for_domain = [out["url"]] + [r["url"] for r in individual_urls if r.get("url") and r["url"] != out["url"]]
                seen_urls = set()
                # Use ScrapeOrchestrator so each URL gets static → playwright escalation
                main_config_repo = PlatformConfigRepository(self._session)
                page_scraper = ScrapeOrchestrator(config_store=main_config_repo, timeout=20)
                page_llm = GeminiLLMService(api_key=config.GEMINI_API_KEY)
                for url in all_urls_for_domain:
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    existing = self._tracked_repo.get_by_url(url)
                    if existing:
                        continue
                    from src.infrastructure.scrapers.base import best_title, title_from_url
                    try:
                        result = page_scraper.scrape(url)
                        content = result.body if not result.is_empty else ""
                        page_body = content[:5000] if content else ""
                        page_title = best_title(result.title, url)
                        if content and len(content.strip()) > 50:
                            prompt = f"URL: {url}\n\nPage content:\n{content[:3000]}"
                            resp = page_llm.generate(prompt, system_prompt=PAGE_CLASSIFICATION_PROMPT, temperature=0.1)
                            try:
                                classification = json.loads(resp.strip().removeprefix("```json").removesuffix("```").strip())
                            except json.JSONDecodeError:
                                classification = {"is_interactive": True, "page_type": "other", "reasoning": "parse failed, default keep"}
                        else:
                            classification = {"is_interactive": True, "page_type": "other", "reasoning": "empty content, default keep"}
                            page_body = ""
                    except Exception as exc:
                        log_msg(f"  Page scrape failed for {url}: {exc}")
                        classification = {"is_interactive": True, "page_type": "other", "reasoning": "scrape error, default keep"}
                        page_body = ""
                        page_title = title_from_url(url)

                    tstatus = "discovered"
                    if not classification.get("is_interactive", True):
                        log_msg(f"  Skipping non-interactive page: {url} ({classification.get('page_type', '?')})")
                        tstatus = "skipped"

                    entity = TrackedURL(
                        url=url,
                        domain=domain,
                        title=page_title or title_from_url(url),
                        source="serper",
                        status=tstatus,
                        discovered_at=datetime.now(timezone.utc),
                    )
                    self._tracked_repo.add(entity)
                    if tstatus == "skipped":
                        continue
                    prospect_repo = ProspectRepository(self._session)
                    existing_prospect = prospect_repo.get_by_url(url)
                    if not existing_prospect:
                        prospect_repo.add(Prospect(
                            tracked_url_id=entity.id,
                            url=url,
                            domain=domain,
                            title=page_title or title_from_url(url),
                            body_preview=page_body,
                            status=prospect_status,
                        ))
                    individual_inserted += 1
                individual_urls_saved += individual_inserted
                actionable += 1
                page_scraper.close()

                total_domains = len(domains_to_analyze)
                if monitor is not None:
                    monitor["domains_analyzed"] = new_analyzed
                    monitor["classified_count"] = classified_count
                    monitor["actionable_sites"] = actionable
                    monitor["errors"] = errors
                    monitor["current_domain"] = domain
                    progress = new_analyzed / total_domains * 100 if total_domains else 100
                    monitor["progress_pct"] = round(progress, 1)

                log_msg(f"[{new_analyzed}/{total_domains}] {domain} → {saved.get('site_type', '?')} {'ACTIONABLE+' + str(individual_inserted) if is_actionable else ''}")

        stats = {
            "keywords": len(keywords),
            "queries": len(queries),
            "total_raw_results": len(all_results),
            "after_dedup": len(unique_results),
            "unique_domains": len(unique_domains),
            "domains_analyzed": analyzed,
            "newly_classified": classified_count,
            "actionable_sites": actionable,
            "individual_urls_saved": individual_urls_saved,
            "errors": errors,
        }

        if monitor is not None:
            monitor["status"] = "completed"
            monitor["phase"] = "done"
            monitor["progress_pct"] = 100
            monitor["stats"] = stats

        log_msg(
            f"Generic discovery complete: {stats['actionable_sites']} actionable sites "
            f"({stats['individual_urls_saved']} individual URLs) "
            f"from {stats['unique_domains']} unique domains ({stats['errors']} errors)"
        )
        return stats
