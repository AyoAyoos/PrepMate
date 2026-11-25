import { useEffect, useRef, useState } from "react";
import { Mic, PhoneOff, Radio } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  getVoiceIntegrationStatus,
  type VoiceAnswerLength,
  type VoiceCourseIndexStatus,
  type VoiceIntegrationStatus,
} from "@/lib/voice";
import type { VoiceCallStatus } from "@/lib/useVoiceCall";

interface VoicePanelProps {
  active: boolean;
  status: VoiceCallStatus;
  statusLabel: string;
  remoteStream: MediaStream | null;
  answerLength: VoiceAnswerLength;
  onAnswerLengthChange: (value: VoiceAnswerLength) => void;
  onToggle: () => void;
}

interface AnswerLengthToggleProps {
  value: VoiceAnswerLength;
  onChange: (value: VoiceAnswerLength) => void;
  disabled?: boolean;
}

/** Brutalist segmented control shared by the header and the inline call strip. */
export function AnswerLengthToggle({ value, onChange, disabled = false }: AnswerLengthToggleProps) {
  return (
    <div
      className="flex items-center gap-0.5 border-2 border-foreground bg-card p-0.5"
      role="group"
      aria-label="Answer length"
    >
      {(["short", "long"] as const).map((option) => (
        <Button
          key={option}
          type="button"
          variant={value === option ? "brutal" : "brutalOutline"}
          size="sm"
          className="h-6 px-2 text-[10px] font-black uppercase tracking-wider"
          aria-pressed={value === option}
          disabled={disabled}
          title="Applies to typed answers now; voice calls use the choice made when they start"
          onClick={() => onChange(option)}
        >
          {option}
        </Button>
      ))}
    </div>
  );
}

/**
 * Inline, chat-native voice controls. There is deliberately no Dialog, popup,
 * or iframe here: the call strip sits inside the chat column and its transcript
 * is appended to the same message list as typed questions.
 */
export function VoicePanel({
  active,
  status,
  statusLabel,
  remoteStream,
  answerLength,
  onAnswerLengthChange,
  onToggle,
}: VoicePanelProps) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [integration, setIntegration] = useState<VoiceIntegrationStatus | null>(null);
  const [courseIndex, setCourseIndex] = useState<VoiceCourseIndexStatus | null>(null);

  useEffect(() => {
    if (!active) return;
    let current = true;
    void getVoiceIntegrationStatus().then((result) => {
      if (!current) return;
      setIntegration(result);
      setCourseIndex(result?.course_index ?? null);
    });
    return () => {
      current = false;
    };
  }, [active]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.srcObject = remoteStream;
  }, [remoteStream]);

  if (!active) return null;

  const live = status === "live" || status === "connecting";
  const dotClass =
    status === "live"
      ? "bg-success"
      : status === "connecting"
        ? "bg-amber-500"
        : status === "error"
          ? "bg-destructive"
          : "bg-muted-foreground";

  const indexLabel = !integration
    ? "Checking course index…"
    : courseIndex?.reachable
      ? `${courseIndex.engine.toUpperCase()} + ${courseIndex.hnsw ? "HNSW" : "exact search"} · ${courseIndex.chunks ?? 0} chunks`
      : integration.reachable
        ? "Course index unavailable"
        : "Start the backend + voice services to speak to your course";

  return (
    <div className="border-b-2 border-foreground bg-secondary px-4 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <Radio className="size-4 shrink-0" />
        <span className="text-[11px] font-black uppercase tracking-widest">Voice Assistant</span>
        <span className={`inline-block size-2 shrink-0 rounded-full ${dotClass}`} />
        <span className="text-xs font-bold">{statusLabel}</span>
        <AnswerLengthToggle value={answerLength} onChange={onAnswerLengthChange} />
        <Button
          variant={live ? "brutalOutline" : "brutal"}
          size="sm"
          className="ml-auto"
          onClick={onToggle}
        >
          {live ? <PhoneOff className="size-4" /> : <Mic className="size-4" />}
          {live ? "End call" : status === "error" ? "Retry" : "Start call"}
        </Button>
      </div>
      <p className="mt-1 text-[11px] font-semibold text-muted-foreground">
        Transcripts appear in this chat. {answerLength.toUpperCase()} applies to typed answers now
        and to the next voice call · course-only · voice temperature{" "}
        {integration?.answer_policy?.voice_temperature ?? "—"}. Course answers come from the same
        DuckDB + HNSW index as typed questions. {indexLabel}
      </p>
      <audio ref={audioRef} autoPlay className="hidden" />
    </div>
  );
}
