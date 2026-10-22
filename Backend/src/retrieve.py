"""Step 2 of the RAG pipeline: retrieval.

Embeds a user question with the same embedding model used at ingest time,
then does a similarity search against the persisted Chroma store to pull
back the most relevant chunks.

Runs constantly (once per question), as opposed to ingest which runs once.
"""
from __future__ import annotations

from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
from langchain_ollama import OllamaEmbeddings

from src.config import (
    NEIGHBOR_PAGES,
    NEIGHBOR_TOP_N,
    OLLAMA_EMBED_MODEL,
    OLLAMA_HOST,
    RETRIEVE_K,
    VECTORSTORE_DIR,
)
from src.query import rewrite_query


def get_vectorstore() -> Chroma:
    """Reopen the persisted vector store without re-embedding everything."""
    embeddings = OllamaEmbeddings(
        base_url=OLLAMA_HOST,
        model=OLLAMA_EMBED_MODEL,
    )
    return Chroma(
        persist_directory=str(VECTORSTORE_DIR),
        embedding_function=embeddings,
    )


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
    """Return the top-k distinct documents most semantically similar to the query.

    Uses similarity_search_with_score: the score is Chroma's raw L2/euclidean
    distance (space='l2'), where LOWER = more similar. The distance is used
    by generate() as a relevance gate (see MAX_DISTANCE), so keep this method
    and DO NOT switch to with_relevance_scores, which inverts the scale.

    Searches with both the raw question and its cleaned-up rewrite, keeping
    each chunk's best distance, so the rewrite can only add recall.
    """
    vectorstore = get_vectorstore()
    fetch_k = k * 3  # over-fetch so de-duplication still leaves k distinct chunks
    pairs = vectorstore.similarity_search_with_score(query, k=fetch_k)

    rewritten = rewrite_query(query)
    if rewritten and rewritten != query.strip():
        pairs += vectorstore.similarity_search_with_score(rewritten, k=fetch_k)

    return _dedupe_top_k(pairs, k)


def neighbor_chunks(hits: list, pages: int = NEIGHBOR_PAGES, top_n: int = NEIGHBOR_TOP_N) -> list:
    """Chunks from the pages adjacent to the best hits, for extra LLM context.

    `hits` are (document, score) pairs, best first. Chunks already present in
    `hits` are skipped. Returns Documents only (no scores): neighbors are
    context, not evidence, so they are never cited or distance-gated.
    """
    if pages <= 0 or not hits:
        return []

    vectorstore = get_vectorstore()
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
            got = vectorstore.get(
                where={"$and": [{"source": source}, {"page": p}]},
                include=["documents", "metadatas"],
            )
            for text, meta in zip(got.get("documents") or [], got.get("metadatas") or []):
                key = _norm(text)
                if key in have:
                    continue
                have.add(key)
                extra.append(Document(page_content=text, metadata=meta or {}))
    return extra


def _has_missing_target(vectorstore: Chroma) -> bool:
    """Chroma requires a collection_name when the store is empty/new."""
    try:
        return vectorstore._collection.count() == 0  # type: ignore[attr-defined]
    except Exception:
        return True


def has_any_documents() -> bool:
    """Quick check whether the vector store has been populated."""
    try:
        vs = get_vectorstore()
        return not _has_missing_target(vs)
    except Exception:
        return False
