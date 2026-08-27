"""Step 3 of the RAG pipeline: generation.

Takes the retrieved chunks, builds a grounded prompt, calls Ollama, and
returns the answer. At this stage every retrieved chunk is passed in as
context and the answer is always reported as grounded — relevance gating
and refusal logic are added in later steps.
"""
from __future__ import annotations

from dataclasses import dataclass

from langchain_ollama import OllamaLLM

from src.config import MAX_DISTANCE, OLLAMA_HOST, OLLAMA_LLM_MODEL


@dataclass
class Answer:
    text: str
    grounded: bool = True
    note: str = ""


UNANSWERABLE = "I could not find the answer to this question in the course documents."
NO_RETRIEVAL = (
    "No retrieved content was sufficiently relevant to ground an answer, so I am "
    "declining to answer rather than risk hallucinating."
)

# Fixed, literal marker the model is asked to emit verbatim when the provided
# context does not answer the question. Detection below matches it
# case-insensitively (LLMs vary capitalization/punctuation).
REFUSAL_MARKER = "This isn't covered in the provided materials."

SYSTEM_PROMPT = (
    "You are a helpful assistant that answers questions ONLY from the provided "
    "context. Follow these rules in order:\n"
    "1. Answer only using the provided context — use NO outside knowledge.\n"
    f"2. If the context does not contain the answer, reply with exactly: "
    f'"{REFUSAL_MARKER}" — do not hedge into a partial guess.\n'
    "3. When you do answer, stay close to what the context actually says; do not "
    "generalize into claims broader than the context states."
)


CONSIDERED_REFUSAL = (
    "The model considered the retrieved chunks but none of them answered the "
    "question, so it refused. Chunks shown below were considered but insufficient."
)


def build_prompt(question: str, context: str) -> str:
    """Assemble the system + context + question prompt."""
    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"### CONTEXT (the only source of truth):\n{context}\n\n"
        f"### QUESTION:\n{question}\n\n"
        "### ANSWER:"
    )


def _get_llm() -> OllamaLLM:
    return OllamaLLM(
        base_url=OLLAMA_HOST,
        model=OLLAMA_LLM_MODEL,
        temperature=0.0,
    )


def generate(retrieved: list, question: str) -> Answer:
    """Generate an answer from the retrieved (document, score) pairs.

    Layer (a): chunks beyond MAX_DISTANCE are discarded BEFORE the LLM runs.
    """
    # Layer (a): retrieval distance gate. L2 distance, lower = more similar,
    # so keep only chunks at or under MAX_DISTANCE.
    kept = [(doc, score) for doc, score in retrieved if score is not None and score <= MAX_DISTANCE]

    if not kept:
        return Answer(text=UNANSWERABLE, grounded=False, note=NO_RETRIEVAL)

    context = "\n\n---\n\n".join(doc.page_content for doc, _ in kept)
    prompt = build_prompt(question, context)

    llm = _get_llm()
    raw = llm.invoke(prompt).strip()

    # Layer (c): output-side refusal detection. Matches the fixed marker
    # case-insensitively + tolerates trailing punctuation.
    normalized = " ".join(raw.lower().split())
    marker = " ".join(REFUSAL_MARKER.lower().split()).rstrip(".")
    refused = marker in normalized

    if refused:
        return Answer(text=raw, grounded=False, note=CONSIDERED_REFUSAL)

    return Answer(text=raw, grounded=True, note="Answer grounded in retrieved context.")
