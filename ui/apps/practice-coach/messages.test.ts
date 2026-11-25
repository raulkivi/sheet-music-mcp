import { describe, expect, it } from "vitest";
import type { ToolResult } from "@sheet-music-mcp/ui-kit/host/HostBridge";
import {
  NOTICES,
  practiceAgainArgs,
  readPosition,
  readScoreXml,
  readSession,
  readSessionState,
  readSummary,
} from "./messages.ts";

const text = (data: unknown): ToolResult => ({ content: [{ type: "text", text: JSON.stringify(data) }] });
const failure = (code: string): ToolResult => ({
  isError: true,
  content: [{ type: "text", text: JSON.stringify({ error: "x", error_code: code }) }],
});

const SESSION = {
  session_id: "s1",
  part_id: "P2",
  part_name: "Alto",
  measure_count: 4,
  duration_seconds: 16,
  tempo_bpm: 60,
};

describe("readSession", () => {
  it("reads the session view start_practice returns as structuredContent", () => {
    expect(readSession({ part: "Alto" }, { structuredContent: SESSION })).toEqual({
      kind: "session",
      session: { sessionId: "s1", partName: "Alto", measureCount: 4, tempoBpm: 60 },
    });
  });

  it("takes the session id from the arguments when the opening tool was start_monitoring", () => {
    expect(readSession({ session_id: "s9" }, text({ status: "started", session_id: "s9" }))).toEqual({
      kind: "session",
      session: { sessionId: "s9" },
    });
  });

  it("reports the server's error code, not its text", () => {
    expect(readSession({}, failure("PROCESSING_FAILED"))).toEqual({
      kind: "error",
      code: "PROCESSING_FAILED",
      message: NOTICES.openFailed("PROCESSING_FAILED"),
    });
  });

  it("is empty when the call carried no session", () => {
    expect(readSession({}, { content: [] })).toEqual({ kind: "none" });
    expect(readSession({ session_id: 7 }, {})).toEqual({ kind: "none" });
  });
});

describe("readPosition", () => {
  const position = {
    session_id: "s1",
    measure: 2,
    beat: 2.5,
    expected_note: "A3",
    sung_pitch_hz: 218.4,
    accuracy_cents: -14,
    status: "flat",
  };

  it("reads the position fields", () => {
    expect(readPosition({ structuredContent: position })).toEqual({
      kind: "position",
      position: { measure: 2, beat: 2.5, expected_note: "A3", sung_pitch_hz: 218.4, accuracy_cents: -14, status: "flat" },
    });
  });

  it("keeps null pitch and cents (no signal, uncertain)", () => {
    const result = readPosition({ structuredContent: { ...position, sung_pitch_hz: null, accuracy_cents: null, status: "uncertain" } });
    expect(result).toMatchObject({ kind: "position", position: { sung_pitch_hz: null, accuracy_cents: null, status: "uncertain" } });
  });

  it("rejects a result that is not a position", () => {
    expect(readPosition({ structuredContent: { measure: "2" } })).toEqual({ kind: "none" });
    expect(readPosition({})).toEqual({ kind: "none" });
  });

  it("returns the error code of a failed poll", () => {
    expect(readPosition(failure("SESSION_NOT_FOUND"))).toEqual({ kind: "error", code: "SESSION_NOT_FOUND" });
  });
});

describe("readSummary", () => {
  const summary = {
    measures_covered: 4,
    avg_accuracy_cents: 18,
    accuracy_histogram: { on_pitch: 10, sharp: 3, flat: 2, uncertain: 1, no_signal: 4 },
    highlights: [{ direction: "sharp", measures: [3, 4], notes: 3, avg_cents: 33, text: "sharp on G3 in m.3–4 (+33 cents avg)" }],
  };

  it("reads stop_monitoring's JSON text block", () => {
    expect(readSummary(text({ session_id: "s1", summary, timed_out: false }))).toEqual({
      kind: "summary",
      report: {
        measuresCovered: 4,
        avgCents: 18,
        histogram: { on_pitch: 10, sharp: 3, flat: 2, uncertain: 1, no_signal: 4 },
        highlights: ["sharp on G3 in m.3–4 (+33 cents avg)"],
        timedOut: false,
      },
    });
  });

  it("prefers structuredContent when the server sends it", () => {
    const result = { structuredContent: { summary, timed_out: true }, content: [] };
    expect(readSummary(result)).toMatchObject({ kind: "summary", report: { timedOut: true } });
  });

  it("keeps a null average (nothing graded) and tolerates no highlights", () => {
    const result = text({ summary: { ...summary, avg_accuracy_cents: null, highlights: undefined }, timed_out: false });
    expect(readSummary(result)).toMatchObject({ kind: "summary", report: { avgCents: null, highlights: [] } });
  });

  it("returns the error code of a failed stop", () => {
    expect(readSummary(failure("SESSION_NOT_FOUND"))).toEqual({ kind: "error", code: "SESSION_NOT_FOUND" });
  });

  it("is none for text that is not a summary", () => {
    expect(readSummary({ content: [{ type: "text", text: "hello" }] })).toEqual({ kind: "none" });
  });
});

describe("readScoreXml", () => {
  it("reads get_score_for_session's musicxml", () => {
    expect(readScoreXml({ structuredContent: { session_id: "s1", musicxml: "<score-partwise/>" } })).toBe("<score-partwise/>");
  });
  it("is undefined for an error or an empty result", () => {
    expect(readScoreXml(failure("SESSION_NOT_FOUND"))).toBeUndefined();
    expect(readScoreXml({ structuredContent: { musicxml: "" } })).toBeUndefined();
  });
});

describe("readSessionState", () => {
  it("finds the session's state in list_sessions", () => {
    const listing = text({
      idle_timeout_minutes: 10,
      sessions: [
        { session_id: "a", part: "Alto", state: "loaded", idle_seconds: 1 },
        { session_id: "b", part: "Alto", state: "monitoring", idle_seconds: 0 },
      ],
    });
    expect(readSessionState(listing, "b")).toBe("monitoring");
    expect(readSessionState(listing, "a")).toBe("loaded");
    expect(readSessionState(listing, "zzz")).toBeUndefined();
  });
});

describe("practiceAgainArgs", () => {
  it("keeps the arguments that start a practice, and nothing else", () => {
    expect(practiceAgainArgs({ musicxml_path: "/a.mxl", part: "Alto", measures: [1, 4], tempo_bpm: 50, junk: 1 })).toEqual({
      musicxml_path: "/a.mxl",
      part: "Alto",
      measures: [1, 4],
      tempo_bpm: 50,
    });
  });

  it("is undefined without a score or a part (the opening call was not start_practice)", () => {
    expect(practiceAgainArgs({ part: "Alto" })).toBeUndefined();
    expect(practiceAgainArgs({ musicxml: "<x/>" })).toBeUndefined();
    expect(practiceAgainArgs({ session_id: "s" })).toBeUndefined();
  });
});
