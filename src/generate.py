"""Step 3 of the RAG pipeline: generation.

Takes the retrieved chunks, builds a grounded prompt, calls Ollama, and
returns the answer. At this stage every retrieved chunk is passed in as
context and the answer is always reported as grounded — relevance gating
and refusal logic are added in later steps.
"""
from __future__ import annotations

from dataclasses import dataclass

from langchain_ollama import OllamaLLM

from src.config import OLLAMA_HOST, OLLAMA_LLM_MODEL


@dataclass
class Answer:
    text: str
    grounded: bool = True


SYSTEM_PROMPT = (
    "You are a helpful assistant that answers questions ONLY from the provided "
    "context. Use no outside knowledge."
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
    """Generate an answer from the retrieved (document, score) pairs."""
    context = "\n\n---\n\n".join(doc.page_content for doc, _ in retrieved)
    prompt = build_prompt(question, context)

    llm = _get_llm()
    raw = llm.invoke(prompt).strip()

    return Answer(text=raw, grounded=True)
