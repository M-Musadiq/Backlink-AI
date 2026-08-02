"""Generate search queries from keywords for broad discovery."""
import logging
from typing import List

logger = logging.getLogger(__name__)


def generate_queries(keywords: List[str]) -> List[str]:
    return [kw.strip() for kw in keywords if kw.strip()]


def deduplicate_queries(queries: List[str]) -> List[str]:
    seen = set()
    result = []
    for q in queries:
        ql = q.lower().strip()
        if ql not in seen:
            seen.add(ql)
            result.append(q)
    return result
