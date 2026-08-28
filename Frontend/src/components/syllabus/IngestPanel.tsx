import { useRef, useState } from "react";
import { Loader2, Paperclip, Trash2, X } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { clearStore, uploadSources, type IngestMode, type StoredDocument } from "@/lib/api";
import { cn } from "@/lib/utils";

const ACCEPT =
  ".pdf,.docx,.txt,.md,.csv,.xlsx,.xls,.log,.json";

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

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
  const [pending, setPending] = useState<File[]>([]);
  const [mode, setMode] = useState<IngestMode>("append");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  function pick() {
    fileRef.current?.click();
  }

  function onFilesChanged(e: React.ChangeEvent<HTMLInputElement>) {
    const picked = Array.from(e.target.files ?? []);
    if (picked.length) setPending((prev) => [...prev, ...picked]);
    e.target.value = "";
  }

  function removeFile(name: string) {
    setPending((prev) => prev.filter((f) => f.name !== name));
  }

  async function add() {
    if (!pending.length || busy) return;
    setBusy(true);
    setNote(null);
    try {
      const res = await uploadSources(pending, mode);
      onChange(res.documents);
      setNote(res.note);
      setPending([]);
    } catch (err) {
      setNote(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    setBusy(true);
    setNote(null);
    try {
      const res = await clearStore();
      onChange(res.documents);
      setNote(res.note);
    } catch (err) {
      setNote(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg gap-5 rounded-none border-2 border-foreground shadow-brutal">
        <DialogHeader>
          <DialogTitle className="text-xl font-black uppercase tracking-tight">
            Add documents
          </DialogTitle>
          <DialogDescription className="font-semibold">
            Pick files from your computer (PDF, DOCX, XLSX, TXT, MD, CSV&hellip;).
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

        <input
          ref={fileRef}
          type="file"
          accept={ACCEPT}
          multiple
          className="hidden"
          onChange={onFilesChanged}
        />

        {pending.length === 0 ? (
          <Button
            variant="brutal"
            className="w-full"
            onClick={pick}
            disabled={busy}
          >
            <Paperclip className="size-4" />
            Add files…
          </Button>
        ) : (
          <div className="space-y-3">
            <div className="max-h-36 space-y-1.5 overflow-y-auto">
              {pending.map((f) => (
                <div
                  key={f.name}
                  className="flex items-center justify-between gap-3 border-2 border-foreground bg-card px-3 py-1.5"
                >
                  <span className="truncate font-mono text-xs font-bold">{f.name}</span>
                  <span className="shrink-0 text-[11px] font-semibold uppercase text-muted-foreground">
                    {formatBytes(f.size)}
                  </span>
                  {!busy && (
                    <button
                      onClick={() => removeFile(f.name)}
                      className="shrink-0 text-muted-foreground transition-colors hover:text-foreground"
                      aria-label={`Remove ${f.name}`}
                    >
                      <X className="size-3.5" />
                    </button>
                  )}
                </div>
              ))}
            </div>
            <div className="flex gap-2">
              <Button variant="brutalOutline" className="flex-1" onClick={pick} disabled={busy}>
                <Paperclip className="size-4" />
                Add more
              </Button>
              <Button variant="brutal" className="flex-1" onClick={add} disabled={busy}>
                {busy ? <Loader2 className="size-4 animate-spin" /> : <Paperclip className="size-4" />}
                Upload {pending.length} file{pending.length > 1 ? "s" : ""}
              </Button>
            </div>
          </div>
        )}

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
