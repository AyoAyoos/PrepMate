/**
 * Connection details for the bundled Voice Assistant service.
 *
 * The voice app runs as its own FastAPI process (VoiceAssistant/app.py). The
 * PrepMate chat UI talks to it directly over WebRTC signaling — no iframe or
 * popup — while course answers come from PrepMate's shared DuckDB + HNSW index
 * through the backend /ask endpoint.
 */
export const VOICE_ASSISTANT_URL = (
  import.meta.env.VITE_VOICE_ASSISTANT_URL ?? "http://127.0.0.1:45124"
).replace(/\/+$/, "");

function normalizePath(path = "/"): string {
  return path.startsWith("/") ? path : `/${path}`;
}

export function voiceAssistantUrl(path = "/"): string {
  return `${VOICE_ASSISTANT_URL}${normalizePath(path)}`;
}

export function voiceAssistantWsUrl(path = "/"): string {
  const url = new URL(voiceAssistantUrl(path));
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

export interface VoiceCourseIndexStatus {
  engine: string;
  reachable: boolean;
  hnsw: boolean | null;
  chunks: number | null;
  documents: number | null;
}

export interface VoiceIntegrationStatus {
  prepmate_api_base: string;
  syllabus_search: boolean;
  reachable: boolean;
  documents: number | null;
  course_index: VoiceCourseIndexStatus;
}

/** Best-effort health check; the inline voice control still works when down. */
export async function getVoiceIntegrationStatus(): Promise<VoiceIntegrationStatus | null> {
  try {
    const response = await fetch(voiceAssistantUrl("/api/integration/status"));
    if (!response.ok) return null;
    return (await response.json()) as VoiceIntegrationStatus;
  } catch {
    return null;
  }
}
