import sys
sys.path.insert(0, ".")
from src.infrastructure.scrapers.static_scraper import StaticScraper

scraper = StaticScraper(timeout=15)

urls = [
    "https://dev.to/t/ai",
    "https://stackoverflow.com/questions/79904851/how-to-create-an-ai-agent",
    "https://www.reddit.com/r/ChatGPT/",
]

print("=" * 60)
print("STATIC SCRAPER TEST")
print("=" * 60)

for url in urls:
    print(f"\nURL: {url[:60]}...")
    try:
        r = scraper.scrape(url)
        title = r.title if r.title else "No title"
        body_len = len(r.body) if r.body else 0
        print(f"  Title: {title[:60]}")
        print(f"  Body: {body_len} chars")
        print(f"  Status: {'OK' if body_len > 100 else 'TOO SHORT'}")
    except Exception as e:
        err = str(e)[:80]
        print(f"  FAILED: {err}")

print("\n" + "=" * 60)
