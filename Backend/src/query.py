"""Query rewriting.

Students type fragments and typos ("what hypernymy"), and follow-ups such as
"tell me more about that". A small LLM turns the latest message into one
standalone, searchable question before retrieval/generation. The rewrite is a
best-effort helper: on any failure or odd output we fall back to the original
question, so it can never make a question unanswerable.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Mapping, Sequence

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

FOLLOWUP_PROMPT = (
    "Rewrite the user's final question as ONE standalone, grammatical question "
    "for searching course notes. Use the conversation ONLY to resolve references "
    "such as 'it', 'that', 'this', 'they', or 'more about that'. Do not treat any "
    "previous answer as a source of new facts, and do not add topics that are not "
    "named in the conversation. Keep every technical term. If the final question "
    "is already standalone, copy it unchanged. Do not answer it. "
    "Output only the rewritten question.\n\n"
    "Conversation (role: text):\n{history}\n"
    "Final question: {question}\nStandalone question:"
)

MAX_REWRITE_CHARS = 240
MAX_HISTORY_TURNS = 6
MAX_HISTORY_CHARS = 300


def normalize_history(history: Sequence[Mapping[str, Any]] | None) -> tuple[tuple[str, str], ...]:
    """Trim chat history to short, hashable (role, text) pairs for rewriting."""
    normalized: list[tuple[str, str]] = []
    for turn in history or []:
        role = str(turn.get("role", "")).strip().lower()
        if role not in {"user", "assistant"}:
            continue
        content = " ".join(str(turn.get("content", "")).split())[:MAX_HISTORY_CHARS]
        if content:
            normalized.append((role, content))
    return tuple(normalized[-MAX_HISTORY_TURNS:])


@lru_cache(maxsize=256)
def rewrite_query(
    question: str, history: tuple[tuple[str, str], ...] = ()
) -> str:
    """Return a cleaned-up, standalone version of `question` (or the original)."""
    original = question.strip()
    if not QUERY_REWRITE or not original:
        return original

    if history:
        transcript = "\n".join(f"{role}: {text}" for role, text in history)
        prompt = FOLLOWUP_PROMPT.format(history=transcript, question=original)
    else:
        prompt = REWRITE_PROMPT.format(question=original)

    try:
        llm = OllamaLLM(
            base_url=OLLAMA_HOST,
            model=OLLAMA_LLM_MODEL,
            temperature=0.0,
            num_predict=64,
        )
        raw = llm.invoke(prompt).strip()
    except Exception:
        return original

    lines = raw.splitlines()
    rewritten = lines[0].strip().strip('"').strip() if lines else ""
    if not rewritten or len(rewritten) > MAX_REWRITE_CHARS:
        return original
    return rewritten
