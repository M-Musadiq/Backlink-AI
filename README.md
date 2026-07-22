# AI Backlink Campaign System

An AI-powered backlink generation system that discovers forum threads, scrapes content, drafts replies with Gaper.io backlinks, and posts them across platforms.

---

## Tech Stack
- **Python 3.12+**
- **LLM**: Gemini API (paid key)
- **Scraping**: 4-tier auto-escalation (API → Static → Playwright → LLM)
- **Browser Automation**: browser-use + Playwright
- **Database**: Supabase (PostgreSQL + pgvector)
- **Queue**: Upstash Redis
- **Dashboard**: FastAPI + Jinja2
- **Deployment**: Docker + Google Cloud Run

---

## Project Structure
```text
backlink/
├── Dockerfile              # Container image for Cloud Run
├── .dockerignore           # Docker build exclusions
├── .github/workflows/
│   └── deploy.yml          # GitHub Actions CI/CD pipeline
├── .env                    # Credentials & API keys (not committed)
├── env.example             # Template for .env
├── requirements.txt        # Dependencies
├── data/
│   └── platform_configs.json  # Platform search/post config
├── src/
│   ├── config.py           # Central config
│   ├── main.py             # CLI entry point
│   ├── domain/             # Domain entities & interfaces
│   ├── infrastructure/
│   │   ├── database.py     # SQLAlchemy engine
│   │   ├── models.py       # ORM models
│   │   ├── discovery/      # SERP/RSS discovery
│   │   ├── scrapers/       # 4-tier scraping
│   │   ├── llm/            # RAG, relevance, drafting
│   │   ├── posting/        # Platform posters (browser-use)
│   │   ├── repositories/   # Data access layer
│   │   └── tasks/          # Background tasks
│   └── presentation/
│       ├── app.py          # FastAPI dashboard + API
│       └── templates/      # HTML templates
```

---

## Setup

### 1. Virtual Environment
```bash
python -m venv .venv
.venv\Scripts\Activate.ps1  # Windows
source .venv/bin/activate   # Mac/Linux
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
playwright install chromium
```

### 3. Configure `.env`
```env
# Supabase (PostgreSQL)
DATABASE_URL=postgresql://postgres.[ref]:[password]@aws-1-ap-northeast-2.pooler.supabase.com:6543/postgres

# Upstash Redis
REDIS_URL=rediss://:[password]@apn1-1-ucl2.upstash.io:6379

# Gemini API
GEMINI_API_KEY=your_key

# Search (Serper.dev)
SERPER_API_KEY=your_key

# 2Captcha (for CAPTCHA solving)
TWOCAPTCHA_API_KEY=your_key

# Dev.to API
DEVTO_API_KEY=your_key

# Vault Encryption Key
VAULT_ENCRYPTION_KEY=your_key
```

### 4. Run Dashboard
```bash
python -m uvicorn src.presentation.app:app --host 0.0.0.0 --port 8000
```

---

## Dashboard Pages

| Page | URL | Description |
|------|-----|-------------|
| Dashboard | `/` | Stats overview, discovery trigger |
| Prospects | `/prospects` | Review/approve drafted replies |
| Tracked URLs | `/urls` | All discovered threads |
| Sessions | `/sessions` | Platform login cookies |
| Platforms | `/platforms` | Enable/disable search per platform |
| Activity | `/activity` | Audit log |

---

## Platform Support

| Platform | Discovery | Scraping | Posting |
|----------|-----------|----------|---------|
| Reddit | ✅ | ✅ | ✅ (browser-use) |
| Dev.to | ✅ | ✅ | ✅ (browser-use) |
| Hashnode | ✅ | ✅ | ✅ (browser-use) |
| Hacker News | ✅ | ✅ | ✅ (browser-use) |
| Stack Overflow | ✅ | ✅ | ❌ (Turnstile blocked) |
| Medium | ✅ | ✅ | ❌ (reCAPTCHA Enterprise blocked) |

---

## Deployment (Google Cloud Run)

### Prerequisites
1. GCP project: `gaper-internship`
2. Service account with Cloud Run + Artifact Registry permissions
3. GitHub repository secrets configured

### GitHub Secrets Required
```
GCP_SA_KEY              # Service account JSON key
GEMINI_API_KEY          # Gemini API key
SERPER_API_KEY          # Serper.dev API key
TWOCAPTCHA_API_KEY      # 2Captcha API key
DEVTO_API_KEY           # Dev.to API key
DATABASE_URL            # Supabase connection string
REDIS_URL               # Upstash Redis URL
VAULT_ENCRYPTION_KEY    # Fernet encryption key
```

### Deploy
Push to `main` branch triggers automatic deployment:
```bash
git add .
git commit -m "your message"
git push origin main
```

### Cost Estimate
- **Idle**: $0 (min instances = 0)
- **Active**: ~$0.04/hour per instance
- **Free tier**: 180,000 vCPU-seconds/month
- **Expected**: $0-5/month for light usage

---

## Architecture

```
SERP/RSS Discovery
       ↓
  Dedup Check
       ↓
 4-Tier Scraping (API → Static → Playwright → LLM)
       ↓
  Guidelines Cache
       ↓
  Relevance Check (Gemini)
       ↓
  RAG Retrieval (pgvector)
       ↓
  LLM Drafting (Gemini)
       ↓
  Human Review (Dashboard)
       ↓
  Execution Router (5 platform types)
       ↓
  CRM Tracking
```
