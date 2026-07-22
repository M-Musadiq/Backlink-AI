import sys
sys.path.insert(0, ".")
from src.infrastructure.scrapers.scrape_orchestrator import ScrapeOrchestrator
from src.infrastructure.repositories.platform_config_repo import PlatformConfigRepository
from src.infrastructure.database import SessionLocal

urls = [
    "https://www.reddit.com/r/AI_Agents/comments/1rrj8zr/those_deploying_ai_agents_in/",
    "https://stackoverflow.com/questions/12345/how-to-build-chatbot",
    "https://dev.to/ben/the-html-css-of-the-dev-community-3m1i",
]

print("=" * 60)
print("FULL ORCHESTRATOR TEST (4-tier escalation)")
print("=" * 60)

session = SessionLocal()
config_repo = PlatformConfigRepository(session)
orchestrator = ScrapeOrchestrator(config_store=config_repo)

for url in urls:
    print(f"\nTesting: {url[:60]}...")
    try:
        result = orchestrator.scrape(url)
        title = result.title if result.title else "No title"
        body_len = len(result.body) if result.body else 0
        scraper_used = result.scraper_type
        print(f"  Scraper: {scraper_used}")
        print(f"  Title: {title[:60]}")
        print(f"  Body: {body_len} chars")
        print(f"  OK: {'YES' if body_len > 100 else 'FAILED'}")
    except Exception as e:
        print(f"  ERROR: {e}")

orchestrator.close()
print("\n" + "=" * 60)
print("DONE")
