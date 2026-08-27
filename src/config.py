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
RETRIEVE_K = _get_int("RETRIEVE_K", 4)

# Relevance gate on Chroma's L2/HNSW distance (space='l2'): LOWER = more
# similar. Empirically calibrated on this corpus: answerable top-hits are
# ~0.21-0.50, unanswerable top-hits are ~0.80-1.19. 0.70 sits in the gap with
# ~0.20 margin on each side. Retrieved chunks whose distance is WORSE
# (larger) than this are discarded *before* the LLM is called.
MAX_DISTANCE = _get_float("MAX_DISTANCE", 0.70)

VECTORSTORE_DIR = PROJECT_ROOT / _get("VECTORSTORE_DIR", "vectorstore/chroma")
PDF_DIR = PROJECT_ROOT / _get("PDF_DIR", "data/pdfs")
