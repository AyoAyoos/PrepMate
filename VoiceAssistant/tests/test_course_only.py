"""This PrepMate bundle exposes a course-only voice assistant.

Run from VoiceAssistant/ with:
    .venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import bootstrap  # noqa: E402,F401  (vendored Pipecat on sys.path)
from tools.voice_tools import build_tool_schemas  # noqa: E402


COURSE_ONLY_REFUSAL = (
    "I can only answer questions from the course material. "
    "Ask me something about the course."
)


class CourseOnlyVoiceTest(unittest.TestCase):
    def test_prompt_contains_exact_refusal_and_no_outside_tool_instructions(self) -> None:
        prompt = (_ROOT / "pipeline.py").read_text(encoding="utf-8")

        self.assertIn(COURSE_ONLY_REFUSAL, prompt)
        self.assertIn("syllabus_search is your only information tool", prompt)
        self.assertNotIn("For non-course questions, you may answer", prompt)
        self.assertNotIn("live web search", prompt)
        self.assertNotIn("For coding requests, use code_task", prompt)
        self.assertNotIn("Reminders are only stored and recalled", prompt)

    def test_only_course_search_and_end_call_tools_are_exposed(self) -> None:
        schemas = build_tool_schemas(lambda: None, lambda: "short")
        names = [schema.name for schema in schemas]

        self.assertEqual(names, ["syllabus_search", "end_conversation"])
        self.assertNotIn("web_search", names)
        self.assertNotIn("fetch_page", names)
        self.assertNotIn("memory_search", names)
        self.assertNotIn("code_task", names)


if __name__ == "__main__":
    unittest.main()
