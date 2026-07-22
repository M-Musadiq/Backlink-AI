import os
from pathlib import Path
from dotenv import load_dotenv
import logging

BASE_DIR = Path(__file__).resolve().parent.parent

env_path = BASE_DIR / '.env'
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger("DevToAgent")

logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)

# === Existing Config ===
DEVTO_API_KEY = os.getenv("DEVTO_API_KEY")

WP_ACCESS_TOKEN = os.getenv("WP_ACCESS_TOKEN")
WP_SITE_ID = os.getenv("WP_SITE_ID")
WP_SITE_URL = os.getenv("WP_SITE_URL")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemini-2.5-flash")

# === Database ===
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://backlink:backlink@localhost:5432/backlink")

# === Redis ===
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# === 2Captcha ===
TWOCAPTCHA_API_KEY = os.getenv("TWOCAPTCHA_API_KEY")

# === SERP API ===
# Option 1: DuckDuckGo (free, unlimited) - works without any key
# Option 2: Serper.dev (2,500 free credits, Google results) - set SERPER_API_KEY
SERPER_API_KEY = os.getenv("SERPER_API_KEY")

# === Auth Vault ===
VAULT_ENCRYPTION_KEY = os.getenv("VAULT_ENCRYPTION_KEY")

# === Dashboard ===
DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "0.0.0.0")
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8000"))


def check_configuration():
    warnings = []
    if not DEVTO_API_KEY:
        warnings.append("DEVTO_API_KEY is not configured. Set it in .env file.")
    if not TWOCAPTCHA_API_KEY or TWOCAPTCHA_API_KEY == "PASTE_YOUR_2CAPTCHA_KEY_HERE":
        warnings.append("TWOCAPTCHA_API_KEY is not configured. Set it in .env file.")
    if not VAULT_ENCRYPTION_KEY:
        warnings.append("VAULT_ENCRYPTION_KEY is not configured. Set it in .env file.")

    if warnings:
        for warning in warnings:
            logger.warning(warning)
        return False

    logger.info("Configuration validation succeeded.")
    return True
