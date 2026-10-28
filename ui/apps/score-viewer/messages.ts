// Pure parsing of the render tools' contract and the fixed texts the viewer sends to the host.
// Anything sent to the model is a template filled with server-produced values; nothing from
// the MusicXML (titles, lyrics, credits) ever reaches a message.

import type { ToolResult } from "@sheet-music-mcp/ui-kit/host/HostBridge";

export type ScoreInput = { kind: "inline"; xml: string } | { kind: "path" } | { kind: "none" };

export interface SavedFile {
  path?: string;
  error?: string;
}

const MAX_PATH_CHARS = 512;

export function readScoreInput(args: Record<string, unknown>): ScoreInput {
  if (typeof args.musicxml === "string" && args.musicxml.trim() !== "") {
    return { kind: "inline", xml: args.musicxml };
  }
  if (typeof args.musicxml_path === "string" && args.musicxml_path !== "") return { kind: "path" };
  return { kind: "none" };
}

/** `render_to_pdf` → `pdf_path`; `render_to_image` → `image_path`; errors → `error_code`. */
export function readSavedFile(result: ToolResult): SavedFile {
  if (result.isError) return { error: errorCode(result) };
  const data = result.structuredContent ?? {};
  const path = data.pdf_path ?? data.image_path;
  return typeof path === "string" && path !== "" ? { path } : {};
}

function errorCode(result: ToolResult): string {
  for (const block of result.content ?? []) {
    const text = (block as { type?: string; text?: unknown }).text;
    if (typeof text !== "string") continue;
    try {
      const code = (JSON.parse(text) as { error_code?: unknown }).error_code;
      if (typeof code === "string") return code;
    } catch {
      // Not the JSON envelope; keep looking.
    }
  }
  return "UNKNOWN_ERROR";
}

/** D6 fallback: asks the model to help open or share the file the render tool saved. */
export function helpMessage(path: string): string {
  const quoted = path.replace(/[\u0000-\u001f\u007f`]/g, "").slice(0, MAX_PATH_CHARS);
  return (
    "I could not download the file from the Score Viewer. Please help me open or share the " +
    `rendered score saved at \`${quoted}\`.`
  );
}

export function pageContext(page: number, pageCount: number): string {
  return `Score Viewer: the user is looking at page ${page} of ${pageCount}.`;
}
