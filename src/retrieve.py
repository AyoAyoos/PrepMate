"""Step 2 of the RAG pipeline: retrieval.

Embeds a user question with the same embedding model used at ingest time,
then does a similarity search against the persisted Chroma store to pull
back the most relevant chunks.
"""
from __future__ import annotations

from langchain_community.vectorstores import Chroma
from langchain_ollama import OllamaEmbeddings

from src.config import OLLAMA_EMBED_MODEL, OLLAMA_HOST, RETRIEVE_K, VECTORSTORE_DIR


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
    """Return the top-k documents most semantically similar to the query."""
    vectorstore = get_vectorstore()
    return vectorstore.similarity_search_with_relevance_scores(query, k=k)
