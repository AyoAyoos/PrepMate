"""Shared function-calling tools for Gemini Live and the local LLM fallback.

All API keys are read from the environment on the backend and are never part of
a tool result, browser message, or log line. Every handler always calls the
result callback, even on failure, so a tool call can never stall a voice turn.
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import re
import socket
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytz
from loguru import logger
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.frames.frames import EndFrame, FunctionCallResultProperties
from pipecat.services.llm_service import FunctionCallParams

from storage import embeddings as embedding_service
from storage.duckdb_store import store
from tools.opencode_client import OpenCodeError, opencode_client

_WEB_TIMEOUT = 8.0
_MAX_RESULT_CHARS = 4000
_web_client: httpx.AsyncClient | None = None
# request_id -> timer task. A missing spoken answer always rejects the request.
_approval_timers: dict[str, asyncio.Task] = {}


async def get_web_client() -> httpx.AsyncClient:
    """One pooled client so search/extract connections stay warm."""
    global _web_client
    if _web_client is None or _web_client.is_closed:
        _web_client = httpx.AsyncClient(
            timeout=_WEB_TIMEOUT,
            headers={"User-Agent": "voice-assistant/1.0 (+local)"},
        )
    return _web_client


async def close_web_client() -> None:
    global _web_client
    if _web_client is not None and not _web_client.is_closed:
        await _web_client.aclose()
    _web_client = None


def _redact(text: str) -> str:
    safe = text
    for name in ("TAVILY_API_KEY", "BRAVE_API_KEY", "GEMINI_API_KEY", "NVIDIA_API_KEY"):
        key = os.getenv(name, "").strip()
        if key:
            safe = safe.replace(key, "***REDACTED***")
    return safe


async def _safe_call(params: FunctionCallParams, handler) -> None:
    try:
        await handler()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        message = _redact(str(exc))
        logger.error(f"Tool {params.function_name} failed: {message}")
        await params.result_callback(
            {"error": f"{params.function_name} is unavailable right now."},
            properties=FunctionCallResultProperties(run_llm=True),
        )


def _coerce_limit(value: Any, default: int, maximum: int) -> int:
    try:
        return max(1, min(int(value), maximum))
    except (TypeError, ValueError):
        return default


# ------------------------------------------------------- PrepMate syllabus RAG


async def syllabus_search(params: FunctionCallParams) -> None:
    """Answer spoken course questions from PrepMate's DuckDB + HNSW-backed /ask endpoint."""

    question = str(params.arguments.get("question") or "").strip()

    async def handler() -> None:
        if not question:
            await params.result_callback(
                {"error": "Please tell me your course question."},
                properties=FunctionCallResultProperties(run_llm=True),
            )
            return

        base = os.getenv("PREPMATE_API_BASE", "http://127.0.0.1:8000").strip().rstrip("/")
        # RAG retrieval + generation can take longer than the short web timeout.
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{base}/ask",
                json={"question": question[:1000]},
                headers={"Content-Type": "application/json"},
            )
        if response.status_code != 200:
            raise RuntimeError(f"PrepMate /ask returned HTTP {response.status_code}")

        payload = response.json()
        answer = " ".join(str(payload.get("answer") or "").split())[:_MAX_RESULT_CHARS]
        note = " ".join(str(payload.get("note") or "").split())[:500]
        sources: list[str] = []
        for citation in (payload.get("citations") or [])[:4]:
            if not isinstance(citation, dict):
                continue
            filename = str(citation.get("source_file") or "").strip()
            if not filename:
                continue
            page = citation.get("page") or 0
            sources.append(f"{filename}, page {page}" if page else filename)

        result: dict[str, Any] = {
            "answer": answer,
            "grounded": bool(payload.get("grounded")),
            "sources": sources,
            "note": note,
            "source": "prepmate-syllabus-rag",
        }
        if not answer:
            result["error"] = "The course index did not return an answer."
        await params.result_callback(
            result, properties=FunctionCallResultProperties(run_llm=True)
        )

    await _safe_call(params, handler)


# ---------------------------------------------------------------- web search


async def _tavily_search(query: str, limit: int) -> dict[str, Any]:
    key = os.getenv("TAVILY_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Tavily is not configured")
    client = await get_web_client()
    response = await client.post(
        "https://api.tavily.com/search",
        json={
            "api_key": key,
            "query": query,
            "search_depth": "basic",
            "topic": "general",
            "max_results": limit,
            "include_answer": True,
            "include_raw_content": False,
        },
    )
    response.raise_for_status()
    data = response.json()
    results = []
    for item in data.get("results") or []:
        if not isinstance(item, dict):
            continue
        results.append(
            {
                "title": str(item.get("title") or "")[:200],
                "url": str(item.get("url") or "")[:500],
                "snippet": " ".join(str(item.get("content") or "").split())[:600],
            }
        )
    return {
        "answer": " ".join(str(data.get("answer") or "").split())[:800] or None,
        "results": results,
        "source": "tavily",
    }


async def _brave_search(query: str, limit: int) -> dict[str, Any]:
    key = os.getenv("BRAVE_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Brave is not configured")
    client = await get_web_client()
    response = await client.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": limit},
        headers={"X-Subscription-Token": key, "Accept": "application/json"},
    )
    response.raise_for_status()
    data = response.json()
    results = []
    for item in (data.get("web") or {}).get("results") or []:
        if not isinstance(item, dict):
            continue
        results.append(
            {
                "title": str(item.get("title") or "")[:200],
                "url": str(item.get("url") or "")[:500],
                "snippet": " ".join(str(item.get("description") or "").split())[:600],
            }
        )
    return {"answer": None, "results": results, "source": "brave"}


async def web_search(params: FunctionCallParams) -> None:
    query = str(params.arguments.get("query") or "").strip()
    limit = _coerce_limit(params.arguments.get("max_results"), 5, 8)

    async def handler() -> None:
        if not query:
            await params.result_callback(
                {"error": "Please tell me what to search for."},
                properties=FunctionCallResultProperties(run_llm=True),
            )
            return
        payload: dict[str, Any] | None = None
        failures: list[str] = []
        for search in (_tavily_search, _brave_search):
            try:
                payload = await search(query, limit)
                if payload.get("results") or payload.get("answer"):
                    break
                payload = None
            except Exception as exc:
                failures.append(_redact(str(exc)))
        if payload is None:
            logger.warning(f"Web search unavailable: {'; '.join(failures)[:300]}")
            payload = {
                "error": "Web search is unavailable right now.",
                "results": [],
                "answer": None,
                "source": "none",
            }
        payload["query"] = query[:300]
        await params.result_callback(
            payload, properties=FunctionCallResultProperties(run_llm=True)
        )

    await _safe_call(params, handler)


# --------------------------------------------------------------- fetch page


def _html_to_text(html: str) -> str:
    text = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    return " ".join(text.split())


async def _tavily_extract(url: str) -> str:
    key = os.getenv("TAVILY_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Tavily is not configured")
    client = await get_web_client()
    response = await client.post(
        "https://api.tavily.com/extract",
        json={"api_key": key, "urls": [url], "include_raw_content": True},
    )
    response.raise_for_status()
    data = response.json()
    for item in data.get("results") or []:
        if isinstance(item, dict):
            content = item.get("raw_content") or item.get("content") or ""
            if content:
                return " ".join(str(content).split())[:_MAX_RESULT_CHARS]
    return ""


async def fetch_page(params: FunctionCallParams) -> None:
    url = str(params.arguments.get("url") or "").strip()

    async def handler() -> None:
        if not url.lower().startswith(("http://", "https://")):
            await params.result_callback(
                {"error": "That is not a valid web address."},
                properties=FunctionCallResultProperties(run_llm=True),
            )
            return
        text, source, failure = "", "none", ""
        try:
            text = await _tavily_extract(url)
            if text:
                source = "tavily"
        except Exception as exc:
            failure = _redact(str(exc))
        if not text:
            try:
                client = await get_web_client()
                response = await client.get(url, follow_redirects=True)
                response.raise_for_status()
                text = _html_to_text(response.text)[:_MAX_RESULT_CHARS]
                if text:
                    source = "direct"
            except Exception as exc:
                failure = f"{failure}; {_redact(str(exc))}" if failure else _redact(str(exc))
        if not text:
            logger.warning(f"fetch_page failed for {url[:120]}: {failure[:300]}")
        await params.result_callback(
            {
                "url": url[:500],
                "text": text or None,
                "source": source,
                "error": None if text else "I could not read that page.",
            },
            properties=FunctionCallResultProperties(run_llm=True),
        )

    await _safe_call(params, handler)


# ------------------------------------------------------------ memory search


async def memory_search(params: FunctionCallParams) -> None:
    query = str(params.arguments.get("query") or "").strip()

    async def handler() -> None:
        if not query:
            await params.result_callback(
                {"memories": [], "count": 0},
                properties=FunctionCallResultProperties(run_llm=True),
            )
            return
        limit = _coerce_limit(params.arguments.get("limit"), 6, 12)
        embedding = await embedding_service.embedder.embed_text(query)
        matches = await store.search_memories(
            embedding=embedding, query=query, limit=limit
        )
        memories = [
            {
                "content": str(item.get("content") or "")[:300],
                "category": item.get("category"),
            }
            for item in matches
            if str(item.get("content") or "").strip()
        ]
        if matches:
            await store.touch_memories([str(item["id"]) for item in matches])
        await params.result_callback(
            {"memories": memories, "count": len(memories)},
            properties=FunctionCallResultProperties(run_llm=True),
        )

    await _safe_call(params, handler)


# ------------------------------------------------------------- time and date


async def get_current_time(params: FunctionCallParams) -> None:
    tz_name = str(params.arguments.get("timezone") or "").strip() or "local"

    async def handler() -> None:
        zone = None
        if tz_name != "local":
            try:
                zone = pytz.timezone(tz_name)
            except (pytz.UnknownTimeZoneError, ValueError):
                zone = None
        now = datetime.now(zone) if zone else datetime.now().astimezone()
        label = tz_name if zone else "local"
        await params.result_callback(
            {
                "time": now.strftime("%I:%M %p").lstrip("0"),
                "date": now.strftime("%A, %B %-d, %Y")
                if os.name != "nt"
                else now.strftime("%A, %B %d, %Y"),
                "iso": now.isoformat(timespec="seconds"),
                "timezone": label,
            },
            properties=FunctionCallResultProperties(run_llm=True),
        )

    await _safe_call(params, handler)


# ----------------------------------------------------------------- reminders


def _parse_due_at(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        logger.warning(f"Ignoring unparseable reminder due_at: {text[:60]}")
        return None
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.astimezone(timezone.utc)


async def store_reminder(params: FunctionCallParams) -> None:
    content = str(params.arguments.get("content") or "").strip()

    async def handler() -> None:
        if not content:
            await params.result_callback(
                {"error": "I need the reminder text."},
                properties=FunctionCallResultProperties(run_llm=True),
            )
            return
        due_at = _parse_due_at(params.arguments.get("due_at"))
        category = params.arguments.get("category")
        reminder_id = await store.add_reminder(
            content=content,
            due_at=due_at,
            category=str(category)[:40] if category else None,
            metadata={"source": "voice"},
        )
        await params.result_callback(
            {
                "status": "success",
                "action": "stored",
                "id": reminder_id,
                "content": content[:300],
                "due_at": due_at.isoformat() if due_at else None,
            },
            properties=FunctionCallResultProperties(run_llm=True),
        )

    await _safe_call(params, handler)


async def list_reminders(params: FunctionCallParams) -> None:
    async def handler() -> None:
        status = str(params.arguments.get("status") or "pending").strip().lower()
        if status not in {"pending", "done", "all"}:
            status = "pending"
        limit = _coerce_limit(params.arguments.get("limit"), 10, 25)
        rows = await store.list_reminders(
            status=None if status == "all" else status, limit=limit
        )
        reminders = [
            {
                "content": str(item.get("content") or "")[:300],
                "status": item.get("status"),
                "due_at": str(item["due_at"]) if item.get("due_at") else None,
            }
            for item in rows
        ]
        await params.result_callback(
            {"reminders": reminders, "count": len(reminders)},
            properties=FunctionCallResultProperties(run_llm=True),
        )

    await _safe_call(params, handler)


async def complete_reminder(params: FunctionCallParams) -> None:
    async def handler() -> None:
        reminder_id = str(params.arguments.get("reminder_id") or "").strip() or None
        text = str(params.arguments.get("content_contains") or "").strip() or None
        done = await store.complete_reminder(reminder_id=reminder_id, content_contains=text)
        await params.result_callback(
            {"status": "success" if done else "not_found", "completed": done},
            properties=FunctionCallResultProperties(run_llm=True),
        )

    await _safe_call(params, handler)


# --------------------------------------------------------------- system info


async def get_system_info(params: FunctionCallParams) -> None:
    async def handler() -> None:
        try:
            hostname = socket.gethostname()
        except Exception:
            hostname = "unknown"
        await params.result_callback(
            {
                "os": f"{platform.system()} {platform.release()}",
                "architecture": platform.machine(),
                "cpu_cores": os.cpu_count(),
                "hostname": hostname,
                "backend": os.getenv("VOICE_BACKEND", "auto"),
                "python": platform.python_version(),
            },
            properties=FunctionCallResultProperties(run_llm=True),
        )

    await _safe_call(params, handler)


# ------------------------------------------------------------- OpenCode bridge


def _env_float(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
        return value if value > 0 else default
    except ValueError:
        return default


def _short_code(session_id: str) -> str:
    return str(session_id or "")[-8:]


def _clean_text(value: Any, limit: int = 600) -> str:
    return " ".join(str(value or "").split())[:limit]


def _decode_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        decoded = json.loads(str(value))
        return decoded if isinstance(decoded, list) else []
    except (TypeError, ValueError):
        return []


def _timestamp(value: Any) -> datetime | None:
    """OpenCode time fields are epoch milliseconds."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return datetime.fromtimestamp(number / 1000, timezone.utc)


async def _fetch_resilient(coro_factory, *, attempts: int = 3):
    """Retry short transient OpenCode 500s while a turn is still settling."""
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return await coro_factory()
        except OpenCodeError as exc:
            last_error = exc
            if "500" not in str(exc) or attempt == attempts - 1:
                raise
            await asyncio.sleep(0.5 * (attempt + 1))
    raise last_error or OpenCodeError("OpenCode request failed.")


def _record_from_row(row: dict[str, Any]) -> dict[str, Any]:
    record = dict(row)
    for field in ("files_changed", "milestones"):
        record[field] = _decode_list(record.get(field))
    return record


def _permission_question(permission: dict[str, Any]) -> str:
    action = _clean_text(permission.get("action"), 60) or "an action"
    resources = permission.get("resources") or []
    resource = _clean_text(resources[0] if resources else "that resource", 160)
    message = _clean_text(permission.get("message"), 220)
    lead = message or "OpenCode is asking for approval"
    return f"{lead} for {action} on {resource}. Should I allow it once?"


def _cancel_approval_timer(request_id: str) -> None:
    task = _approval_timers.pop(request_id, None)
    if task is not None and not task.done():
        task.cancel()


async def cancel_approval_timers() -> None:
    """Cancel pending default-reject timers during backend shutdown."""
    for task in list(_approval_timers.values()):
        if not task.done():
            task.cancel()
    _approval_timers.clear()


async def _reject_expired_permission(
    session_id: str, request_id: str, expires_at: datetime
) -> None:
    """Default rejection when the user never answers a spoken approval question."""
    try:
        delay = max(0.0, (expires_at - datetime.now(timezone.utc)).total_seconds())
        if delay:
            await asyncio.sleep(delay)
        row = await store.get_opencode_session(session_id)
        if not row or str(row.get("pending_permission_id") or "") != request_id:
            return
        try:
            pending = await opencode_client.pending_permissions(session_id)
        except OpenCodeError:
            pending = []
        if not any(str(item.get("id") or "") == request_id for item in pending):
            await store.clear_opencode_permission(session_id, status="running")
            return
        try:
            await opencode_client.reply_permission(session_id, request_id, "reject")
        except OpenCodeError as exc:
            logger.warning(f"Could not auto-reject expired approval: {_safe_bridge_error(exc)}")
        await store.clear_opencode_permission(session_id, status="interrupted")
        await store.upsert_opencode_session(
            {
                "opencode_session_id": session_id,
                "status": "interrupted",
                "end_reason": "Approval timed out",
                "updated_at": datetime.now(timezone.utc),
            }
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning(f"Approval timeout handler failed: {_safe_bridge_error(exc)}")
    finally:
        _approval_timers.pop(request_id, None)


async def _store_pending_permission(
    session_id: str, permission: dict[str, Any]
) -> datetime:
    request_id = str(permission.get("id") or "")
    resources = [str(item) for item in (permission.get("resources") or [])]
    expires = datetime.now(timezone.utc) + timedelta(
        seconds=_env_float("OPENCODE_APPROVAL_TIMEOUT_SECONDS", 60)
    )
    await store.set_opencode_permission(
        session_id,
        request_id,
        str(permission.get("action") or ""),
        resources,
        str(permission.get("message") or ""),
        expires,
    )
    if request_id:
        _cancel_approval_timer(request_id)
        task = asyncio.create_task(
            _reject_expired_permission(session_id, request_id, expires),
            name=f"opencode-approval-{request_id[-8:]}",
        )
        _approval_timers[request_id] = task
    return expires


def _assistant_text(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for message in messages:
        if message.get("type") != "assistant":
            continue
        for content in message.get("content") or []:
            if isinstance(content, dict) and content.get("type") == "text":
                text = _clean_text(content.get("text"), 1200)
                if text:
                    parts.append(text)
    return "\n".join(parts)


def _summarize_messages(
    messages: list[dict[str, Any]], diffs: list[dict[str, Any]]
) -> dict[str, Any]:
    last_user = next((msg for msg in messages if msg.get("type") == "user"), None)
    idle = next((msg for msg in messages if msg.get("type") == "idle"), None)
    summary = _assistant_text(messages)
    error = next(
        (
            _clean_text(msg.get("error"), 300)
            for msg in messages
            if msg.get("type") == "assistant" and msg.get("error")
        ),
        "",
    )
    if not summary and error:
        summary = f"OpenCode reported an error: {error}"
    if not summary:
        summary = "The task finished without a written summary."
    files: list[str] = []
    additions = 0
    deletions = 0
    for diff in diffs:
        name = _clean_text(diff.get("file"), 200)
        if name:
            files.append(name)
        try:
            additions += int(diff.get("additions") or 0)
            deletions += int(diff.get("deletions") or 0)
        except (TypeError, ValueError):
            pass
    if idle and str(idle.get("outcome") or "") in {"failed", "interrupted"}:
        summary = f"OpenCode ended with {idle.get('outcome')}. {summary}"[:1200]
    first_sentence = re.split(r"(?<=[.!?])\s+", summary, maxsplit=1)[0][:220]
    milestones: list[str] = []
    if files:
        milestones.append(f"{len(files)} file{'s' if len(files) != 1 else ''} changed")
    if additions or deletions:
        milestones.append(f"{additions} additions, {deletions} deletions")
    if error:
        milestones.append("an error was reported")
    return {
        "last_request": _clean_text(last_user.get("text"), 500) if last_user else None,
        "resume_anchor": str(last_user.get("id") or "") if last_user else None,
        "summary": summary[:1200],
        "one_line_recap": first_sentence,
        "files_changed": files[:40],
        "milestones": milestones,
        "outcome": str((idle or {}).get("outcome") or "") or None,
        "error": error,
    }


async def _record_from_opencode(info: dict[str, Any], mode: str | None = None) -> dict[str, Any]:
    session_id = str(info.get("id") or "")
    location = info.get("location") or {}
    directory = str(location.get("directory") or opencode_client.project_dir)
    model = info.get("model") or {}
    timestamps = info.get("time") or {}
    now = datetime.now(timezone.utc)
    outcome = info.get("outcome")
    status = "succeeded" if outcome == "succeeded" else (
        "failed" if outcome == "failed" else ("interrupted" if outcome == "interrupted" else "idle")
    )
    return {
        "opencode_session_id": session_id,
        "short_code": _short_code(session_id),
        "project_id": str(info.get("projectID") or ""),
        "worktree_dir": directory,
        "status": status,
        "end_reason": outcome,
        "agent": str(info.get("agent") or "") or None,
        "model_provider": str(model.get("providerID") or "") or None,
        "model_id": str(model.get("id") or "") or None,
        "mode": mode or "read",
        "title": _clean_text(info.get("title"), 120) or f"OpenCode session {_short_code(session_id)}",
        "review_state": "unreviewed",
        "created_at": _timestamp(timestamps.get("created")) or now,
        "updated_at": _timestamp(timestamps.get("updated")) or now,
        "metadata": {"source": "opencode-api"},
    }


async def _resolve_record(key: str) -> dict[str, Any] | None:
    row = await store.get_opencode_session(key)
    if row:
        return _record_from_row(row)
    try:
        info = await opencode_client.get_session(key)
    except OpenCodeError:
        return None
    if not info.get("id"):
        return None
    record = await _record_from_opencode(info)
    await store.upsert_opencode_session(record)
    return record


async def _finalize_record(
    record: dict[str, Any], terminal: dict[str, Any] | None, *, fetch: bool = True
) -> dict[str, Any]:
    """Refresh speakable metadata from OpenCode and persist the local notebook."""
    session_id = str(record.get("opencode_session_id") or "")
    terminal = terminal or {}
    status = terminal.get("status")
    if status in {"succeeded", "idle"}:
        status = "succeeded"
    elif status in {"failed", "interrupted"}:
        pass
    elif status in {"permission", "timeout"}:
        status = "running"
    else:
        status = str(record.get("status") or "running")
    end_reason = _clean_text(
        terminal.get("error") or terminal.get("reason") or record.get("end_reason"), 300
    ) or None
    updated = dict(record)
    updated["status"] = status
    updated["end_reason"] = end_reason
    updated["updated_at"] = datetime.now(timezone.utc)
    if status in {"succeeded", "failed", "interrupted"}:
        updated["ended_at"] = updated["updated_at"]
        await store.clear_opencode_permission(session_id, status=status)
    if fetch:
        await asyncio.sleep(0.3)  # let the OpenCode projection settle first
        try:
            info = await _fetch_resilient(lambda: opencode_client.get_session(session_id))
            if info:
                model = info.get("model") or {}
                tokens = info.get("tokens") or {}
                updated["agent"] = str(info.get("agent") or updated.get("agent") or "") or None
                updated["model_provider"] = str(model.get("providerID") or updated.get("model_provider") or "") or None
                updated["model_id"] = str(model.get("id") or updated.get("model_id") or "") or None
                updated["title"] = _clean_text(info.get("title"), 120) or updated.get("title")
                try:
                    updated["tokens_input"] = int(tokens.get("input") or 0)
                    updated["tokens_output"] = int(tokens.get("output") or 0)
                except (TypeError, ValueError):
                    pass
                try:
                    updated["cost"] = float(info.get("cost") or 0)
                except (TypeError, ValueError):
                    pass
        except OpenCodeError as exc:
            logger.warning(f"Could not refresh OpenCode session info: {_safe_bridge_error(exc)}")
        try:
            messages = await _fetch_resilient(
                lambda: opencode_client.messages(session_id, limit=50)
            )
            diffs = await _fetch_resilient(lambda: opencode_client.diff(session_id))
            summary = _summarize_messages(messages, diffs)
            if summary["last_request"]:
                updated["last_request"] = summary["last_request"]
            if summary["resume_anchor"]:
                updated["resume_anchor"] = summary["resume_anchor"]
            updated["summary"] = summary["summary"]
            updated["one_line_recap"] = summary["one_line_recap"]
            updated["files_changed"] = summary["files_changed"]
            updated["milestones"] = summary["milestones"]
            if summary["outcome"] and status == "running":
                updated["status"] = summary["outcome"]
                status = summary["outcome"]
        except OpenCodeError as exc:
            logger.warning(f"Could not summarize OpenCode session: {_safe_bridge_error(exc)}")
    if updated.get("files_changed") and status in {"succeeded", "running"}:
        updated["review_state"] = updated.get("review_state") or "unreviewed"
    await store.upsert_opencode_session(updated)
    return updated


def _safe_bridge_error(exc: Exception) -> str:
    text = str(exc)
    values = [
        os.getenv(name, "").strip()
        for name in ("OPENCODE_SERVICE_PASSWORD", "GEMINI_API_KEY", "TAVILY_API_KEY", "BRAVE_API_KEY", "NVIDIA_API_KEY")
    ]
    try:
        values.append(opencode_client._service_password())
    except Exception:
        pass
    for value in values:
        if value:
            text = text.replace(value, "***REDACTED***")
    return text[:250]


def _session_payload(record: dict[str, Any], status: str | None = None) -> dict[str, Any]:
    provider = str(record.get("model_provider") or "")
    model_id = str(record.get("model_id") or "")
    return {
        "status": status or record.get("status") or "unknown",
        "short_code": record.get("short_code") or _short_code(str(record.get("opencode_session_id") or "")),
        "session_id": record.get("opencode_session_id"),
        "title": record.get("title"),
        "mode": record.get("mode"),
        "model": _spoken_model(f"{provider}/{model_id}" if provider and model_id else None),
        "summary": _clean_text(record.get("summary"), 900) or None,
        "recap": _clean_text(record.get("one_line_recap"), 300) or None,
        "file_count": len(_decode_list(record.get("files_changed"))),
        "files_changed": _decode_list(record.get("files_changed"))[:12],
        "milestones": _decode_list(record.get("milestones"))[:6],
        "worktree": record.get("worktree_dir"),
        "review_state": record.get("review_state"),
        "end_reason": record.get("end_reason"),
    }


async def _background_finalize(
    record: dict[str, Any], baseline: dict[str, Any] | None = None
) -> None:
    """Finish a long task after the voice turn has already been released."""
    try:
        terminal = await opencode_client.wait_for_terminal(
            str(record["opencode_session_id"]),
            _env_float("OPENCODE_TASK_TIMEOUT_SECONDS", 300),
            baseline=baseline,
        )
        if terminal.get("status") == "permission":
            await _store_pending_permission(
                str(record["opencode_session_id"]), terminal.get("permission") or {}
            )
            return
        await _finalize_record(record, terminal)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning(f"Background OpenCode finalizer failed: {_safe_bridge_error(exc)}")


def _code_model_chain() -> list[str]:
    """Ordered coding models for code_task when the caller does not pick one.

    An empty entry means "use OpenCode's own default model". Every non-empty
    entry is tried in order; a missing model or a failed session moves on to
    the next tier. A permission prompt never triggers a fallback.
    """
    defaults = {
        "VOICE_CODE_MODEL_PRIMARY": "nvidia/minimaxai/minimax-m3.1-flash",
        # A distinct NVIDIA model. The global OpenCode default is also NVIDIA,
        # so leaving this empty would retry the exact same model as tier 1.
        "VOICE_CODE_MODEL_SECONDARY": "nvidia/nemotron-3.5-lightning-30b-a3b",
        "VOICE_CODE_MODEL_FALLBACK": "ollama/qwen2.5:3b-instruct",
    }
    chain: list[str] = []
    for name, default in defaults.items():
        value = os.getenv(name, default).strip()
        # An empty value means "use OpenCode's own default model". It is a
        # meaningful tier, so keep exactly one even when several are empty.
        if value:
            if value in chain:
                continue
        elif "" in chain:
            continue
        chain.append(value)
    return chain


def _model_label(record: dict[str, Any], requested: str | None) -> str | None:
    provider = str(record.get("model_provider") or "")
    model_id = str(record.get("model_id") or "")
    if provider and model_id:
        return f"{provider}/{model_id}"[:160]
    return requested or None


def _spoken_model(label: str | None) -> str | None:
    """Shorten a provider/model id into something easy to say aloud.

    NVIDIA model ids often repeat the provider ("nvidia/nvidia/nemotron-..."),
    which is meaningless when spoken. Fall back to the raw id when unknown.
    """
    if not label:
        return None
    provider, _, model = label.partition("/")
    model = model.strip()
    if provider.lower() == "nvidia" and model.lower().startswith("nvidia/"):
        model = model[len("nvidia/"):]
    if provider.lower() == "ollama":
        return f"local Ollama {model}"
    if provider.lower() == "nvidia":
        return f"NVIDIA {model}"
    return label[:160]


async def code_task(params: FunctionCallParams) -> None:
    text = str(params.arguments.get("text") or "").strip()
    session_key = str(params.arguments.get("session") or "").strip() or None
    mode = str(params.arguments.get("mode") or "read").strip().lower()
    if mode not in {"read", "plan", "build"}:
        mode = "read"
    explicit_model = str(params.arguments.get("model") or "").strip() or None
    title = str(params.arguments.get("title") or "").strip() or text[:80]

    async def _approval_result(
        session_id: str, terminal: dict[str, Any]
    ) -> None:
        permission = terminal.get("permission") or {}
        await _store_pending_permission(session_id, permission)
        await params.result_callback(
            {
                "status": "awaiting_approval",
                "question": _permission_question(permission),
                "short_code": _short_code(session_id),
                "session_id": session_id,
                "request_id": str(permission.get("id") or ""),
            },
            properties=FunctionCallResultProperties(run_llm=True),
        )

    async def handler() -> None:
        if not text:
            await params.result_callback(
                {"error": "Please tell me what the coding task should do."},
                properties=FunctionCallResultProperties(run_llm=True),
            )
            return
        try:
            healthy = await opencode_client.health()
            if not healthy:
                raise OpenCodeError("The OpenCode service is not running.")

            if session_key:
                record = await _resolve_record(session_key)
                if not record:
                    raise OpenCodeError("I could not find that OpenCode session.")
                session_id = str(record["opencode_session_id"])
                directory = str(record.get("worktree_dir") or opencode_client.project_dir)
                agent = str(record.get("agent") or "") or await opencode_client.pick_agent(mode, directory)
                baseline = (await opencode_client.session_state(session_id)).get("baseline") or {}
                terminal = await opencode_client.prompt_and_wait(
                    session_id,
                    text,
                    _env_float("OPENCODE_TASK_WAIT_SECONDS", 45),
                    metadata={"voice_source": "voice-assistant", "voice_mode": mode},
                    baseline=baseline,
                )
                if terminal.get("status") == "permission":
                    await _approval_result(session_id, terminal)
                    return
                if terminal.get("status") in {"timeout", "running"}:
                    asyncio.create_task(
                        _background_finalize(record, baseline),
                        name=f"opencode-finalize-{_short_code(session_id)}",
                    )
                    await params.result_callback(
                        {
                            "status": "running",
                            "short_code": _short_code(session_id),
                            "session_id": session_id,
                            "mode": mode,
                            "model": _spoken_model(_model_label(record, None)),
                            "worktree": directory,
                            "message": "The task is still running. Ask me for a recap when you want the result.",
                        },
                        properties=FunctionCallResultProperties(run_llm=True),
                    )
                    return
                updated = await _finalize_record(record, terminal)
                await params.result_callback(
                    _session_payload(
                        updated,
                        "completed" if updated.get("status") == "succeeded" else updated.get("status"),
                    ),
                    properties=FunctionCallResultProperties(run_llm=True),
                )
                return

            directory = await opencode_client.create_worktree()
            agent = await opencode_client.pick_agent(mode, directory)
            models = [explicit_model] if explicit_model else _code_model_chain()
            if not models:
                models = [""]
            last_error = ""
            for index, model_ref in enumerate(models):
                label = model_ref or "opencode-default"
                if model_ref:
                    try:
                        await opencode_client.resolve_model(model_ref, directory)
                    except OpenCodeError as exc:
                        last_error = _safe_bridge_error(exc)
                        logger.warning(f"Coding model {label} is unavailable: {last_error}")
                        continue
                info = await opencode_client.create_session(
                    directory=directory,
                    agent=agent,
                    title=title,
                    mode=mode,
                    model_ref=model_ref or None,
                )
                session_id = str(info["id"])
                record = await _record_from_opencode(info, mode=mode)
                record["worktree_dir"] = directory
                await store.upsert_opencode_session(record)
                baseline = (await opencode_client.session_state(session_id)).get("baseline") or {}
                terminal = await opencode_client.prompt_and_wait(
                    session_id,
                    text,
                    _env_float("OPENCODE_TASK_WAIT_SECONDS", 45),
                    metadata={
                        "voice_source": "voice-assistant",
                        "voice_mode": mode,
                        "voice_model_attempt": label,
                    },
                    baseline=baseline,
                )
                if terminal.get("status") == "permission":
                    await _approval_result(session_id, terminal)
                    return
                if terminal.get("status") in {"timeout", "running"}:
                    asyncio.create_task(
                        _background_finalize(record, baseline),
                        name=f"opencode-finalize-{_short_code(session_id)}",
                    )
                    await params.result_callback(
                        {
                            "status": "running",
                            "short_code": _short_code(session_id),
                            "session_id": session_id,
                            "mode": mode,
                            "model": _spoken_model(_model_label(record, label)),
                            "worktree": directory,
                            "message": "The task is still running. Ask me for a recap when you want the result.",
                        },
                        properties=FunctionCallResultProperties(run_llm=True),
                    )
                    return
                updated = await _finalize_record(record, terminal)
                if terminal.get("status") == "failed" and index < len(models) - 1:
                    last_error = _clean_text(
                        updated.get("end_reason") or terminal.get("error"), 300
                    ) or f"{label} failed"
                    logger.warning(
                        f"Coding model {label} failed; trying the next model. {last_error}"
                    )
                    continue
                await params.result_callback(
                    _session_payload(
                        updated,
                        "completed" if updated.get("status") == "succeeded" else updated.get("status"),
                    ),
                    properties=FunctionCallResultProperties(run_llm=True),
                )
                return
            message = "No coding model was available for this task."
            if last_error:
                message = f"{message} Last error: {last_error}"
            await params.result_callback(
                {"error": message}, properties=FunctionCallResultProperties(run_llm=True)
            )
        except OpenCodeError as exc:
            message = _safe_bridge_error(exc)
            logger.warning(f"code_task failed: {message}")
            await params.result_callback(
                {"error": message}, properties=FunctionCallResultProperties(run_llm=True)
            )

    await _safe_call(params, handler)


async def list_code_sessions(params: FunctionCallParams) -> None:
    async def handler() -> None:
        limit = _coerce_limit(params.arguments.get("limit"), 8, 20)
        status = str(params.arguments.get("status") or "").strip() or None
        search = str(params.arguments.get("search") or "").strip() or None
        try:
            healthy = await opencode_client.health()
        except OpenCodeError:
            healthy = False
        if healthy:
            try:
                api_sessions = await opencode_client.list_sessions(
                    directory=opencode_client.project_dir, limit=limit
                )
                known = {
                    str(row.get("opencode_session_id") or "")
                    for row in await store.list_opencode_sessions(limit=50)
                }
                for info in api_sessions:
                    sid = str(info.get("id") or "")
                    if sid and sid not in known:
                        record = await _record_from_opencode(info)
                        await store.upsert_opencode_session(record)
            except OpenCodeError as exc:
                logger.warning(f"Could not sync OpenCode session list: {_safe_bridge_error(exc)}")
        rows = await store.list_opencode_sessions(limit=limit, status=status, search=search)
        sessions = [
            {
                "short_code": row.get("short_code") or _short_code(str(row.get("opencode_session_id") or "")),
                "title": _clean_text(row.get("title"), 100),
                "status": row.get("status"),
                "mode": row.get("mode"),
                "recap": _clean_text(row.get("one_line_recap"), 220) or None,
                "updated": str(row.get("updated_at") or "")[:19],
                "review_state": row.get("review_state"),
                "worktree": row.get("worktree_dir"),
            }
            for row in rows
        ]
        await params.result_callback(
            {"sessions": sessions, "count": len(sessions)},
            properties=FunctionCallResultProperties(run_llm=True),
        )

    await _safe_call(params, handler)


async def recap_code_session(params: FunctionCallParams) -> None:
    session_key = str(params.arguments.get("session") or "").strip() or None
    include_details = bool(params.arguments.get("include_details"))

    async def handler() -> None:
        key = session_key
        if not key:
            rows = await store.list_opencode_sessions(limit=1)
            key = str(rows[0].get("opencode_session_id") or "") if rows else ""
        if not key:
            await params.result_callback(
                {"error": "I do not have any OpenCode sessions to recap yet."},
                properties=FunctionCallResultProperties(run_llm=True),
            )
            return
        record = await _resolve_record(key)
        if not record:
            await params.result_callback(
                {"error": "I could not find that OpenCode session."},
                properties=FunctionCallResultProperties(run_llm=True),
            )
            return
        if record.get("pending_expires_at"):
            try:
                expires = datetime.fromisoformat(str(record["pending_expires_at"]))
                if expires.tzinfo is None:
                    expires = expires.astimezone()
                if expires < datetime.now(timezone.utc):
                    await store.clear_opencode_permission(
                        str(record["opencode_session_id"]), status="running"
                    )
                    record["status"] = "running"
            except ValueError:
                pass
        updated = await _finalize_record(record, {})
        payload = _session_payload(updated)
        payload["last_request"] = _clean_text(updated.get("last_request"), 400) or None
        payload["pending_approval"] = bool(updated.get("pending_permission_id"))
        if include_details:
            payload["details"] = {
                "files_changed": _decode_list(updated.get("files_changed"))[:30],
                "milestones": _decode_list(updated.get("milestones"))[:10],
                "resume_anchor": updated.get("resume_anchor"),
                "agent": updated.get("agent"),
                "model": f"{updated.get('model_provider') or ''}/{updated.get('model_id') or ''}".strip("/"),
            }
        await params.result_callback(
            payload, properties=FunctionCallResultProperties(run_llm=True)
        )

    await _safe_call(params, handler)


async def code_permission_reply(params: FunctionCallParams) -> None:
    raw_decision = str(params.arguments.get("decision") or "").strip().lower()
    decision = "once" if raw_decision in {"yes", "allow", "approve", "ok", "okay"} else (
        "reject" if raw_decision in {"no", "deny", "stop", "cancel"} else raw_decision
    )
    request_id = str(params.arguments.get("request_id") or "").strip() or None
    session_key = str(params.arguments.get("session") or "").strip() or None

    async def handler() -> None:
        if decision not in {"once", "always", "reject"}:
            await params.result_callback(
                {"error": "Please answer yes or no to the approval question."},
                properties=FunctionCallResultProperties(run_llm=True),
            )
            return
        record: dict[str, Any] | None = None
        if session_key:
            record = await _resolve_record(session_key)
        candidates = [
            _record_from_row(row)
            for row in await store.list_opencode_sessions(
                limit=20, status="awaiting_approval"
            )
        ]
        if request_id:
            record = next(
                (
                    item
                    for item in candidates
                    if str(item.get("pending_permission_id") or "") == request_id
                ),
                record,
            )
        elif record is None or not record.get("pending_permission_id"):
            record = candidates[0] if candidates else None
        if not record or not record.get("pending_permission_id"):
            await params.result_callback(
                {"status": "no_pending", "message": "There is no approval waiting right now."},
                properties=FunctionCallResultProperties(run_llm=True),
            )
            return
        pending_id = request_id or str(record["pending_permission_id"])
        session_id = str(record["opencode_session_id"])
        expires_raw = record.get("pending_expires_at")
        if expires_raw:
            try:
                expires = datetime.fromisoformat(str(expires_raw))
                if expires.tzinfo is None:
                    expires = expires.astimezone()
                if expires < datetime.now(timezone.utc):
                    _cancel_approval_timer(pending_id)
                    try:
                        await opencode_client.reply_permission(
                            session_id, pending_id, "reject"
                        )
                    except OpenCodeError as exc:
                        logger.debug(f"Expired approval was already closed: {_safe_bridge_error(exc)}")
                    await store.clear_opencode_permission(
                        session_id, status="interrupted"
                    )
                    await store.upsert_opencode_session(
                        {
                            "opencode_session_id": session_id,
                            "status": "interrupted",
                            "end_reason": "Approval timed out",
                            "updated_at": datetime.now(timezone.utc),
                        }
                    )
                    await params.result_callback(
                        {
                            "status": "expired",
                            "message": "That approval timed out, so I rejected it by default.",
                        },
                        properties=FunctionCallResultProperties(run_llm=True),
                    )
                    return
            except ValueError:
                pass
        _cancel_approval_timer(pending_id)
        baseline = (await opencode_client.session_state(session_id)).get("baseline") or {}
        await opencode_client.reply_permission(session_id, pending_id, decision)
        await store.clear_opencode_permission(
            session_id, status="interrupted" if decision == "reject" else "running"
        )
        if decision == "reject":
            await params.result_callback(
                {
                    "status": "rejected",
                    "short_code": _short_code(session_id),
                    "message": "I rejected that request. Nothing was changed by it.",
                },
                properties=FunctionCallResultProperties(run_llm=True),
            )
            return
        terminal = await opencode_client.wait_for_terminal(
            session_id, _env_float("OPENCODE_TASK_WAIT_SECONDS", 45), baseline=baseline
        )
        if terminal.get("status") == "permission":
            permission = terminal.get("permission") or {}
            await _store_pending_permission(session_id, permission)
            await params.result_callback(
                {
                    "status": "awaiting_approval",
                    "question": _permission_question(permission),
                    "short_code": _short_code(session_id),
                    "session_id": session_id,
                    "request_id": str(permission.get("id") or ""),
                },
                properties=FunctionCallResultProperties(run_llm=True),
            )
            return
        if terminal.get("status") in {"timeout", "running"}:
            asyncio.create_task(
                _background_finalize(record, baseline),
                name=f"opencode-finalize-{_short_code(session_id)}",
            )
            await params.result_callback(
                {
                    "status": "running",
                    "short_code": _short_code(session_id),
                    "message": "Approved. The task is still running; ask me for a recap in a moment.",
                },
                properties=FunctionCallResultProperties(run_llm=True),
            )
            return
        updated = await _finalize_record(record, terminal)
        await params.result_callback(
            _session_payload(updated, "completed" if updated.get("status") == "succeeded" else updated.get("status")),
            properties=FunctionCallResultProperties(run_llm=True),
        )

    await _safe_call(params, handler)


# ----------------------------------------------------------- end conversation


def create_end_conversation_handler(worker_getter):
    """End the call after the assistant has spoken its goodbye."""

    async def end_conversation(params: FunctionCallParams) -> None:
        logger.info("end_conversation tool called")
        await params.result_callback(
            {"status": "success", "action": "ending_call"},
            properties=FunctionCallResultProperties(run_llm=False),
        )
        worker = worker_getter()
        if worker is None:
            raise RuntimeError("Pipeline worker is not ready")
        # Gemini Live defers EndFrame until the current bot turn finishes; in the
        # local pipeline TTS also drains its audio context before the EndFrame.
        await worker.queue_frame(EndFrame(reason="end_call_tool"))

    return end_conversation


# ------------------------------------------------------------- schema factory


def build_tool_schemas(worker_getter) -> list[FunctionSchema]:
    """Build one fresh set of tools (with handlers) for a single call."""
    return [
        FunctionSchema(
            name="syllabus_search",
            description=(
                "Answer questions about the user's course, syllabus, lectures, slides, "
                "assignments or exams by searching the indexed PrepMate course PDFs. "
                "Use this FIRST for any course-material question instead of web_search "
                "or your own knowledge. Returns the grounded answer and the source "
                "files it came from."
            ),
            properties={
                "question": {
                    "type": "string",
                    "description": "The course-related question in the user's own words.",
                }
            },
            required=["question"],
            handler=syllabus_search,
        ),
        FunctionSchema(
            name="web_search",
            description=(
                "Search the live web for current or recent information, breaking news, "
                "people, companies, prices, or anything the assistant cannot know from "
                "its own knowledge. Returns short source snippets. Use this whenever a "
                "question could depend on information that changed recently."
            ),
            properties={
                "query": {
                    "type": "string",
                    "description": "A focused search query in the user's language.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "How many sources to return (1-8). Defaults to 5.",
                },
            },
            required=["query"],
            handler=web_search,
        ),
        FunctionSchema(
            name="fetch_page",
            description=(
                "Read the text of a specific web page when a search snippet is not "
                "enough. Pass a full http:// or https:// URL."
            ),
            properties={
                "url": {"type": "string", "description": "The full page URL to read."}
            },
            required=["url"],
            handler=fetch_page,
        ),
        FunctionSchema(
            name="memory_search",
            description=(
                "Search saved long-term facts about the user when their question depends "
                "on something they told the assistant in an earlier conversation."
            ),
            properties={
                "query": {
                    "type": "string",
                    "description": "What to look for in saved memories.",
                },
                "limit": {"type": "integer", "description": "Maximum results (1-12)."},
            },
            required=["query"],
            handler=memory_search,
        ),
        FunctionSchema(
            name="get_current_time",
            description=(
                "Get the current local time and date, or the time in a named IANA "
                "timezone such as Asia/Kolkata or America/New_York. Use this for any "
                "question about what time or date it is."
            ),
            properties={
                "timezone": {
                    "type": "string",
                    "description": "IANA timezone name. Omit for the user's local time.",
                }
            },
            required=[],
            handler=get_current_time,
        ),
        FunctionSchema(
            name="store_reminder",
            description=(
                "Store a reminder for later recall. This only saves it; it does not "
                "schedule a notification or speak it back. Convert relative times to an "
                "ISO 8601 due_at such as 2026-11-20T09:00:00 when the user gives one."
            ),
            properties={
                "content": {
                    "type": "string",
                    "description": "The reminder text, written as a short sentence.",
                },
                "due_at": {
                    "type": "string",
                    "description": "Optional ISO 8601 due date/time.",
                },
                "category": {"type": "string", "description": "Optional short category."},
            },
            required=["content"],
            handler=store_reminder,
        ),
        FunctionSchema(
            name="list_reminders",
            description="Recall reminders the user previously asked to store.",
            properties={
                "status": {
                    "type": "string",
                    "description": "pending (default), done, or all.",
                },
                "limit": {"type": "integer", "description": "Maximum results (1-25)."},
            },
            required=[],
            handler=list_reminders,
        ),
        FunctionSchema(
            name="complete_reminder",
            description="Mark a previously stored reminder as done.",
            properties={
                "reminder_id": {
                    "type": "string",
                    "description": "The reminder id returned when it was stored.",
                },
                "content_contains": {
                    "type": "string",
                    "description": "Or a few words from the reminder text.",
                },
            },
            required=[],
            handler=complete_reminder,
        ),
        FunctionSchema(
            name="get_system_info",
            description=(
                "Get basic information about the local machine running the assistant "
                "(operating system, CPU count, hostname, current backend)."
            ),
            properties={},
            required=[],
            handler=get_system_info,
        ),
        FunctionSchema(
            name="code_task",
            description=(
                "Ask the already-running OpenCode coding service to do a read-only, plan, or "
                "build task in an isolated git worktree. Use this when the user wants code "
                "explored, planned, or changed. Coding models are tried automatically in "
                "order: the user's NVIDIA model, then a second NVIDIA model, then local Ollama; "
                "the result says which model was used. Always summarise the result by voice; "
                "never read code or diffs aloud. The returned short_code is how the user "
                "refers to the session later. If the result says awaiting_approval, ask the "
                "user yes or no and then call code_permission_reply."
            ),
            properties={
                "text": {
                    "type": "string",
                    "description": "The full coding task in the user's own words.",
                },
                "mode": {
                    "type": "string",
                    "description": "read, plan, or build. Defaults to read. Build can edit the isolated worktree.",
                },
                "session": {
                    "type": "string",
                    "description": "Optional short_code or session id to continue an earlier task.",
                },
                "model": {
                    "type": "string",
                    "description": (
                        "Optional OpenCode model such as nvidia/minimaxai/minimax-m3.1-flash "
                        "or ollama/qwen2.5:3b-instruct. Omit it to use the automatic fallback "
                        "chain; supplying one overrides that chain."
                    ),
                },
                "title": {
                    "type": "string",
                    "description": "Optional short title for the session notebook.",
                },
            },
            required=["text"],
            handler=code_task,
        ),
        FunctionSchema(
            name="list_code_sessions",
            description=(
                "List the user's OpenCode coding sessions with their short codes, titles, "
                "status, and one-line recaps. Use when the user asks what coding tasks exist "
                "or wants to pick one to resume."
            ),
            properties={
                "limit": {"type": "integer", "description": "Maximum sessions (1-20). Defaults to 8."},
                "status": {
                    "type": "string",
                    "description": "Optional status filter such as running or succeeded.",
                },
                "search": {
                    "type": "string",
                    "description": "Optional words to match in title, request, short code, or worktree.",
                },
            },
            required=[],
            handler=list_code_sessions,
        ),
        FunctionSchema(
            name="recap_code_session",
            description=(
                "Give a spoken recap of an OpenCode session: what was asked, what changed, "
                "file names and counts, review state, and the worktree path. Never includes "
                "raw code or patches. Omit the session to recap the most recent one."
            ),
            properties={
                "session": {
                    "type": "string",
                    "description": "Optional short_code, full session id, or title words.",
                },
                "include_details": {
                    "type": "boolean",
                    "description": "Set true only when the user explicitly asks for file-level detail.",
                },
            },
            required=[],
            handler=recap_code_session,
        ),
        FunctionSchema(
            name="code_permission_reply",
            description=(
                "Answer a spoken approval question from OpenCode after code_task reports "
                "awaiting_approval. Use yes/once to allow that single action, or no/reject to "
                "decline. If the user does not answer, the request is rejected by default."
            ),
            properties={
                "decision": {
                    "type": "string",
                    "description": "yes or once to allow; no or reject to decline.",
                },
                "session": {
                    "type": "string",
                    "description": "Optional short_code or session id of the pending approval.",
                },
                "request_id": {
                    "type": "string",
                    "description": "Optional permission request id from the awaiting_approval result.",
                },
            },
            required=["decision"],
            handler=code_permission_reply,
        ),
        FunctionSchema(
            name="end_conversation",
            description=(
                "End the voice call after the assistant has spoken a short goodbye."
            ),
            properties={},
            required=[],
            handler=create_end_conversation_handler(worker_getter),
        ),
    ]
