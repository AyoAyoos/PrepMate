"""Entry point for the Ask-the-Syllabus Bot.

Runs an interactive Q&A loop: asks a question, retrieves relevant chunks,
generates a grounded answer with citations, then prints everything.

Usage:
    python -m src.cli
"""
from __future__ import annotations

from src.citations import render_citations
from src.generate import UNANSWERABLE, generate
from src.retrieve import has_any_documents, retrieve

BANNER = """
Ask-the-Syllabus Bot (RAG)
--------------------------
Ingest your course PDFs first with:  python -m src.ingest
Type a question, or 'quit' to exit.
"""


def answer_question(question: str) -> None:
    if not has_any_documents():
        print("The vector store is empty. Run `python -m src.ingest` first.\n")
        return

    try:
        retrieved = retrieve(question)
    except Exception as exc:  # e.g. Ollama not running
        print(f"Retrieval failed (is Ollama running?): {exc}\n")
        return

    if not retrieved:
        print(f"{UNANSWERABLE}\n")
        return

    answer = generate(retrieved, question)

    print("\n--- ANSWER ---")
    print(answer.text.strip())

    if answer.citations:
        if answer.grounded:
            print("\n" + render_citations(answer.citations, label="SOURCES"))
        else:
            print("\n" + render_citations(answer.citations, label="SOURCES (considered but insufficient)"))

    if not answer.grounded:
        print(f"\n(Not grounded: {answer.note})")
    print()


def main() -> None:
    print(BANNER)
    while True:
        try:
            question = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not question:
            continue
        if question.lower() in {"quit", "exit", "q"}:
            print("Goodbye.")
            break

        answer_question(question)


if __name__ == "__main__":
    main()
