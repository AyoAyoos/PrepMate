"""Unit tests for the multi-format ingestion loader dispatch.

These tests run without Ollama or Chroma — they exercise pure parsing logic:
extension resolution and the per-type text extraction. Run from Backend/:

    python -m unittest tests.test_ingest_loader -v
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.ingest import _read_as_documents, resolve_source_files


class ResolveSourceFilesTest(unittest.TestCase):
    def test_single_supported_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "notes.md"
            p.write_text("# hi", encoding="utf-8")
            self.assertEqual(resolve_source_files(p), [p])

    def test_folder_filters_supported_types(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.pdf").write_bytes(b"%PDF-1.4")
            (root / "b.txt").write_text("hello", encoding="utf-8")
            (root / "c.exe").write_bytes(b"nope")
            found = resolve_source_files(root)
            names = sorted(f.name for f in found)
            self.assertEqual(names, ["a.pdf", "b.txt"])

    def test_unsupported_single_file_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.exe"
            p.write_bytes(b"x")
            with self.assertRaises(FileNotFoundError):
                resolve_source_files(p)

    def test_empty_folder_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                resolve_source_files(tmp)


class ReadAsDocumentsTest(unittest.TestCase):
    def test_text_file_utf8(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.txt"
            p.write_text("alpha\nbeta", encoding="utf-8")
            docs = _read_as_documents(p)
            self.assertEqual(len(docs), 1)
            self.assertIn("alpha", docs[0].page_content)

    def test_text_file_latin1_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "b.md"
            p.write_bytes("caf\xe9".encode("latin-1"))
            docs = _read_as_documents(p)
            self.assertIn("caf", docs[0].page_content)


if __name__ == "__main__":
    unittest.main()
