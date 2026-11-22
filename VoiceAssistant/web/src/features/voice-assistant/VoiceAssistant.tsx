import { useEffect, useRef, useState } from "react";

import CallButton from "./components/CallButton";
import HistoryPanel from "./components/HistoryPanel";
import NbButton from "./components/NbButton";
import StatusBadge from "./components/StatusBadge";
import Transcript from "./components/Transcript";
import Waveform from "./components/Waveform";
import { useVoiceSession } from "./useVoiceSession";
import styles from "./VoiceAssistant.module.css";

interface RemoteAudioProps {
  stream: MediaStream | null;
}

function RemoteAudio({ stream }: RemoteAudioProps) {
  const audioRef = useRef<HTMLAudioElement>(null);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.srcObject = stream;
    if (stream) void audio.play().catch(() => {});
  }, [stream]);

  return <audio ref={audioRef} autoPlay playsInline className={styles.audio} />;
}

export default function VoiceAssistant() {
  const { status, statusLabel, messages, remoteStream, start, stop } =
    useVoiceSession();
  const [historyOpen, setHistoryOpen] = useState(false);
  const autoStartedRef = useRef(false);

  const params = new URLSearchParams(window.location.search);
  const compact = params.get("compact") === "1";
  const autoStart = params.get("autostart") === "1";

  useEffect(() => {
    document.title = compact ? "Voice Assistant Mini" : "Voice Assistant";
    document.body.style.overflow = compact ? "hidden" : "";
    return () => {
      document.title = "Voice Assistant";
      document.body.style.overflow = "";
    };
  }, [compact]);

  useEffect(() => {
    if (!autoStart) return;
    const timer = window.setTimeout(() => {
      if (autoStartedRef.current) return;
      autoStartedRef.current = true;
      void start();
    }, 250);
    return () => window.clearTimeout(timer);
  }, [autoStart, start]);

  if (compact) {
    const latest = messages[messages.length - 1];

    return (
      <main className={styles.compactPage}>
        <div className={styles.compactCard}>
          <div className={styles.compactControls}>
            <CallButton status={status} onStart={start} onStop={stop} />
            <StatusBadge status={status} label={statusLabel} />
          </div>

          <Waveform
            active={status === "live"}
            stream={remoteStream}
            className={styles.compactWaveform}
          />

          <div className={styles.compactTranscript} role="log" aria-live="polite">
            {latest
              ? `${latest.role === "user" ? "You" : "Assistant"}: ${latest.text}`
              : autoStart
                ? "Starting your call…"
                : "Press Start and say hi 👋"}
          </div>

          <button
            type="button"
            className={styles.expandButton}
            onClick={() => {
              window.open(window.location.pathname, "_blank");
            }}
          >
            Expand ↗
          </button>
        </div>
        <RemoteAudio stream={remoteStream} />
      </main>
    );
  }

  return (
    <main className={styles.page}>
      <div className={styles.container}>
        <header className={styles.header}>
          <div>
            <h1 className={styles.title}>Voice Assistant</h1>
            <p className={styles.subtitle}>
              Speak after pressing Start. Your browser sends microphone audio over
              WebRTC; the reply is played back here. Calls and memory are stored
              locally.
            </p>
          </div>
          <NbButton variant="lilac" onClick={() => setHistoryOpen(true)}>
            History &amp; Memory
          </NbButton>
        </header>

        <section className={styles.card}>
          <div className={styles.controls}>
            <CallButton status={status} onStart={start} onStop={stop} />
            <StatusBadge status={status} label={statusLabel} />
          </div>

          <Waveform
            active={status === "live"}
            stream={remoteStream}
            className={styles.waveform}
          />
          <Transcript messages={messages} className={styles.transcript} />
        </section>

        <RemoteAudio stream={remoteStream} />
      </div>

      <HistoryPanel open={historyOpen} onClose={() => setHistoryOpen(false)} />
    </main>
  );
}
