"""Smoke test for the voice -> OpenCode bridge (read task, list, recap).

Starts no extra coding agent. It assumes `opencode service status` already
works. The test uses a throwaway DuckDB file and a throwaway worktree root; it
never touches the live project checkout or reads credentials into the script.

Run:
    .\\.venv\\Scripts\\python.exe scripts\\verify_opencode_bridge.py

OpenCode may keep a worktree directory locked on Windows until the service is
restarted; see OPENCODE_BRIDGE.md for cleanup notes.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKTREE_ROOT = Path(tempfile.gettempdir()) / "voice-bridge-smoke-worktrees"
DB_PATH = Path(tempfile.gettempdir()) / "voice-bridge-smoke.duckdb"


class Params:
    """Minimal stand-in for Pipecat's FunctionCallParams."""

    def __init__(self, name: str, arguments: dict[str, Any]) -> None:
        self.function_name = name
        self.arguments = arguments
        self.result: dict[str, Any] | None = None

    async def result_callback(self, payload: dict[str, Any], properties: Any = None) -> None:
        self.result = payload


async def call(handler: Any, name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    params = Params(name, arguments)
    await handler(params)
    return params.result


async def main() -> None:
    # Importing the full Pipecat stack can exhaust OpenBLAS thread slots on
    # some Windows machines. One thread is enough for these HTTP-only tests.
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ["VOICE_DB_PATH"] = str(DB_PATH)
    os.environ["OPENCODE_WORKTREE_ROOT"] = str(WORKTREE_ROOT)
    os.environ.setdefault("OPENCODE_TASK_WAIT_SECONDS", "20")
    WORKTREE_ROOT.mkdir(parents=True, exist_ok=True)
    DB_PATH.unlink(missing_ok=True)

    sys.path.insert(0, str(PROJECT_ROOT))
    import bootstrap  # noqa: F401

    from storage.duckdb_store import store
    from tools import voice_tools
    from tools.opencode_client import opencode_client

    await store.initialize()
    print(f"OpenCode healthy: {await opencode_client.health()}")

    task = await call(
        voice_tools.code_task,
        "code_task",
        {
            "text": "List the top-level folders in this worktree and answer in one short sentence. Do not use tools.",
            "mode": "read",
            "model": "ollama/qwen2.5:3b-instruct",
            "title": "Bridge smoke test",
        },
    )
    print(f"Task result: {task}")
    if not task or "short_code" not in task:
        raise SystemExit("FAIL: code_task did not return a short code")

    sessions = await call(
        voice_tools.list_code_sessions, "list_code_sessions", {"limit": 5}
    )
    found = any(
        item.get("short_code") == task["short_code"]
        for item in (sessions or {}).get("sessions", [])
    )
    print(f"Listed and found short code: {found}")

    recap = await call(
        voice_tools.recap_code_session,
        "recap_code_session",
        {"session": task["short_code"], "include_details": True},
    )
    print(f"Recap: {recap}")

    session_id = str(task.get("session_id") or "")
    if session_id:
        try:
            await opencode_client._request("DELETE", f"/api/session/{session_id}")
        except Exception as exc:  # pragma: no cover - test cleanup only
            print(f"Session cleanup skipped: {str(exc)[:120]}")
        worktree = str((recap or {}).get("worktree") or "")
        if worktree:
            print(f"Worktree cleanup: {await opencode_client.remove_worktree(worktree)}")

    await voice_tools.cancel_approval_timers()
    await opencode_client.close()
    await store.close()

    ok = found and bool(recap and recap.get("summary"))
    print("PASS" if ok else "FAIL")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
