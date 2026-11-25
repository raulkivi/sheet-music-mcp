import { describe, expect, it } from "vitest";
import { composeTools, noTools, placeholderTools } from "./tool-backends.ts";
import { TAKES, pitchTools, summarizeTake, type TakeStep } from "./pitch-backend.ts";

const XML = "<score-partwise/>";
const text = (result: { content?: unknown[] }) => JSON.parse(((result.content ?? [])[0] as { text: string }).text);

function backend(take: keyof typeof TAKES = "steady", state: "monitoring" | "loaded" = "monitoring") {
  return pitchTools({ xml: XML, take, state, latencyMs: 0 });
}

describe("pitchTools", () => {
  it("serves the score of the session", async () => {
    const result = await backend().callTool({ name: "get_score_for_session", arguments: { session_id: "mock-session" } });
    expect(result.structuredContent).toEqual({ session_id: "mock-session", musicxml: XML });
  });

  it("lists the session in the state the scenario names", async () => {
    const listing = text(await backend("steady", "loaded").callTool({ name: "list_sessions" }));
    expect(listing.sessions).toEqual([{ session_id: "mock-session", part: "Alto", state: "loaded", idle_seconds: 0 }]);
  });

  it("start_monitoring turns a loaded session to monitoring", async () => {
    const tools = backend("steady", "loaded");
    const started = text(await tools.callTool({ name: "start_monitoring", arguments: { session_id: "mock-session" } }));
    expect(started).toEqual({ status: "started", session_id: "mock-session" });
    expect(text(await tools.callTool({ name: "list_sessions" })).sessions[0].state).toBe("monitoring");
  });

  it("answers each get_current_position with the next step of the take, then holds the last", async () => {
    const tools = backend();
    const seen: unknown[] = [];
    for (let i = 0; i < TAKES.steady.length + 2; i++) {
      const result = await tools.callTool({ name: "get_current_position", arguments: { session_id: "mock-session" } });
      const position = result.structuredContent as { measure: number; status: string };
      seen.push([position.measure, position.status]);
    }
    expect(seen.slice(0, TAKES.steady.length)).toEqual(TAKES.steady.map((s) => [s.measure, s.status]));
    expect(seen.at(-1)).toEqual(seen.at(-2));
  });

  it("the steady take visits the bars in order and every grading state", () => {
    const measures = TAKES.steady.map((s) => s.measure);
    expect(measures).toEqual([...measures].sort((a, b) => a - b));
    expect(new Set(TAKES.steady.map((s) => s.status))).toEqual(new Set(["on_pitch", "sharp", "flat", "uncertain", "no_signal"]));
    for (const step of TAKES.steady.filter((s) => s.status === "uncertain" || s.status === "no_signal")) {
      expect(step.accuracy_cents).toBeNull();
    }
  });

  it("stop_monitoring summarizes the steps polled, in the server's JSON text", async () => {
    const tools = backend();
    for (let i = 0; i < 4; i++) await tools.callTool({ name: "get_current_position", arguments: {} });
    const stopped = text(await tools.callTool({ name: "stop_monitoring", arguments: { session_id: "mock-session" } }));
    expect(stopped).toMatchObject({ session_id: "mock-session", timed_out: false });
    expect(Object.keys(stopped.summary)).toEqual(["measures_covered", "avg_accuracy_cents", "accuracy_histogram", "highlights"]);
    expect(stopped.summary.measures_covered).toBeGreaterThan(0);
  });

  it("start_practice begins a new take on the same session, from the first step", async () => {
    const tools = backend();
    for (let i = 0; i < 3; i++) await tools.callTool({ name: "get_current_position", arguments: {} });
    const started = await tools.callTool({ name: "start_practice", arguments: { part: "Alto" } });
    expect(started.structuredContent).toMatchObject({ session_id: "mock-session", part_name: "Alto" });
    const first = await tools.callTool({ name: "get_current_position", arguments: {} });
    expect(first.structuredContent).toMatchObject({ measure: TAKES.steady[0]!.measure, status: TAKES.steady[0]!.status });
  });

  it("take=closed ends the session after a few polls: SESSION_NOT_FOUND, then a timed-out summary", async () => {
    const tools = backend("closed");
    let last = await tools.callTool({ name: "get_current_position", arguments: {} });
    for (let i = 0; i < 6; i++) last = await tools.callTool({ name: "get_current_position", arguments: {} });
    expect(last.isError).toBe(true);
    expect(text(last).error_code).toBe("SESSION_NOT_FOUND");
    expect(text(await tools.callTool({ name: "stop_monitoring", arguments: {} })).timed_out).toBe(true);
  });

  it("take=lost answers a few polls, then fails every one with a server error", async () => {
    const tools = backend("lost");
    const results = [];
    for (let i = 0; i < 8; i++) results.push(await tools.callTool({ name: "get_current_position", arguments: {} }));
    expect(results.slice(0, 3).every((r) => !r.isError)).toBe(true);
    expect(results.slice(3).every((r) => r.isError)).toBe(true);
  });

  it("delays its answers by latencyMs", async () => {
    const tools = pitchTools({ xml: XML, take: "steady", state: "monitoring", latencyMs: 40 });
    const started = performance.now();
    await tools.callTool({ name: "list_sessions" });
    expect(performance.now() - started).toBeGreaterThanOrEqual(35);
  });

  it("knows no other tool", async () => {
    await expect(backend().callTool({ name: "render_to_pdf" })).rejects.toThrow(/render_to_pdf/);
  });
});

describe("summarizeTake", () => {
  const steps: TakeStep[] = [
    { measure: 1, beat: 1, expected_note: "A3", sung_pitch_hz: 220, accuracy_cents: 4, status: "on_pitch" },
    { measure: 2, beat: 1, expected_note: "B3", sung_pitch_hz: 250, accuracy_cents: 40, status: "sharp" },
    { measure: 2, beat: 2, expected_note: "B3", sung_pitch_hz: 250, accuracy_cents: 30, status: "sharp" },
    { measure: 3, beat: 1, expected_note: "C4", sung_pitch_hz: null, accuracy_cents: null, status: "uncertain" },
  ];

  it("counts every state, averages |cents| of graded steps and names sharp or flat runs", () => {
    const summary = summarizeTake(steps);
    expect(summary.measures_covered).toBe(3);
    expect(summary.avg_accuracy_cents).toBe(25);
    expect(summary.accuracy_histogram).toEqual({ on_pitch: 1, sharp: 2, flat: 0, uncertain: 1, no_signal: 0 });
    expect(summary.highlights).toHaveLength(1);
    expect(summary.highlights[0]).toMatchObject({ direction: "sharp", measures: [2, 2], notes: 2 });
  });

  it("has a null average when nothing was graded", () => {
    expect(summarizeTake(steps.slice(3)).avg_accuracy_cents).toBeNull();
    expect(summarizeTake([]).avg_accuracy_cents).toBeNull();
  });
});

describe("composeTools", () => {
  it("asks each backend in turn and uses the first that knows the tool", async () => {
    const tools = composeTools(backend(), placeholderTools);
    expect((await tools.callTool({ name: "list_sessions" })).content).toBeDefined();
    const page = await tools.callTool({ name: "render_page_svg", arguments: { musicxml: "<score-partwise/>", page: 1, width_px: 100, zoom: 1 } });
    expect(page.structuredContent).toMatchObject({ page: 1 });
  });

  it("fails like a single backend when none knows the tool", async () => {
    await expect(composeTools(noTools, noTools).callTool({ name: "x" })).rejects.toThrow(/x/);
  });
});
