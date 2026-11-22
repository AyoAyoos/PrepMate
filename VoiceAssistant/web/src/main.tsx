import React from "react";
import ReactDOM from "react-dom/client";

import VoiceAssistant from "./features/voice-assistant/VoiceAssistant";
import { reportClientError } from "./features/voice-assistant/errors";
import "./features/voice-assistant/styles/tokens.css";
import "./features/voice-assistant/styles/global.css";

window.addEventListener("error", (event: ErrorEvent) => {
  void reportClientError(event.error ?? event.message, {
    source: "window-error",
    filename: event.filename,
    lineno: event.lineno,
    colno: event.colno,
  });
});

window.addEventListener("unhandledrejection", (event: PromiseRejectionEvent) => {
  void reportClientError(event.reason, { source: "unhandled-rejection" });
});

const rootElement = document.getElementById("root");
if (!rootElement) {
  const error = new Error("Missing #root element");
  void reportClientError(error, { source: "bootstrap" });
  throw error;
}

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <VoiceAssistant />
  </React.StrictMode>,
);

if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    void navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}
