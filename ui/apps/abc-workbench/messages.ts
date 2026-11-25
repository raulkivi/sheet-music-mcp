// Pure parsing of the ABC tools' contract and the fixed texts the workbench sends to the host.
// Anything sent to the model is a template filled with numbers and a file path the server
// produced; the ABC itself (titles, lyrics) never reaches a message.

import type { ToolResult } from "@sheet-music-mcp/ui-kit/host/HostBridge";
import { errorEnvelope } from "@sheet-music-mcp/ui-kit/host/toolErrors";

export interface StoredAbc {
  abc: string;
  abcId: string;
  warnings: string[];
}

export type Conversion =
  | { kind: "inline"; musicxml: string; bytes: number; warnings: string[] }
  | { kind: "file"; path: string; bytes: number; warnings: string[] }
  | { kind: "error"; code: string; message: string };

const MAX_PATH_CHARS = 512;

const strings = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];

/** The model's ABC: the `abc` argument of abc_to_musicxml. */
export function readProposal(args: Record<string, unknown>): string | undefined {
  return typeof args.abc === "string" && args.abc.trim() !== "" ? args.abc : undefined;
}

/** `musicxml_to_abc` and the app-only `get_abc` share this result: `{abc_id, abc, parts_included, warnings}`. */
export function readStoredAbc(result: ToolResult): StoredAbc | undefined {
  if (result.isError) return undefined;
  const data = result.structuredContent;
  if (!data || typeof data.abc !== "string" || typeof data.abc_id !== "string") return undefined;
  return { abc: data.abc, abcId: data.abc_id, warnings: strings(data.warnings) };
}

function contentJson(result: ToolResult): Record<string, unknown> {
  for (const block of result.content ?? []) {
    const raw = (block as { text?: unknown }).text;
    if (typeof raw !== "string") continue;
    try {
      const data: unknown = JSON.parse(raw);
      if (data && typeof data === "object" && !Array.isArray(data)) return data as Record<string, unknown>;
    } catch {
      // Not the JSON block; keep looking.
    }
  }
  return {};
}

/** `abc_to_musicxml`: warnings and delivery from structuredContent, the file path or text from content. */
export function readConversion(result: ToolResult): Conversion {
  const failure = errorEnvelope(result);
  if (failure) return { kind: "error", code: failure.code, message: failure.error };
  const data = result.structuredContent ?? {};
  const body = contentJson(result);
  const bytes = typeof data.musicxml_bytes === "number" ? data.musicxml_bytes : 0;
  const warnings = strings(data.warnings);
  if (data.delivery === "path" && typeof body.musicxml_path === "string") {
    return { kind: "file", path: body.musicxml_path, bytes, warnings };
  }
  if (data.delivery === "inline" && typeof body.musicxml === "string") {
    return { kind: "inline", musicxml: body.musicxml, bytes, warnings };
  }
  return { kind: "error", code: "MALFORMED_RESULT", message: "The conversion result could not be read." };
}

const cleanPath = (path: string): string => path.replace(/[\u0000-\u001f\u007f`]/g, "").slice(0, MAX_PATH_CHARS);

export function acceptContext(decision: { accepted: number; total: number; path?: string }): string {
  const where = decision.path === undefined ? "" : `, saved at \`${cleanPath(decision.path)}\``;
  return (
    `ABC Workbench: the user accepted ${decision.accepted} of ${decision.total} proposed changes ` +
    `and converted the result to MusicXML${where}.`
  );
}

export function rejectContext(total: number): string {
  return `ABC Workbench: the user rejected all ${total} proposed changes; the score is unchanged.`;
}

export function reviseMessage(rejected: { number: number; originalLine: number }[], total: number): string {
  const lead = "I reviewed your ABC edit in the ABC Workbench and";
  if (rejected.length === 0) return `${lead} kept all ${total} changes, but I would like a revision. Please revise it.`;
  const list = rejected.map((r) => `change ${r.number} (original line ${r.originalLine})`).join(", ");
  return `${lead} rejected ${rejected.length} of ${total} changes: ${list}. Please revise it.`;
}
