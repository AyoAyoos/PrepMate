import { useCallback, useEffect, useRef, useState } from "react";

import { voiceAssistantUrl, voiceAssistantWsUrl, type VoiceAnswerLength } from "@/lib/voice";

export type VoiceCallStatus = "idle" | "connecting" | "live" | "error";
export type VoiceTranscriptRole = "user" | "assistant";

export interface VoiceTranscript {
  id: string;
  role: VoiceTranscriptRole;
  text: string;
  final: boolean;
}

interface IncomingMessage {
  type: string;
  payload?: unknown;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : null;
}

function mapServerState(state: string): { status: VoiceCallStatus; label: string } {
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
 * Browser-side WebRTC + signaling for the inline PrepMate voice chat.
 * No iframe or popup: transcripts are emitted into the normal chat stream and
 * audio is exposed as a MediaStream for a hidden <audio> element.
 */
export function useVoiceCall(onTranscript: (message: VoiceTranscript) => void) {
  const [status, setStatus] = useState<VoiceCallStatus>("idle");
  const [statusLabel, setStatusLabel] = useState("Idle");
  const [remoteStream, setRemoteStream] = useState<MediaStream | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const localStreamRef = useRef<MediaStream | null>(null);
  const pcIdRef = useRef<string | null>(null);
  const activeRef = useRef(false);
  const mountedRef = useRef(true);
  const pendingRef = useRef<{ id: string; role: VoiceTranscriptRole } | null>(null);
  const onTranscriptRef = useRef(onTranscript);

  useEffect(() => {
    onTranscriptRef.current = onTranscript;
  }, [onTranscript]);

  const updateStatus = useCallback((next: VoiceCallStatus, label: string) => {
    if (!mountedRef.current) return;
    setStatus(next);
    setStatusLabel(label);
  }, []);

  const emitTranscript = useCallback((role: VoiceTranscriptRole, text: string, final: boolean) => {
    if (!mountedRef.current || !text.trim()) return;
    const pending = pendingRef.current;
    const id =
      !final && pending?.role === role
        ? pending.id
        : final && pending?.role === role
          ? pending.id
          : crypto.randomUUID();
    pendingRef.current = final ? null : { id, role };
    onTranscriptRef.current({ id, role, text, final });
  }, []);

  const reportError = useCallback(async (value: unknown, action: string) => {
    const error = value instanceof Error ? value : new Error(String(value));
    console.error(error);
    try {
      await fetch(voiceAssistantUrl("/api/client-error"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: error.message,
          source: "prepmate-inline-voice",
          stack: error.stack ?? null,
          context: { action },
        }),
      });
    } catch {
      // The voice service may be stopping while the call tears down.
    }
  }, []);

  const cleanup = useCallback((nextStatus: VoiceCallStatus = "idle", label = "Idle") => {
    activeRef.current = false;
    pendingRef.current = null;

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
  }, []);

  const start = useCallback(
    async (answerLength: VoiceAnswerLength = "short") => {
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
        const localStream = await navigator.mediaDevices.getUserMedia({
          audio: {
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          },
        });
        if (!mountedRef.current) {
          localStream.getTracks().forEach((track) => track.stop());
          return;
        }
        localStreamRef.current = localStream;

        const pcId = crypto.randomUUID();
        pcIdRef.current = pcId;
        const pc = new RTCPeerConnection({
          iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
        });
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

        const ws = new WebSocket(voiceAssistantWsUrl("/ws/signaling/1"));
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
                void reportError(error, "addIceCandidate");
              }
            }
          } else if (message.type === "transcript") {
            const role: VoiceTranscriptRole = payload?.role === "user" ? "user" : "assistant";
            emitTranscript(role, typeof payload?.text === "string" ? payload.text : "", true);
          } else if (message.type === "state") {
            const mapped = mapServerState(typeof payload?.state === "string" ? payload.state : "");
            updateStatus(mapped.status, mapped.label);
          } else if (message.type === "error") {
            const text =
              typeof payload?.message === "string" ? payload.message : "Voice connection error";
            emitTranscript("assistant", text, true);
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
          ws.onerror = () => reject(new Error("Voice signaling connection failed"));
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
              call_context_vars: { answer_length: answerLength },
            },
          }),
        );
      } catch (error) {
        void reportError(error, "start");
        emitTranscript("assistant", error instanceof Error ? error.message : String(error), true);
        cleanup("error", "Error");
      }
    },
    [cleanup, emitTranscript, reportError, status, updateStatus],
  );

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

  return { status, statusLabel, remoteStream, start, stop };
}
