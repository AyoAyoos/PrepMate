import { useEffect, useRef } from "react";

import type { TranscriptMessage } from "../types";
import MessageBubble from "./MessageBubble";
import styles from "./Transcript.module.css";

export interface TranscriptProps {
  messages: TranscriptMessage[];
  className?: string;
}

export default function Transcript({ messages, className = "" }: TranscriptProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const previousCountRef = useRef(messages.length);

  useEffect(() => {
    const container = containerRef.current;
    const bottom = bottomRef.current;
    if (!container || !bottom) return;

    const distanceFromBottom =
      container.scrollHeight - container.scrollTop - container.clientHeight;
    const grew = messages.length > previousCountRef.current;
    previousCountRef.current = messages.length;

    if (grew && distanceFromBottom > 80) return;

    const reduceMotion = window.matchMedia?.(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    bottom.scrollIntoView({
      block: "end",
      behavior: reduceMotion ? "auto" : "smooth",
    });
  }, [messages]);

  return (
    <div
      ref={containerRef}
      className={`${styles.transcript} ${className}`.trim()}
      role="log"
      aria-live="polite"
    >
      {messages.length === 0 ? (
        <div className={styles.empty}>PRESS START AND SAY HI 👋</div>
      ) : (
        messages.map((message) => (
          <MessageBubble key={message.id} {...message} />
        ))
      )}
      <div ref={bottomRef} className={styles.sentinel} aria-hidden="true" />
    </div>
  );
}
