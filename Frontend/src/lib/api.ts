/**
 * API layer for the Ask-the-Syllabus Bot.
 *
 * Talks to the FastAPI backend (see Backend/src/api.py). Set the base URL with
 * the VITE_API_BASE env var, e.g. VITE_API_BASE=http://localhost:8000.
 */

export type Citation = {
  source_file: string;
  page: number;
  distance_score: number;
};

export type AskResponse = {
  answer: string;
  grounded: boolean;
  citations: Citation[];
  /** Explanation, e.g. why the model refused. */
  note: string;
};

export type StoredDocument = {
  id: string;
  filename: string;
  pages: number;
  chunks: number;
  ingested_at: string | null;
};

export type IngestMode = "append" | "clear";

export type IngestResponse = {
  documents: StoredDocument[];
  note: string;
  uploaded?: number;
  duplicates?: number;
  skipped?: string[];
};

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });

  if (!res.ok) {
    let detail = `HTTP ${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) {
        detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      }
    } catch {
      // non-JSON error body; keep the status-text fallback
    }
    throw new Error(detail);
  }

  return (await res.json()) as T;
}

/** POST /ask */
export async function askQuestion(question: string): Promise<AskResponse> {
  return request<AskResponse>("/ask", {
    method: "POST",
    body: JSON.stringify({ question }),
  });
}

/** GET /documents */
export async function getStoredDocuments(): Promise<StoredDocument[]> {
  return request<StoredDocument[]>("/documents");
}

/** POST /ingest  (append by default, clear resets the store first) */
export async function ingestSource(
  filename: string,
  mode: IngestMode = "append",
): Promise<IngestResponse> {
  return request<IngestResponse>("/ingest", {
    method: "POST",
    body: JSON.stringify({ filename, mode }),
  });
}

/** POST /ingest/upload  (multipart) — upload one or more files from disk */
export async function uploadSources(
  files: File[],
  mode: IngestMode = "append",
): Promise<IngestResponse> {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  form.append("mode", mode);

  const res = await fetch(`${API_BASE}/ingest/upload`, {
    method: "POST",
    body: form,
  });

  if (!res.ok) {
    let detail = `HTTP ${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) {
        detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      }
    } catch {
      // keep fallback
    }
    throw new Error(detail);
  }

  return (await res.json()) as IngestResponse;
}

/** DELETE /documents */
export async function clearStore(): Promise<IngestResponse> {
  return request<IngestResponse>("/documents", { method: "DELETE" });
}
