"""RAG Retrieval - embed content and query for relevant context."""
import logging
import json
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text

from src.infrastructure.llm_factory import get_llm

logger = logging.getLogger(__name__)

# Gemini embedding model
EMBEDDING_MODEL = "gemini-embedding-2"
EMBEDDING_DIM = 3072


class RAGRetrieval:
    """
    RAG (Retrieval-Augmented Generation) system.

    - Embeds gaper.io content chunks into pgvector
    - Queries for relevant context given a thread
    - Returns top-k relevant chunks for the drafter
    """

    def __init__(self, session: Session):
        self._session = session
        self._llm = get_llm()

    def embed_and_store(self, title: str, content: str, url: str = "") -> int:
        """
        Embed content and store in gaper_content table.

        Args:
            title: Content title
            content: Content text
            url: Source URL

        Returns:
            ID of stored record
        """
        embedding = self._get_embedding(content)

        result = self._session.execute(
            text(
                "INSERT INTO gaper_content (title, content, url, embedding) "
                "VALUES (:title, :content, :url, :embedding) RETURNING id"
            ),
            {
                "title": title,
                "content": content,
                "url": url,
                "embedding": json.dumps(embedding),
            },
        )
        self._session.commit()
        row = result.fetchone()
        logger.info(f"Stored embedding for '{title}' (id={row[0]})")
        return row[0]

    def query(self, query_text: str, top_k: int = 3) -> List[Dict]:
        """
        Query for relevant content using cosine similarity.

        Args:
            query_text: The query text (e.g., thread content)
            top_k: Number of results to return

        Returns:
            List of dicts with keys: title, content, url, similarity
        """
        query_embedding = self._get_embedding(query_text)
        query_vec_str = json.dumps(query_embedding)

        # Use raw connection to avoid SQLAlchemy parameter binding issues with pgvector
        conn = self._session.connection()
        result = conn.execute(
            text(
                "SELECT title, content, url, "
                "1 - (embedding <=> CAST(:query_vec AS vector)) as similarity "
                "FROM gaper_content "
                "ORDER BY embedding <=> CAST(:query_vec AS vector) "
                "LIMIT :top_k"
            ),
            {"query_vec": query_vec_str, "top_k": top_k},
        )

        results = []
        for row in result:
            results.append({
                "title": row[0],
                "content": row[1],
                "url": row[2],
                "similarity": float(row[3]),
            })

        logger.info(f"RAG query returned {len(results)} results (top similarity: {results[0]['similarity']:.3f})" if results else "RAG query returned 0 results")
        return results

    def get_context_for_drafter(self, thread_content: str, max_chars: int = 2000) -> str:
        """
        Get relevant context string for the drafter agent.

        Args:
            thread_content: The thread/question content
            max_chars: Maximum characters for context

        Returns:
            Formatted context string
        """
        results = self.query(thread_content, top_k=3)

        if not results:
            return "No relevant Gaper.io content found."

        context_parts = []
        total_chars = 0

        for r in results:
            chunk = f"--- {r['title']} (similarity: {r['similarity']:.2f}) ---\n{r['content'][:500]}"
            if total_chars + len(chunk) > max_chars:
                break
            context_parts.append(chunk)
            total_chars += len(chunk)

        return "\n\n".join(context_parts)

    def _get_embedding(self, text: str) -> List[float]:
        """Get embedding vector for text using Gemini Embedding API."""
        import requests

        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{EMBEDDING_MODEL}:embedContent?key={GEMINI_API_KEY}",
            headers={"Content-Type": "application/json"},
            json={
                "model": f"models/{EMBEDDING_MODEL}",
                "content": {"parts": [{"text": text[:8000]}]},
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["embedding"]["values"]

    def ensure_table(self):
        """Create gaper_content table if not exists (768-dim for Gemini)."""
        self._session.execute(text("""
            CREATE TABLE IF NOT EXISTS gaper_content (
                id SERIAL PRIMARY KEY,
                title TEXT,
                content TEXT,
                url TEXT,
                embedding vector(3072)
            )
        """))
        self._session.commit()

    def count(self) -> int:
        """Count stored embeddings."""
        result = self._session.execute(text("SELECT COUNT(*) FROM gaper_content"))
        return result.fetchone()[0]
