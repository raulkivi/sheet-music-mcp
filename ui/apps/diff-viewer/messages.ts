// The Diff Viewer's server contract (compare_scores' helper tools) and the one text it sends to
// the model. Anything sent to the model is a fixed template filled with server-produced values
// (file paths); nothing from the MusicXML ever reaches a message.

import type { ToolResult } from "@sheet-music-mcp/ui-kit/host/HostBridge";
import { errorEnvelope } from "@sheet-music-mcp/ui-kit/host/toolErrors";

export type Scores =
  | { ok: true; reference: string; target: string; legend: Record<string, string> }
  | { ok: false; code: string };

export type Exported = { ok: true; reference: string; target: string } | { ok: false; code: string };

const UNEXPECTED = "UNEXPECTED_RESULT";
const MAX_PATH_CHARS = 512;

const text = (value: unknown): string | undefined => (typeof value === "string" && value !== "" ? value : undefined);

/** `get_diff_scores` → both annotated scores; an error envelope → its code. */
export function readScores(result: ToolResult): Scores {
  const failure = errorEnvelope(result);
  if (failure) return { ok: false, code: failure.code };
  const data = result.structuredContent ?? {};
  const reference = text(data.reference_musicxml);
  const target = text(data.target_musicxml);
  if (!reference || !target) return { ok: false, code: UNEXPECTED };
  const legend: Record<string, string> = {};
  if (typeof data.legend === "object" && data.legend !== null) {
    for (const [kind, color] of Object.entries(data.legend)) if (typeof color === "string") legend[kind] = color;
  }
  return { ok: true, reference, target, legend };
}

/** `export_diff_scores` → the two file paths; an error envelope → its code. */
export function readExported(result: ToolResult): Exported {
  const failure = errorEnvelope(result);
  if (failure) return { ok: false, code: failure.code };
  const data = result.structuredContent ?? {};
  const reference = text(data.reference_annotated_musicxml_path);
  const target = text(data.target_annotated_musicxml_path);
  return reference && target ? { ok: true, reference, target } : { ok: false, code: UNEXPECTED };
}

export function fileName(path: string): string {
  return path.split(/[\\/]/).pop() ?? path;
}

const quoted = (path: string): string => path.replace(/[\u0000-\u001f\u007f`]/g, "").slice(0, MAX_PATH_CHARS);

/** The one `ui/message` of "Open in Score Viewer": the model chains to render-mcp from it. */
export function openInScoreViewerMessage(referencePath: string, targetPath: string): string {
  return (
    `Open the annotated target score \`${quoted(targetPath)}\` (and the annotated reference ` +
    `\`${quoted(referencePath)}\`) from the Diff Viewer in the Score Viewer: render it with ` +
    "render-mcp, passing the path as musicxml_path."
  );
}

/**
 * Position of the measure printed as `number` among the first part's measures. Verovio draws
 * the measures in that order, so it is also the index among the rendered `g.measure` elements.
 */
export function measureIndex(musicxml: string, number: number): number | undefined {
  const part = musicxml.match(/<part\b[^>]*>([\s\S]*?)<\/part>/);
  if (!part) return undefined;
  const numbers = [...part[1]!.matchAll(/<measure\b[^>]*?\bnumber="([^"]*)"/g)].map((m) => m[1]);
  const index = numbers.indexOf(String(number));
  return index < 0 ? undefined : index;
}
