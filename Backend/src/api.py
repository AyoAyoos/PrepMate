"""FastAPI HTTP layer for the Ask-the-Syllabus Bot.

Exposes the RAG pipeline over HTTP so the frontend (see Frontend/src/lib/api.ts)
can talk to the backend instead of using mocks.

Endpoints (contract matches Frontend/src/lib/api.ts):
    GET    /documents   -> list of currently stored source documents
    POST   /ask         -> ask a question, get a grounded answer + citations
    POST   /ingest      -> append a PDF (or clear + re-ingest) by filename
    DELETE /documents   -> wipe the vector store

Run with:
    python -m src.api        (uvicorn, default http://localhost:8000)
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Optional

import chromadb
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.config import COLLECTION_NAME, PDF_DIR, SOURCE_DEFAULT, VECTORSTORE_DIR
from src.generate import UNANSWERABLE, generate
from src.ingest import clear_store, ingest, list_sources
from src.retrieve import has_any_documents, retrieve

app = FastAPI(title="Ask-the-Syllabus Bot API", version="1.0.0")

# Allow the local frontend dev/preview servers (and anything local) to call the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# Pydantic models (frames the frontend contract)
# --------------------------------------------------------------------------- #
class Citation(BaseModel):
    source_file: str
    page: int = 0
    distance_score: float = 0.0


class AskRequest(BaseModel):
    question: str = Field(min_length=1)


class AskResponse(BaseModel):
    answer: str
    grounded: bool
    citations: list[Citation] = []
    note: str = ""


class StoredDocument(BaseModel):
    id: str
    filename: str
    pages: int = 0
    chunks: int = 0
    ingested_at: Optional[str] = None


class IngestRequest(BaseModel):
    filename: str = Field(min_length=1)
    mode: str = "append"  # "append" or "clear"


class IngestResponse(BaseModel):
    documents: list[StoredDocument]
    note: str = ""


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _chunk_counts_by_source() -> dict[str, int]:
    """Return {source_filename: number_of_chunks} from the Chroma collection."""
    client = chromadb.PersistentClient(path=str(VECTORSTORE_DIR))
    try:
        col = client.get_collection(COLLECTION_NAME)
        data = col.get(include=["metadatas"])
    except Exception:
        return {}
    counts: dict[str, int] = {}
    for m in data.get("metadatas") or []:
        src = (m or {}).get("source")
        if src:
            counts[src] = counts.get(src, 0) + 1
    return counts


def _pdf_page_count(filename: str) -> int:
    """Number of pages in a source PDF, if the file is present."""
    try:
        from pypdf import PdfReader

        path = PDF_DIR / filename
        if not path.exists():
            return 0
        return len(PdfReader(str(path)).pages)
    except Exception:
        return 0


def _ingested_at(filename: str) -> Optional[str]:
    """Best-effort timestamp: source PDF file mtime (vectorstore doesn't track it)."""
    path = PDF_DIR / filename
    try:
        if path.exists():
            import datetime

            dt = datetime.datetime.fromtimestamp(path.stat().st_mtime, tz=datetime.timezone.utc)
            return dt.isoformat()
    except Exception:
        pass
    return None


def _list_documents() -> list[StoredDocument]:
    """Assemble the current list of stored documents."""
    counts = _chunk_counts_by_source()
    sources = list_sources() or sorted(counts.keys())
    docs: list[StoredDocument] = []
    for source in sources:
        doc_id = hashlib.sha1(source.encode("utf-8")).hexdigest()[:12]
        docs.append(
            StoredDocument(
                id=doc_id,
                filename=source,
                pages=_pdf_page_count(source),
                chunks=counts.get(source, 0),
                ingested_at=_ingested_at(source),
            )
        )
    return docs


def _answer_to_response(answer: Any) -> AskResponse:
    """Map a backend generate.Answer into the frontend contract."""
    citations: list[Citation] = []
    for c in answer.citations or []:
        citations.append(
            Citation(
                source_file=c.get("source", "unknown.pdf"),
                page=int(c["page"]) if c.get("page") is not None else 0,
                distance_score=float(c["score"]) if c.get("score") is not None else 0.0,
            )
        )
    return AskResponse(
        answer=(answer.text or "").strip(),
        grounded=answer.grounded,
        citations=citations,
        note=answer.note or "",
    )


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@app.get("/documents", response_model=list[StoredDocument])
def get_documents() -> list[StoredDocument]:
    """Return the source documents currently in the vector store."""
    return _list_documents()


@app.post("/ask", response_model=AskResponse)
def ask_question(payload: AskRequest) -> AskResponse:
    question = payload.question.strip()

    if not question:
        raise HTTPException(status_code=422, detail="Question cannot be empty.")

    if not has_any_documents():
        return AskResponse(
            answer=UNANSWERABLE,
            grounded=False,
            citations=[],
            note="The vector store is empty. Ingest PDFs before asking.",
        )

    try:
        retrieved = retrieve(question)
    except Exception as exc:  # e.g. Ollama / embedding service unavailable
        raise HTTPException(
            status_code=502,
            detail=f"Retrieval failed (is Ollama running?): {exc}",
        )

    if not retrieved:
        return AskResponse(
            answer=UNANSWERABLE,
            grounded=False,
            citations=[],
            note="No relevant chunks were retrieved for this question.",
        )

    try:
        answer = generate(retrieved, question)
    except Exception as exc:  # e.g. Ollama chat model unavailable
        raise HTTPException(
            status_code=502,
            detail=f"Generation failed (is the LLM model available in Ollama?): {exc}",
        )

    return _answer_to_response(answer)


@app.post("/ingest", response_model=IngestResponse)
def ingest_source(payload: IngestRequest) -> IngestResponse:
    filename = Path(payload.filename).name  # strip any directory traversal
    mode = "clear" if payload.mode == "clear" else "append"

    source_path = PDF_DIR / filename
    if not source_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"PDF not found in {PDF_DIR}: '{filename}'.",
        )

    try:
        added = ingest(source_path, clear=(mode == "clear"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Ingest failed: {exc}")

    documents = _list_documents()

    if mode == "clear":
        note = f"Vector store cleared and re-indexed with {filename}."
    elif added == 0:
        note = f"{filename} is already in the store (name + content-hash match)."
    else:
        note = f"{filename} appended to the existing vector store."

    return IngestResponse(documents=documents, note=note)


@app.delete("/documents", response_model=IngestResponse)
def delete_documents() -> IngestResponse:
    clear_store()
    return IngestResponse(
        documents=[],
        note="Vector store cleared. No documents indexed.",
    )


@app.get("/health")
def health() -> dict[str, str]:
    """Simple liveness check."""
    return {"status": "ok"}


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
