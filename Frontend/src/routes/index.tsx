import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { BookOpen, Moon, Send, Sun, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ChatMessage, type ChatItem } from "@/components/syllabus/ChatMessage";
import { DocumentList } from "@/components/syllabus/DocumentList";
import { IngestPanel } from "@/components/syllabus/IngestPanel";
import { ThinkingIndicator } from "@/components/syllabus/ThinkingIndicator";
import { askQuestion, getStoredDocuments, type StoredDocument } from "@/lib/api";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Ask-the-Syllabus Bot — Grounded Course Q&A" },
      {
        name: "description",
        content:
          "A retrieval-augmented chatbot that answers questions about your course PDFs with page-level citations, distance scores, and honest refusals.",
      },
      { property: "og:title", content: "Ask-the-Syllabus Bot — Grounded Course Q&A" },
      {
        property: "og:description",
        content:
          "RAG chat over syllabus PDFs: cited answers, grounding badges, and transparent refusals.",
      },
    ],
  }),
  component: Index,
});

const SUGGESTIONS = [
  "How does retrieval-augmented generation work in this course?",
  "When is the final exam date?",
  "What is the weather in Paris?",
];

function Index() {
  const [items, setItems] = useState<ChatItem[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [docs, setDocs] = useState<StoredDocument[]>([]);
  const [loadingDocs, setLoadingDocs] = useState(true);
  const [ingestOpen, setIngestOpen] = useState(false);
  const [dark, setDark] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getStoredDocuments().then((d) => {
      setDocs(d);
      setLoadingDocs(false);
    });
  }, []);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [items, busy]);

  async function send(question: string) {
    const q = question.trim();
    if (!q || busy) return;
    setInput("");
    setBusy(true);
    setItems((prev) => [
      ...prev.map((i) => (i.role === "bot" ? { ...i, fresh: false } : i)),
      { id: crypto.randomUUID(), role: "user", text: q },
    ]);
    const res = await askQuestion(q);
    setItems((prev) => [
      ...prev,
      { id: crypto.randomUUID(), role: "bot", response: res, fresh: true },
    ]);
    setBusy(false);
  }

  return (
    <div className="grid-paper min-h-screen bg-background text-foreground">
      <div className="mx-auto flex min-h-screen max-w-6xl flex-col">
        <header className="flex items-center gap-3 border-b-2 border-foreground bg-card px-4 py-4">
          <div className="flex size-10 shrink-0 items-center justify-center border-2 border-foreground bg-primary text-primary-foreground shadow-brutal-sm">
            <BookOpen className="size-5" />
          </div>
          <div className="min-w-0">
            <h1 className="truncate text-lg font-black uppercase tracking-tight sm:text-xl">
              Ask-the-Syllabus Bot
            </h1>
            <p className="truncate text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
              Grounded RAG over course PDFs
            </p>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <Button variant="brutalOutline" size="icon" onClick={() => setDark((v) => !v)}>
              {dark ? <Sun className="size-4" /> : <Moon className="size-4" />}
            </Button>
            <Button variant="brutal" onClick={() => setIngestOpen(true)}>
              <Upload className="size-4" />
              <span className="hidden sm:inline">Ingest</span>
            </Button>
          </div>
        </header>

        <div className="flex flex-1 flex-col-reverse gap-0 lg:flex-row">
          <main className="flex min-h-0 flex-1 flex-col">
            <div className="flex-1 space-y-4 overflow-y-auto p-4">
              {items.length === 0 && (
                <div className="border-2 border-foreground bg-card p-5 shadow-brutal">
                  <h2 className="text-sm font-black uppercase tracking-widest">
                    Ask about your course material
                  </h2>
                  <p className="mt-2 text-sm font-medium text-muted-foreground">
                    Answers are generated only from indexed slide chunks. When the retrieved
                    context is weak, the bot refuses instead of guessing.
                  </p>
                  <div className="mt-4 flex flex-wrap gap-2">
                    {SUGGESTIONS.map((s) => (
                      <button
                        key={s}
                        onClick={() => send(s)}
                        className="border-2 border-foreground bg-secondary px-3 py-1.5 text-xs font-bold shadow-brutal-sm transition-all hover:-translate-y-0.5 hover:bg-accent hover:text-accent-foreground"
                      >
                        {s}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {items.map((item) => (
                <ChatMessage key={item.id} item={item} />
              ))}

              {busy && <ThinkingIndicator />}
              <div ref={endRef} />
            </div>

            <div className="sticky bottom-0 border-t-2 border-foreground bg-card p-3">
              <div className="flex gap-2">
                <input
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && send(input)}
                  placeholder="Ask a question about the syllabus…"
                  className="h-11 flex-1 border-2 border-foreground bg-background px-3 text-sm font-semibold outline-none placeholder:text-muted-foreground focus:shadow-brutal-sm"
                />
                <Button
                  variant="brutal"
                  className="h-11"
                  onClick={() => send(input)}
                  disabled={busy || !input.trim()}
                >
                  <Send className="size-4" />
                  <span className="hidden sm:inline">Ask</span>
                </Button>
              </div>
            </div>
          </main>

          <aside className="border-b-2 border-foreground bg-sidebar p-4 lg:w-72 lg:shrink-0 lg:border-b-0 lg:border-l-2">
            <DocumentList documents={docs} loading={loadingDocs} />
          </aside>
        </div>
      </div>

      <IngestPanel
        open={ingestOpen}
        onOpenChange={setIngestOpen}
        documents={docs}
        onChange={setDocs}
      />
    </div>
  );
}
