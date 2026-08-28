import { Database, FileStack } from "lucide-react";
import type { StoredDocument } from "@/lib/api";

export function DocumentList({
  documents,
  loading,
}: {
  documents: StoredDocument[];
  loading?: boolean;
}) {
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 border-b-2 border-foreground pb-2">
        <Database className="size-4" />
        <h2 className="text-sm font-black uppercase tracking-widest">Vector Store</h2>
        <span className="ml-auto border-2 border-foreground bg-primary px-2 text-xs font-black text-primary-foreground">
          {documents.length}
        </span>
      </div>

      {loading ? (
        <p className="text-xs font-semibold text-muted-foreground">Loading index…</p>
      ) : documents.length === 0 ? (
        <div className="border-2 border-dashed border-muted-foreground/60 p-4 text-xs font-semibold text-muted-foreground">
          Store is empty. Ingest a PDF to start answering questions.
        </div>
      ) : (
        <ul className="space-y-2">
          {documents.map((doc, i) => (
            <li
              key={doc.id}
              style={{ animationDelay: `${i * 60}ms` }}
              className="animate-in fade-in slide-in-from-left-2 border-2 border-foreground bg-card p-3 shadow-brutal-sm duration-300"
            >
              <p className="truncate font-mono text-xs font-bold">{doc.filename}</p>
              <p className="mt-1 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                <FileStack className="size-3" />
                {doc.pages} pages · {doc.chunks} chunks
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
