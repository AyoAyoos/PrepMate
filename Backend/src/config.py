"""Shared configuration loader.

Loads values from .env (see .env.example) so that the ingest, retrieve,
generate, and cli scripts all agree on the same settings.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(PROJECT_ROOT / ".env")


def _get(name: str, default: str) -> str:
    return os.getenv(name, default)


def _get_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _get_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


OLLAMA_HOST = _get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_EMBED_MODEL = _get("OLLAMA_EMBED_MODEL", "nomic-embed-text")
OLLAMA_LLM_MODEL = _get("OLLAMA_LLM_MODEL", "llama3.2")
RETRIEVE_K = _get_int("RETRIEVE_K", 5)

# Rewrite fragments/typos into a clean question before retrieval.
QUERY_REWRITE = _get("QUERY_REWRITE", "true").strip().lower() in {"1", "true", "yes", "on"}

# Slides are tiny, so definitions and examples often sit on adjacent pages.
# For the top NEIGHBOR_TOP_N hits, also give the LLM the NEIGHBOR_PAGES pages on
# each side (context only: they are not gated by distance or cited).
NEIGHBOR_PAGES = _get_int("NEIGHBOR_PAGES", 1)
NEIGHBOR_TOP_N = _get_int("NEIGHBOR_TOP_N", 2)

# Relevance gate on DuckDB's cosine distance: LOWER = more similar.
# Retrieved chunks whose distance is WORSE (larger) than this are discarded
# *before* the LLM is called. Calibrate against the DuckDB/HNSW index, not the
# old Chroma L2 scale.
# On this corpus answerable top-hits are ~0.17-0.34, unanswerable ~0.48-0.59.
MAX_DISTANCE = _get_float("MAX_DISTANCE", 0.40)

# One DuckDB + HNSW course database shared by chat and voice (voice uses /ask).
COURSE_DB_PATH = PROJECT_ROOT / _get("COURSE_DB_PATH", "vectorstore/course.duckdb")
EMBEDDING_DIM = _get_int("EMBEDDING_DIM", 768)

# Legacy path kept only so older local .env files still parse.
VECTORSTORE_DIR = PROJECT_ROOT / _get("VECTORSTORE_DIR", "vectorstore/chroma")
PDF_DIR = PROJECT_ROOT / _get("PDF_DIR", "data/pdfs")


MAX_UPLOAD_MB = _get_int("MAX_UPLOAD_MB", 50)

# Default source for ingestion when --source is not given (a folder or file).
SOURCE_DEFAULT = PDF_DIR

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 100
