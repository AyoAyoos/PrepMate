import { FileText } from "lucide-react";
import type { Citation } from "@/lib/api";
import { cn } from "@/lib/utils";

export function CitationCard({
  citation,
  variant = "cited",
}: {
  citation: Citation;
  variant?: "cited" | "insufficient";
}) {
  const insufficient = variant === "insufficient";
  return (
    <div
      className={cn(
        "group flex items-start gap-3 rounded-none border-2 p-3 transition-transform duration-150 hover:-translate-y-0.5",
        insufficient
          ? "border-dashed border-muted-foreground/50 bg-muted/40 text-muted-foreground"
          : "border-foreground bg-card shadow-brutal-sm hover:shadow-brutal",
      )}
    >
      <FileText className="mt-0.5 size-4 shrink-0" />
      <div className="min-w-0 flex-1">
        <p className="truncate font-mono text-xs font-bold">{citation.source_file}</p>
        <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] font-semibold uppercase tracking-wide">
          <span className={cn("border px-1.5 py-0.5", insufficient ? "border-dashed" : "border-foreground bg-accent text-accent-foreground")}>
            p. {citation.page}
          </span>
          <span className="font-mono normal-case tracking-normal opacity-70">
            distance {citation.distance_score.toFixed(2)}
          </span>
        </div>
      </div>
    </div>
  );
}
