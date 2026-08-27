"""Step 2 of the RAG pipeline: retrieval.

Embeds a user question with the same embedding model used at ingest time,
then does a similarity search against the persisted Chroma store to pull
back the most relevant chunks.

Runs constantly (once per question), as opposed to ingest which runs once.
"""
from __future__ import annotations

from langchain_community.vectorstores import Chroma
from langchain_ollama import OllamaEmbeddings

from src.config import (
    OLLAMA_EMBED_MODEL,
    OLLAMA_HOST,
    RETRIEVE_K,
    VECTORSTORE_DIR,
)


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


def retrieve(query: str, k: int = RETRIEVE_K) -> list:
    """Return the top-k documents most semantically similar to the query.

    Uses similarity_search_with_score: the score is Chroma's raw L2/euclidean
    distance (space='l2'), where LOWER = more similar. The distance is used
    by generate() as a relevance gate (see MAX_DISTANCE), so keep this method
    and DO NOT switch to with_relevance_scores, which inverts the scale.
    """
    vectorstore = get_vectorstore()
    return vectorstore.similarity_search_with_score(query, k=k)


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
