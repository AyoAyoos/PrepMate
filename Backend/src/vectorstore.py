"""DuckDB + HNSW course-chunk store.

This is the single course-knowledge store used by PrepMate. The HTTP chat
endpoint and the bundled Voice Assistant both reach it through this backend;
the voice process never opens course files or this database directly.

DuckDB allows one writer process per file. Each operation therefore opens a
short-lived connection and closes it immediately, so the API, CLI, and eval
scripts can all use the same file without holding a lock between calls.
"""
from __future__ import annotations

import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence

import duckdb
from langchain_core.documents import Document

from src.config import COURSE_DB_PATH, EMBEDDING_DIM, OLLAMA_EMBED_MODEL

_TABLE = "course_chunks"
_HNSW_INDEX = "course_chunks_hnsw_idx"


class CourseVectorStore:
    """Persistent course chunks with a cosine HNSW index."""

    def __init__(
        self,
        path: Path | str = COURSE_DB_PATH,
        embedding_dim: int = EMBEDDING_DIM,
        model: str = OLLAMA_EMBED_MODEL,
    ) -> None:
        self.path = Path(path)
        self.embedding_dim = int(embedding_dim)
        self.model = model
        self.hnsw_available = False
        self._lock = threading.RLock()

    @property
    def vector_type(self) -> str:
        return f"FLOAT[{self.embedding_dim}]"

    @contextmanager
    def _connection(self, *, ensure_index: bool = False) -> Iterator[Any]:
        """Open, initialize, and promptly close a DuckDB connection."""
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = duckdb.connect(str(self.path))
            try:
                self._load_vss(conn)
                self._ensure_schema(conn, ensure_index=ensure_index)
                yield conn
            finally:
                conn.close()

    def _load_vss(self, conn: Any) -> None:
        """Enable DuckDB's vss extension and persistent HNSW indexes."""
        try:
            conn.execute("LOAD vss")
        except Exception:
            try:
                conn.execute("INSTALL vss")
                conn.execute("LOAD vss")
            except Exception as exc:
                print(f"WARNING: DuckDB vss/HNSW unavailable: {exc}")
                self.hnsw_available = False
                return

        try:
            # DuckDB requires this opt-in for HNSW indexes in file-backed DBs.
            conn.execute("SET hnsw_enable_experimental_persistence=true")
            self.hnsw_available = True
        except Exception as exc:
            print(f"WARNING: Could not enable persistent HNSW indexes: {exc}")
            self.hnsw_available = False

    def _ensure_schema(self, conn: Any, *, ensure_index: bool = False) -> None:
        vector_type = self.vector_type
        exists = conn.execute(
            """
            SELECT 1 FROM information_schema.tables
            WHERE table_name = ?
            """,
            [_TABLE],
        ).fetchone()

        if exists:
            column = conn.execute(
                """
                SELECT data_type FROM information_schema.columns
                WHERE table_name = ? AND column_name = 'embedding'
                """,
                [_TABLE],
            ).fetchone()
            if column:
                actual = str(column[0]).upper().replace(" ", "")
                expected = vector_type.upper().replace(" ", "")
                if actual != expected:
                    raise RuntimeError(
                        f"Course index embedding column is {actual}, expected {expected}. "
                        "Set EMBEDDING_DIM to the stored dimension or re-ingest with "
                        "python -m src.ingest --clear."
                    )
        else:
            conn.execute(
                f"""
                CREATE TABLE {_TABLE} (
                    id VARCHAR PRIMARY KEY,
                    source VARCHAR NOT NULL,
                    file_sha1 VARCHAR NOT NULL,
                    page INTEGER NOT NULL DEFAULT 0,
                    content TEXT NOT NULL,
                    embedding {vector_type} NOT NULL,
                    model VARCHAR NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            conn.execute(
                f"CREATE INDEX course_chunks_source_page_idx ON {_TABLE}(source, page)"
            )
            conn.execute(f"CREATE INDEX course_chunks_sha_idx ON {_TABLE}(file_sha1)")

        if ensure_index and self.hnsw_available:
            count = self._count(conn)
            if count:
                self._rebuild_hnsw_index(conn)

    def _rebuild_hnsw_index(self, conn: Any) -> None:
        if not self.hnsw_available:
            return
        try:
            conn.execute(f"DROP INDEX IF EXISTS {_HNSW_INDEX}")
            count = self._count(conn)
            if count:
                conn.execute(
                    f"CREATE INDEX {_HNSW_INDEX} ON {_TABLE} USING HNSW (embedding) "
                    "WITH (metric = 'cosine')"
                )
        except Exception as exc:
            print(f"WARNING: Could not rebuild course HNSW index: {exc}")
            self.hnsw_available = False

    def _validate_vector(self, vector: Sequence[float]) -> list[float]:
        values = [float(value) for value in vector]
        if len(values) != self.embedding_dim:
            raise ValueError(
                f"Expected a {self.embedding_dim}-dim embedding, got {len(values)}."
            )
        return values

    def _count(self, conn: Any) -> int:
        return int(conn.execute(f"SELECT count(*) FROM {_TABLE}").fetchone()[0])

    def _documents_from_rows(self, rows: Sequence[Sequence[Any]]) -> list[Document]:
        return [
            Document(
                page_content=str(row[3]),
                metadata={
                    "source": str(row[0]),
                    "file_sha1": str(row[1]),
                    "page": int(row[2]),
                },
            )
            for row in rows
        ]

    # ------------------------------------------------------------------ writes
    def add_chunks(
        self,
        chunks: Sequence[Document],
        vectors: Sequence[Sequence[float]],
        model: str | None = None,
    ) -> int:
        """Insert embedded chunks, then rebuild the HNSW index."""
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must have the same length")
        if not chunks:
            return 0

        rows = []
        for chunk, vector in zip(chunks, vectors):
            metadata = chunk.metadata or {}
            rows.append(
                (
                    uuid.uuid4().hex,
                    str(metadata.get("source", "unknown")),
                    str(metadata.get("file_sha1", "")),
                    int(metadata.get("page", 0) or 0),
                    chunk.page_content,
                    self._validate_vector(vector),
                    model or self.model,
                )
            )

        with self._connection() as conn:
            conn.executemany(
                f"""
                INSERT INTO {_TABLE}
                    (id, source, file_sha1, page, content, embedding, model, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, current_timestamp)
                """,
                rows,
            )
            self._rebuild_hnsw_index(conn)
            return len(rows)

    def clear(self) -> None:
        """Drop all course chunks (the index is rebuilt from scratch)."""
        with self._connection() as conn:
            conn.execute(f"DROP INDEX IF EXISTS {_HNSW_INDEX}")
            conn.execute(f"DROP TABLE IF EXISTS {_TABLE}")
            self._ensure_schema(conn)

    # ------------------------------------------------------------------ reads
    def count(self) -> int:
        with self._connection() as conn:
            return self._count(conn)

    def existing_hashes(self) -> set[str]:
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT DISTINCT file_sha1 FROM {_TABLE} WHERE file_sha1 <> ''"
            ).fetchall()
            return {str(row[0]) for row in rows}

    def list_sources(self) -> list[str]:
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT DISTINCT source FROM {_TABLE} ORDER BY source"
            ).fetchall()
            return [str(row[0]) for row in rows]

    def chunk_counts_by_source(self) -> dict[str, int]:
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT source, count(*) FROM {_TABLE} GROUP BY source"
            ).fetchall()
            return {str(source): int(count) for source, count in rows}

    def search(self, vector: Sequence[float], k: int) -> list[tuple[Document, float]]:
        """Return the nearest chunks as (Document, cosine distance) pairs.

        Cosine distance is 0 for identical direction and grows as vectors differ;
        the relevance gate in generate.py keeps only the lowest distances.
        """
        if k <= 0:
            return []
        query_vector = self._validate_vector(vector)
        with self._connection() as conn:
            if self._count(conn) == 0:
                return []
            rows = conn.execute(
                f"""
                SELECT source, file_sha1, page, content,
                       array_cosine_distance(embedding, ?::{self.vector_type}) AS distance
                FROM {_TABLE}
                ORDER BY distance
                LIMIT ?
                """,
                [query_vector, k],
            ).fetchall()
        docs = self._documents_from_rows(rows)
        return [(doc, float(row[4])) for doc, row in zip(docs, rows)]

    def source_page_chunks(self, source: str, page: int) -> list[Document]:
        with self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT source, file_sha1, page, content
                FROM {_TABLE}
                WHERE source = ? AND page = ?
                ORDER BY content
                """,
                [source, page],
            ).fetchall()
        return self._documents_from_rows(rows)

    def status(self) -> dict[str, Any]:
        with self._connection() as conn:
            return {
                "engine": "duckdb",
                "path": str(self.path),
                "hnsw": self.hnsw_available,
                "embedding_dim": self.embedding_dim,
                "embedding_model": self.model,
                "chunks": self._count(conn),
                "documents": len(
                    conn.execute(f"SELECT DISTINCT source FROM {_TABLE}").fetchall()
                ),
            }

    def close(self) -> None:
        """No persistent connection to close."""
        return None


store = CourseVectorStore()
