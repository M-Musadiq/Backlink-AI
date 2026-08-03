"""Seed guidelines for test platforms."""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, ".")

import logging
from src.infrastructure.database import SessionLocal
from src.infrastructure.guidelines.guidelines_extractor import GuidelinesExtractor
from src.infrastructure.guidelines.guidelines_cache import GuidelinesCacheManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# Domains with guidelines URLs configured in platform_config
PLATFORMS_TO_SEED = [
    "dev.to",
    "reddit.com",
    "stackoverflow.com",
]


def seed():
    print("=" * 60)
    print("GUIDELINES SEED SCRIPT")
    print("=" * 60)

    session = SessionLocal()
    try:
        extractor = GuidelinesExtractor(session)
        cache = GuidelinesCacheManager(session)

        results = {}
        for domain in PLATFORMS_TO_SEED:
            print(f"\n[{domain}] Extracting guidelines...")
            try:
                guidelines = extractor.extract_guidelines(domain, force_refresh=True)
                if guidelines:
                    results[domain] = {
                        "status": "OK",
                        "length": len(guidelines),
                        "preview": guidelines[:200].replace("\n", " ") + "...",
                    }
                    print(f"  OK: {len(guidelines)} chars")
                    print(f"  Preview: {guidelines[:150].replace(chr(10), ' ')}...")
                else:
                    results[domain] = {"status": "SKIPPED", "reason": "no guidelines_url or empty content"}
                    print(f"  SKIPPED: no guidelines_url or empty content")
            except Exception as e:
                results[domain] = {"status": "ERROR", "reason": str(e)}
                print(f"  ERROR: {e}")

        # Summary
        print("\n" + "=" * 60)
        print("SEED RESULTS")
        print("=" * 60)
        for domain, info in results.items():
            status = info["status"]
            if status == "OK":
                print(f"  {domain}: OK ({info['length']} chars)")
            else:
                print(f"  {domain}: {status} ({info.get('reason', '')})")

        # Check staleness
        print("\n" + "=" * 60)
        print("STALENESS CHECK")
        print("=" * 60)
        staleness = cache.get_all_staleness()
        for info in staleness:
            stale_mark = "STALE" if info["is_stale"] else "FRESH"
            print(f"  {info['domain']}: {stale_mark} (age: {info['age_days']} days)")

        print("\n" + "=" * 60)
        print("DONE")
        print("=" * 60)

    finally:
        session.close()


if __name__ == "__main__":
    seed()
