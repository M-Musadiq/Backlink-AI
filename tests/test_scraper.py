import sys
sys.path.insert(0, ".")
from src.infrastructure.scrapers.static_scraper import StaticScraper
from src.infrastructure.scrapers.scrape_orchestrator import ScrapeOrchestrator
from src.infrastructure.repositories.platform_config_repo import PlatformConfigRepository
from src.infrastructure.database import SessionLocal

urls = [
    "https://www.reddit.com/r/AI_Agents/comments/1rrj8zr/those_deploying_ai_agents_in/",
    "https://stackoverflow.com/questions/tagged/chatbot",
    "https://dev.to/t/ai",
]

print("=" * 60)
print("SCRAPER TEST")
print("=" * 60)

session = SessionLocal()
config_repo = PlatformConfigRepository(session)

scraper = StaticScraper(timeout=15)
orchestrator = ScrapeOrchestrator(config_store=config_repo)

for url in urls:
    print(f"\nTesting: {url[:60]}...")
    try:
        result = scraper.scrape(url)
        title = result.title if result.title else "No title"
        body_len = len(result.body) if result.body else 0
        print(f"  Title: {title[:60]}")
        print(f"  Body: {body_len} chars")
        print(f"  Empty: {result.is_empty}")
        print(f"  OK: {'YES' if body_len > 100 else 'FAILED - too short'}")
    except Exception as e:
        print(f"  ERROR: {e}")

print("\n" + "=" * 60)
print("DONE")
print("=" * 60)
