"""Unit tests for the upload helper functions in src.api.

These tests exercise filename collision handling without starting the server
or hitting Ollama/Chroma. Run from Backend/:

    python -m unittest tests.test_api_helpers -v
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.api import _unique_dest


class UniqueDestTest(unittest.TestCase):
    def test_first_file_keeps_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dest = _unique_dest(root, "notes.pdf", set())
            self.assertEqual(dest.name, "notes.pdf")
            dest.touch()

    def test_collision_on_disk_appends_counter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "notes.pdf").write_bytes(b"x")
            dest = _unique_dest(root, "notes.pdf", set())
            self.assertEqual(dest.name, "notes_1.pdf")

    def test_collision_within_batch_appends_counter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            taken = set()
            first = _unique_dest(root, "a.txt", taken)
            second = _unique_dest(root, "a.txt", taken)
            self.assertEqual(first.name, "a.txt")
            self.assertEqual(second.name, "a_1.txt")

    def test_reuses_extension_and_escapes_until_free(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.docx").write_bytes(b"x")
            (root / "a_1.docx").write_bytes(b"x")
            dest = _unique_dest(root, "a.docx", set())
            self.assertEqual(dest.name, "a_2.docx")


if __name__ == "__main__":
    unittest.main()
