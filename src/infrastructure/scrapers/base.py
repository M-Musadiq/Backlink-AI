"""Shared utilities for all scraper types."""

import re
import logging
from urllib.parse import urlparse
from typing import Optional

from markdownify import markdownify as md
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

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


def extract_metadata(soup: BeautifulSoup) -> dict:
    """Extract common metadata from HTML (title, author, date, description)."""
    meta = {}

    # Title: og:title > <title> > h1
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        meta["title"] = og_title["content"].strip()
    elif soup.title and soup.title.string:
        meta["title"] = soup.title.string.strip()
    else:
        h1 = soup.find("h1")
        if h1:
            meta["title"] = h1.get_text(strip=True)

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
