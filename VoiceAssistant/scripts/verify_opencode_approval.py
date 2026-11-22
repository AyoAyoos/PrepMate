"""Smoke test for spoken OpenCode approvals and default timeout rejection.

The first task asks for an edit, answers "yes", and checks that the file was
created. The second task asks for another edit and is deliberately left
unanswered, so the bridge must reject it after
``OPENCODE_APPROVAL_TIMEOUT_SECONDS``.

Run:
    .\\.venv\\Scripts\\python.exe scripts\\verify_opencode_approval.py

This starts no extra coding agent; it only drives the running OpenCode service.
Throwaway worktrees may remain locked until OpenCode is restarted on Windows.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKTREE_ROOT = Path(tempfile.gettempdir()) / "voice-bridge-approval-worktrees"
DB_PATH = Path(tempfile.gettempdir()) / "voice-bridge-approval.duckdb"


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


async def cleanup_session(client: Any, session_id: str) -> None:
    if not session_id:
        return
    try:
        await client._request("DELETE", f"/api/session/{session_id}")
    except Exception as exc:  # pragma: no cover - test cleanup only
        print(f"Session cleanup skipped: {str(exc)[:120]}")


async def main() -> None:
    # Importing the full Pipecat stack can exhaust OpenBLAS thread slots on
    # some Windows machines. One thread is enough for these HTTP-only tests.
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ["VOICE_DB_PATH"] = str(DB_PATH)
    os.environ["OPENCODE_WORKTREE_ROOT"] = str(WORKTREE_ROOT)
    os.environ["OPENCODE_TASK_WAIT_SECONDS"] = "25"
    os.environ["OPENCODE_APPROVAL_TIMEOUT_SECONDS"] = "3"
    WORKTREE_ROOT.mkdir(parents=True, exist_ok=True)
    DB_PATH.unlink(missing_ok=True)

    sys.path.insert(0, str(PROJECT_ROOT))
    import bootstrap  # noqa: F401

    from storage.duckdb_store import store
    from tools import voice_tools
    from tools.opencode_client import opencode_client

    await store.initialize()

    # 1. Spoken "yes" path.
    asked = await call(
        voice_tools.code_task,
        "code_task",
        {
            "text": "Create a file named approval_probe.txt whose only content is OK. Use the write tool now.",
            "mode": "build",
            "model": "ollama/qwen2.5:3b-instruct",
            "title": "Approval yes smoke test",
        },
    )
    print(f"Approval asked: {asked}")
    yes_session = str((asked or {}).get("session_id") or "")
    if not asked or asked.get("status") != "awaiting_approval":
        raise SystemExit("FAIL: build task did not ask for approval")

    answered = await call(
        voice_tools.code_permission_reply,
        "code_permission_reply",
        {
            "decision": "yes",
            "session": asked.get("short_code"),
            "request_id": asked.get("request_id"),
        },
    )
    print(f"Answered yes: {answered}")
    row = await store.get_opencode_session(yes_session) or {}
    worktree = str(row.get("worktree_dir") or "")
    created = bool(worktree and list(Path(worktree).rglob("approval_probe.txt")))
    print(f"Approved file created: {created}")

    # 2. Unanswered approval must auto-reject.
    timeout_ask = await call(
        voice_tools.code_task,
        "code_task",
        {
            "text": "Create a new file named timeout_probe.txt with the exact content TIMEOUT using the write tool. Do this now.",
            "mode": "build",
            "model": "ollama/qwen2.5:3b-instruct",
            "title": "Approval timeout smoke test",
        },
    )
    print(f"Timeout approval asked: {timeout_ask}")
    timeout_session = str((timeout_ask or {}).get("session_id") or "")
    expired = False
    if timeout_ask and timeout_ask.get("status") == "awaiting_approval":
        await asyncio.sleep(6)
        row = await store.get_opencode_session(timeout_session) or {}
        pending = await opencode_client.pending_permissions(timeout_session)
        expired = (
            row.get("status") == "interrupted"
            and not row.get("pending_permission_id")
            and not pending
        )
        print(
            "After timeout: "
            f"status={row.get('status')} pending={row.get('pending_permission_id')} "
            f"api_requests={len(pending)}"
        )

    for session_id in {yes_session, timeout_session}:
        await cleanup_session(opencode_client, session_id)
    await voice_tools.cancel_approval_timers()
    await opencode_client.close()
    await store.close()

    ok = created and expired
    print("PASS" if ok else "FAIL")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
