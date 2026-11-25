"""Chat behaviour of POST /ask (no Ollama/DuckDB calls).

Run from Backend/:
    python -m unittest tests.test_api_chat -v
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from langchain_core.documents import Document

from src.api import AskRequest, _is_overview_question, ask_question
from src.config import RETRIEVE_K, RETRIEVE_K_LONG
from src.generate import Answer


class AskChatTest(unittest.TestCase):
    def test_overview_question_is_detected(self) -> None:
        for question in (
            "What's in my course?",
            "Tell me about the topics covered in this course",
            "What documents are available?",
        ):
            with self.subTest(question=question):
                self.assertTrue(_is_overview_question(question))

        self.assertFalse(_is_overview_question("What is stopword removal?"))

    @patch("src.api._course_overview")
    @patch("src.api.retrieve")
    def test_broad_question_uses_db_overview_and_skips_retrieval(
        self, retrieve_mock: object, overview_mock: object
    ) -> None:
        overview_mock.return_value = {  # type: ignore[attr-defined]
            "answer": "I have 2 documents indexed.",
            "grounded": True,
            "documents": [{"source": "notes.pdf", "chunks": 42}],
            "topics": ["Morphology", "Semantics"],
        }

        response = ask_question(
            AskRequest(question="What's in my course?", answer_length="long")
        )

        self.assertEqual(response.source, "course-overview")
        self.assertTrue(response.grounded)
        self.assertEqual(response.topics, ["Morphology", "Semantics"])
        self.assertEqual(response.documents[0].source, "notes.pdf")
        overview_mock.assert_called_once_with("long")  # type: ignore[attr-defined]
        retrieve_mock.assert_not_called()  # type: ignore[attr-defined]

    @patch("src.api.generate")
    @patch("src.api.retrieve")
    @patch("src.api.has_any_documents", return_value=True)
    @patch("src.api.rewrite_query", return_value="What is morphology?")
    def test_follow_up_uses_rewritten_question_and_selected_length(
        self,
        rewrite_mock: object,
        _has_docs_mock: object,
        retrieve_mock: object,
        generate_mock: object,
    ) -> None:
        hits = [
            (
                Document(
                    page_content="Morphology studies word structure.",
                    metadata={"source": "notes.pdf", "page": 7},
                ),
                0.25,
            )
        ]
        retrieve_mock.return_value = hits  # type: ignore[attr-defined]
        generate_mock.return_value = Answer(  # type: ignore[attr-defined]
            text="Morphology studies word structure.",
            grounded=True,
            citations=[],
            note="Answer grounded in retrieved context.",
        )

        response = ask_question(
            AskRequest(
                question="Tell me more about that.",
                answer_length="long",
                history=[{"role": "user", "content": "What is morphology?"}],
            )
        )

        self.assertTrue(response.grounded)
        self.assertEqual(response.source, "rag")
        rewrite_mock.assert_called_once_with(  # type: ignore[attr-defined]
            "Tell me more about that.", (("user", "What is morphology?"),)
        )
        retrieve_mock.assert_called_once_with(  # type: ignore[attr-defined]
            "What is morphology?", k=RETRIEVE_K_LONG, rewrite=False
        )
        generate_mock.assert_called_once_with(  # type: ignore[attr-defined]
            hits,
            "Tell me more about that.",
            answer_length="long",
            resolved_question="What is morphology?",
        )

    @patch("src.api.generate")
    @patch("src.api.retrieve")
    @patch("src.api.has_any_documents", return_value=True)
    @patch("src.api.rewrite_query")
    def test_short_question_uses_short_retrieval_k(
        self,
        rewrite_mock: object,
        _has_docs_mock: object,
        retrieve_mock: object,
        generate_mock: object,
    ) -> None:
        rewrite_mock.return_value = "What is NLP?"  # type: ignore[attr-defined]
        retrieve_mock.return_value = [  # type: ignore[attr-defined]
            (Document(page_content="NLP context", metadata={"source": "notes.pdf", "page": 1}), 0.2)
        ]
        generate_mock.return_value = Answer(text="Short answer.", grounded=True)  # type: ignore[attr-defined]

        ask_question(AskRequest(question="What is NLP?"))

        self.assertEqual(
            retrieve_mock.call_args.kwargs,  # type: ignore[attr-defined]
            {"k": RETRIEVE_K, "rewrite": False},
        )


if __name__ == "__main__":
    unittest.main()
