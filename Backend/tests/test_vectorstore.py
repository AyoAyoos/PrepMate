"""Unit tests for the shared DuckDB + HNSW course store.

No Ollama required: vectors are supplied directly. Run from Backend/:

    python -m unittest tests.test_vectorstore -v
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from langchain_core.documents import Document

from src.vectorstore import CourseVectorStore


class CourseVectorStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = CourseVectorStore(Path(self.tmp.name) / "course.duckdb", embedding_dim=4)

    def tearDown(self) -> None:
        self.store.close()
        self.tmp.cleanup()

    def test_insert_search_and_metadata(self) -> None:
        chunks = [
            Document(page_content="alpha", metadata={"source": "a.pdf", "page": 0, "file_sha1": "h1"}),
            Document(page_content="beta", metadata={"source": "a.pdf", "page": 1, "file_sha1": "h1"}),
            Document(page_content="gamma", metadata={"source": "b.pdf", "page": 0, "file_sha1": "h2"}),
        ]
        vectors = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.9, 0.1, 0.0, 0.0]]

        self.assertEqual(self.store.add_chunks(chunks, vectors), 3)
        self.assertEqual(self.store.count(), 3)
        self.assertEqual(self.store.existing_hashes(), {"h1", "h2"})
        self.assertEqual(self.store.list_sources(), ["a.pdf", "b.pdf"])
        self.assertEqual(self.store.chunk_counts_by_source(), {"a.pdf": 2, "b.pdf": 1})

        hits = self.store.search([1.0, 0.0, 0.0, 0.0], k=2)
        self.assertEqual([doc.page_content for doc, _ in hits], ["alpha", "gamma"])
        self.assertAlmostEqual(hits[0][1], 0.0, places=4)
        self.assertEqual(hits[0][0].metadata["page"], 0)

        neighbors = self.store.source_page_chunks("a.pdf", 1)
        self.assertEqual([doc.page_content for doc in neighbors], ["beta"])

    def test_clear_empties_index(self) -> None:
        self.store.add_chunks(
            [Document(page_content="x", metadata={"source": "a.pdf", "page": 0, "file_sha1": "h"})],
            [[1.0, 0.0, 0.0, 0.0]],
        )
        self.store.clear()
        self.assertEqual(self.store.count(), 0)
        self.assertEqual(self.store.search([1.0, 0.0, 0.0, 0.0], k=3), [])


if __name__ == "__main__":
    unittest.main()
