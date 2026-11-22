import { useCallback, useEffect, useRef, useState } from "react";

import { reportClientError } from "./errors";
import type {
  CallStatus,
  MessageRole,
  TranscriptMessage,
  VoiceSession,
} from "./types";

const SIGNALING_SESSION_ID = 1;
const ICE_SERVERS: RTCIceServer[] = [
  { urls: "stun:stun.l.google.com:19302" },
];
const MIC_CONSTRAINTS: MediaStreamConstraints = {
  audio: {
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true,
  },
};

interface IncomingMessage {
  type: string;
  payload?: unknown;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null
    ? (value as Record<string, unknown>)
    : null;
}

function mapServerState(state: string): { status: CallStatus; label: string } {
  switch (state) {
    case "connecting":
      return { status: "connecting", label: "Connecting…" };
    case "listening":
      return { status: "live", label: "Listening…" };
    case "thinking":
      return { status: "live", label: "Thinking…" };
    case "speaking":
      return { status: "live", label: "Speaking…" };
    case "error":
      return { status: "error", label: "Error" };
    case "ended":
      return { status: "idle", label: "Call ended" };
    default:
      return { status: "idle", label: state || "Idle" };
  }
}

/**
 * Wraps the browser-side WebRTC / signaling logic used by the old HTML page.
 * The signaling URL, ICE setup, mic constraints and transcript merge behaviour
 * are intentionally unchanged.
 */
export function useVoiceSession(): VoiceSession {
  const [status, setStatus] = useState<CallStatus>("idle");
  const [statusLabel, setStatusLabel] = useState("Idle");
  const [messages, setMessages] = useState<TranscriptMessage[]>([]);
  const [remoteStream, setRemoteStream] = useState<MediaStream | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const localStreamRef = useRef<MediaStream | null>(null);
  const pcIdRef = useRef<string | null>(null);
  const activeRef = useRef(false);
  const mountedRef = useRef(true);

  const updateStatus = useCallback((next: CallStatus, label: string) => {
    if (!mountedRef.current) return;
    setStatus(next);
    setStatusLabel(label);
  }, []);

  const appendMessage = useCallback(
    (role: MessageRole, text: string, final: boolean) => {
      if (!mountedRef.current) return;
      setMessages((previous) => {
        const last = previous[previous.length - 1];
        if (!final && last && last.role === role) {
          return [...previous.slice(0, -1), { ...last, text }];
        }
        return [
          ...previous,
          { id: crypto.randomUUID(), role, text },
        ];
      });
    },
    [],
  );

  const cleanup = useCallback(
    (nextStatus: CallStatus = "idle", label = "Idle") => {
      activeRef.current = false;

      const pc = pcRef.current;
      if (pc) {
        pc.close();
        pcRef.current = null;
      }

      const localStream = localStreamRef.current;
      if (localStream) {
        localStream.getTracks().forEach((track) => track.stop());
        localStreamRef.current = null;
      }

      const ws = wsRef.current;
      if (ws) {
        wsRef.current = null;
        ws.close();
      }

      pcIdRef.current = null;

      if (mountedRef.current) {
        setRemoteStream(null);
        setStatus(nextStatus);
        setStatusLabel(label);
      }
    },
    [],
  );

  const start = useCallback(async () => {
    if (
      activeRef.current ||
      wsRef.current ||
      pcRef.current ||
      status === "connecting" ||
      status === "live"
    ) {
      return;
    }

    updateStatus("connecting", "Connecting…");

    try {
      const localStream = await navigator.mediaDevices.getUserMedia(
        MIC_CONSTRAINTS,
      );
      if (!mountedRef.current) {
        localStream.getTracks().forEach((track) => track.stop());
        return;
      }
      localStreamRef.current = localStream;

      const pcId = crypto.randomUUID();
      pcIdRef.current = pcId;
      const pc = new RTCPeerConnection({ iceServers: ICE_SERVERS });
      pcRef.current = pc;

      localStream.getTracks().forEach((track) => pc.addTrack(track, localStream));

      pc.ontrack = (event) => {
        if (mountedRef.current && event.streams[0]) {
          setRemoteStream(event.streams[0]);
        }
      };

      pc.onicecandidate = (event) => {
        const ws = wsRef.current;
        const currentPcId = pcIdRef.current;
        if (!ws || ws.readyState !== WebSocket.OPEN || !currentPcId) return;
        ws.send(
          JSON.stringify({
            type: "ice-candidate",
            payload: {
              pc_id: currentPcId,
              candidate: event.candidate ? event.candidate.toJSON() : null,
            },
          }),
        );
      };

      const scheme = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(
        `${scheme}://${location.host}/ws/signaling/${SIGNALING_SESSION_ID}`,
      );
      wsRef.current = ws;

      ws.onmessage = async (event) => {
        let message: IncomingMessage;
        try {
          message = JSON.parse(String(event.data)) as IncomingMessage;
        } catch {
          return;
        }
        const payload = asRecord(message.payload);

        if (message.type === "answer") {
          const sdp = payload?.sdp;
          if (typeof sdp === "string") {
            await pc.setRemoteDescription({ type: "answer", sdp });
            activeRef.current = true;
            updateStatus("live", "Listening…");
          }
        } else if (message.type === "ice-candidate") {
          const candidate = payload?.candidate;
          if (candidate && typeof candidate === "object") {
            try {
              await pc.addIceCandidate(candidate as RTCIceCandidateInit);
            } catch (error) {
              void reportClientError(error, {
                source: "webrtc-ice",
                action: "addIceCandidate",
              });
            }
          }
        } else if (message.type === "transcript") {
          const role: MessageRole = payload?.role === "user" ? "user" : "assistant";
          const text = typeof payload?.text === "string" ? payload.text : "";
          appendMessage(role, text, payload?.final !== false);
        } else if (message.type === "state") {
          const state = typeof payload?.state === "string" ? payload.state : "";
          const mapped = mapServerState(state);
          updateStatus(mapped.status, mapped.label);
        } else if (message.type === "error") {
          const text =
            typeof payload?.message === "string"
              ? payload.message
              : "Connection error";
          appendMessage("assistant", text, true);
          updateStatus("error", "Error");
        } else if (message.type === "call-ended") {
          cleanup("idle", "Call ended");
        }
      };

      ws.onclose = () => {
        if (activeRef.current) cleanup("idle", "Call ended");
      };

      await new Promise<void>((resolve, reject) => {
        ws.onopen = () => resolve();
        ws.onerror = () => reject(new Error("Signaling connection failed"));
      });

      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      ws.send(
        JSON.stringify({
          type: "offer",
          payload: {
            pc_id: pcId,
            sdp: offer.sdp,
            type: offer.type,
            call_context_vars: {},
          },
        }),
      );
    } catch (error) {
      void reportClientError(error, {
        source: "voice-session",
        action: "start",
      });
      appendMessage(
        "assistant",
        error instanceof Error ? error.message : String(error),
        true,
      );
      cleanup("error", "Error");
    }
  }, [appendMessage, cleanup, status, updateStatus]);

  const stop = useCallback(() => {
    cleanup("idle", "Call ended");
  }, [cleanup]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      cleanup();
    };
  }, [cleanup]);

  return { status, statusLabel, messages, remoteStream, start, stop };
}
