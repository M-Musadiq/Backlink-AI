"""One-time migration: JSON platform_configs.json -> PostgreSQL platform_config table."""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, ".")

from src.infrastructure.database import SessionLocal
from src.infrastructure.repositories.platform_config_repo import PlatformConfigRepository


def migrate():
    json_path = Path("data/platform_configs.json")
    if not json_path.exists():
        print(f"❌ File not found: {json_path}")
        return False

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not data:
        print("❌ JSON file is empty")
        return False

    print(f"Found {len(data)} configs in {json_path}")

    session = SessionLocal()
    try:
        repo = PlatformConfigRepository(session)
        migrated = 0
        errors = 0

        for domain, config in data.items():
            try:
                last_updated = datetime.fromisoformat(config["last_updated"]) if config.get("last_updated") else datetime.utcnow()

                repo.upsert(
                    domain=domain,
                    scraper_type=config.get("scraper_type", "static"),
                    post_method=config.get("post_method", "not_supported"),
                    requires_auth=config.get("requires_auth", False),
                    rate_limit_seconds=config.get("rate_limit_seconds", 5),
                    guidelines_url=config.get("guidelines_url", ""),
                    last_updated=last_updated,
                )
                migrated += 1
                print(f"  ✅ {domain}: {config.get('scraper_type', 'static')}")
            except Exception as e:
                errors += 1
                print(f"  ❌ {domain}: {e}")

        print(f"\nMigration complete: {migrated} migrated, {errors} errors")

        # Verify
        all_configs = repo.get_all_domains()
        print(f"Database now has {len(all_configs)} platform configs: {all_configs}")

        return errors == 0
    finally:
        session.close()


if __name__ == "__main__":
    success = migrate()
    sys.exit(0 if success else 1)
