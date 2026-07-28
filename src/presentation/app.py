"""Web Dashboard - FastAPI app for visualizing and controlling the backlink system."""
import sys
import logging
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*datetime\\.datetime\\.utcnow.*")
sys.path.insert(0, ".")

import asyncio
from datetime import datetime, timezone
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from src.infrastructure.database import SessionLocal
from src.infrastructure.repositories.tracked_url_repo import TrackedURLRepository
from src.infrastructure.repositories.prospect_repo import ProspectRepository
from src.infrastructure.repositories.audit_log_repo import AuditLogRepository

logger = logging.getLogger(__name__)

app = FastAPI(title="Backlink AI Dashboard")
templates = Jinja2Templates(directory="src/presentation/templates")


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard page."""
    session = SessionLocal()
    try:
        tracked_repo = TrackedURLRepository(session)
        prospect_repo = ProspectRepository(session)
        audit_repo = AuditLogRepository(session)

        # Get stats
        all_urls = tracked_repo.get_all()
        total_urls = len(all_urls)
        new_urls = len([u for u in all_urls if u.status == "discovered"])
        scraped_urls = len([u for u in all_urls if u.status == "scraped"])

        all_prospects = prospect_repo.get_all()
        total_prospects = len(all_prospects)
        discovered = len([p for p in all_prospects if p.status in ("discovered", "scraped")])
        relevant = len([p for p in all_prospects if p.status == "relevant"])
        drafted = len([p for p in all_prospects if p.status == "drafted"])
        approved = len([p for p in all_prospects if p.status == "approved"])
        posted = len([p for p in all_prospects if p.status == "posted"])
        archived = len([p for p in all_prospects if p.status == "archived"])

        # Recent activity
        recent_logs = audit_repo.get_recent(limit=10)

        return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context={
                "stats": {
                    "total_urls": total_urls,
                    "new_urls": new_urls,
                    "scraped_urls": scraped_urls,
                    "total_prospects": total_prospects,
                    "discovered": new_urls,
                    "relevant": relevant,
                    "drafted": drafted,
                    "approved": approved,
                    "posted": posted,
                    "archived": archived,
                },
                "recent_logs": recent_logs,
            },
        )
    finally:
        session.close()


@app.get("/prospects", response_class=HTMLResponse)
async def prospects_page(request: Request, status: str = ""):
    """Prospects page with filtering."""
    session = SessionLocal()
    try:
        prospect_repo = ProspectRepository(session)

        if status:
            if status == "discovered":
                prospects = prospect_repo.get_by_statuses(["discovered", "scraped"])
            else:
                prospects = prospect_repo.get_by_status(status)
        else:
            prospects = prospect_repo.get_all()

        # Filter out excluded domains
        from src.infrastructure.discovery.dedup import EXCLUDED_DOMAINS, extract_domain
        prospects = [p for p in prospects if not p.tracked_url or extract_domain(p.tracked_url.url) not in EXCLUDED_DOMAINS]

        return templates.TemplateResponse(
            request=request,
            name="prospects.html",
            context={
                "prospects": prospects,
                "current_status": status,
            },
        )
    finally:
        session.close()


@app.get("/urls", response_class=HTMLResponse)
async def urls_page(request: Request):
    """Tracked URLs page."""
    session = SessionLocal()
    try:
        tracked_repo = TrackedURLRepository(session)
        urls = tracked_repo.get_all()

        return templates.TemplateResponse(
            request=request,
            name="urls.html",
            context={"urls": urls},
        )
    finally:
        session.close()





@app.get("/activity", response_class=HTMLResponse)
async def activity_page(request: Request):
    """Activity/audit log page."""
    session = SessionLocal()
    try:
        audit_repo = AuditLogRepository(session)
        logs = audit_repo.get_recent(limit=50)

        return templates.TemplateResponse(
            request=request,
            name="activity.html",
            context={"logs": logs},
        )
    finally:
        session.close()


@app.get("/sessions", response_class=HTMLResponse)
async def sessions_page(request: Request):
    """Session management page."""
    from src.infrastructure.posting.session_manager import SessionManager

    session = SessionLocal()
    try:
        sm = SessionManager(session)
        sessions = sm.get_all_sessions()

        return templates.TemplateResponse(
            request=request,
            name="sessions.html",
            context={"sessions": sessions},
        )
    finally:
        session.close()


# === API Endpoints for triggering actions ===

@app.post("/api/scrape/{url_id}")
async def scrape_url(url_id: int):
    """Scrape a single tracked URL on demand."""
    from src.infrastructure.scrapers.scrape_orchestrator import ScrapeOrchestrator
    from src.infrastructure.repositories.platform_config_repo import PlatformConfigRepository

    session = SessionLocal()
    scraper = None
    try:
        tracked_repo = TrackedURLRepository(session)
        prospect_repo = ProspectRepository(session)
        config_repo = PlatformConfigRepository(session)
        scraper = ScrapeOrchestrator(config_store=config_repo, timeout=15)

        url_entity = tracked_repo.get_by_id(url_id)
        if not url_entity:
            return {"success": False, "error": "URL not found"}
        if url_entity.status == "scraped":
            return {"success": False, "error": "Already scraped"}

        def _do():
            content = scraper.scrape(url_entity.url)
            if content.is_empty or len(content.body) <= 100:
                return {"success": False, "error": "No content scraped"}
            existing = prospect_repo.get_by_url(url_entity.url)
            if not existing:
                from src.infrastructure.models import Prospect
                prospect = Prospect(
                    tracked_url_id=url_entity.id,
                    url=url_entity.url,
                    domain=url_entity.domain,
                    title=content.title or url_entity.title,
                    body_preview=content.body[:2000],
                    status="discovered",
                )
                session.add(prospect)
                session.commit()
            tracked_repo.mark_scraped(url_entity.id)
            return {"success": True}

        return await asyncio.to_thread(_do)
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        if scraper:
            scraper.close()
        session.close()


@app.post("/api/discovery")
async def run_discovery(keywords: str = Form(...)):
    """Trigger discovery run + auto-scrape."""
    from src.infrastructure.discovery.discovery_node import DiscoveryNode
    from src.infrastructure.scrapers.scrape_orchestrator import ScrapeOrchestrator
    from src.infrastructure.repositories.platform_config_repo import PlatformConfigRepository

    session = SessionLocal()
    scraper = None
    try:
        node = DiscoveryNode(session)
        keyword_list = [k.strip() for k in keywords.split(",")]
        stats = node.discover(keywords=keyword_list, num_per_platform=5)

        # Auto-scrape only the URLs we just inserted
        tracked_repo = TrackedURLRepository(session)
        prospect_repo = ProspectRepository(session)
        config_repo = PlatformConfigRepository(session)
        scraper = ScrapeOrchestrator(config_store=config_repo, timeout=15)
        inserted_entities = stats.pop("inserted_entities", [])

        def _do_scrape():
            scraped = 0
            for url_entity in inserted_entities:
                try:
                    content = scraper.scrape(url_entity.url)
                    if not content.is_empty and len(content.body) > 100:
                        existing = prospect_repo.get_by_url(url_entity.url)
                        if not existing:
                            from src.infrastructure.models import Prospect
                            prospect = Prospect(
                                tracked_url_id=url_entity.id,
                                url=url_entity.url,
                                domain=url_entity.domain,
                                title=content.title or url_entity.title,
                                body_preview=content.body[:2000],
                                status="discovered",
                            )
                            session.add(prospect)
                            session.commit()
                            scraped += 1
                        tracked_repo.mark_scraped(url_entity.id)
                except Exception as e:
                    logger.warning(f"Failed to scrape {url_entity.url}: {e}")
            return scraped

        scraped = await asyncio.to_thread(_do_scrape)
        stats["scraped"] = scraped
        return {"success": True, "stats": stats}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        if scraper:
            scraper.close()
        session.close()


@app.post("/api/evaluate/{prospect_id}")
async def evaluate_prospect(prospect_id: int):
    """Evaluate a single prospect for relevance."""
    session = SessionLocal()
    try:
        prospect_repo = ProspectRepository(session)
        prospect = prospect_repo.get_by_id(prospect_id)

        if not prospect:
            return {"success": False, "error": "Prospect not found"}

        from src.infrastructure.llm.relevance_node import RelevanceNode
        evaluator = RelevanceNode(session)

        result = evaluator.evaluate(
            thread_title=prospect.title,
            thread_content=prospect.body_preview,
            domain=prospect.domain,
        )

        # Update prospect
        prospect.relevance_score = result["score"]
        if result["relevant"]:
            prospect.status = "relevant"
        else:
            prospect.status = "archived"
        prospect.updated_at = datetime.now(timezone.utc)
        session.commit()

        return {"success": True, "result": result}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        session.close()


@app.post("/api/draft/{prospect_id}")
async def draft_reply(prospect_id: int):
    """Draft a reply for a prospect."""
    session = SessionLocal()
    try:
        prospect_repo = ProspectRepository(session)
        prospect = prospect_repo.get_by_id(prospect_id)

        if not prospect:
            return {"success": False, "error": "Prospect not found"}

        from src.infrastructure.llm.drafter_agent import DrafterAgent
        drafter = DrafterAgent(session)

        result = drafter.draft(
            thread_title=prospect.title,
            thread_content=prospect.body_preview,
            domain=prospect.domain,
        )

        prospect_repo.save_draft(prospect_id, result["draft"])

        return {"success": True, "result": result}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        session.close()


@app.post("/api/save-draft/{prospect_id}")
async def save_draft(prospect_id: int, request: Request):
    """Save edited draft content."""
    session = SessionLocal()
    try:
        body = await request.json()
        draft_content = body.get("draft", "")
        
        prospect_repo = ProspectRepository(session)
        prospect = prospect_repo.get_by_id(prospect_id)
        
        if not prospect:
            return {"success": False, "error": "Prospect not found"}
        
        prospect.draft_content = draft_content
        prospect.updated_at = datetime.now(timezone.utc)
        session.commit()
        
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        session.close()


@app.post("/api/approve/{prospect_id}")
async def approve_prospect(prospect_id: int):
    """Approve a prospect for posting."""
    session = SessionLocal()
    try:
        prospect_repo = ProspectRepository(session)
        prospect_repo.update_status(prospect_id, "approved")
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        session.close()


@app.post("/api/archive/{prospect_id}")
async def archive_prospect(prospect_id: int):
    """Archive a prospect."""
    session = SessionLocal()
    try:
        prospect_repo = ProspectRepository(session)
        prospect_repo.archive(prospect_id)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        session.close()


@app.get("/api/gaper-keywords")
async def get_gaper_keywords():
    """Extract search keywords from gaper.io for discovery."""
    from src.infrastructure.discovery.gaper_keywords import extract_keywords_from_gaper
    try:
        keywords = extract_keywords_from_gaper()
        return {"success": True, "keywords": keywords}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/stats")
async def get_stats():
    """Get current stats as JSON (for live updates)."""
    session = SessionLocal()
    try:
        tracked_repo = TrackedURLRepository(session)
        prospect_repo = ProspectRepository(session)

        all_urls = tracked_repo.get_all()
        all_prospects = prospect_repo.get_all()

        return {
            "total_urls": len(all_urls),
            "total_prospects": len(all_prospects),
            "discovered": len([p for p in all_prospects if p.status in ("discovered", "scraped")]),
            "relevant": len([p for p in all_prospects if p.status == "relevant"]),
            "drafted": len([p for p in all_prospects if p.status == "drafted"]),
            "approved": len([p for p in all_prospects if p.status == "approved"]),
            "posted": len([p for p in all_prospects if p.status == "posted"]),
            "archived": len([p for p in all_prospects if p.status == "archived"]),
        }
    finally:
        session.close()


@app.get("/api/activity")
async def get_activity(limit: int = 10):
    """Get recent activity logs as JSON (for live updates)."""
    session = SessionLocal()
    try:
        audit_repo = AuditLogRepository(session)
        logs = audit_repo.get_recent(limit=limit)
        return {
            "logs": [
                {
                    "action": log.action,
                    "details": (log.details or "")[:80],
                    "time": log.created_at.strftime("%H:%M") if log.created_at else "",
                }
                for log in logs
            ]
        }
    finally:
        session.close()


# === Posting Endpoints ===

@app.post("/api/post/{prospect_id}")
async def trigger_post(prospect_id: int):
    """Post an approved prospect directly (no Celery needed)."""
    from datetime import datetime as dt, timezone
    from src.infrastructure.posting.session_manager import SessionManager
    from src.infrastructure.posting import get_poster

    session = SessionLocal()
    try:
        prospect_repo = ProspectRepository(session)
        prospect = prospect_repo.get_by_id(prospect_id)
        if not prospect:
            return {"success": False, "error": "Prospect not found"}
        if prospect.status not in ("approved", "post_failed"):
            return {"success": False, "error": f"Status is '{prospect.status}', must be 'approved' or 'post_failed'"}

        # Load session cookies
        sm = SessionManager(session)
        cookies = sm.get_cookies(prospect.domain)
        if not cookies:
            return {"success": False, "error": f"No saved session for {prospect.domain}. Go to Sessions page and log in first."}

        # Get poster and execute
        try:
            poster = get_poster(prospect.domain)
        except ValueError:
            return {"success": False, "error": f"Unknown platform: {prospect.domain}"}

        # Run async poster properly
        result = await poster.post_reply_async(
            url=prospect.url,
            content=prospect.draft_content,
            cookies=cookies,
        )

        if result.success:
            prospect.status = "posted"
            prospect.posted_at = dt.now(timezone.utc)
            prospect.posted_url = result.post_url or prospect.url
            prospect.post_error = ""
        else:
            prospect.status = "post_failed"
            prospect.post_error = result.error or "Unknown error"
            prospect.updated_at = dt.now(timezone.utc)
        session.commit()

        audit_repo = AuditLogRepository(session)
        audit_repo.log_action(
            action="posted" if result.success else "post_failed",
            details=str(result.to_dict()),
            prospect_id=prospect_id,
        )

        return result.to_dict()
    finally:
        session.close()


@app.get("/api/sessions")
async def list_sessions():
    """List all platform session statuses."""
    from src.infrastructure.posting.session_manager import SessionManager

    session = SessionLocal()
    try:
        sm = SessionManager(session)
        sessions = sm.get_all_sessions()
        return {"success": True, "sessions": sessions}
    finally:
        session.close()


async def _solve_turnstile_if_present(page, page_url: str):
    """Detect Turnstile CAPTCHA on page and solve via 2Captcha."""
    try:
        # Look for Turnstile iframe or widget
        turnstile_frame = page.frame_locator("iframe[src*='turnstile'], iframe[src*='challenges.cloudflare.com']")
        turnstile_div = page.locator("[data-sitekey*='0x'], div.cf-turnstile")

        sitekey = None

        # Try getting sitekey from div attribute
        if await turnstile_div.count() > 0:
            sitekey = await turnstile_div.first.get_attribute("data-sitekey")

        # Try getting sitekey from intercepted params
        if not sitekey:
            params = await page.evaluate("window.__turnstileParams || null")
            if params and params.get("sitekey"):
                sitekey = params["sitekey"]

        if not sitekey:
            return

        print(f"Turnstile detected, sitekey={sitekey[:20]}... Solving via 2Captcha...")

        from src.infrastructure.posting.captcha_solver import solve_turnstile
        token = await solve_turnstile(sitekey=sitekey, page_url=page_url)

        if not token:
            print("2Captcha: no token returned")
            return

        # Inject token into the hidden input
        await page.evaluate(f"""
            const input = document.querySelector('[name="cf-turnstile-response"], [name="g-recaptcha-response"]');
            if (input) {{
                input.value = '{token}';
                input.dispatchEvent(new Event('input', {{bubbles: true}}));
                input.dispatchEvent(new Event('change', {{bubbles: true}}));
            }}
            // Also try calling the callback directly
            if (window.__turnstileCallback) {{
                window.__turnstileCallback('{token}');
            }}
            // Try clicking submit/verify button
            const btn = document.querySelector('button[type="submit"], input[type="submit"], .cf-turnstile-error button');
            if (btn) btn.click();
        """)
        print(f"Turnstile token injected")

    except Exception as e:
        print(f"Turnstile solve skipped: {e}")


@app.post("/api/sessions/import-cookies/{domain:path}")
async def import_cookies(domain: str, request: Request):
    """Import cookies from JSON (e.g., exported from Cookie Editor extension)."""
    from src.infrastructure.posting.session_manager import SessionManager
    from datetime import timedelta

    session = SessionLocal()
    try:
        body = await request.json()
        cookies = body.get("cookies", [])

        if not cookies:
            return {"success": False, "error": "No cookies provided"}

        # Normalize cookies - Cookie Editor exports in different formats
        normalized = []
        for c in cookies:
            cookie = {
                "name": c.get("name", ""),
                "value": c.get("value", ""),
                "domain": c.get("domain", ""),
                "path": c.get("path", "/"),
            }
            # Handle expiration
            exp = c.get("expires") or c.get("expirationDate")
            if exp and isinstance(exp, (int, float)) and exp > 0:
                cookie["expires"] = float(exp)

            # Handle flags
            if c.get("httpOnly") is not None:
                cookie["httpOnly"] = bool(c["httpOnly"])
            if c.get("secure") is not None:
                cookie["secure"] = bool(c["secure"])

            # Handle sameSite - Playwright only accepts "Strict", "Lax", "None"
            ss = c.get("sameSite", "Lax")
            if ss in ("Strict", "Lax", "None"):
                cookie["sameSite"] = ss
            elif ss == "no_restriction":
                cookie["sameSite"] = "None"
            else:
                cookie["sameSite"] = "Lax"

            # __Host- prefix cookies are auto-managed by browser, skip them
            if cookie["name"].startswith("__Host-"):
                continue

            normalized.append(cookie)

        logger.info(f"Importing {len(normalized)} cookies for {domain}: {[(c['name'], c['domain']) for c in normalized[:5]]}")

        # Fix domain for platforms with subdomains (e.g., Hashnode blogs are on *.hashnode.com)
        if domain == "hashnode.com":
            for c in normalized:
                if c["domain"] == "hashnode.com":
                    c["domain"] = ".hashnode.com"
                    logger.info(f"Fixed domain for {c['name']}: hashnode.com -> .hashnode.com")

        sm = SessionManager(session)
        sm.save_cookies(domain, normalized, expires_at=datetime.now(timezone.utc) + timedelta(days=30))
        return {"success": True, "cookies_count": len(normalized), "domain": domain}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        session.close()


@app.post("/api/sessions/capture/{domain:path}")
async def capture_session(domain: str):
    """Launch Playwright to capture login cookies for a platform.
    Opens a visible browser. Detects login automatically and captures cookies.
    """
    import asyncio
    from playwright.async_api import async_playwright
    from src.infrastructure.posting.session_manager import SessionManager
    from datetime import timedelta

    PLATFORM_CONFIG = {
        "reddit.com": {"url": "https://www.reddit.com", "logged_in_selector": "#email-collection-tooltip, a[href='/user/'], header button[aria-label='user menu']"},
        "dev.to": {"url": "https://dev.to/enter", "logged_in_selector": "a.profile-preview-card__trigger, a[href='/dashboard'], .crayons-header__menu"},
        "stackoverflow.com": {"url": "https://stackoverflow.com/users/login", "logged_in_selector": ".my-profile, .topbar-icon, .js-topbar-telemetry, a[href*='/users/edit/']"},
        "news.ycombinator.com": {"url": "https://news.ycombinator.com/login", "logged_in_selector": "a[href='user?id='], span.pagetop a:last-child"},
        "hashnode.com": {"url": "https://hashnode.com", "logged_in_selector": "button[data-testid='user-menu'], a[href*='/dashboard']"},
        "medium.com": {"url": "https://medium.com", "logged_in_selector": "button[aria-label='User menu'], img[data-testid='userAvatar'], a[href*='/settings'], img[alt*='Avatar']"},
    }

    config = PLATFORM_CONFIG.get(domain)
    if not config:
        return {"success": False, "error": f"Unknown platform: {domain}"}

    try:
        async with async_playwright() as p:
            # Use real Chrome to avoid bot detection (Chromium is fingerprinted)
            browser = await p.chromium.launch(
                headless=False,
                channel="chrome",
                args=[
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            )
            # Remove webdriver flag
            page = await context.new_page()
            await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            await page.goto(config["url"], wait_until="domcontentloaded", timeout=60000)

            # Auto-solve Turnstile CAPTCHA if present
            await _solve_turnstile_if_present(page, config["url"])

            # Poll for login detection (max 5 minutes)
            logged_in = False
            for i in range(60):  # 60 x 5 seconds = 5 minutes
                await page.wait_for_timeout(5000)
                current_url = page.url
                try:
                    selector = config["logged_in_selector"]
                    if await page.locator(selector).count() > 0:
                        logged_in = True
                        print(f"[SESSION] {domain}: logged in (selector) at {current_url}")
                        break
                except Exception:
                    pass
                # Cookie-based fallback: check for auth cookies
                try:
                    auth_cookies = await context.cookies()
                    auth_names = {c["name"] for c in auth_cookies}
                    # SO uses 'acct', dev.to uses '_devto', reddit uses 'reddit_session', medium uses 'prism' or 'sid'
                    if any(n in auth_names for n in ["acct", "_devto", "reddit_session", " loggedIn", "user", "prism", "sid", "_xsrf"]):
                        logged_in = True
                        print(f"[SESSION] {domain}: logged in (cookie) at {current_url}")
                        break
                    if i % 6 == 0:
                        domain_cookies = [c["name"] for c in auth_cookies if domain in c.get("domain", "")]
                        print(f"[SESSION] {domain}: cookies on {domain}: {domain_cookies}")
                except Exception:
                    pass
                if i % 6 == 0:
                    print(f"[SESSION] {domain}: waiting... ({i*5}s) url={current_url}")
                # Retry CAPTCHA solve every 15 seconds if still not logged in
                if i > 0 and i % 3 == 0:
                    await _solve_turnstile_if_present(page, config["url"])

            if not logged_in:
                await browser.close()
                return {"success": False, "error": "Login not detected within 5 minutes. Try again."}

            # Wait a moment for cookies to settle
            await page.wait_for_timeout(2000)
            cookies = await context.cookies()
            await browser.close()

        if not cookies:
            return {"success": False, "error": "No cookies captured"}

        # Normalize cookies for Playwright compatibility
        normalized = []
        for c in cookies:
            ss = c.get("sameSite", "Lax")
            if ss is None or ss not in ("Strict", "Lax", "None"):
                ss = "Lax"
            normalized.append({
                "name": c["name"],
                "value": c["value"],
                "domain": c.get("domain", ""),
                "path": c.get("path", "/"),
                "httpOnly": bool(c.get("httpOnly", False)),
                "secure": bool(c.get("secure", False)),
                "sameSite": ss,
                "expires": c.get("expires", -1),
            })

        session = SessionLocal()
        try:
            sm = SessionManager(session)
            sm.save_cookies(domain, normalized, expires_at=datetime.now(timezone.utc) + timedelta(days=30))
            return {"success": True, "cookies_count": len(normalized), "domain": domain}
        finally:
            session.close()

    except Exception as e:
        return {"success": False, "error": str(e)}


@app.delete("/api/sessions/{domain:path}")
async def delete_session(domain: str):
    """Invalidate a platform session."""
    from src.infrastructure.posting.session_manager import SessionManager

    session = SessionLocal()
    try:
        sm = SessionManager(session)
        sm.invalidate_session(domain)
        return {"success": True, "message": f"Session for {domain} invalidated"}
    finally:
        session.close()


# === Platform Config Endpoints ===

# === Article Endpoints ===

@app.get("/articles", response_class=HTMLResponse)
async def articles_page(request: Request):
    """Articles management page."""
    return templates.TemplateResponse(
        request=request,
        name="articles.html",
        context={},
    )


@app.post("/api/articles/suggest-topics")
async def suggest_topics():
    """Generate article topic suggestions from gaper.io content, excluding already published titles."""
    from src.infrastructure.gemini_service import GeminiLLMService
    from src.infrastructure.discovery.gaper_keywords import extract_keywords_from_gaper, GAPER_PAGES
    from src.infrastructure.scrapers.static_scraper import StaticScraper
    import src.config as config

    try:
        llm = GeminiLLMService(api_key=config.GEMINI_API_KEY)
        scraper = StaticScraper(timeout=20)

        all_content = []
        for url in GAPER_PAGES:
            try:
                result = scraper.scrape(url)
                if not result.is_empty and len(result.body) > 100:
                    all_content.append(f"Page: {url}\n{result.body[:2000]}")
            except Exception:
                pass

        if not all_content:
            return {"success": False, "error": "Could not fetch gaper.io content"}

        # Get already published article titles to exclude
        already_published = []
        if config.DEVTO_API_KEY:
            try:
                from src.infrastructure.devto_repository import DevtoArticleRepository
                devto_repo = DevtoArticleRepository(api_key=config.DEVTO_API_KEY)
                for a in devto_repo.get_my_articles():
                    if a.title:
                        already_published.append(a.title)
            except Exception:
                pass
        if config.WP_ACCESS_TOKEN and config.WP_SITE_ID:
            try:
                from src.infrastructure.wordpress_repository import WordPressArticleRepository
                wp_repo = WordPressArticleRepository(access_token=config.WP_ACCESS_TOKEN, site_id=config.WP_SITE_ID)
                for a in wp_repo.get_my_articles():
                    if a.title:
                        already_published.append(a.title)
            except Exception:
                pass

        exclude_str = "\n".join(f"- {t}" for t in already_published) if already_published else "(none published yet)"

        combined = "\n\n".join(all_content)
        prompt = f"""Based on content from gaper.io (an AI agent platform for businesses), suggest 10 article topics.

The articles should be helpful developer-focused content that naturally relates to gaper.io's products (AI agents, chatbots, customer support automation, LLM deployment).

Topics should be:
- Tutorial or how-to style
- Relevant to developers building AI-powered apps
- Naturally mention or relate to AI agent deployment (gaper.io)
- Specific and actionable (not vague)

DO NOT suggest these already published titles:
{exclude_str}

FORMAT: Return ONLY a JSON array of objects with "title", "description", "keywords", and "strategy" fields.
strategy must be one of: "tutorial", "howto", "opinion"
Example:
[
  {{"title": "How to Deploy AI Agents for Customer Support", "description": "Step-by-step guide to deploying AI agents", "keywords": ["ai agents", "customer support", "deployment"], "strategy": "tutorial"}},
  ...
]

Content from gaper.io:
{combined[:8000]}"""

        response = llm.generate(prompt=prompt, temperature=0.7)

        import json
        import re
        json_match = re.search(r'\[[\s\S]*\]', response)
        if json_match:
            topics = json.loads(json_match.group())
        else:
            return {"success": False, "error": "Could not parse topic suggestions"}

        return {"success": True, "topics": topics[:10]}
    except Exception as e:
        logger.error(f"Topic suggestion failed: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/articles/generate")
async def generate_article(request: Request):
    """Generate an article using LLM."""
    from src.domain.entities import Topic
    from src.infrastructure.content_generators import LLMContentGenerator
    from src.infrastructure.gemini_service import GeminiLLMService
    import src.config as config

    try:
        body = await request.json()
        topic_name = body.get("topic", "")
        strategy = body.get("strategy", "tutorial")
        keywords_str = body.get("keywords", "")
        backlink = body.get("backlink", True)

        if not topic_name:
            return {"success": False, "error": "Topic is required"}

        keywords = [k.strip() for k in keywords_str.split(",") if k.strip()] if keywords_str else [topic_name]

        topic = Topic(name=topic_name, description=topic_name, keywords=keywords)

        llm = GeminiLLMService(api_key=config.GEMINI_API_KEY)
        generator = LLMContentGenerator(llm_service=llm, strategy_type=strategy, backlink_enabled=backlink)
        article = generator.generate(topic)
        article = generator.review(article)

        return {
            "success": True,
            "title": article.title,
            "body": article.body_markdown,
            "description": article.description,
            "tags": article.tags,
        }
    except Exception as e:
        logger.error(f"Article generation failed: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/articles/publish")
async def publish_article(request: Request):
    """Publish article to selected platforms."""
    from src.domain.entities import Article
    from src.infrastructure.devto_repository import DevtoArticleRepository
    from src.infrastructure.wordpress_repository import WordPressArticleRepository
    import src.config as config

    try:
        body = await request.json()
        title = body.get("title", "")
        content = body.get("body", "")
        description = body.get("description", "")
        tags = body.get("tags", [])
        publish_devto = body.get("publish_devto", False)
        publish_wordpress = body.get("publish_wordpress", False)
        published = body.get("published", False)

        if not title or not content:
            return {"success": False, "error": "Title and body are required"}

        article = Article(
            title=title,
            body_markdown=content,
            description=description,
            tags=tags,
            published=published,
        )

        results = {}

        if publish_devto and config.DEVTO_API_KEY:
            try:
                repo = DevtoArticleRepository(api_key=config.DEVTO_API_KEY)
                result = repo.create(article)
                results["devto_url"] = result.url or ""
                results["devto_id"] = result.id
                logger.info(f"Published to Dev.to: {result.url}")
            except Exception as e:
                logger.error(f"Dev.to publish failed: {e}")
                results["devto_error"] = str(e)

        if publish_wordpress and config.WP_ACCESS_TOKEN and config.WP_SITE_ID:
            try:
                repo = WordPressArticleRepository(
                    access_token=config.WP_ACCESS_TOKEN,
                    site_id=config.WP_SITE_ID,
                )
                result = repo.create(article)
                results["wordpress_url"] = result.url or ""
                results["wordpress_id"] = result.id
                logger.info(f"Published to WordPress: {result.url}")
            except Exception as e:
                logger.error(f"WordPress publish failed: {e}")
                results["wordpress_error"] = str(e)

        if not results:
            return {"success": False, "error": "No platforms selected or missing API keys"}

        has_error = "devto_error" in results or "wordpress_error" in results
        has_success = "devto_url" in results or "wordpress_url" in results

        return {
            "success": has_success,
            **results,
            "error": "Partial failure" if has_error and has_success else (results.get("devto_error") or results.get("wordpress_error", "")),
        }
    except Exception as e:
        logger.error(f"Article publish failed: {e}")
        return {"success": False, "error": str(e)}


@app.get("/api/articles/list")
async def list_articles():
    """List articles from Dev.to and WordPress."""
    from src.infrastructure.devto_repository import DevtoArticleRepository
    from src.infrastructure.wordpress_repository import WordPressArticleRepository
    import src.config as config

    articles = []

    if config.DEVTO_API_KEY:
        try:
            repo = DevtoArticleRepository(api_key=config.DEVTO_API_KEY)
            for a in repo.get_my_articles():
                articles.append({
                    "id": a.id,
                    "platform": "Dev.to",
                    "title": a.title,
                    "url": a.url or "",
                    "status": "published" if a.published else "draft",
                    "published_at": a.published_at.isoformat() if a.published_at else "",
                })
        except Exception as e:
            logger.warning(f"Failed to fetch Dev.to articles: {e}")

    if config.WP_ACCESS_TOKEN and config.WP_SITE_ID:
        try:
            repo = WordPressArticleRepository(
                access_token=config.WP_ACCESS_TOKEN,
                site_id=config.WP_SITE_ID,
            )
            for a in repo.get_my_articles():
                articles.append({
                    "id": a.id,
                    "platform": "WordPress",
                    "title": a.title,
                    "url": a.url or "",
                    "status": "published" if a.published else "draft",
                    "published_at": a.published_at.isoformat() if a.published_at else "",
                })
        except Exception as e:
            logger.warning(f"Failed to fetch WordPress articles: {e}")

    return {"success": True, "articles": articles}


@app.post("/api/articles/publish-draft")
async def publish_draft_article(request: Request):
    """Publish an existing draft article."""
    from src.domain.entities import Article
    from src.infrastructure.devto_repository import DevtoArticleRepository
    from src.infrastructure.wordpress_repository import WordPressArticleRepository
    import src.config as config

    try:
        body = await request.json()
        article_id = body.get("article_id")
        platform = body.get("platform", "")

        if not article_id or not platform:
            return {"success": False, "error": "article_id and platform required"}

        if platform == "Dev.to" and config.DEVTO_API_KEY:
            repo = DevtoArticleRepository(api_key=config.DEVTO_API_KEY)
            articles = repo.get_my_articles()
            draft = next((a for a in articles if a.id == article_id), None)
            if not draft:
                return {"success": False, "error": "Draft not found on Dev.to"}
            draft.published = True
            result = repo.update(article_id, draft)
            return {"success": True, "url": result.url or "", "platform": "Dev.to"}

        if platform == "WordPress" and config.WP_ACCESS_TOKEN and config.WP_SITE_ID:
            repo = WordPressArticleRepository(
                access_token=config.WP_ACCESS_TOKEN,
                site_id=config.WP_SITE_ID,
            )
            articles = repo.get_my_articles()
            draft = next((a for a in articles if a.id == article_id), None)
            if not draft:
                return {"success": False, "error": "Draft not found on WordPress"}
            draft.published = True
            result = repo.update(article_id, draft)
            return {"success": True, "url": result.url or "", "platform": "WordPress"}

        return {"success": False, "error": f"Platform '{platform}' not configured"}
    except Exception as e:
        logger.error(f"Publish draft failed: {e}")
        return {"success": False, "error": str(e)}


@app.get("/api/articles/get/{platform}/{article_id}")
async def get_article_for_review(platform: str, article_id: int):
    """Fetch a draft article's content so it can be loaded into the form."""
    import src.config as config

    try:
        if platform == "Dev.to" and config.DEVTO_API_KEY:
            from src.infrastructure.devto_repository import DevtoArticleRepository
            repo = DevtoArticleRepository(api_key=config.DEVTO_API_KEY)
        elif platform == "WordPress" and config.WP_ACCESS_TOKEN and config.WP_SITE_ID:
            from src.infrastructure.wordpress_repository import WordPressArticleRepository
            repo = WordPressArticleRepository(
                access_token=config.WP_ACCESS_TOKEN,
                site_id=config.WP_SITE_ID,
            )
        else:
            return {"success": False, "error": f"Platform '{platform}' not configured"}

        articles = repo.get_my_articles()
        article = next((a for a in articles if a.id == article_id), None)
        if not article:
            return {"success": False, "error": "Article not found"}

        return {
            "success": True,
            "title": article.title or "",
            "body": article.body or "",
            "description": getattr(article, 'description', '') or '',
            "tags": getattr(article, 'tags', []) or [],
        }
    except Exception as e:
        logger.error(f"Get article failed: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/articles/update-and-publish")
async def update_and_publish_article(request: Request):
    """Update a draft article's content and publish it."""
    import src.config as config

    try:
        data = await request.json()
        article_id = data.get("article_id")
        platform = data.get("platform", "")
        title = data.get("title", "")
        body = data.get("body", "")
        description = data.get("description", "")
        tags = data.get("tags", [])

        if not article_id or not platform:
            return {"success": False, "error": "article_id and platform required"}
        if not title or not body:
            return {"success": False, "error": "title and body are required"}

        if platform == "Dev.to" and config.DEVTO_API_KEY:
            from src.infrastructure.devto_repository import DevtoArticleRepository
            from src.domain.entities import Article
            repo = DevtoArticleRepository(api_key=config.DEVTO_API_KEY)
            articles = repo.get_my_articles()
            existing = next((a for a in articles if a.id == article_id), None)
            if not existing:
                return {"success": False, "error": "Draft not found on Dev.to"}
            existing.title = title
            existing.body = body
            existing.description = description
            existing.tags = tags
            existing.published = True
            result = repo.update(article_id, existing)
            return {"success": True, "url": result.url or "", "platform": "Dev.to"}

        if platform == "WordPress" and config.WP_ACCESS_TOKEN and config.WP_SITE_ID:
            from src.infrastructure.wordpress_repository import WordPressArticleRepository
            from src.domain.entities import Article
            repo = WordPressArticleRepository(
                access_token=config.WP_ACCESS_TOKEN,
                site_id=config.WP_SITE_ID,
            )
            articles = repo.get_my_articles()
            existing = next((a for a in articles if a.id == article_id), None)
            if not existing:
                return {"success": False, "error": "Draft not found on WordPress"}
            existing.title = title
            existing.body = body
            existing.description = description
            existing.tags = tags
            existing.published = True
            result = repo.update(article_id, existing)
            return {"success": True, "url": result.url or "", "platform": "WordPress"}

        return {"success": False, "error": f"Platform '{platform}' not configured"}
    except Exception as e:
        logger.error(f"Update and publish failed: {e}")
        return {"success": False, "error": str(e)}


# === Platform Config Endpoints ===

@app.get("/platforms", response_class=HTMLResponse)
async def platforms_page(request: Request):
    """Platforms management page."""
    from src.infrastructure.platform_config import PlatformConfigService
    pcs = PlatformConfigService()
    platforms = pcs.get_all()
    return templates.TemplateResponse(
        request=request,
        name="platforms.html",
        context={"platforms": platforms},
    )


@app.get("/api/platforms")
async def get_platforms():
    """Return all platform configs as JSON."""
    from src.infrastructure.platform_config import PlatformConfigService
    pcs = PlatformConfigService()
    return {"success": True, "platforms": pcs.get_all()}


@app.post("/api/platforms/toggle-search/{domain}")
async def toggle_platform_search(domain: str, enabled: bool = Form(...)):
    """Toggle search_enabled for a platform."""
    from src.infrastructure.platform_config import PlatformConfigService
    pcs = PlatformConfigService()
    ok = pcs.toggle_search(domain, enabled)
    if not ok:
        return {"success": False, "error": f"Platform '{domain}' not found"}
    return {"success": True, "message": f"{domain} search={'enabled' if enabled else 'disabled'}"}


@app.post("/api/platforms/toggle-post/{domain}")
async def toggle_platform_post(domain: str, enabled: bool = Form(...)):
    """Toggle post_enabled for a platform."""
    from src.infrastructure.platform_config import PlatformConfigService
    pcs = PlatformConfigService()
    ok = pcs.toggle_post(domain, enabled)
    if not ok:
        return {"success": False, "error": f"Platform '{domain}' not found"}
    return {"success": True, "message": f"{domain} post={'enabled' if enabled else 'disabled'}"}


@app.post("/api/platforms/toggle/{domain}")
async def toggle_platform(domain: str, enabled: bool = Form(...)):
    """Toggle enabled for a platform."""
    from src.infrastructure.platform_config import PlatformConfigService
    pcs = PlatformConfigService()
    ok = pcs.toggle_enabled(domain, enabled)
    if not ok:
        return {"success": False, "error": f"Platform '{domain}' not found"}
    return {"success": True, "message": f"{domain}={'enabled' if enabled else 'disabled'}"}


@app.post("/api/platforms/add")
async def add_platform(domain: str = Form(...), serp_site_filter: str = Form("")):
    """Add a new platform."""
    from src.infrastructure.platform_config import PlatformConfigService
    pcs = PlatformConfigService()
    config = {}
    if serp_site_filter:
        config["serp_site_filter"] = serp_site_filter
    ok = pcs.add_platform(domain, config)
    if not ok:
        return {"success": False, "error": f"Platform '{domain}' already exists"}
    return {"success": True, "message": f"Platform '{domain}' added"}


@app.post("/api/platforms/remove/{domain}")
async def remove_platform(domain: str):
    """Remove a platform."""
    from src.infrastructure.platform_config import PlatformConfigService
    pcs = PlatformConfigService()
    ok = pcs.remove_platform(domain)
    if not ok:
        return {"success": False, "error": f"Platform '{domain}' not found"}
    return {"success": True, "message": f"Platform '{domain}' removed"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
