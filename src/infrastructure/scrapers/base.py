"""Shared utilities for all scraper types."""

import re
import logging
from urllib.parse import urlparse
from typing import Optional

from markdownify import markdownify as md
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Titles that are clearly not the article's own title (bot gates, logins, etc.).
GENERIC_TITLE_MARKERS = (
    "just a moment",
    "verify you are human",
    "attention required",
    "access denied",
    "sign in",
    "log in",
    "login",
    "page not found",
    "not found",
    "captcha",
    "rate limit",
    "too many requests",
    "prove your humanity",
    "verification required",
    "suspicious activity",
    "you are blocked",
)


def title_from_url(url: str) -> str:
    """Derive a readable title from a URL slug as a last-resort fallback.

    Guarantees every page keeps its own exact title instead of borrowing a
    sibling article's title. Handles trailing id/hash suffixes:
    ``/learning-how-to-build-ai-agents-7349f3821c3d`` -> "Learning How To
    Build Ai Agents"; ``/p/1gH83v2-x`` -> "P 1G H83V2 X".
    """
    if not url:
        return ""
    try:
        path = urlparse(url).path
    except Exception:
        return ""
    segs = [s for s in path.split("/") if s and "@" not in s]
    if not segs:
        return ""
    best_slug = ""
    for seg in reversed(segs):
        # Drop trailing id/hash tokens iteratively until stable:
        #   medium hex suffix  -> -7349f3821c3d
        #   linkedin post code -> -NpPK (mixed case), trailing activity+digits
        while True:
            prev = seg
            seg = re.sub(r"-([0-9a-fA-F]{6,})(\.\w+)?$", "", seg)
            seg = re.sub(r"-([A-Za-z0-9]*[A-Z][A-Za-z0-9]*)$", "", seg)
            if seg == prev:
                break
        parts = [w for w in re.split(r"[\s\-_/.]+", seg) if w]
        if len(parts) >= 2:
            best_slug = " ".join(parts)
            break
    if not best_slug and segs:
        best_slug = re.sub(r"[\s\-_/.]+", " ", segs[-1])
    slug = re.sub(r"\s+", " ", best_slug).strip()
    words = [w for w in slug.split()]
    if not words:
        return ""
    return " ".join(words).title()


def best_title(title: str, url: str = "") -> str:
    """Pick the most reliable exact title for a scraped page, generically.

    Precedence:
    1. Non-empty scraped title that isn't a bot/login gate — cleaned.
    2. Title derived from the URL slug (never a sibling article's title).
    """
    t = (title or "").strip()
    t = re.sub(r"\s+", " ", t)
    low = t.lower()
    if t and len(t) >= 8 and not any(m in low for m in GENERIC_TITLE_MARKERS):
        return t
    return title_from_url(url)

# Realistic browser User-Agent
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
}

# Elements to strip from HTML before content extraction
STRIP_TAGS = [
    "script", "style", "noscript", "iframe", "svg",
    "nav", "footer", "header",
    "aside",
]

STRIP_SELECTORS = [
    "[role='navigation']",
    "[role='banner']",
    "[role='contentinfo']",
    ".sidebar", ".nav", ".navbar", ".footer", ".header",
    ".advertisement", ".ad", ".ads", ".adsbygoogle",
    ".cookie-banner", ".cookie-consent",
    ".share-buttons", ".social-share",
    ".related-posts", ".recommended",
    ".comments-section",  # We want the thread body, not all comments
]

# Selectors to find main content, in priority order
CONTENT_SELECTORS = [
    "article",
    "[role='main']",
    "main",
    ".post-content",
    ".article-content",
    ".entry-content",
    ".post-body",
    ".article-body",
    ".content-body",
    ".markdown-body",
    "#content",
    ".post",
]


def extract_domain(url: str) -> str:
    """Extract the domain (without www.) from a URL."""
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def clean_html_to_markdown(html: str) -> str:
    """Convert raw HTML to clean readable markdown."""
    if not html:
        return ""

    soup = BeautifulSoup(html, "html.parser")

    # Strip unwanted tags entirely
    for tag_name in STRIP_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    # Strip unwanted elements by CSS selector
    for selector in STRIP_SELECTORS:
        for el in soup.select(selector):
            el.decompose()

    # Convert to markdown
    text = md(str(soup), heading_style="ATX", bullets="-", strip=["img"])

    # Clean up excessive whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)

    return text.strip()


def extract_main_content(soup: BeautifulSoup) -> Optional[BeautifulSoup]:
    """Find the main content element using common selectors."""
    for selector in CONTENT_SELECTORS:
        el = soup.select_one(selector)
        if el and len(el.get_text(strip=True)) > 100:
            return el

    # Fallback: find the largest text block
    best = None
    best_len = 0
    for tag in soup.find_all(["div", "section"]):
        text_len = len(tag.get_text(strip=True))
        if text_len > best_len:
            best_len = text_len
            best = tag

    return best


def extract_metadata(soup: BeautifulSoup, url: str = "") -> dict:
    """Extract common metadata from HTML (title, author, date, description)."""
    meta = {}

    # Title: og:title > <title> > h1, then falls back to the URL slug.
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        meta["title"] = og_title["content"].strip()
    elif soup.title and soup.title.string:
        meta["title"] = soup.title.string.strip()
    else:
        h1 = soup.find("h1")
        if h1:
            meta["title"] = h1.get_text(strip=True)
    meta["title"] = best_title(meta.get("title", ""), url)

    # Author
    author_meta = soup.find("meta", attrs={"name": "author"})
    if author_meta and author_meta.get("content"):
        meta["author"] = author_meta["content"].strip()
    else:
        # Try schema.org or common class names
        author_el = soup.select_one(
            "[rel='author'], .author-name, .post-author, .byline, [itemprop='author']"
        )
        if author_el:
            meta["author"] = author_el.get_text(strip=True)

    # Published date
    time_el = soup.find("time")
    if time_el:
        meta["published_at"] = time_el.get("datetime", time_el.get_text(strip=True))
    else:
        date_meta = soup.find("meta", property="article:published_time")
        if date_meta and date_meta.get("content"):
            meta["published_at"] = date_meta["content"]

    # Description
    og_desc = soup.find("meta", property="og:description")
    if og_desc and og_desc.get("content"):
        meta["description"] = og_desc["content"].strip()
    else:
        desc_meta = soup.find("meta", attrs={"name": "description"})
        if desc_meta and desc_meta.get("content"):
            meta["description"] = desc_meta["content"].strip()

    return meta


def is_js_rendered_page(html: str) -> bool:
    """Heuristic check: does this page require JavaScript to render content?"""
    if not html:
        return True

    soup = BeautifulSoup(html, "html.parser")

    # Check for common SPA indicators
    noscript = soup.find("noscript")
    if noscript and "enable javascript" in noscript.get_text().lower():
        return True

    # Check if body has very little visible text
    body = soup.find("body")
    if body:
        visible_text = body.get_text(strip=True)
        if len(visible_text) < 200:
            return True

    # Check for React/Vue/Angular root elements with no content
    for root_id in ["root", "app", "__next", "__nuxt"]:
        el = soup.find(id=root_id)
        if el and len(el.get_text(strip=True)) < 50:
            return True

    return False
