import type { CallStatus } from "../types";
import NbButton from "./NbButton";

export interface CallButtonProps {
  status: CallStatus;
  onStart: () => Promise<void>;
  onStop: () => void;
}

export default function CallButton({ status, onStart, onStop }: CallButtonProps) {
  if (status === "connecting") {
    return (
      <NbButton variant="lilac" disabled aria-pressed={false}>
        Connecting…
      </NbButton>
    );
  }

  if (status === "live") {
    return (
      <NbButton variant="danger" onClick={onStop} aria-pressed="true">
        ■ Stop
      </NbButton>
    );
  }

  return (
    <NbButton
      variant="primary"
      onClick={() => {
        void onStart();
      }}
      aria-pressed="false"
    >
      ▶ Start
    </NbButton>
  );
}
