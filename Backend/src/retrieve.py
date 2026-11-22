"""Step 2 of the RAG pipeline: retrieval.

Embeds a user question with the same embedding model used at ingest time,
then searches the shared DuckDB + HNSW course index for the most relevant
chunks. The voice assistant reaches this same pipeline through /ask.

Runs constantly (once per question), as opposed to ingest which runs once.
"""
from __future__ import annotations

from langchain_core.documents import Document
from langchain_ollama import OllamaEmbeddings

from src.config import (
    NEIGHBOR_PAGES,
    NEIGHBOR_TOP_N,
    OLLAMA_EMBED_MODEL,
    OLLAMA_HOST,
    RETRIEVE_K,
)
from src.query import rewrite_query
from src.vectorstore import store


def _embeddings() -> OllamaEmbeddings:
    return OllamaEmbeddings(base_url=OLLAMA_HOST, model=OLLAMA_EMBED_MODEL)


def _norm(text: str) -> str:
    return " ".join(text.split()).lower()


def _dedupe_top_k(pairs: list, k: int) -> list:
    """Best-scoring k pairs with identical chunk text collapsed."""
    seen: set[str] = set()
    out = []
    for doc, score in sorted(pairs, key=lambda p: p[1]):
        key = _norm(doc.page_content)
        if key in seen:
            continue
        seen.add(key)
        out.append((doc, score))
        if len(out) == k:
            break
    return out


def retrieve(query: str, k: int = RETRIEVE_K) -> list:
    """Return the top-k distinct documents most similar to the query.

    Scores are DuckDB cosine distances (lower = more similar). generate() uses
    them as the relevance gate, so keep the raw distance rather than inverting
    it into a similarity percentage.
    """
    embeddings = _embeddings()
    fetch_k = k * 3  # over-fetch so de-duplication still leaves k distinct chunks

    queries = [query]
    rewritten = rewrite_query(query)
    if rewritten and rewritten != query.strip():
        queries.append(rewritten)

    pairs: list[tuple[Document, float]] = []
    for text in queries:
        pairs.extend(store.search(embeddings.embed_query(text), fetch_k))

    return _dedupe_top_k(pairs, k)


def neighbor_chunks(hits: list, pages: int = NEIGHBOR_PAGES, top_n: int = NEIGHBOR_TOP_N) -> list:
    """Chunks from the pages adjacent to the best hits, for extra LLM context.

    `hits` are (document, score) pairs, best first. Chunks already present in
    `hits` are skipped. Returns Documents only (no scores): neighbors are
    context, not evidence, so they are never cited or distance-gated.
    """
    if pages <= 0 or not hits:
        return []

    have = {_norm(doc.page_content) for doc, _ in hits}
    extra = []
    for doc, _ in hits[:top_n]:
        source = doc.metadata.get("source")
        page = doc.metadata.get("page")
        if source is None or not isinstance(page, int):
            continue
        for p in range(page - pages, page + pages + 1):
            if p == page or p < 0:
                continue
            for found in store.source_page_chunks(str(source), p):
                key = _norm(found.page_content)
                if key in have:
                    continue
                have.add(key)
                extra.append(found)
    return extra


def has_any_documents() -> bool:
    """Quick check whether the shared course index has any chunks."""
    try:
        return store.count() > 0
    except Exception:
        return False
