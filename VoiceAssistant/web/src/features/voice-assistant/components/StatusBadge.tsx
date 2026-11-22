import type { CallStatus } from "../types";
import styles from "./StatusBadge.module.css";

export interface StatusBadgeProps {
  status: CallStatus;
  label: string;
}

const badgeClass: Record<CallStatus, string> = {
  idle: styles.idle,
  connecting: styles.connecting,
  live: styles.live,
  error: styles.error,
};

const dotClass: Record<CallStatus, string> = {
  idle: styles.dotIdle,
  connecting: styles.dotConnecting,
  live: styles.dotLive,
  error: styles.dotError,
};

export default function StatusBadge({ status, label }: StatusBadgeProps) {
  return (
    <div className={`${styles.badge} ${badgeClass[status]}`} role="status">
      <span className={`${styles.dot} ${dotClass[status]}`} aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}
