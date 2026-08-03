"""Smoke test: verify all tables created + CRUD works."""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from datetime import datetime, timedelta

sys.path.insert(0, ".")

from src.infrastructure.database import engine, SessionLocal, Base
from src.infrastructure.models import TrackedURL, PlatformConfigDB, GuidelinesCache, Prospect, PlatformSession, AuditLog
from src.infrastructure.repositories import (
    TrackedURLRepository,
    PlatformConfigRepository,
    GuidelinesRepository,
    ProspectRepository,
    SessionVaultRepository,
    AuditLogRepository,
)
from src.legacy.redis_client import redis_client


def test_database():
    print("=" * 60)
    print("STEP 1 SMOKE TEST: Database Foundation")
    print("=" * 60)

    # Test 1: Connect to PostgreSQL
    print("\n[1/8] Connecting to PostgreSQL...")
    try:
        with engine.connect() as conn:
            print("  ✅ Connected to PostgreSQL")
    except Exception as e:
        print(f"  ❌ Failed to connect: {e}")
        return False

    # Test 2: Connect to Redis
    print("\n[2/8] Connecting to Redis...")
    try:
        redis_client.ping()
        print("  ✅ Connected to Redis")
    except Exception as e:
        print(f"  ❌ Failed to connect: {e}")
        return False

    # Test 3: Verify tables exist
    print("\n[3/8] Verifying tables exist...")
    expected_tables = ["tracked_urls", "platform_config", "guidelines_cache", "prospects", "platform_sessions", "audit_log"]
    from sqlalchemy import text
    with engine.connect() as conn:
        result = conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'"))
        actual_tables = [row[0] for row in result]
    for table in expected_tables:
        if table in actual_tables:
            print(f"  ✅ Table '{table}' exists")
        else:
            print(f"  ❌ Table '{table}' NOT found")
            return False

    # Test 4: TrackedURL CRUD
    print("\n[4/8] Testing TrackedURL CRUD...")
    session = SessionLocal()
    try:
        repo = TrackedURLRepository(session)
        entity = repo.add(TrackedURL(
            url="https://test.example.com/thread/1",
            domain="example.com",
            title="Test Thread",
            source="test",
            status="discovered",
        ))
        print(f"  ✅ Insert: id={entity.id}")

        fetched = repo.get_by_id(entity.id)
        assert fetched.url == "https://test.example.com/thread/1"
        print(f"  ✅ Query by ID: url={fetched.url}")

        assert repo.url_exists("https://test.example.com/thread/1")
        print("  ✅ URL exists check")

        repo.mark_scraped(entity.id)
        updated = repo.get_by_id(entity.id)
        assert updated.status == "scraped"
        print("  ✅ Update status to 'scraped'")

        repo.delete(entity)
        assert repo.get_by_id(entity.id) is None
        print("  ✅ Delete")
    finally:
        session.close()

    # Test 5: PlatformConfigDB CRUD
    print("\n[5/8] Testing PlatformConfigDB CRUD...")
    session = SessionLocal()
    try:
        repo = PlatformConfigRepository(session)
        entity = repo.upsert(
            domain="test.dev.to",
            scraper_type="api",
            post_method="api",
            requires_auth=True,
            rate_limit_seconds=5,
            guidelines_url="https://dev.to/guidelines",
        )
        print(f"  ✅ Upsert: domain={entity.domain}")

        fetched = repo.get_by_domain("test.dev.to")
        assert fetched.scraper_type == "api"
        print(f"  ✅ Query by domain: scraper_type={fetched.scraper_type}")

        repo.upsert(domain="test.dev.to", scraper_type="playwright")
        updated = repo.get_by_domain("test.dev.to")
        assert updated.scraper_type == "playwright"
        print("  ✅ Update via upsert")

        repo.delete(updated)
        print("  ✅ Delete")
    finally:
        session.close()

    # Test 6: GuidelinesCache CRUD
    print("\n[6/8] Testing GuidelinesCache CRUD...")
    session = SessionLocal()
    try:
        repo = GuidelinesRepository(session)
        entity = repo.save_guidelines(
            domain="test.dev.to",
            content="Be nice. Use code blocks. No self-promotion.",
            scraper_type_used="static",
            expires_days=7,
        )
        print(f"  ✅ Save guidelines: id={entity.id}")

        fresh = repo.get_fresh_guidelines("test.dev.to", max_age_days=7)
        assert fresh is not None
        print("  ✅ Get fresh guidelines")

        assert not repo.is_stale("test.dev.to", max_age_days=7)
        print("  ✅ Staleness check (fresh)")

        repo.delete(entity)
        print("  ✅ Delete")
    finally:
        session.close()

    # Test 7: Prospect + AuditLog CRUD
    print("\n[7/8] Testing Prospect + AuditLog CRUD...")
    session = SessionLocal()
    try:
        prospect_repo = ProspectRepository(session)
        audit_repo = AuditLogRepository(session)

        prospect = prospect_repo.add(Prospect(
            url="https://test.example.com/thread/2",
            domain="example.com",
            title="Test Prospect",
            status="discovered",
        ))
        print(f"  ✅ Insert prospect: id={prospect.id}")

        prospect_repo.update_status(prospect.id, "scraped")
        updated = prospect_repo.get_by_id(prospect.id)
        assert updated.status == "scraped"
        print("  ✅ Update prospect status")

        prospect_repo.save_draft(prospect.id, "Here is a helpful reply...")
        drafted = prospect_repo.get_by_id(prospect.id)
        assert drafted.status == "drafted"
        assert drafted.draft_content == "Here is a helpful reply..."
        print("  ✅ Save draft")

        log = audit_repo.log_action("scraped", "Successfully scraped thread", prospect.id)
        print(f"  ✅ Audit log: id={log.id}")

        history = audit_repo.get_prospect_history(prospect.id)
        assert len(history) == 1
        print(f"  ✅ Prospect history: {len(history)} entries")

        prospect_repo.delete(prospect)
        audit_repo.delete(log)
        print("  ✅ Cleanup")
    finally:
        session.close()

    # Test 8: PlatformSession (encrypted vault)
    print("\n[8/8] Testing PlatformSession (encrypted vault)...")
    session = SessionLocal()
    try:
        repo = SessionVaultRepository(session)

        from cryptography.fernet import Fernet
        from src.config import VAULT_ENCRYPTION_KEY
        fernet = Fernet(VAULT_ENCRYPTION_KEY.encode())

        original_data = '{"cookies": [{"name": "session", "value": "abc123"}]}'
        encrypted = fernet.encrypt(original_data.encode()).decode()

        entity = repo.save_session(
            domain="test.dev.to",
            encrypted_data=encrypted,
            expires_at=datetime.utcnow() + timedelta(days=30),
        )
        print(f"  ✅ Save encrypted session: id={entity.id}")

        fetched = repo.get_by_domain("test.dev.to")
        decrypted = fernet.decrypt(fetched.session_data_encrypted.encode()).decode()
        assert decrypted == original_data
        print("  ✅ Decrypt and verify data matches")

        assert repo.is_valid("test.dev.to")
        print("  ✅ Session is valid")

        repo.flag_for_reauth("test.dev.to")
        assert not repo.is_valid("test.dev.to")
        print("  ✅ Flag for re-auth (session expired)")

        repo.delete(entity)
        print("  ✅ Delete")
    finally:
        session.close()

    print("\n" + "=" * 60)
    print("✅ ALL TESTS PASSED!")
    print("=" * 60)
    return True


if __name__ == "__main__":
    success = test_database()
    sys.exit(0 if success else 1)
