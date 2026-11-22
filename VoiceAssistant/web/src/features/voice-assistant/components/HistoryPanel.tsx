import { useCallback, useEffect, useState } from "react";

import { getJson } from "../api";
import { reportClientError } from "../errors";
import type {
  MemoryFact,
  SearchResults,
  SessionSummary,
  StoredMessage,
} from "../types";
import NbButton from "./NbButton";
import styles from "./HistoryPanel.module.css";

interface HistoryPanelProps {
  open: boolean;
  onClose: () => void;
}

interface SessionsResponse {
  sessions: SessionSummary[];
}

interface MemoryResponse {
  memories: MemoryFact[];
}

interface MessagesResponse {
  messages: StoredMessage[];
}

function formatDate(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function similarity(value?: number | null): string {
  if (typeof value !== "number") return "";
  return `${Math.max(0, Math.min(100, Math.round((1 - value) * 100)))}%`;
}

export default function HistoryPanel({ open, onClose }: HistoryPanelProps) {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [memories, setMemories] = useState<MemoryFact[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedMessages, setSelectedMessages] = useState<StoredMessage[]>([]);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResults | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [sessionData, memoryData] = await Promise.all([
        getJson<SessionsResponse>("/api/sessions?limit=50"),
        getJson<MemoryResponse>("/api/memory?limit=100"),
      ]);
      setSessions(sessionData.sessions);
      setMemories(memoryData.memories);
    } catch (loadError) {
      setError("Could not load history. Check the server logs.");
      void reportClientError(loadError, { source: "history-panel", action: "load" });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    void loadAll();
  }, [loadAll, open]);

  const selectSession = useCallback(async (sessionId: string) => {
    setSelectedId(sessionId);
    setSelectedMessages([]);
    try {
      const data = await getJson<MessagesResponse>(
        `/api/sessions/${encodeURIComponent(sessionId)}/messages?limit=200`,
      );
      setSelectedMessages(data.messages);
    } catch (loadError) {
      setError("Could not load that session.");
      void reportClientError(loadError, {
        source: "history-panel",
        action: "select-session",
        session_id: sessionId,
      });
    }
  }, []);

  const runSearch = useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      const clean = query.trim();
      if (!clean) {
        setResults(null);
        return;
      }
      setLoading(true);
      setError("");
      try {
        const data = await getJson<SearchResults>(
          `/api/search?q=${encodeURIComponent(clean)}&limit=10`,
        );
        setResults(data);
      } catch (searchError) {
        setError("Search failed. Check the server logs.");
        void reportClientError(searchError, {
          source: "history-panel",
          action: "search",
        });
      } finally {
        setLoading(false);
      }
    },
    [query],
  );

  if (!open) return null;

  return (
    <div
      className={styles.backdrop}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        className={styles.panel}
        role="dialog"
        aria-modal="true"
        aria-label="History and memory"
      >
        <header className={styles.header}>
          <div>
            <h2 className={styles.title}>History &amp; Memory</h2>
            <p className={styles.subtitle}>
              Local sessions, transcripts, and distilled facts.
            </p>
          </div>
          <NbButton variant="neutral" onClick={onClose}>
            Close
          </NbButton>
        </header>

        <form className={styles.searchRow} onSubmit={runSearch}>
          <input
            className={styles.searchInput}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search past calls and memory…"
            aria-label="Search past calls and memory"
          />
          <NbButton variant="primary" type="submit" disabled={loading}>
            Search
          </NbButton>
          <NbButton variant="lilac" type="button" onClick={() => void loadAll()}>
            Refresh
          </NbButton>
        </form>

        {error ? <p className={styles.error}>{error}</p> : null}
        {loading ? <p className={styles.loading}>Loading…</p> : null}

        {results ? (
          <section className={styles.searchResults}>
            <h3 className={styles.sectionTitle}>
              Search results
              {results.embedding_used ? " · semantic" : " · keyword"}
            </h3>
            {results.memories.length === 0 && results.messages.length === 0 ? (
              <p className={styles.empty}>No matches.</p>
            ) : null}
            {results.memories.map((memory) => (
              <div key={memory.id} className={styles.resultRow}>
                <span className={styles.tag}>MEMORY</span>
                <span>{memory.content}</span>
                {similarity(memory.distance) ? (
                  <span className={styles.score}>{similarity(memory.distance)}</span>
                ) : null}
              </div>
            ))}
            {results.messages.map((message) => (
              <div key={message.id} className={styles.resultRow}>
                <span className={styles.tag}>{message.role.toUpperCase()}</span>
                <span>{message.text}</span>
                {similarity(message.distance) ? (
                  <span className={styles.score}>{similarity(message.distance)}</span>
                ) : null}
              </div>
            ))}
          </section>
        ) : null}

        <div className={styles.columns}>
          <section className={styles.column}>
            <h3 className={styles.sectionTitle}>Sessions</h3>
            <div className={styles.list}>
              {sessions.length === 0 ? (
                <p className={styles.empty}>No calls yet.</p>
              ) : null}
              {sessions.map((session) => (
                <button
                  key={session.id}
                  type="button"
                  className={`${styles.sessionItem} ${
                    selectedId === session.id ? styles.selected : ""
                  }`.trim()}
                  onClick={() => void selectSession(session.id)}
                >
                  <strong>{session.title || "Untitled session"}</strong>
                  <span>{formatDate(session.started_at)}</span>
                  <small>
                    {session.stored_message_count} turns · {session.memory_count} facts · {session.status}
                  </small>
                </button>
              ))}
            </div>

            {selectedId ? (
              <div className={styles.transcript}>
                <h4 className={styles.sectionTitle}>Selected transcript</h4>
                {selectedMessages.length === 0 ? (
                  <p className={styles.empty}>No stored messages.</p>
                ) : null}
                {selectedMessages.map((message) => (
                  <p key={message.id} className={styles.transcriptLine}>
                    <strong>{message.role === "user" ? "You" : "Assistant"}:</strong>{" "}
                    {message.text}
                  </p>
                ))}
              </div>
            ) : null}
          </section>

          <section className={styles.column}>
            <h3 className={styles.sectionTitle}>Memory facts</h3>
            <div className={styles.list}>
              {memories.length === 0 ? (
                <p className={styles.empty}>No distilled facts yet.</p>
              ) : null}
              {memories.map((memory) => (
                <div key={memory.id} className={styles.memoryItem}>
                  <span className={styles.tag}>{memory.category ?? "note"}</span>
                  <span>{memory.content}</span>
                  <small>Used {memory.use_count ?? 0} times</small>
                </div>
              ))}
            </div>
          </section>
        </div>
      </section>
    </div>
  );
}
