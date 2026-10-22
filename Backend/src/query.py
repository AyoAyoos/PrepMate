"""Query rewriting.

Students type fragments and typos ("what hypernymy"). A small LLM turns the
raw input into one clean question before retrieval/generation. The rewrite is
a best-effort helper: on any failure or odd output we fall back to the
original question, so it can never make a question unanswerable.
"""
from __future__ import annotations

from functools import lru_cache

from langchain_ollama import OllamaLLM

from src.config import OLLAMA_HOST, OLLAMA_LLM_MODEL, QUERY_REWRITE

REWRITE_PROMPT = (
    "Rewrite the user's question as ONE clear, complete, grammatical question "
    "for searching course notes. Fix typos and expand fragments "
    "(e.g. 'what hypernymy' -> 'What is hypernymy?'). Keep the same meaning and "
    "every technical term. Do not answer it and do not add new topics. "
    "Output only the rewritten question.\n\n"
    "Question: {question}\nRewritten:"
)

MAX_REWRITE_CHARS = 200


@lru_cache(maxsize=256)
def rewrite_query(question: str) -> str:
    """Return a cleaned-up version of `question` (or `question` itself)."""
    original = question.strip()
    if not QUERY_REWRITE or not original:
        return original

    try:
        llm = OllamaLLM(
            base_url=OLLAMA_HOST,
            model=OLLAMA_LLM_MODEL,
            temperature=0.0,
            num_predict=64,
        )
        raw = llm.invoke(REWRITE_PROMPT.format(question=original)).strip()
    except Exception:
        return original

    lines = raw.splitlines()
    rewritten = lines[0].strip().strip('"').strip() if lines else ""
    if not rewritten or len(rewritten) > MAX_REWRITE_CHARS:
        return original
    return rewritten
