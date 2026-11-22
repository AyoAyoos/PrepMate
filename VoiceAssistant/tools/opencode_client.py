"""Backend-only HTTP client for the already-running OpenCode service.

This module never starts a coding agent. It only talks to the loopback OpenCode
HTTP service (default http://127.0.0.1:28894) using the service password that is
kept on the backend. No password, header, raw diff, or code is ever returned to
voice tools, logs, or the browser.

The event stream (``GET /api/event``) is shared by all callers: one background
SSE reader dispatches only the handful of event types the voice bridge needs to
per-session queues.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from loguru import logger

_DEFAULT_BASE_URL = "http://127.0.0.1:28894"
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_INTERESTING_EVENTS = {
    "permission.asked",
    "permission.replied",
    "session.idle",
    "session.execution.started",
    "session.execution.succeeded",
    "session.execution.failed",
    "session.execution.interrupted",
}

# Read-only discovery, narrow test commands, and git inspection. Anything else
# shell-related falls through to "ask" so the spoken approval flow can handle it.
_READ_SHELL_ALLOWS = [
    {"action": "shell", "resource": "git status *", "effect": "allow"},
    {"action": "shell", "resource": "git diff *", "effect": "allow"},
    {"action": "shell", "resource": "git log *", "effect": "allow"},
    {"action": "shell", "resource": "git branch --show-current *", "effect": "allow"},
    {"action": "shell", "resource": "python -m compileall *", "effect": "allow"},
    {"action": "shell", "resource": "python -m pytest *", "effect": "allow"},
    {"action": "shell", "resource": "npm test *", "effect": "allow"},
    {"action": "shell", "resource": "npm run build *", "effect": "allow"},
]

# Explicit hard denies. These come last so they win over the broad "ask" rule.
_HARD_DENIES = [
    {"action": "read", "resource": "*.env", "effect": "deny"},
    {"action": "read", "resource": "*.env.*", "effect": "deny"},
    {"action": "edit", "resource": "*.env", "effect": "deny"},
    {"action": "edit", "resource": "*.env.*", "effect": "deny"},
    {"action": "external_directory", "resource": "*", "effect": "deny"},
    {"action": "webfetch", "resource": "*", "effect": "deny"},
    {"action": "websearch", "resource": "*", "effect": "deny"},
    {"action": "subagent", "resource": "*", "effect": "deny"},
    {"action": "skill", "resource": "*", "effect": "deny"},
    {"action": "question", "resource": "*", "effect": "deny"},
    {"action": "execute", "resource": "*", "effect": "deny"},
    {"action": "opencode_list_mcp_resources", "resource": "*", "effect": "deny"},
    {"action": "opencode_read_mcp_resource", "resource": "*", "effect": "deny"},
    {"action": "Neon_*", "resource": "*", "effect": "deny"},
    {"action": "MCP_DOCKER_*", "resource": "*", "effect": "deny"},
    {"action": "shell", "resource": "rm *", "effect": "deny"},
    {"action": "shell", "resource": "del *", "effect": "deny"},
    {"action": "shell", "resource": "rmdir *", "effect": "deny"},
    {"action": "shell", "resource": "format *", "effect": "deny"},
    {"action": "shell", "resource": "git push *", "effect": "deny"},
    {"action": "shell", "resource": "git reset --hard *", "effect": "deny"},
    {"action": "shell", "resource": "git clean *", "effect": "deny"},
    {"action": "shell", "resource": "git checkout -- *", "effect": "deny"},
    {"action": "shell", "resource": "git restore *", "effect": "deny"},
    {"action": "shell", "resource": "Stop-Process *", "effect": "deny"},
    {"action": "shell", "resource": "Remove-Item *", "effect": "deny"},
    {"action": "shell", "resource": "sudo *", "effect": "deny"},
]


def permission_ruleset(mode: str) -> list[dict[str, str]]:
    """Build the ordered V2 permission ruleset attached to every voice session.

    ``read`` and ``plan`` never get an edit rule, so edits are denied by the
    leading default-deny rule. ``build`` gets an ``ask`` rule, which surfaces a
    spoken approval request rather than silently editing.
    """
    rules: list[dict[str, str]] = [
        {"action": "*", "resource": "*", "effect": "deny"},
        {"action": "read", "resource": "*", "effect": "allow"},
        {"action": "glob", "resource": "*", "effect": "allow"},
        {"action": "grep", "resource": "*", "effect": "allow"},
    ]
    rules.extend(_READ_SHELL_ALLOWS)
    if mode == "build":
        rules.append({"action": "edit", "resource": "*", "effect": "ask"})
        rules.append({"action": "shell", "resource": "*", "effect": "ask"})
    else:
        rules.append({"action": "shell", "resource": "*", "effect": "deny"})
    rules.extend(_HARD_DENIES)
    return rules


def _clean(value: Any, limit: int = 500) -> str:
    return " ".join(str(value or "").split())[:limit]


class OpenCodeError(RuntimeError):
    """A safe, voice-friendly OpenCode bridge error (never contains secrets)."""


def _service_password() -> str:
    """Resolve the loopback service password without ever exposing it."""
    explicit = os.getenv("OPENCODE_SERVICE_PASSWORD", "").strip()
    if explicit:
        return explicit
    try:
        config = Path.home() / ".config" / "opencode" / "service.json"
        if config.is_file():
            data = json.loads(config.read_text(encoding="utf-8"))
            return str(data.get("password") or "")
    except Exception as exc:  # pragma: no cover - local config edge cases
        logger.warning(f"Could not read local OpenCode service config: {exc}")
    return ""


def _safe_error(exc: Exception) -> str:
    """Strips anything that looks like a credential from an exception string."""
    text = str(exc)
    values = [
        os.getenv(name, "").strip()
        for name in (
            "OPENCODE_SERVICE_PASSWORD",
            "GEMINI_API_KEY",
            "TAVILY_API_KEY",
            "BRAVE_API_KEY",
            "NVIDIA_API_KEY",
        )
    ]
    # When the password comes from the local service config, it is not in the
    # environment but can still appear in an upstream error string.
    try:
        values.append(_service_password())
    except Exception:
        pass
    for value in values:
        if value:
            text = text.replace(value, "***REDACTED***")
    text = re.sub(r"(?i)(authorization|password|token)[\"':= ]+[^\s,}\"']+", r"\1=***REDACTED***", text)
    return text[:300]


class OpenCodeClient:
    def __init__(self) -> None:
        base = os.getenv("OPENCODE_BASE_URL", _DEFAULT_BASE_URL).strip() or _DEFAULT_BASE_URL
        parsed = urlparse(base)
        if parsed.hostname not in _LOOPBACK_HOSTS:
            raise OpenCodeError("OpenCode must be a loopback-only service.")
        self.base_url = f"{parsed.scheme}://{parsed.hostname}:{parsed.port or 80}".rstrip("/")
        _default_project = str(Path(__file__).resolve().parent.parent)
        _default_worktrees = str(Path(_default_project).parent / "VoiceAssistant-worktrees")
        self.project_dir = Path(
            os.getenv("OPENCODE_PROJECT_DIR", _default_project).strip() or _default_project
        )
        self.worktree_root = Path(
            os.getenv("OPENCODE_WORKTREE_ROOT", _default_worktrees).strip() or _default_worktrees
        )
        self._http: httpx.AsyncClient | None = None
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()
        self._stream_task: asyncio.Task | None = None
        self._agent_cache: tuple[float, list[str]] | None = None

    def _client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            password = _service_password()
            if not password:
                raise OpenCodeError("OpenCode service password is not configured on the backend.")
            self._http = httpx.AsyncClient(
                base_url=self.base_url,
                auth=("opencode", password),
                timeout=httpx.Timeout(20.0),
                headers={"User-Agent": "voice-assistant-opencode-bridge/1.0"},
            )
        return self._http

    async def close(self) -> None:
        task = self._stream_task
        if task is not None and not task.done():
            task.cancel()
        self._stream_task = None
        client = self._http
        if client is not None and not client.is_closed:
            await client.aclose()
        self._http = None
        self._subscribers.clear()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        try:
            response = await self._client().request(
                method, path, json=json_body, params=params, timeout=timeout
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code in (401, 403):
                raise OpenCodeError("OpenCode rejected the backend credentials.") from None
            raise OpenCodeError(f"OpenCode returned an HTTP {code} error.") from None
        except httpx.HTTPError as exc:
            raise OpenCodeError(f"OpenCode is not reachable. {_safe_error(exc)}") from None
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise OpenCodeError("OpenCode returned an unreadable response.") from exc

    # ------------------------------------------------------------------ basics

    async def health(self) -> bool:
        try:
            data = await self._request("GET", "/api/info", timeout=5.0)
            return bool(data.get("version"))
        except OpenCodeError:
            return False

    async def resolve_location(self, directory: str | Path) -> dict[str, Any]:
        """Resolve a directory to an OpenCode location/project pair."""
        data = await self._request(
            "GET", "/api/location", params={"location[directory]": str(directory)}
        )
        return data

    async def list_agents(self, directory: str | Path | None = None) -> list[str]:
        now = time.monotonic()
        if self._agent_cache and self._agent_cache[0] > now:
            return self._agent_cache[1]
        params = {"location[directory]": str(directory)} if directory else None
        data = await self._request("GET", "/api/agent", params=params)
        names = [str(item.get("name") or item.get("id") or "") for item in data.get("data") or []]
        names = [name for name in names if name]
        self._agent_cache = (now + 60.0, names)
        return names

    async def pick_agent(self, mode: str, directory: str | Path | None = None) -> str:
        """Prefer restricted voice agents, falling back to OpenCode built-ins."""
        preferred = "voice-coder" if mode == "build" else "voice-planner"
        fallback = "build" if mode == "build" else "plan"
        try:
            available = await self.list_agents(directory)
        except OpenCodeError:
            return fallback
        lowered = {name.lower() for name in available}
        if preferred.lower() in lowered:
            return preferred
        return fallback if fallback.lower() in lowered else (available[0] if available else fallback)

    async def list_models(self, directory: str | Path | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"types": "chat"}
        if directory:
            params["location[directory]"] = str(directory)
        data = await self._request("GET", "/api/model", params=params)
        return list(data.get("data") or [])

    async def resolve_model(self, model_ref: str, directory: str | Path | None = None) -> dict[str, Any]:
        """Accept provider/id, provider/model, or a bare model id / variant ref."""
        text = model_ref.strip()
        if not text:
            raise OpenCodeError("Please name the model you want.")
        models = await self.list_models(directory)
        by_id = {str(item.get("id") or "").lower(): item for item in models}
        candidates: list[str] = []
        if "/" in text:
            provider, _, rest = text.partition("/")
            candidates.append(text.lower())
            candidates.append(rest.split("#", 1)[0].lower())
            candidates.append(f"{provider}/{rest}".lower())
        else:
            candidates.append(text.lower())
        for key in candidates:
            match = by_id.get(key)
            if match:
                result: dict[str, Any] = {
                    "providerID": str(match.get("providerID") or ""),
                    "id": str(match.get("modelID") or match.get("id") or ""),
                }
                if "#" in text:
                    result["variant"] = text.split("#", 1)[1]
                if result["providerID"] and result["id"]:
                    return result
        raise OpenCodeError("I could not find that model in OpenCode's catalog.")

    # ---------------------------------------------------------------- worktree

    def _ensure_isolated_root(self) -> None:
        project = self.project_dir.resolve()
        root = self.worktree_root.resolve()
        if root == project or project in root.parents:
            raise OpenCodeError(
                "OpenCode worktrees must live outside the live project directory."
            )
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise OpenCodeError(f"Could not create the worktree root. {_safe_error(exc)}") from None

    async def create_worktree(self, label: str = "voice") -> str:
        """Create an isolated git worktree and return its directory."""
        self._ensure_isolated_root()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        name = f"{label}-{stamp}-{secrets.token_hex(2)}"
        location = await self.resolve_location(self.project_dir)
        project_id = str((location.get("project") or {}).get("id") or "")
        if not project_id:
            raise OpenCodeError("I could not resolve the OpenCode project id.")
        target = self.worktree_root.resolve() / name
        data = await self._request(
            "POST",
            "/api/worktree",
            json_body={"projectID": project_id, "name": name, "directory": str(target)},
        )
        directory = str(data.get("directory") or "")
        if not directory:
            raise OpenCodeError("OpenCode did not return a worktree directory.")
        logger.info(f"Created isolated OpenCode worktree at {directory}")
        return directory

    def _git_worktree_command(self, *args: str) -> str:
        """Run a read-only/maintenance git worktree command in the project."""
        result = subprocess.run(
            ["git", "-C", str(self.project_dir), "worktree", *args],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return result.stdout.strip()

    def _worktree_status(self, directory: Path) -> str:
        result = subprocess.run(
            ["git", "-C", str(directory), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return result.stdout.strip()

    async def remove_worktree(self, directory: str) -> bool:
        """Remove a worktree, its git registration, and its empty wrapper folder.

        OpenCode creates ``<root>/<name>/<name>`` but only removes the inner
        path, which leaves the outer wrapper behind. On Windows an OpenCode
        session whose working directory is that path keeps it locked, so the
        OpenCode DELETE can fail with ``Permission denied`` (HTTP 400). Retry
        briefly for the lock to clear, then fall back to git itself so cleanup
        does not silently leave hundreds of megabytes of stale worktrees.

        Only directories under the configured isolated root are ever touched.
        """
        location = await self.resolve_location(self.project_dir)
        project_id = str((location.get("project") or {}).get("id") or "")
        if not project_id:
            return False
        target = Path(directory).resolve()
        root = self.worktree_root.resolve()
        if root not in target.parents:
            logger.warning("Refusing to remove an OpenCode worktree outside the isolated root.")
            return False

        removed = False
        for attempt in range(3):
            try:
                await self._request(
                    "DELETE",
                    "/api/worktree",
                    json_body={
                        "projectID": project_id,
                        "directory": str(target),
                        "force": True,
                    },
                )
                removed = True
                break
            except OpenCodeError as exc:
                logger.debug(
                    f"OpenCode worktree removal attempt {attempt + 1} failed: {_safe_error(exc)}"
                )
                await asyncio.sleep(0.5 * (attempt + 1))

        try:
            await self._request(
                "POST", "/api/worktree/refresh", json_body={"projectID": project_id}
            )
        except OpenCodeError as exc:
            logger.debug(f"Could not refresh worktree list: {_safe_error(exc)}")

        # OpenCode deregisters the worktree even when it cannot delete the
        # files, so fall back to git to finish the job.
        if target.exists():
            try:
                await asyncio.to_thread(self._git_worktree_command, "remove", "--force", str(target))
            except (OSError, subprocess.SubprocessError) as exc:
                logger.debug(f"Could not git-remove worktree: {_safe_error(exc)}")
            try:
                await asyncio.to_thread(self._git_worktree_command, "prune")
            except (OSError, subprocess.SubprocessError) as exc:
                logger.debug(f"Could not prune worktree registration: {_safe_error(exc)}")

            # OpenCode may already have deregistered the worktree (and removed
            # its .git file) while leaving the checkout behind, so git cannot
            # finish the job. Remove any remnants directly, with a short retry
            # for the Windows directory lock to clear.
            for attempt in range(3):
                if not target.exists():
                    break
                try:
                    await asyncio.to_thread(shutil.rmtree, target)
                except OSError as exc:
                    logger.debug(
                        f"Could not remove worktree files (attempt {attempt + 1}): "
                        f"{_safe_error(exc)}"
                    )
                    await asyncio.sleep(0.5 * (attempt + 1))

        parent = target.parent
        if root in parent.parents and parent.exists():
            try:
                # OpenCode leaves <root>/<name> behind. rmdir succeeds once the
                # inner directory is gone; rmtree only removes the now-empty
                # wrapper and never reaches the project checkout.
                if any(parent.iterdir()):
                    logger.debug(f"Worktree wrapper is not empty, preserving it: {parent}")
                else:
                    parent.rmdir()
            except OSError as exc:
                logger.debug(f"Could not remove empty worktree wrapper: {_safe_error(exc)}")

        gone = not target.exists()
        if removed and not gone:
            logger.warning("OpenCode deregistered a worktree whose files are still on disk.")
        return gone

    def worktree_cleanup_report(self, *, max_age_days: int = 7) -> list[dict[str, str]]:
        """Read-only report of which voice worktrees would be pruned, and why.

        A worktree is only a cleanup candidate when it is older than
        ``max_age_days`` and its git status is clean (no tracked edits and no
        untracked files). Worktrees containing files the voice agent created are
        always preserved so the user can inspect them.
        """
        report: list[dict[str, str]] = []
        root = self.worktree_root.resolve()
        if not root.exists():
            return report
        cutoff = time.time() - max(0, max_age_days) * 86400
        for wrapper in sorted(root.iterdir()):
            if not wrapper.is_dir():
                continue
            target = wrapper / wrapper.name
            if not target.is_dir() or not (target / ".git").exists():
                # A failed earlier removal can leave an empty wrapper behind.
                try:
                    has_files = any(path.is_file() for path in wrapper.rglob("*"))
                except OSError:
                    has_files = True
                reason = "not a worktree" if has_files else "empty leftover"
                action = "keep" if has_files else "prune"
                report.append({"path": str(wrapper), "action": action, "reason": reason})
                continue
            entry = {"path": str(target), "action": "prune", "reason": "old and clean"}
            try:
                if self._worktree_status(target):
                    entry.update(action="keep", reason="has agent files")
                elif wrapper.stat().st_mtime > cutoff:
                    entry.update(action="keep", reason="recent")
            except OSError as exc:
                entry.update(action="keep", reason=f"inspection failed: {_safe_error(exc)}")
            report.append(entry)
        return report

    async def prune_stale_worktrees(self, *, max_age_days: int = 7) -> dict[str, int]:
        """Remove old, clean worktrees. Preserve any worktree with agent files."""
        stats = {"pruned": 0, "preserved_files": 0, "preserved_recent": 0, "failed": 0}
        for entry in self.worktree_cleanup_report(max_age_days=max_age_days):
            action = entry["action"]
            if action == "keep":
                key = "preserved_files" if entry["reason"] == "has agent files" else "preserved_recent"
                stats[key] += 1
                continue
            if entry["reason"] == "empty leftover":
                try:
                    await asyncio.to_thread(shutil.rmtree, entry["path"])
                    stats["pruned"] += 1
                except OSError as exc:
                    logger.debug(f"Could not remove empty worktree wrapper: {_safe_error(exc)}")
                    stats["failed"] += 1
                continue
            if await self.remove_worktree(entry["path"]):
                stats["pruned"] += 1
            else:
                stats["failed"] += 1
        return stats

    # ----------------------------------------------------------------- session

    async def create_session(
        self,
        *,
        directory: str,
        agent: str,
        title: str,
        mode: str,
        model_ref: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "title": title[:120],
            "location": {"directory": directory},
            "agent": agent,
            "permissions": permission_ruleset(mode),
            "metadata": {
                "voice_source": "voice-assistant",
                "voice_mode": mode,
                "worktree_dir": directory,
            },
        }
        data = await self._request("POST", "/api/session", json_body=body)
        info = data.get("data") or {}
        session_id = str(info.get("id") or "")
        if not session_id:
            raise OpenCodeError("OpenCode did not create a session.")
        if model_ref:
            try:
                await self.set_model(session_id, model_ref, directory)
            except OpenCodeError as exc:
                logger.warning(f"Could not select requested OpenCode model: {_safe_error(exc)}")
        return info

    async def get_session(self, session_id: str) -> dict[str, Any]:
        data = await self._request("GET", f"/api/session/{session_id}")
        return dict(data.get("data") or {})

    async def list_sessions(self, directory: str | Path | None = None, limit: int = 30) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": str(max(1, min(int(limit), 100))), "order": "desc"}
        if directory:
            params["directory"] = str(directory)
        data = await self._request("GET", "/api/session", params=params)
        return list(data.get("data") or [])

    async def set_model(self, session_id: str, model_ref: str, directory: str | Path | None = None) -> None:
        model = await self.resolve_model(model_ref, directory)
        await self._request("POST", f"/api/session/{session_id}/model", json_body={"model": model})

    async def set_agent(self, session_id: str, agent: str) -> None:
        await self._request("POST", f"/api/session/{session_id}/agent", json_body={"agent": agent})

    async def prompt(
        self,
        session_id: str,
        text: str,
        *,
        resume: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"text": text, "delivery": "steer"}
        if resume:
            body["resume"] = True
        if metadata:
            body["metadata"] = metadata
        data = await self._request("POST", f"/api/session/{session_id}/prompt", json_body=body)
        return dict(data.get("data") or {})

    async def messages(self, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        data = await self._request(
            "GET",
            f"/api/session/{session_id}/message",
            params={"limit": str(max(1, min(int(limit), 100))), "order": "desc"},
        )
        return list(data.get("data") or [])

    async def pending_permissions(self, session_id: str) -> list[dict[str, Any]]:
        """Read pending approval requests from OpenCode, not just the SSE stream.

        This is a reliable fallback when a short-lived prompt finishes before the
        bridge's event subscription is established, or when the stream reconnects.
        """
        data = await self._request("GET", f"/api/session/{session_id}/permission")
        return [dict(item) for item in (data.get("data") or []) if isinstance(item, dict)]

    async def session_state(self, session_id: str) -> dict[str, Any]:
        """One poll of the two state sources the bridge needs."""
        info: dict[str, Any] = {}
        permissions: list[dict[str, Any]] = []
        try:
            info = await self.get_session(session_id)
        except OpenCodeError as exc:
            logger.debug(f"Could not poll OpenCode session state: {_safe_error(exc)}")
        try:
            permissions = await self.pending_permissions(session_id)
        except OpenCodeError as exc:
            logger.debug(f"Could not poll OpenCode permissions: {_safe_error(exc)}")
        return {
            "info": info,
            "permissions": permissions,
            "baseline": {
                "updated": ((info.get("time") or {}).get("updated")),
                "permission_ids": {str(item.get("id") or "") for item in permissions},
            },
        }

    async def diff(self, session_id: str) -> list[dict[str, Any]]:
        data = await self._request("GET", f"/api/session/{session_id}/diff")
        return list(data.get("data") or [])

    async def reply_permission(
        self, session_id: str, request_id: str, decision: str
    ) -> None:
        if decision not in {"once", "always", "reject"}:
            raise OpenCodeError("Invalid approval decision.")
        await self._request(
            "POST",
            f"/api/session/{session_id}/permission/{request_id}/reply",
            json_body={"decision": decision},
        )

    # ------------------------------------------------------------ event stream

    async def subscribe(self, session_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        async with self._lock:
            self._subscribers.setdefault(session_id, set()).add(queue)
            if self._stream_task is None or self._stream_task.done():
                self._stream_task = asyncio.create_task(
                    self._stream_loop(), name="opencode-event-stream"
                )
        return queue

    async def unsubscribe(self, session_id: str, queue: asyncio.Queue) -> None:
        async with self._lock:
            subscribers = self._subscribers.get(session_id)
            if subscribers:
                subscribers.discard(queue)
                if not subscribers:
                    self._subscribers.pop(session_id, None)

    async def _dispatch(self, event: dict[str, Any]) -> None:
        session_id = str((event.get("data") or {}).get("sessionID") or "")
        if not session_id:
            return
        async with self._lock:
            targets = list(self._subscribers.get(session_id) or [])
            targets.extend(self._subscribers.get("*") or [])
        for queue in targets:
            queue.put_nowait(event)

    async def _stream_loop(self) -> None:
        backoff = 1.0
        while True:
            try:
                async with self._client().stream(
                    "GET", "/api/event", timeout=None
                ) as response:
                    response.raise_for_status()
                    backoff = 1.0
                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if not raw or raw.startswith("heartbeat"):
                            continue
                        try:
                            payload = json.loads(raw)
                        except ValueError:
                            continue
                        event_type = str(payload.get("type") or "")
                        if event_type not in _INTERESTING_EVENTS:
                            continue
                        event = {
                            "id": payload.get("id"),
                            "type": event_type,
                            "data": payload.get("data") or {},
                        }
                        await self._dispatch(event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(f"OpenCode event stream interrupted: {_safe_error(exc)}")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 10.0)

    @staticmethod
    def _event_terminal(event: dict[str, Any]) -> dict[str, Any] | None:
        """Translate one lifecycle event into a small, speakable status."""
        event_type = event.get("type")
        data = event.get("data") or {}
        if event_type == "permission.asked":
            return {"status": "permission", "permission": dict(data)}
        if event_type == "session.execution.succeeded":
            return {"status": "succeeded"}
        if event_type == "session.execution.failed":
            return {"status": "failed", "error": _clean(data.get("error"), 300)}
        if event_type == "session.execution.interrupted":
            return {"status": "interrupted", "reason": _clean(data.get("reason"), 100)}
        if event_type == "session.idle":
            outcome = data.get("outcome")
            if outcome:
                return {"status": str(outcome)}
            return {"status": "idle"}
        return None

    async def wait_for_terminal(
        self,
        session_id: str,
        timeout: float,
        *,
        queue: asyncio.Queue | None = None,
        baseline: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Wait for completion, a permission prompt, or a timeout.

        The SSE queue is fast; polling ``/api/session/{id}`` and
        ``/api/session/{id}/permission`` covers events missed during a stream
        reconnect. ``baseline`` prevents the previous outcome of a resumed
        session from being mistaken for the new task's result.
        """
        owns_queue = queue is None
        if queue is None:
            queue = await self.subscribe(session_id)
        if baseline is None:
            state = await self.session_state(session_id)
            baseline = {
                "updated": ((state.get("info") or {}).get("time") or {}).get("updated"),
                "permission_ids": {
                    str(item.get("id") or "") for item in state.get("permissions") or []
                },
            }
        baseline_ids = set(baseline.get("permission_ids") or set())
        baseline_updated = baseline.get("updated")
        deadline = time.monotonic() + max(1.0, timeout)
        try:
            while True:
                # Drain anything already queued before falling back to HTTP state.
                while True:
                    try:
                        event = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    terminal = self._event_terminal(event)
                    if terminal:
                        return terminal

                state = await self.session_state(session_id)
                for permission in state.get("permissions") or []:
                    request_id = str(permission.get("id") or "")
                    if not baseline_ids or request_id not in baseline_ids:
                        return {"status": "permission", "permission": dict(permission)}
                info = state.get("info") or {}
                outcome = info.get("outcome")
                updated = ((info.get("time") or {}).get("updated"))
                changed = baseline_updated is None or (
                    bool(updated) and str(updated) != str(baseline_updated)
                )
                if outcome and changed:
                    return {"status": str(outcome)}

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return {"status": "timeout"}
                try:
                    event = await asyncio.wait_for(queue.get(), min(remaining, 1.0))
                except asyncio.TimeoutError:
                    continue
                terminal = self._event_terminal(event)
                if terminal:
                    return terminal
        finally:
            if owns_queue:
                await self.unsubscribe(session_id, queue)

    async def prompt_and_wait(
        self,
        session_id: str,
        text: str,
        timeout: float,
        *,
        metadata: dict[str, Any] | None = None,
        baseline: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Subscribe first, then prompt, so no early event can be missed."""
        queue = await self.subscribe(session_id)
        try:
            await self.prompt(session_id, text, metadata=metadata)
            return await self.wait_for_terminal(
                session_id, timeout, queue=queue, baseline=baseline
            )
        finally:
            await self.unsubscribe(session_id, queue)


opencode_client = OpenCodeClient()


async def close_opencode_client() -> None:
    await opencode_client.close()
