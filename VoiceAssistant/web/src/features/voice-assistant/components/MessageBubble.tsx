import { memo } from "react";

import type { TranscriptMessage } from "../types";
import styles from "./MessageBubble.module.css";

export type MessageBubbleProps = TranscriptMessage;

function MessageBubble({ role, text }: MessageBubbleProps) {
  const isUser = role === "user";

  return (
    <div
      className={`${styles.wrapper} ${isUser ? styles.user : styles.assistant}`}
    >
      <span className={styles.label}>{isUser ? "You" : "Assistant"}</span>
      <p className={`${styles.bubble} ${isUser ? styles.userBubble : styles.assistantBubble}`}>
        {text}
      </p>
    </div>
  );
}

export default memo(MessageBubble);
