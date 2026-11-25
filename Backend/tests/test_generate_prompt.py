"""Generation prompts keep grounding fixed while changing only answer depth."""

from __future__ import annotations

import unittest

from src.generate import LENGTH_RULES, PRACTICE_CHUNK_RE, build_prompt


class AnswerLengthPromptTest(unittest.TestCase):
    def test_short_rule_keeps_original_concise_instruction(self) -> None:
        prompt = build_prompt("What is NLP?", "context", "short")
        self.assertIn(LENGTH_RULES["short"], prompt)
        self.assertIn("2-4 complete sentences", prompt)
        self.assertIn("hard maximum: 4", prompt)

    def test_long_rule_replaces_only_the_length_instruction(self) -> None:
        prompt = build_prompt("What is NLP?", "context", "long")
        self.assertIn(LENGTH_RULES["long"], prompt)
        self.assertIn("at least six complete sentences", prompt)
        self.assertNotIn("2-4 complete sentences", prompt)
        self.assertNotIn("hard maximum: 4", prompt)
        # Grounding rules are unchanged.
        self.assertIn("ONLY from the provided course context", prompt)
        self.assertIn("NO outside knowledge", prompt)

    def test_embedded_practice_prompt_is_detected_across_line_breaks(self) -> None:
        chunk = "Stopword Corpus Management: Suppose\nyou are building a sentiment analyzer"
        self.assertIsNotNone(PRACTICE_CHUNK_RE.search(chunk))

    def test_unknown_length_falls_back_to_short(self) -> None:
        self.assertEqual(build_prompt("q", "c", "medium"), build_prompt("q", "c", "short"))


if __name__ == "__main__":
    unittest.main()
