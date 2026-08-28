import { useState } from "react";
import { ChevronDown, ShieldCheck, ShieldX, Quote } from "lucide-react";
import type { AskResponse } from "@/lib/api";
import { cn } from "@/lib/utils";
import { CitationCard } from "./CitationCard";
import { TypeText } from "./TypeText";

export type ChatItem =
  | { id: string; role: "user"; text: string }
  | { id: string; role: "bot"; response: AskResponse; fresh: boolean };

function GroundingBadge({ response }: { response: AskResponse }) {
  const considered = !response.grounded && response.citations.length > 0;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 border-2 border-foreground px-2 py-0.5 text-[11px] font-black uppercase tracking-widest",
        response.grounded ? "bg-success text-success-foreground" : "bg-muted text-muted-foreground",
      )}
    >
      {response.grounded ? <ShieldCheck className="size-3" /> : <ShieldX className="size-3" />}
      <span className={response.grounded ? "shiny-text" : undefined}>
        {response.grounded ? "Grounded" : considered ? "Refused · insufficient" : "Refused · no match"}
      </span>
    </span>
  );
}

export function ChatMessage({ item }: { item: ChatItem }) {
  const [open, setOpen] = useState(false);

  if (item.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] border-2 border-foreground bg-primary px-4 py-3 text-sm font-bold text-primary-foreground shadow-brutal-sm sm:max-w-[70%]">
          {item.text}
        </div>
      </div>
    );
  }

  const { response } = item;
  const considered = !response.grounded && response.citations.length > 0;
  const hasSources = response.citations.length > 0;

  return (
    <div className="max-w-[95%] border-2 border-foreground bg-card shadow-brutal sm:max-w-[80%]">
      <div className="flex items-center gap-2 border-b-2 border-foreground bg-secondary px-3 py-2">
        <Quote className="size-3.5" />
        <span className="text-[11px] font-black uppercase tracking-widest">Syllabus Bot</span>
        <span className="ml-auto">
          <GroundingBadge response={response} />
        </span>
      </div>

      <div className="space-y-3 p-4">
        <TypeText
          text={response.answer}
          animate={item.fresh}
          className="text-sm leading-relaxed font-medium"
        />

        {response.note && (
          <p className="border-l-4 border-primary bg-muted px-3 py-2 text-xs font-semibold text-muted-foreground">
            {response.note}
          </p>
        )}

        {hasSources && (
          <div className="border-t-2 border-dashed border-foreground/30 pt-3">
            <button
              onClick={() => setOpen((v) => !v)}
              className="flex w-full items-center gap-2 text-[11px] font-black uppercase tracking-widest"
            >
              <ChevronDown
                className={cn("size-3.5 transition-transform", open && "rotate-180")}
              />
              {considered
                ? `Considered but insufficient (${response.citations.length})`
                : `Citations (${response.citations.length})`}
            </button>

            {open && (
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                {response.citations.map((c, i) => (
                  <CitationCard
                    key={`${c.source_file}-${c.page}-${i}`}
                    citation={c}
                    variant={considered ? "insufficient" : "cited"}
                  />
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
