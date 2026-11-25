import { useState } from "react";
import { ChevronDown, Mic, ShieldCheck, ShieldX, Quote } from "lucide-react";
import type { AskResponse } from "@/lib/api";
import { cn } from "@/lib/utils";
import { CitationCard } from "./CitationCard";
import { TypeText } from "./TypeText";

export type ChatItem =
  | { id: string; role: "user"; text: string }
  | { id: string; role: "bot"; response: AskResponse; fresh: boolean }
  | { id: string; role: "voice-user"; text: string }
  | { id: string; role: "voice-bot"; text: string }
  | { id: string; role: "voice-status"; text: string };

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
        {response.grounded
          ? "Grounded"
          : considered
            ? "Refused · insufficient"
            : "Refused · no match"}
      </span>
    </span>
  );
}

export function ChatMessage({ item }: { item: ChatItem }) {
  const [open, setOpen] = useState(false);

  if (item.role === "user" || item.role === "voice-user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] border-2 border-foreground bg-primary px-4 py-3 text-sm font-bold text-primary-foreground shadow-brutal-sm sm:max-w-[70%]">
          {item.role === "voice-user" && (
            <span className="mb-1 flex items-center justify-end gap-1 text-[10px] font-black uppercase tracking-widest opacity-80">
              <Mic className="size-3" /> Spoken
            </span>
          )}
          {item.text}
        </div>
      </div>
    );
  }

  if (item.role === "voice-status") {
    return (
      <div className="flex justify-center">
        <div className="border-2 border-dashed border-foreground/50 bg-muted px-3 py-1 text-[11px] font-bold uppercase tracking-widest text-muted-foreground">
          {item.text}
        </div>
      </div>
    );
  }

  if (item.role === "voice-bot") {
    return (
      <div className="max-w-[95%] border-2 border-foreground bg-card shadow-brutal sm:max-w-[80%]">
        <div className="flex items-center gap-2 border-b-2 border-foreground bg-secondary px-3 py-2">
          <Mic className="size-3.5" />
          <span className="text-[11px] font-black uppercase tracking-widest">Voice Assistant</span>
          <span className="ml-auto border-2 border-foreground px-2 py-0.5 text-[10px] font-black uppercase tracking-widest">
            Spoken
          </span>
        </div>
        <div className="p-4">
          <TypeText text={item.text} animate className="text-sm leading-relaxed font-medium" />
        </div>
      </div>
    );
  }

  const { response } = item;
  const considered = !response.grounded && response.citations.length > 0;
  const hasSources = response.citations.length > 0;
  const isOverview = response.source === "course-overview";

  return (
    <div className="max-w-[95%] border-2 border-foreground bg-card shadow-brutal sm:max-w-[80%]">
      <div className="flex items-center gap-2 border-b-2 border-foreground bg-secondary px-3 py-2">
        <Quote className="size-3.5" />
        <span className="text-[11px] font-black uppercase tracking-widest">
          {isOverview ? "Course Index" : "Syllabus Bot"}
        </span>
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

        {!!response.topics?.length && (
          <div className="border-t-2 border-dashed border-foreground/30 pt-3">
            <p className="text-[11px] font-black uppercase tracking-widest">Indexed topics</p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {response.topics.map((topic) => (
                <span
                  key={topic}
                  className="border-2 border-foreground bg-secondary px-2 py-0.5 text-[11px] font-bold"
                >
                  {topic}
                </span>
              ))}
            </div>
          </div>
        )}

        {hasSources && (
          <div className="border-t-2 border-dashed border-foreground/30 pt-3">
            <button
              onClick={() => setOpen((v) => !v)}
              className="flex w-full items-center gap-2 text-[11px] font-black uppercase tracking-widest"
            >
              <ChevronDown className={cn("size-3.5 transition-transform", open && "rotate-180")} />
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
