// Reads the {error, error_code} envelope every sheet-music server puts in an isError result
// (docs/conventions.md, Error Response Format).

import type { ToolResult } from "./HostBridge.ts";

export interface ErrorEnvelope {
  error: string;
  code: string;
  hint?: string;
}

/** The envelope of an isError result, or undefined for a successful one. */
export function errorEnvelope(result: ToolResult): ErrorEnvelope | undefined {
  if (!result.isError) return undefined;
  for (const block of result.content ?? []) {
    const text = (block as { text?: unknown }).text;
    if (typeof text !== "string") continue;
    try {
      const data = JSON.parse(text) as { error?: unknown; error_code?: unknown; hint?: unknown };
      if (typeof data.error_code !== "string") continue;
      const envelope: ErrorEnvelope = { error: typeof data.error === "string" ? data.error : "", code: data.error_code };
      if (typeof data.hint === "string") envelope.hint = data.hint;
      return envelope;
    } catch {
      // Not the JSON envelope; keep looking.
    }
  }
  return { error: "", code: "UNKNOWN_ERROR" };
}
