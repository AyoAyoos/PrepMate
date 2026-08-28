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

const ACCEPT_EXTENSIONS = ACCEPT.split(",").map((e) => e.toLowerCase());
const MAX_FILE_MB = 50;

function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot === -1 ? "" : name.slice(dot).toLowerCase();
}

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
  const [summary, setSummary] = useState<{
    uploaded: number;
    duplicates: number;
    skipped: string[];
  } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  function pick() {
    fileRef.current?.click();
  }

  function acceptFiles(list: ArrayLike<File>) {
    const picked = Array.from(list);
    if (!picked.length) return;
    const valid: File[] = [];
    const rejected: string[] = [];
    for (const f of picked) {
      const ext = extensionOf(f.name);
      if (!ACCEPT_EXTENSIONS.includes(ext)) {
        rejected.push(`${f.name} (unsupported type)`);
      } else if (f.size > MAX_FILE_MB * 1024 * 1024) {
        rejected.push(`${f.name} (exceeds ${MAX_FILE_MB} MB)`);
      } else if (f.size === 0) {
        rejected.push(`${f.name} (empty file)`);
      } else {
        valid.push(f);
      }
    }
    if (valid.length) {
      setPending((prev) => [...prev, ...valid]);
    }
    if (rejected.length) {
      setNote(`Couldn't add: ${rejected.join(", ")}`);
    }
    setSummary(null);
  }

  function onFilesChanged(e: React.ChangeEvent<HTMLInputElement>) {
    acceptFiles(e.target.files ?? []);
    e.target.value = "";
  }

  function removeFile(name: string) {
    setPending((prev) => prev.filter((f) => f.name !== name));
    setSummary(null);
  }

  async function add() {
    if (!pending.length || busy) return;
    setBusy(true);
    setNote(null);
    setSummary(null);
    try {
      const res = await uploadSources(pending, mode);
      onChange(res.documents);
      setNote(res.note);
      setSummary({
        uploaded: res.uploaded ?? 0,
        duplicates: res.duplicates ?? 0,
        skipped: res.skipped ?? [],
      });
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
    setSummary(null);
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

        <div
          onDragOver={(e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = "copy";
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            acceptFiles(e.dataTransfer.files);
          }}
          className={cn(
            "border-2 border-dashed transition-colors",
            dragging ? "border-primary bg-primary/5 shadow-brutal-sm" : "border-muted-foreground/60",
          )}
        >
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
              {dragging ? "Drop files here" : "Add files…"}
            </Button>
          ) : (
            <div className="space-y-3 p-3">
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

        {summary && (
          <div className="space-y-1 border-2 border-foreground bg-muted px-3 py-2 text-xs font-semibold">
            <div className="flex gap-4 uppercase tracking-wide">
              <span className="text-primary">Added: {summary.uploaded}</span>
              <span className="text-muted-foreground">Duplicates: {summary.duplicates}</span>
              <span className="text-destructive">Skipped: {summary.skipped.length}</span>
            </div>
            {summary.skipped.length > 0 && (
              <ul className="list-disc space-y-0.5 pl-4 text-[11px] text-muted-foreground">
                {summary.skipped.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>
            )}
          </div>
        )}

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
