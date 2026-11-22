"""NEW (glue): single-command entrypoint for the voice assistant."""

import os
import sys
import urllib.request
from dotenv import load_dotenv

# Load .env before importing anything that initializes native libraries.
load_dotenv()

_HOST = os.getenv("HOST", "127.0.0.1")
_PORT = int(os.getenv("PORT", "45123"))


def _backend_already_healthy(host: str, port: int) -> bool:
    """True when another Voice Assistant backend already answers /health."""
    try:
        with urllib.request.urlopen(
            f"http://{host}:{port}/health", timeout=0.75
        ) as response:
            return response.status == 200
    except Exception:
        # Connection refused, timeout, or a non-HTTP listener all mean there is
        # no healthy backend to reuse.
        return False


# Run this before the heavy native imports so a duplicate launch exits fast.
if __name__ == "__main__" and _backend_already_healthy(_HOST, _PORT):
    print(
        f"A Voice Assistant backend is already healthy on {_HOST}:{_PORT} "
        "(GET /health -> 200).\n"
        "Not starting a second instance. Open the Voice button in PrepMate, "
        "run ..\\Start-PrepMate.ps1 -Status to inspect it, "
        "or set PORT to a different value to run another one.",
        file=sys.stderr,
    )
    raise SystemExit(0)

# CTranslate2/MKL (faster-whisper) allocates a workspace per CPU thread. On
# machines with many cores and limited free RAM, the default thread count makes
# Whisper's int8 model fail to load with "mkl_malloc: failed to allocate memory".
# Set a conservative default before Pipecat/onnxruntime/CTranslate2 load so the
# offline STT fallback stays reliable. Override with LOCAL_STT_NUM_THREADS in .env.
_threads = os.getenv("LOCAL_STT_NUM_THREADS", "2")
os.environ.setdefault("OMP_NUM_THREADS", _threads)
os.environ.setdefault("MKL_NUM_THREADS", _threads)

import bootstrap  # noqa: E402,F401  (puts the vendored Pipecat package on sys.path)

import asyncio  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

import uvicorn  # noqa: E402
from fastapi import FastAPI, Query, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from loguru import logger
from pydantic import BaseModel, Field

_ROOT = Path(__file__).parent
_LOG_DIR = _ROOT / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

# One ERROR-only file sink in addition to stderr. stderr goes to
# .voice-backend.err.log when started by the hotkey launcher.
logger.add(
    str(_LOG_DIR / "errors.log"),
    level="ERROR",
    rotation="10 MB",
    retention="14 days",
    compression="zip",
    encoding="utf-8",
    enqueue=True,
    backtrace=True,
    diagnose=True,
)

from pipeline import (  # noqa: E402
    close_memory_client,
    voice_temperature,
    warm_network,
    warm_smart_turn,
)
from routes.webrtc_signaling import router as signaling_router  # noqa: E402
from storage.duckdb_store import store  # noqa: E402
from storage.embeddings import embedder  # noqa: E402
from tools.opencode_client import close_opencode_client  # noqa: E402
from tools.voice_tools import cancel_approval_timers, close_web_client  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm the pieces that would otherwise land on the first call's critical path.
    warm_task = asyncio.create_task(warm_network())
    await asyncio.to_thread(warm_smart_turn)
    await store.initialize()
    try:
        yield
    finally:
        await warm_task
        await close_memory_client()
        await close_web_client()
        await cancel_approval_timers()
        await close_opencode_client()
        await embedder.close()
        await store.close()


app = FastAPI(title="Voice Assistant", lifespan=lifespan)

# The PrepMate frontend calls this service directly from its local dev port for
# WebRTC signaling and error reporting. Keep it loopback-only.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(signaling_router)


class ClientErrorPayload(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    source: str = "frontend"
    stack: str | None = None
    context: dict[str, Any] | None = None
    session_id: str | None = None


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.opt(exception=exc).error(
        f"Unhandled error on {request.method} {request.url.path}"
    )
    await store.log_error(
        source="fastapi",
        level="ERROR",
        message=f"Unhandled error on {request.method} {request.url.path}: {exc}",
        stack=str(exc),
        context={"path": request.url.path, "method": request.method},
    )
    return JSONResponse(status_code=500, content={"error": "Internal server error"})


@app.get("/health", include_in_schema=False)
async def health():
    return JSONResponse({"status": "ok"})


@app.get("/api/status")
async def api_status():
    return {
        "storage": {
            "available": store.available,
            "path": str(store.path),
            "hnsw": store.hnsw_available,
            "embedding_dim": store.embedding_dim,
        },
        "embeddings": {
            "provider": "ollama",
            "model": embedder.model,
            "url": embedder.base_url,
        },
    }


@app.post("/api/client-error", include_in_schema=False)
async def client_error(payload: ClientErrorPayload):
    await store.log_error(
        source=payload.source[:80],
        level="ERROR",
        message=payload.message,
        stack=payload.stack,
        context=payload.context,
        session_id=payload.session_id,
    )
    return {"ok": True}


@app.get("/api/sessions")
async def api_sessions(limit: int = Query(50, ge=1, le=200)):
    return {"sessions": await store.list_sessions(limit=limit)}


@app.get("/api/sessions/{session_id}/messages")
async def api_session_messages(
    session_id: str, limit: int = Query(200, ge=1, le=1000)
):
    return {"messages": await store.get_session_messages(session_id, limit=limit)}


@app.get("/api/memory")
async def api_memory(limit: int = Query(100, ge=1, le=500)):
    return {"memories": await store.list_memories(limit=limit)}


@app.get("/api/search")
async def api_search(
    q: str = Query("", max_length=500),
    limit: int = Query(10, ge=1, le=50),
):
    query = q.strip()
    if not query:
        return {"query": "", "embedding_used": False, "memories": [], "messages": []}

    embedding = await embedder.embed_text(query)
    memories = await store.search_memories(embedding=embedding, query=query, limit=limit)
    messages = await store.search_messages(embedding=embedding, query=query, limit=limit)
    return {
        "query": query,
        "embedding_used": embedding is not None,
        "memories": memories,
        "messages": messages,
    }


@app.get("/api/integration/status")
async def integration_status():
    """Report whether the voice agent can reach PrepMate's RAG backend."""
    import httpx

    base = os.getenv("PREPMATE_API_BASE", "http://127.0.0.1:8000").strip().rstrip("/")
    result: dict[str, Any] = {
        "prepmate_api_base": base,
        "syllabus_search": True,
        "reachable": False,
        "documents": None,
        "answer_policy": {
            "course_only": True,
            "voice_temperature": voice_temperature(),
        },
        "course_index": {
            "engine": "duckdb",
            "reachable": False,
            "hnsw": None,
            "chunks": None,
            "documents": None,
        },
    }
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            health = await client.get(f"{base}/health")
            result["reachable"] = health.status_code == 200
            if result["reachable"]:
                documents = await client.get(f"{base}/documents")
                if documents.status_code == 200:
                    payload = documents.json()
                    result["documents"] = len(payload) if isinstance(payload, list) else None
                course = await client.get(f"{base}/course-index/status")
                if course.status_code == 200:
                    payload = course.json()
                    result["course_index"] = {
                        "engine": str(payload.get("engine", "duckdb")),
                        "reachable": True,
                        "hnsw": payload.get("hnsw"),
                        "chunks": payload.get("chunks"),
                        "documents": payload.get("documents"),
                    }
    except Exception:
        # The panel should still render when PrepMate is not running yet.
        pass
    return result


class CachedStaticFiles(StaticFiles):
    """Serve Vite's hashed assets with long-lived immutable cache headers."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if scope.get("path", "").startswith("/assets/") and response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


_web_root = _ROOT / "web"
_static_dir = _web_root / "dist" if (_web_root / "dist").is_dir() else _web_root
app.mount(
    "/",
    CachedStaticFiles(directory=_static_dir, html=True),
    name="web",
)


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=_HOST,
        port=_PORT,
    )
