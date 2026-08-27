"""Evaluation harness for the RAG pipeline.

Runs a fixed question set through retrieval + generation and scores each
answer as grounded vs hallucinated based on whether it produced citations.
"""
from __future__ import annotations

import json
from pathlib import Path

from src.citations import render_citations
from src.generate import generate
from src.retrieve import retrieve

EVAL_FILE = Path(__file__).resolve().parent / "test_questions.json"


def load_eval_set() -> list[dict]:
    with open(EVAL_FILE, encoding="utf-8") as fh:
        return json.load(fh)["questions"]


def run() -> None:
    items = load_eval_set()
    results = []
    for item in items:
        question = item["question"]
        expected = item["expected"]
        try:
            retrieved = retrieve(question)
            answer = generate(retrieved, question)
        except Exception as exc:
            results.append({
                "question": question, "expected": expected,
                "ok": False, "error": str(exc), "answer": "",
            })
            continue

        # Scoring: use Answer.grounded (set by the three-layer refusal logic),
        # NOT bool(citations) — a "considered but insufficient" refusal still
        # carries citations yet must count as a correct refusal, not grounded.
        grounded = answer.grounded
        ok = (grounded and expected == "answerable") or (
            not grounded and expected == "unanswerable"
        )
        results.append({
            "question": question, "expected": expected, "ok": ok,
            "grounded": grounded, "answer": answer.text.strip(),
            "citations": answer.citations,
        })

    passed = sum(1 for r in results if r["ok"])
    total = len(results)
    print("=" * 60)
    print("EVAL - grounded vs hallucinated")
    print("=" * 60)
    for r in results:
        flag = "PASS" if r["ok"] else "FAIL"
        print(f"{flag} ({r['expected']}) {r['question']}")
        if not r["ok"] and r.get("error"):
            print(f"     error: {r['error']}")
    print("=" * 60)
    print(f"Ground score: {passed}/{total} ({100 * passed / max(total, 1):.0f}%)")
    print()


if __name__ == "__main__":
    run()
