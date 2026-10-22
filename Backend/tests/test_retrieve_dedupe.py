"""Unit tests for retrieval de-duplication (no Ollama/Chroma needed).

Run from Backend/:

    python -m unittest tests.test_retrieve_dedupe -v
"""
from __future__ import annotations

import unittest

from langchain_core.documents import Document

from src.retrieve import _dedupe_top_k


def _pair(text: str, score: float, page: int = 0) -> tuple:
    return Document(page_content=text, metadata={"source": "a.pdf", "page": page}), score


class DedupeTopKTests(unittest.TestCase):
    def test_identical_text_keeps_best_score(self):
        pairs = [_pair("same slide", 0.60), _pair("same  slide\n", 0.55), _pair("other", 0.70)]
        out = _dedupe_top_k(pairs, k=5)
        self.assertEqual([round(s, 2) for _, s in out], [0.55, 0.70])

    def test_sorted_best_first_and_limited_to_k(self):
        pairs = [_pair(f"chunk {i}", 0.9 - i * 0.1) for i in range(5)]
        out = _dedupe_top_k(pairs, k=3)
        self.assertEqual(len(out), 3)
        self.assertEqual(sorted(s for _, s in out), [s for _, s in out])

    def test_empty(self):
        self.assertEqual(_dedupe_top_k([], k=4), [])


if __name__ == "__main__":
    unittest.main()
