"""Verifies that the syllabus_search voice tool calls PrepMate's /ask API.

Run from VoiceAssistant/ with:
    .venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import bootstrap  # noqa: E402,F401  (vendored Pipecat on sys.path)
from tools.voice_tools import syllabus_search  # noqa: E402


class _FakeParams:
    def __init__(self, arguments: dict[str, Any]) -> None:
        self.arguments = arguments
        self.function_name = "syllabus_search"
        self.result: dict[str, Any] | None = None

    async def result_callback(self, payload: dict[str, Any], properties: Any = None) -> None:
        self.result = payload


class _AskHandler(BaseHTTPRequestHandler):
    received: dict[str, Any] | None = None

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler name
        length = int(self.headers.get("Content-Length", "0"))
        _AskHandler.received = json.loads(self.rfile.read(length) or b"{}")
        body = json.dumps(
            {
                "answer": "Retrieval augmented generation grounds answers in source chunks.",
                "grounded": True,
                "citations": [
                    {
                        "source_file": "NLP Unit 1.pdf",
                        "page": 7,
                        "distance_score": 0.42,
                    }
                ],
                "note": "",
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        pass


class SyllabusSearchIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _AskHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        host, port = cls.server.server_address
        cls.old_base = os.getenv("PREPMATE_API_BASE")
        os.environ["PREPMATE_API_BASE"] = f"http://{host}:{port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        if cls.old_base is None:
            os.environ.pop("PREPMATE_API_BASE", None)
        else:
            os.environ["PREPMATE_API_BASE"] = cls.old_base

    def test_tool_returns_grounded_answer_with_sources(self) -> None:
        params = _FakeParams({"question": "What is RAG?"})
        asyncio.run(syllabus_search(params))

        self.assertIsNotNone(params.result)
        assert params.result is not None
        self.assertEqual(params.result["source"], "prepmate-syllabus-rag")
        self.assertTrue(params.result["grounded"])
        self.assertIn("retrieval augmented", params.result["answer"].lower())
        self.assertEqual(params.result["sources"], ["NLP Unit 1.pdf, page 7"])
        self.assertEqual(_AskHandler.received, {"question": "What is RAG?"})


if __name__ == "__main__":
    unittest.main()
