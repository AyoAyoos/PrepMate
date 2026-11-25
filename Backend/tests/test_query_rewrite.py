"""Follow-up rewriting tests (no Ollama needed).

Run from Backend/:
    python -m unittest tests.test_query_rewrite -v
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from src.query import (
    FOLLOWUP_PROMPT,
    MAX_HISTORY_TURNS,
    normalize_history,
    rewrite_query,
)


class FakeLLM:
    last_prompt = ""
    reply = "What is morphology?"

    def __init__(self, **kwargs: object) -> None:
        pass

    def invoke(self, prompt: str) -> str:
        type(self).last_prompt = prompt
        return type(self).reply


class QueryRewriteTest(unittest.TestCase):
    def setUp(self) -> None:
        rewrite_query.cache_clear()
        FakeLLM.last_prompt = ""
        FakeLLM.reply = "What is morphology?"

    @patch("src.query.OllamaLLM", FakeLLM)
    def test_plain_question_uses_single_question_prompt(self) -> None:
        self.assertEqual(rewrite_query("what morphlogy"), "What is morphology?")
        self.assertIn("Question: what morphlogy", FakeLLM.last_prompt)
        self.assertNotIn("Conversation (role: text)", FakeLLM.last_prompt)

    @patch("src.query.OllamaLLM", FakeLLM)
    def test_history_produces_standalone_question(self) -> None:
        history = (("user", "What is morphology?"), ("assistant", "It studies word structure."))
        FakeLLM.reply = "What are affixes in morphology?"

        result = rewrite_query("Tell me more about that.", history)

        self.assertEqual(result, "What are affixes in morphology?")
        self.assertIn(FOLLOWUP_PROMPT.split("\n")[0], FakeLLM.last_prompt)
        self.assertIn("user: What is morphology?", FakeLLM.last_prompt)
        self.assertIn("Final question: Tell me more about that.", FakeLLM.last_prompt)

    @patch("src.query.OllamaLLM", FakeLLM)
    def test_failed_rewrite_falls_back_to_original(self) -> None:
        FakeLLM.reply = ""
        self.assertEqual(rewrite_query("What is NLP?"), "What is NLP?")

    def test_normalize_history_keeps_recent_valid_turns(self) -> None:
        turns = [
            {"role": "user", "content": "  first   question "},
            {"role": "system", "content": "ignore me"},
            {"role": "assistant", "content": "an answer"},
            {"role": "user", "content": "last"},
        ]
        normalized = normalize_history(turns)
        self.assertEqual(
            normalized,
            (("user", "first question"), ("assistant", "an answer"), ("user", "last")),
        )

        many = [{"role": "user", "content": str(i)} for i in range(MAX_HISTORY_TURNS + 4)]
        self.assertEqual(len(normalize_history(many)), MAX_HISTORY_TURNS)


if __name__ == "__main__":
    unittest.main()
