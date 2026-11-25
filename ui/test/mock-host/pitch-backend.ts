// Stand-in for pitch-mcp's session tools, for the Practice Coach in the mock host. It answers in
// the server's contract (pitch-mcp presenter.py, engine.py): get_current_position as
// structuredContent, start_monitoring / stop_monitoring / list_sessions as JSON text, the
// error envelope for failures. The singing is a script (a "take"): each get_current_position
// returns the next step, then holds the last, so a spec can walk the whole take.
// This is mock-host test data, never shipped in a page.

import type { CallToolResult } from "@modelcontextprotocol/client";
import type { TakeName } from "./options.ts";
import { SESSION_ID, SESSION_VIEW } from "./pitch-session.ts";
import { NoSuchTool, toolError, type ToolBackend, type ToolCall } from "./tool-backends.ts";



export interface TakeStep {
  measure: number;
  beat: number;
  expected_note: string;
  sung_pitch_hz: number | null;
  accuracy_cents: number | null;
  status: "on_pitch" | "sharp" | "flat" | "uncertain" | "no_signal";
}

const step = (measure: number, beat: number, expected_note: string, status: TakeStep["status"], cents: number | null, hz: number | null): TakeStep => ({
  measure,
  beat,
  expected_note,
  sung_pitch_hz: hz,
  accuracy_cents: cents,
  status,
});

// satb-4bars, Alto: four bars, every grading state once or more, bars in order.
const STEADY: TakeStep[] = [
  step(1, 1, "A3", "on_pitch", 4, 220.5),
  step(1, 3, "A3", "on_pitch", -6, 219.2),
  step(2, 1, "B3", "sharp", 32, 251.6),
  step(2, 3, "B3", "sharp", 70, 257.0),
  step(3, 1, "C4", "flat", -30, 257.0),
  step(3, 3, "C4", "uncertain", null, 130.8),
  step(4, 1, "D4", "no_signal", null, null),
  step(4, 3, "D4", "on_pitch", 2, 293.9),
];

export const TAKES: Record<TakeName, TakeStep[]> = {
  steady: STEADY,
  closed: STEADY,
  lost: STEADY,
};

/** `closed`: the session expires after this many polls, as the idle timeout would. */
const CLOSES_AFTER = 4;
/** `lost`: the server answers this many polls, then fails every one (a dead link). */
const ANSWERS_BEFORE_LOST = 3;

const STATUSES = ["on_pitch", "sharp", "flat", "uncertain", "no_signal"] as const;

function json(data: unknown): CallToolResult {
  return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
}

/** The server's summarize(): histogram, mean |cents| of graded notes, runs of flat or sharp notes. */
export function summarizeTake(steps: readonly TakeStep[]) {
  const histogram = Object.fromEntries(STATUSES.map((s) => [s, 0])) as Record<(typeof STATUSES)[number], number>;
  const graded: number[] = [];
  for (const s of steps) {
    histogram[s.status]++;
    if (s.status !== "uncertain" && s.accuracy_cents !== null) graded.push(Math.abs(s.accuracy_cents));
  }
  return {
    measures_covered: new Set(steps.map((s) => s.measure)).size,
    avg_accuracy_cents: graded.length === 0 ? null : Math.round(graded.reduce((a, b) => a + b, 0) / graded.length),
    accuracy_histogram: histogram,
    highlights: highlightsOf(steps),
  };
}

function highlightsOf(steps: readonly TakeStep[]) {
  const runs: TakeStep[][] = [];
  let run: TakeStep[] = [];
  for (const s of steps) {
    const direction = s.status === "sharp" || s.status === "flat" ? s.status : undefined;
    if (direction && (run.length === 0 || run[0]!.status === direction)) run.push(s);
    else {
      if (run.length >= 2) runs.push(run);
      run = direction ? [s] : [];
    }
  }
  if (run.length >= 2) runs.push(run);
  return runs.map((r) => {
    const avg = Math.round(r.reduce((sum, s) => sum + (s.accuracy_cents ?? 0), 0) / r.length);
    const direction = avg < 0 ? "flat" : "sharp";
    const measures = [r[0]!.measure, r.at(-1)!.measure];
    const span = measures[0] === measures[1] ? `m.${measures[0]}` : `m.${measures[0]}–${measures[1]}`;
    return { direction, measures, notes: r.length, avg_cents: avg, text: `${direction} in ${span} (${avg > 0 ? "+" : ""}${avg} cents avg over ${r.length} notes)` };
  });
}

export interface PitchBackendOptions {
  xml: string;
  take: TakeName;
  /** The state list_sessions reports at first. */
  state: "monitoring" | "loaded";
  latencyMs: number;
}

export function pitchTools(options: PitchBackendOptions): ToolBackend {
  const script = TAKES[options.take];
  let state = options.state;
  let polls = 0;
  let index = 0;
  let consumed: TakeStep[] = [];

  const sessionGone = () => toolError(`Session '${SESSION_ID}' not found. Call load_score first.`, "SESSION_NOT_FOUND");
  const timedOut = () => options.take === "closed" && polls > CLOSES_AFTER;

  const handlers: Record<string, (call: ToolCall) => CallToolResult> = {
    get_score_for_session: () => ({
      content: [{ type: "text", text: `Score for session ${SESSION_ID} fetched for the Practice Coach.` }],
      structuredContent: { session_id: SESSION_ID, musicxml: options.xml },
    }),
    list_sessions: () => json({ idle_timeout_minutes: 10, sessions: [{ session_id: SESSION_ID, part: "Alto", state, idle_seconds: 0 }] }),
    // "Practice again": a new take on the same session id, from the first step.
    start_practice: () => {
      state = "monitoring";
      polls = 0;
      index = 0;
      consumed = [];
      return { content: [{ type: "text", text: JSON.stringify({ ...SESSION_VIEW, status: "started" }, null, 2) }], structuredContent: SESSION_VIEW };
    },
    start_monitoring: () => {
      state = "monitoring";
      return json({ status: "started", session_id: SESSION_ID });
    },
    get_current_position: () => {
      polls++;
      if (timedOut()) return sessionGone();
      if (options.take === "lost" && polls > ANSWERS_BEFORE_LOST) return toolError("Unexpected error: mock failure", "PROCESSING_FAILED");
      const next = script[Math.min(index, script.length - 1)] as TakeStep;
      // The take's own steps only: holding on the last one does not count it again.
      if (index < script.length) consumed.push(next);
      index++;
      const position = { session_id: SESSION_ID, ...next };
      return { content: [{ type: "text", text: JSON.stringify(position, null, 2) }], structuredContent: position };
    },
    stop_monitoring: () => {
      const timed_out = options.take === "closed" && polls > CLOSES_AFTER;
      return json({ session_id: SESSION_ID, summary: summarizeTake(consumed), timed_out });
    },
  };

  return {
    async callTool(call) {
      const handler = handlers[call.name];
      if (!handler) throw new NoSuchTool(call.name);
      if (options.latencyMs > 0) await new Promise((resolve) => setTimeout(resolve, options.latencyMs));
      return handler(call);
    },
  };
}
