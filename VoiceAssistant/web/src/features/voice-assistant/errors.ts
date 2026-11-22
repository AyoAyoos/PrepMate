export interface ClientErrorContext {
  source?: string;
  session_id?: string;
  [key: string]: unknown;
}

/** Report browser errors to the backend so they land in ERROR logs + DuckDB. */
export async function reportClientError(
  value: unknown,
  context: ClientErrorContext = {},
): Promise<void> {
  const error =
    value instanceof Error
      ? value
      : new Error(typeof value === "string" ? value : String(value));

  console.error(error);
  try {
    await fetch("/api/client-error", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: error.message,
        source: context.source ?? "frontend",
        stack: error.stack ?? null,
        context,
        session_id: context.session_id,
      }),
    });
  } catch (reportError) {
    // The backend may be stopped while the panel is closing.
    console.warn("Could not report client error", reportError);
  }
}
