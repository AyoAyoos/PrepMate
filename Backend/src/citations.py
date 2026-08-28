"""Citation formatting.

Retrieved chunks carry metadata (source filename, page number) and an L2
distance score (lower = more relevant). This module turns the raw
(document, score) pairs into a readable, human-friendly list of citations so
that grounding is visible to the user.
"""
from __future__ import annotations

from typing import Any


def _page(metadata: dict[str, Any]) -> int | None:
    """The page number if we can find one in chunk metadata."""
    for key in ("page", "page_number"):
        if key in metadata:
            try:
                return int(metadata[key]) + 1  # Chroma stores page as 0-indexed when available
            except (TypeError, ValueError):
                return None
    return None


def format_citations(docs: list[Any]) -> list[dict[str, Any]]:
    """Turn (document, relevance_score) tuples into citation dicts.

    Each dict contains: index, source (file name), page (1-indexed), and the
    L2 distance score (lower = more similar, i.e. more relevant).
    """
    citations = []
    for i, pair in enumerate(docs, start=1):
        document, score = pair
        metadata = getattr(document, "metadata", {}) or {}
        citations.append(
            {
                "index": i,
                "source": metadata.get("source", "unknown.pdf"),
                "page": _page(metadata),
                "score": round(float(score), 4) if score is not None else None,
            }
        )
    return citations


def render_citations(citations: list[dict[str, Any]], label: str = "SOURCES") -> str:
    """Render citation dicts as a compact readable string.

    `label` prefixes the list (default "SOURCES"). Callers may pass something
    like "SOURCES (considered but insufficient)" when the chunks were
    retrieved but the model refused to answer from them.
    """
    if not citations:
        return "No sources retrieved."

    lines = [f"--- {label} ---"]
    for c in citations:
        loc = f"p.{c['page']}" if c["page"] is not None else "n/a"
        score = f" (d={c['score']:.2f})" if c["score"] is not None else ""
        lines.append(f"  [{c['index']}] {c['source']} — {loc}{score}")
    return "\n".join(lines)
