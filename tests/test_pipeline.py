"""Test the full pipeline: Discovery → Relevance → Drafting."""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, ".")

import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from src.config import OPENROUTER_API_KEY, OPENROUTER_MODEL
from src.infrastructure.database import SessionLocal
from src.infrastructure.discovery.discovery_node import DiscoveryNode
from src.infrastructure.repositories.tracked_url_repo import TrackedURLRepository
from src.infrastructure.repositories.prospect_repo import ProspectRepository
from src.infrastructure.repositories.platform_config_repo import PlatformConfigRepository
from src.infrastructure.scrapers.scrape_orchestrator import ScrapeOrchestrator
from src.infrastructure.llm.relevance_node import RelevanceNode
from src.infrastructure.llm.drafter_agent import DrafterAgent
from src.infrastructure.models import Prospect

# Keywords for AI agent deployment
KEYWORDS = ["deploy ai agents", "chatbot automation"]

def test_pipeline():
    print("=" * 60)
    print("FULL PIPELINE TEST")
    print("=" * 60)

    session = SessionLocal()
    try:
        # Step 1: Discovery
        print("\n[1/5] DISCOVERY")
        print("-" * 40)
        discovery = DiscoveryNode(session)
        stats = discovery.discover(
            keywords=KEYWORDS,
            num_per_platform=3,
        )
        print(f"Discovery stats: {stats}")

        # Get discovered URLs
        tracked_repo = TrackedURLRepository(session)
        urls = tracked_repo.get_new_urls(limit=5)
        print(f"Found {len(urls)} new URLs to track")

        if not urls:
            print("No URLs found. Exiting.")
            return

        # Step 2: Create prospects
        print("\n[2/5] CREATING PROSPECTS")
        print("-" * 40)
        prospect_repo = ProspectRepository(session)
        for url_entity in urls:
            existing = prospect_repo.get_by_url(url_entity.url)
            if not existing:
                p = Prospect(
                    tracked_url_id=url_entity.id,
                    url=url_entity.url,
                    domain=url_entity.domain,
                    title=url_entity.title,
                    status="discovered",
                )
                session.add(p)
                session.commit()
                print(f"  Created prospect: {url_entity.domain} - {url_entity.title[:50]}...")

        # Get prospects for evaluation
        prospects = prospect_repo.get_by_status("discovered")[:3]
        print(f"Evaluating {len(prospects)} prospects")

        # Step 3: Relevance evaluation
        print("\n[3/5] RELEVANCE EVALUATION")
        print("-" * 40)
        relevance = RelevanceNode(session)
        relevant_prospects = []

        for p in prospects:
            print(f"\nEvaluating: {p.title[:60]}...")
            result = relevance.evaluate(
                thread_title=p.title,
                thread_content=p.body_preview,
                domain=p.domain,
            )
            print(f"  Score: {result['score']}/10")
            print(f"  Relevant: {result['relevant']}")
            print(f"  Reason: {result['reason'][:80]}")

            if result["relevant"]:
                p.status = "relevant"
                p.relevance_score = result["score"]
                p.updated_at = __import__("datetime").datetime.utcnow()
                session.commit()
                relevant_prospects.append((p, result))
                print(f"  ✓ Marked as relevant")

        print(f"\nRelevant prospects: {len(relevant_prospects)}/{len(prospects)}")

        if not relevant_prospects:
            print("No relevant prospects found. Exiting.")
            return

        # Step 4: Draft replies
        print("\n[4/5] DRAFTING REPLIES")
        print("-" * 40)
        drafter = DrafterAgent(session)

        for p, relevance_result in relevant_prospects[:2]:  # Test with 2
            print(f"\nDrafting for: {p.title[:60]}...")
            draft_result = drafter.draft(
                thread_title=p.title,
                thread_content=p.body_preview,
                domain=p.domain,
                suggested_angle=relevance_result.get("suggested_angle", ""),
            )
            print(f"  Draft length: {len(draft_result['draft'])} chars")
            print(f"  Tone: {draft_result['tone']}")
            print(f"  Backlink included: {draft_result['backlink_included']}")
            print(f"  Compliance issues: {draft_result['compliance_notes']}")
            print(f"\n  --- DRAFT PREVIEW ---")
            print(f"  {draft_result['draft'][:300]}...")
            print(f"  --- END PREVIEW ---")

            # Save draft
            prospect_repo.save_draft(p.id, draft_result["draft"])

        # Step 5: Summary
        print("\n[5/5] SUMMARY")
        print("-" * 40)
        discovered = len(prospect_repo.get_by_status("discovered"))
        relevant = len(prospect_repo.get_by_status("relevant"))
        drafted = len(prospect_repo.get_by_status("drafted"))

        print(f"Status counts:")
        print(f"  Discovered: {discovered}")
        print(f"  Relevant: {relevant}")
        print(f"  Drafted: {drafted}")

        print("\n" + "=" * 60)
        print("PIPELINE TEST COMPLETE")
        print("=" * 60)

    finally:
        session.close()


if __name__ == "__main__":
    test_pipeline()
