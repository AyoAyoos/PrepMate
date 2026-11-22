export type CallStatus = "idle" | "connecting" | "live" | "error";

export type MessageRole = "assistant" | "user";

export interface TranscriptMessage {
  id: string;
  role: MessageRole;
  text: string;
}

export interface VoiceSession {
  status: CallStatus;
  statusLabel: string;
  messages: TranscriptMessage[];
  remoteStream: MediaStream | null;
  start: () => Promise<void>;
  stop: () => void;
}

export interface SessionSummary {
  id: string;
  signaling_session_id: number;
  started_at: string;
  ended_at: string | null;
  status: string;
  title: string | null;
  model: string | null;
  voice: string | null;
  language: string | null;
  message_count: number;
  memory_count: number;
  stored_message_count: number;
}

export interface StoredMessage {
  id: string;
  session_id: string;
  role: MessageRole;
  text: string;
  created_at: string;
  turn_index: number;
  distance?: number | null;
}

export interface MemoryFact {
  id: string;
  content: string;
  category: string | null;
  confidence: number;
  use_count?: number;
  distance?: number | null;
}

export interface SearchResults {
  query: string;
  embedding_used: boolean;
  memories: Array<MemoryFact & { distance?: number | null }>;
  messages: StoredMessage[];
}
