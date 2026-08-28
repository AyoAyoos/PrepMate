import { useState } from "react";
import { Loader2, Plus, Trash2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { clearStore, ingestSource, type IngestMode, type StoredDocument } from "@/lib/api";
import { cn } from "@/lib/utils";

export function IngestPanel({
  open,
  onOpenChange,
  documents,
  onChange,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  documents: StoredDocument[];
  onChange: (docs: StoredDocument[]) => void;
}) {
  const [filename, setFilename] = useState("");
  const [mode, setMode] = useState<IngestMode>("append");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  async function run() {
    if (!filename.trim() || busy) return;
    setBusy(true);
    const res = await ingestSource(filename, mode);
    onChange(res.documents);
    setNote(res.note);
    setFilename("");
    setBusy(false);
  }

  async function reset() {
    setBusy(true);
    const res = await clearStore();
    onChange(res.documents);
    setNote(res.note);
    setBusy(false);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg gap-5 rounded-none border-2 border-foreground shadow-brutal">
        <DialogHeader>
          <DialogTitle className="text-xl font-black uppercase tracking-tight">
            Ingest Source
          </DialogTitle>
          <DialogDescription className="font-semibold">
            Append adds to the existing index. Clear wipes the store and re-indexes from scratch.
          </DialogDescription>
        </DialogHeader>

        <div className="grid grid-cols-2 gap-2">
          {(["append", "clear"] as IngestMode[]).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={cn(
                "border-2 border-foreground px-3 py-2 text-xs font-black uppercase tracking-widest transition-all",
                mode === m
                  ? "bg-primary text-primary-foreground shadow-brutal-sm"
                  : "bg-card hover:bg-muted",
              )}
            >
              {m === "append" ? "Append (default)" : "Clear + reset"}
            </button>
          ))}
        </div>

        <div className="flex gap-2">
          <Input
            value={filename}
            onChange={(e) => setFilename(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && run()}
            placeholder="Week04_Embeddings.pdf"
            className="rounded-none border-2 border-foreground font-mono text-sm shadow-none focus-visible:ring-0"
          />
          <Button variant="brutal" onClick={run} disabled={busy || !filename.trim()}>
            {busy ? <Loader2 className="size-4 animate-spin" /> : <Plus className="size-4" />}
            Add
          </Button>
        </div>

        <div className="max-h-52 space-y-2 overflow-y-auto">
          {documents.map((d) => (
            <div
              key={d.id}
              className="flex items-center justify-between gap-3 border-2 border-foreground bg-card px-3 py-2"
            >
              <span className="truncate font-mono text-xs font-bold">{d.filename}</span>
              <span className="shrink-0 text-[11px] font-semibold uppercase text-muted-foreground">
                {d.chunks} chunks
              </span>
            </div>
          ))}
          {documents.length === 0 && (
            <p className="border-2 border-dashed border-muted-foreground/60 p-3 text-xs font-semibold text-muted-foreground">
              No documents indexed.
            </p>
          )}
        </div>

        {note && (
          <p className="border-l-4 border-primary bg-muted px-3 py-2 text-xs font-semibold">
            {note}
          </p>
        )}

        <Button
          variant="brutalDestructive"
          onClick={reset}
          disabled={busy || documents.length === 0}
        >
          <Trash2 className="size-4" />
          Clear vector store
        </Button>
      </DialogContent>
    </Dialog>
  );
}
