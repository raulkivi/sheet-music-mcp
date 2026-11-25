// Pure reading of pitch-mcp's tool contract, and the fixed texts the page shows. Nothing from
// the score (titles, lyrics) is ever put in a message or notice.

import type { ToolResult } from "@sheet-music-mcp/ui-kit/host/HostBridge";
import { errorEnvelope } from "@sheet-music-mcp/ui-kit/host/toolErrors";
import type { Sample } from "./history.ts";

export interface SessionInfo {
  sessionId: string;
  partName?: string;
  measureCount?: number;
  tempoBpm?: number;
}

export type SessionRead = { kind: "session"; session: SessionInfo } | { kind: "error"; code: string; message: string } | { kind: "none" };

export type PositionRead = { kind: "position"; position: Sample & { sung_pitch_hz: number | null } } | { kind: "error"; code: string } | { kind: "none" };

export interface SummaryReport {
  measuresCovered: number;
  /** Mean |cents| over graded notes; null when nothing was graded. */
  avgCents: number | null;
  histogram: Record<string, number>;
  /** The server's plain-language runs ("sharp on G3 in m.3–4 (+33 cents avg)"). */
  highlights: string[];
  /** The session closed by the idle timeout before the singer stopped it. */
  timedOut: boolean;
}

export type SummaryRead = { kind: "summary"; report: SummaryReport } | { kind: "error"; code: string } | { kind: "none" };

export const NOTICES = {
  openFailed: (code: string) => `Practice could not start (${code}). Ask Claude to try again.`,
  noSession: "No practice session is open. Ask Claude to start one: name the score and your part.",
  sessionClosed: "This practice session has closed. Showing the summary kept when it did.",
  serverLost: "Lost contact with the server. Still trying.",
  stopFailed: (code: string) => `The summary could not be read (${code}).`,
  startFailed: (code: string) => `Listening could not start (${code}).`,
  scoreFailed: "The score could not be shown. Pitch feedback still works.",
  scoreEngine: "The notation engine could not start in this host. Pitch feedback still works.",
};

/** The data of a tool result: structuredContent, else the JSON in the first text block. */
function dataOf(result: ToolResult): Record<string, unknown> | undefined {
  if (result.structuredContent) return result.structuredContent;
  for (const block of result.content ?? []) {
    const text = (block as { text?: unknown }).text;
    if (typeof text !== "string") continue;
    try {
      const parsed: unknown = JSON.parse(text);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed as Record<string, unknown>;
    } catch {
      // Prose, not JSON; keep looking.
    }
  }
  return undefined;
}

const isNumber = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const orNull = (value: unknown): number | null => (isNumber(value) ? value : null);

export function readSession(args: Record<string, unknown>, result: ToolResult): SessionRead {
  const failure = errorEnvelope(result);
  if (failure) return { kind: "error", code: failure.code, message: NOTICES.openFailed(failure.code) };
  const data = dataOf(result) ?? {};
  const sessionId = typeof data.session_id === "string" && data.session_id !== "" ? data.session_id : undefined;
  const fromArgs = typeof args.session_id === "string" && args.session_id !== "" ? args.session_id : undefined;
  const id = sessionId ?? fromArgs;
  if (!id) return { kind: "none" };
  const session: SessionInfo = { sessionId: id };
  if (typeof data.part_name === "string") session.partName = data.part_name;
  if (isNumber(data.measure_count)) session.measureCount = data.measure_count;
  if (isNumber(data.tempo_bpm)) session.tempoBpm = data.tempo_bpm;
  return { kind: "session", session };
}

export function readPosition(result: ToolResult): PositionRead {
  const failure = errorEnvelope(result);
  if (failure) return { kind: "error", code: failure.code };
  const data = result.structuredContent ?? {};
  if (!isNumber(data.measure) || !isNumber(data.beat) || typeof data.status !== "string") return { kind: "none" };
  return {
    kind: "position",
    position: {
      measure: data.measure,
      beat: data.beat,
      expected_note: typeof data.expected_note === "string" ? data.expected_note : "",
      sung_pitch_hz: orNull(data.sung_pitch_hz),
      accuracy_cents: orNull(data.accuracy_cents),
      status: data.status,
    },
  };
}

export function readSummary(result: ToolResult): SummaryRead {
  const failure = errorEnvelope(result);
  if (failure) return { kind: "error", code: failure.code };
  const data = dataOf(result);
  const summary = data?.summary;
  if (!summary || typeof summary !== "object") return { kind: "none" };
  const s = summary as Record<string, unknown>;
  const histogram: Record<string, number> = {};
  for (const [status, count] of Object.entries((s.accuracy_histogram as Record<string, unknown> | undefined) ?? {})) {
    if (isNumber(count)) histogram[status] = count;
  }
  const highlights = Array.isArray(s.highlights)
    ? s.highlights.flatMap((h) => (h && typeof (h as { text?: unknown }).text === "string" ? [(h as { text: string }).text] : []))
    : [];
  return {
    kind: "summary",
    report: {
      measuresCovered: isNumber(s.measures_covered) ? s.measures_covered : 0,
      avgCents: orNull(s.avg_accuracy_cents),
      histogram,
      highlights,
      timedOut: data?.timed_out === true,
    },
  };
}

export function readScoreXml(result: ToolResult): string | undefined {
  if (errorEnvelope(result)) return undefined;
  const xml = result.structuredContent?.musicxml;
  return typeof xml === "string" && xml !== "" ? xml : undefined;
}

/** `list_sessions` → the state ("loaded" or "monitoring") of one session. */
export function readSessionState(result: ToolResult, sessionId: string): string | undefined {
  const sessions = dataOf(result)?.sessions;
  if (!Array.isArray(sessions)) return undefined;
  const found = sessions.find((s) => (s as { session_id?: unknown })?.session_id === sessionId) as { state?: unknown } | undefined;
  return typeof found?.state === "string" ? found.state : undefined;
}

const PRACTICE_KEYS = ["musicxml", "musicxml_path", "part", "tempo_bpm", "measures"] as const;

/** The arguments to start the same practice again, only when the opening call was start_practice. */
export function practiceAgainArgs(args: Record<string, unknown>): Record<string, unknown> | undefined {
  const hasScore = (typeof args.musicxml === "string" && args.musicxml !== "") || (typeof args.musicxml_path === "string" && args.musicxml_path !== "");
  if (!hasScore || typeof args.part !== "string" || args.part === "") return undefined;
  const kept: Record<string, unknown> = {};
  for (const key of PRACTICE_KEYS) if (args[key] !== undefined) kept[key] = args[key];
  return kept;
}
