"""Step 4 / Phase 7: evaluation of the RAG pipeline.

Runs the fixed eval set in eval/test_questions.json through retrieval +
generation and scores each answer on TWO layers that map onto the two
failure modes of a RAG system:

  Layer 1 - Correctness of the grounded flag.
      Does `Answer.grounded` match the expected label?
      - answerable / embellishable  -> expect grounded=True
      - unanswerable                -> expect grounded=False (refusal)
      This catches wrong refusals and wrong over-answers.

  Layer 2 - Faithfulness of answerable answers (manual + automated tripwire).
      The binary grounded flag cannot catch "correct umbrella, invented
      specifics" (the HMM fabrication). So for every answerable/embellishable
      answer we:
        (a) print the FULL answer text for manual grading on
            Grounded / Partially-grounded / Hallucinated, and
        (b) run an automated tripwire: any numeric token in the answer that
            does not literally appear in the cited chunk text is flagged as a
            potential fabrication (e.g. it would catch the invented
            `N -> V: 0.5` probability).

Usage (from the project root):
    python -m eval.run_eval
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from src.generate import generate
from src.retrieve import retrieve
from src.citations import render_citations
from src.config import MAX_DISTANCE

EVAL_FILE = Path(__file__).resolve().parent / "test_questions.json"

NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")

# Numbers so common they'd produce noise (single small ints, arrow steps, etc.)
TRIPWIRE_STOP = {"0", "1", "2", "3", "4", "5", "10", "100", "-1"}


def load_eval_set() -> list[dict]:
    with open(EVAL_FILE, encoding="utf-8") as fh:
        return json.load(fh)["questions"]


def _expected_grounded(expected: str) -> bool:
    """Which label implies the model should have produced a grounded answer."""
    return expected in {"answerable", "embellishable"}


def _number_tripwire(answer_text: str, source_text: str) -> list[str]:
    """Return numbers in the answer that don't appear in the source chunks."""
    src_tokens = set(NUMBER_RE.findall(source_text))
    flagged = []
    for m in NUMBER_RE.findall(answer_text):
        if m in TRIPWIRE_STOP:
            continue
        if m not in src_tokens:
            flagged.append(m)
    return flagged


def run() -> None:
    items = load_eval_set()
    results = []
    for item in items:
        question = item["question"]
        expected = item["expected"]
        answer: Answer | None = None
        error = None
        try:
            retrieved = retrieve(question)
            answer = generate(retrieved, question)
        except Exception as exc:
            error = str(exc)

        want_grounded = _expected_grounded(expected)
        if error is not None:
            results.append({
                "question": question, "expected": expected, "layer1_pass": False,
                "verdict": "ERROR", "answer": "", "grounded": None,
                "citations": [], "tripwire": [], "note": error, "source_text": "",
            })
            continue

        layer1_pass = answer.grounded == want_grounded
        verdict = (
            "GROUNDED" if layer1_pass and want_grounded
            else "CORRECTLY-REFUSED" if layer1_pass and not want_grounded
            else "HALLUCINATED/MISSED" if want_grounded
            else "WRONGLY-ANSWERED"
        )

        # Rebuild the raw source text from the kept chunks for the tripwire.
        source_parts = []
        for doc, score in retrieved:
            if score is not None and score <= MAX_DISTANCE:
                source_parts.append(doc.page_content)
        source_text = "\n".join(source_parts)

        tripwire = _number_tripwire(answer.text, source_text) if want_grounded else []

        results.append({
            "question": question, "expected": expected, "layer1_pass": layer1_pass,
            "verdict": verdict, "answer": answer.text.strip(), "grounded": answer.grounded,
            "citations": answer.citations, "tripwire": tripwire,
            "note": answer.note, "source_text": source_text,
        })

    # ---- Report ----
    total = len(results)
    layer1_ok = sum(1 for r in results if r["layer1_pass"])
    ans = [r for r in results if _expected_grounded(r["expected"])]
    unans = [r for r in results if not _expected_grounded(r["expected"])]
    ans_flags = [r for r in ans if r["tripwire"]]

    print("=" * 78)
    print("PHASE 7 EVAL - Layer 1 (grounded-flag correctness)")
    print("=" * 78)
    for r in results:
        flag = "PASS" if r["layer1_pass"] else "FAIL"
        tri = f"  [TRIPWIRE: {r['tripwire']}]" if r["tripwire"] else ""
        print(f"{flag}  ({r['verdict']:>18})  {r['question']}{tri}")
    print("=" * 78)
    print(f"Layer 1 accuracy: {layer1_ok}/{total} "
          f"({100 * layer1_ok / total:.0f}%)  "
          f"[answerable+embellishable={len(ans)}, unanswerable={len(unans)}]")
    print(f"Automated faithfulness tripwire fired on {len(ans_flags)}/{len(ans)} "
          f"answerable answers.\n")

    print("=" * 78)
    print("PHASE 7 EVAL - Layer 2 (manual faithfulness grading)\n")
    for r in ans:
        print(f"--- [{r['expected']}] {r['question']}")
        print(f"    grounded={r['grounded']} | tripwire={r['tripwire'] or 'none'}")
        print("    answer:")
        for line in r["answer"].splitlines():
            print(f"      | {line}")
        if r["citations"]:
            print("    citations:")
            print("      " + render_citations(r["citations"]).replace("\n", "\n      "))
        print()


if __name__ == "__main__":
    run()
