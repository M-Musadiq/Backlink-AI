"""Seed gaper.io content into RAG vector store."""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, ".")

import logging
from sqlalchemy import text
from src.infrastructure.database import SessionLocal
from src.infrastructure.llm.rag_retrieval import RAGRetrieval
from src.infrastructure.scrapers.static_scraper import StaticScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# Gaper.io pages to embed
GAPER_PAGES = [
    {"url": "https://gaper.io/", "title": "Gaper.io - AI Agent Deployment Platform", "description": "Main landing page"},
    {"url": "https://gaper.io/ai-agents-for-business", "title": "AI Agents for Business", "description": "Guide to AI agents for business"},
    {"url": "https://gaper.io/build-vs-buy-ai-agents", "title": "Build vs Buy AI Agents", "description": "When to buy vs build"},
    {"url": "https://gaper.io/ai-agents-vs-chatbots", "title": "AI Agents vs Chatbots", "description": "Why agents resolve work chatbots deflect"},
    {"url": "https://gaper.io/ai-agent-development-cost", "title": "AI Agent Development Cost", "description": "What drives cost and how to budget"},
    {"url": "https://gaper.io/deploy-ai-agents", "title": "Deploy AI Agents", "description": "Production deployment guide"},
    {"url": "https://gaper.io/ai-agents-for-customer-support", "title": "AI Agents for Customer Support", "description": "Support automation"},
    {"url": "https://gaper.io/ai-agent-use-cases", "title": "AI Agent Use Cases", "description": "Real-world use cases"},
]


def seed():
    print("=" * 60)
    print("GAPER.IO CONTENT SEEDING")
    print("=" * 60)

    session = SessionLocal()
    try:
        rag = RAGRetrieval(session)

        # Drop old table (may have wrong vector dimension) and recreate
        session.execute(text("DROP TABLE IF EXISTS gaper_content"))
        session.commit()
        rag.ensure_table()
        session.commit()
        print("Table recreated with vector(3072) for Gemini embeddings")
        print(f"Existing embeddings: {rag.count()}")
        print()

        scraper = StaticScraper(timeout=20)

        for page in GAPER_PAGES:
            print(f"Scraping: {page['url']}")
            try:
                content = scraper.scrape(page["url"])

                if content.is_empty:
                    print(f"  SKIP: empty content")
                    continue

                # Chunk the content (simple approach: split by paragraphs)
                chunks = chunk_text(content.body, max_chars=1500)

                for i, chunk in enumerate(chunks):
                    if len(chunk.strip()) < 100:
                        continue

                    title = f"{page['title']} (chunk {i+1})" if len(chunks) > 1 else page["title"]
                    rag.embed_and_store(
                        title=title,
                        content=chunk,
                        url=page["url"],
                    )
                    print(f"  Embedded chunk {i+1}: {len(chunk)} chars")

            except Exception as e:
                print(f"  ERROR: {e}")

        print(f"\nTotal embeddings: {rag.count()}")
        print("=" * 60)
        print("DONE")

    finally:
        session.close()


def chunk_text(text: str, max_chars: int = 1500) -> list:
    """Split text into chunks by paragraphs."""
    paragraphs = text.split("\n\n")
    chunks = []
    current_chunk = ""

    for para in paragraphs:
        if len(current_chunk) + len(para) > max_chars:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = para
        else:
            current_chunk += "\n\n" + para if current_chunk else para

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


if __name__ == "__main__":
    seed()
