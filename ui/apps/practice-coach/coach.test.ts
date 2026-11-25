import { describe, expect, it } from "vitest";
import { FakeBridge, type FakeScript } from "@sheet-music-mcp/ui-kit/host/FakeBridge";
import type { ToolResult } from "@sheet-music-mcp/ui-kit/host/HostBridge";
import {
  PracticeCoach,
  type CoachScore,
  type CoachUi,
  type Mode,
  type Poller,
  type Reading,
  type ReportView,
  type TipsContext,
  type TipsHandler,
} from "./coach.ts";
import type { BarSummary } from "./history.ts";
import { NOTICES, type SessionInfo, type SummaryReport } from "./messages.ts";

const json = (data: unknown): ToolResult => ({ content: [{ type: "text", text: JSON.stringify(data) }] });
const failure = (code: string): ToolResult => ({ isError: true, content: [{ type: "text", text: JSON.stringify({ error: "x", error_code: code }) }] });

const SESSION = { session_id: "s1", part_id: "P2", part_name: "Alto", measure_count: 4, duration_seconds: 16, tempo_bpm: 60 };
const position = (measure: number, beat: number, status: string, cents: number | null) => ({
  structuredContent: { session_id: "s1", measure, beat, expected_note: "A3", sung_pitch_hz: cents === null ? null : 220, accuracy_cents: cents, status },
});
const SUMMARY = {
  session_id: "s1",
  timed_out: false,
  summary: { measures_covered: 2, avg_accuracy_cents: 12, accuracy_histogram: { on_pitch: 3, sharp: 1, flat: 0, uncertain: 1, no_signal: 0 }, highlights: [] },
};

class FakeUi implements CoachUi {
  modes: Mode[] = [];
  notices: (string | undefined)[] = [];
  readings: Reading[] = [];
  histories: BarSummary[][] = [];
  sessions: (SessionInfo | undefined)[] = [];
  reports: ReportView[] = [];
  themes: unknown[] = [];
  applyHostContext(context: unknown) { this.themes.push(context); }
  showMode(mode: Mode) { this.modes.push(mode); }
  showNotice(text: string | undefined) { this.notices.push(text); }
  showSession(session: SessionInfo | undefined) { this.sessions.push(session); }
  showReading(reading: Reading) { this.readings.push(reading); }
  clearReading() { this.readings.push({ cleared: true } as unknown as Reading); }
  showHistory(bars: BarSummary[]) { this.histories.push(bars); }
  showReport(report: ReportView) { this.reports.push(report); }
  get mode() { return this.modes.at(-1); }
  get notice() { return this.notices.at(-1); }
}

class FakeScore implements CoachScore {
  loaded: string[] = [];
  cursors: [number, number][] = [];
  hidden = 0;
  async load(xml: string) { this.loaded.push(xml); }
  showCursor(measure: number, beat: number) { this.cursors.push([measure, beat]); }
  hideCursor() { this.hidden++; }
}

class FakePoller implements Poller {
  running = false;
  constructor(readonly request: () => Promise<void>) {}
  start() { this.running = true; }
  stop() { this.running = false; }
  onVisibilityChange() {}
}

interface Harness {
  coach: PracticeCoach;
  bridge: FakeBridge;
  ui: FakeUi;
  score: FakeScore;
  poller: () => FakePoller;
}

async function open(script: FakeScript & { tips?: TipsHandler }, run = true): Promise<Harness> {
  const bridge = new FakeBridge(script);
  const ui = new FakeUi();
  const score = new FakeScore();
  let poller: FakePoller | undefined;
  const coach = new PracticeCoach(bridge, ui, score, (request) => (poller = new FakePoller(request)), script.tips ? { tips: script.tips } : {});
  if (run) {
    await coach.start();
    await bridge.settled();
    await coach.idle();
  }
  return { coach, bridge, ui, score, poller: () => poller! };
}

const practiceScript = (overrides: Record<string, ToolResult | ((a: Record<string, unknown>) => ToolResult)> = {}): FakeScript => ({
  toolInput: { arguments: { musicxml_path: "/s.mxl", part: "Alto" } },
  toolResult: { structuredContent: SESSION },
  toolAnswers: {
    get_score_for_session: { structuredContent: { session_id: "s1", musicxml: "<score-partwise/>" } },
    list_sessions: json({ sessions: [{ session_id: "s1", part: "Alto", state: "monitoring", idle_seconds: 0 }] }),
    get_current_position: position(1, 1, "on_pitch", 3),
    stop_monitoring: json(SUMMARY),
    start_monitoring: json({ status: "started", session_id: "s1" }),
    start_practice: { structuredContent: SESSION },
    ...overrides,
  },
});

describe("opening", () => {
  it("opens a started practice: shows the session, draws the score, starts polling", async () => {
    const h = await open(practiceScript());
    expect(h.ui.sessions.at(-1)).toMatchObject({ sessionId: "s1", partName: "Alto" });
    expect(h.score.loaded).toEqual(["<score-partwise/>"]);
    expect(h.ui.mode).toBe("listening");
    expect(h.poller().running).toBe(true);
    expect(h.bridge.calls.map((c) => (c.params as { name?: string }).name).filter(Boolean)).toEqual(["get_score_for_session", "list_sessions"]);
  });

  it("is ready, not listening, for a loaded session (microphone still closed)", async () => {
    const h = await open(practiceScript({ list_sessions: json({ sessions: [{ session_id: "s1", state: "loaded" }] }) }));
    expect(h.ui.mode).toBe("ready");
    expect(h.poller()).toBeUndefined();
  });

  it("is ready when list_sessions fails (a session it cannot see is not assumed to listen)", async () => {
    const h = await open(practiceScript({ list_sessions: failure("PROCESSING_FAILED") }));
    expect(h.ui.mode).toBe("ready");
  });

  it("shows the empty state when the call carried no session", async () => {
    const h = await open({ toolInput: { arguments: {} }, toolResult: { content: [] } });
    expect(h.ui.mode).toBe("empty");
    expect(h.ui.notice).toMatch(/No practice session/);
    expect(h.bridge.calls).toEqual([]);
  });

  it("shows the error state with the server's code when start_practice failed", async () => {
    const h = await open({ toolInput: { arguments: { part: "Alto" } }, toolResult: failure("PROCESSING_FAILED") });
    expect(h.ui.mode).toBe("empty");
    expect(h.ui.notice).toMatch(/PROCESSING_FAILED/);
  });

  it("still gives pitch feedback when the score cannot be fetched", async () => {
    const h = await open(practiceScript({ get_score_for_session: failure("SESSION_NOT_FOUND") }));
    expect(h.ui.mode).toBe("listening");
    expect(h.ui.notices).toContain("The score could not be shown. Pitch feedback still works.");
  });

  it("applies the host theme", async () => {
    const h = await open({ ...practiceScript(), context: { theme: "dark" } });
    expect(h.ui.themes[0]).toMatchObject({ theme: "dark" });
  });
});

describe("polling a take", () => {
  it("polls get_current_position, shows each reading and moves the cursor", async () => {
    const answers = [position(1, 1, "on_pitch", 3), position(1, 2, "sharp", 32), position(2, 1, "uncertain", null)];
    let i = 0;
    const h = await open(practiceScript({ get_current_position: () => answers[i++] as ToolResult }));
    for (let n = 0; n < 3; n++) await h.poller().request();
    expect(h.ui.readings.map((r) => [r.status.label, r.measure, r.beat])).toEqual([
      ["On pitch", 1, 1],
      ["Sharp", 1, 2],
      ["Not sure", 2, 1],
    ]);
    expect(h.score.cursors).toEqual([[1, 1], [1, 2], [2, 1]]);
    expect(h.bridge.calls.filter((c) => (c.params as { name?: string }).name === "get_current_position")[0]?.params).toEqual({
      name: "get_current_position",
      arguments: { session_id: "s1" },
    });
  });

  it("gives the meter a needle for graded frames and none for uncertain ones", async () => {
    const answers = [position(1, 1, "flat", -20), position(1, 1, "uncertain", null)];
    let i = 0;
    const h = await open(practiceScript({ get_current_position: () => answers[i++] as ToolResult }));
    await h.poller().request();
    await h.poller().request();
    expect(h.ui.readings.map((r) => r.needle)).toEqual([30, null]);
    expect(h.ui.readings[0]?.text).toBe("-20 cents, flat");
  });

  it("keeps a history and shows the last bars", async () => {
    const answers = [position(1, 1, "on_pitch", 0), position(2, 1, "sharp", 40)];
    let i = 0;
    const h = await open(practiceScript({ get_current_position: () => answers[i++] as ToolResult }));
    await h.poller().request();
    await h.poller().request();
    expect(h.ui.histories.at(-1)?.map((b) => [b.measure, b.status])).toEqual([[1, "on_pitch"], [2, "sharp"]]);
  });

  it("when the session closed (idle timeout), stops polling and shows the summary kept", async () => {
    const h = await open(practiceScript({ get_current_position: failure("SESSION_NOT_FOUND"), stop_monitoring: json({ ...SUMMARY, timed_out: true }) }));
    await h.poller().request();
    await h.coach.idle();
    expect(h.poller().running).toBe(false);
    expect(h.ui.mode).toBe("report");
    expect(h.ui.reports.at(-1)?.report.timedOut).toBe(true);
    expect(h.ui.notices).toContain("This practice session has closed. Showing the summary kept when it did.");
  });

  it("tells the singer after repeated failures and clears the notice when the server answers again", async () => {
    let fail = true;
    const h = await open(practiceScript({ get_current_position: () => (fail ? failure("PROCESSING_FAILED") : position(1, 1, "on_pitch", 0)) }));
    for (let n = 0; n < 3; n++) await h.poller().request();
    expect(h.ui.notice).toBe("Lost contact with the server. Still trying.");
    fail = false;
    await h.poller().request();
    expect(h.ui.notice).toBeUndefined();
  });

  it("treats a thrown call (host gone) as a failure, not a crash", async () => {
    const h = await open(practiceScript());
    h.bridge.callTool = async () => {
      throw new Error("gone");
    };
    for (let n = 0; n < 3; n++) await h.poller().request();
    expect(h.ui.notice).toBe("Lost contact with the server. Still trying.");
  });
});

describe("Start and Stop", () => {
  it("Stop calls stop_monitoring and shows the report from its summary and the history", async () => {
    const h = await open(practiceScript());
    await h.poller().request();
    await h.coach.stop();
    expect(h.poller().running).toBe(false);
    expect(h.ui.modes).toContain("stopping");
    expect(h.ui.mode).toBe("report");
    const view = h.ui.reports.at(-1)!;
    expect(view.report).toMatchObject({ measuresCovered: 2, avgCents: 12 });
    expect(view.bars.map((b) => b.measure)).toEqual([1]);
    expect(view.canPracticeAgain).toBe(true);
    expect(view.canAskForTips).toBe(false);
    expect(h.score.hidden).toBeGreaterThan(0);
  });

  it("a failed stop is reported, not swallowed", async () => {
    const h = await open(practiceScript({ stop_monitoring: failure("SESSION_NOT_FOUND") }));
    await h.coach.stop();
    expect(h.ui.notice).toMatch(/SESSION_NOT_FOUND/);
    expect(h.ui.mode).toBe("empty");
  });

  it("Start opens the microphone of a loaded session and begins polling", async () => {
    const h = await open(practiceScript({ list_sessions: json({ sessions: [{ session_id: "s1", state: "loaded" }] }) }));
    await h.coach.startListening();
    expect(h.bridge.calls.some((c) => (c.params as { name?: string }).name === "start_monitoring")).toBe(true);
    expect(h.ui.mode).toBe("listening");
    expect(h.poller().running).toBe(true);
  });

  it("a failed Start says so and stays ready", async () => {
    const h = await open(practiceScript({ list_sessions: json({ sessions: [] }), start_monitoring: failure("PROCESSING_FAILED") }));
    await h.coach.startListening();
    expect(h.ui.mode).toBe("ready");
    expect(h.ui.notice).toMatch(/PROCESSING_FAILED/);
  });

  it("Practice again re-runs start_practice with the original arguments and opens the new session", async () => {
    const h = await open(practiceScript());
    await h.coach.stop();
    await h.coach.practiceAgain();
    const call = h.bridge.calls.find((c) => (c.params as { name?: string }).name === "start_practice");
    expect(call?.params).toEqual({ name: "start_practice", arguments: { musicxml_path: "/s.mxl", part: "Alto" } });
    expect(h.ui.mode).toBe("listening");
    expect(h.poller().running).toBe(true);
  });

  it("starting again clears the earlier take's history", async () => {
    const h = await open(practiceScript());
    await h.poller().request();
    await h.coach.stop();
    await h.coach.practiceAgain();
    await h.coach.stop();
    expect(h.ui.reports.at(-1)?.bars).toEqual([]);
  });

  it("offers no Practice again when the opening call was not start_practice", async () => {
    const h = await open({ ...practiceScript(), toolInput: { arguments: { session_id: "s1" } }, toolResult: json({ status: "started", session_id: "s1" }) });
    await h.coach.stop();
    expect(h.ui.reports.at(-1)?.canPracticeAgain).toBe(false);
  });
});

describe("the tips seam (T1.5)", () => {
  it("shows no tips button without a handler, and offers one when a handler is given", async () => {
    const asked: string[] = [];
    const tips: TipsHandler = { ask: async (report) => void asked.push(`avg ${report.avgCents}`) };
    const h = await open({ ...practiceScript(), tips });
    await h.coach.stop();
    expect(h.ui.reports.at(-1)?.canAskForTips).toBe(true);
    await h.coach.askForTips();
    expect(asked).toEqual(["avg 12"]);
  });

  it("asking for tips with no handler does nothing", async () => {
    const h = await open(practiceScript());
    await h.coach.stop();
    await h.coach.askForTips();
    expect(h.bridge.calls.some((c) => c.method === "ui/message")).toBe(false);
  });
});

describe("asking Claude for tips (T1.5)", () => {
  it("tells the handler once when the singer stops, with the part name and the per-bar history", async () => {
    const seen: { report: SummaryReport; context: TipsContext }[] = [];
    const tips: TipsHandler = {
      ask: async () => {},
      stopped: async (report, context) => void seen.push({ report, context }),
    };
    const h = await open({ ...practiceScript(), tips });
    await h.poller().request();
    await h.coach.stop();
    expect(seen).toHaveLength(1);
    expect(seen[0]!.report).toMatchObject({ measuresCovered: 2, avgCents: 12 });
    expect(seen[0]!.context.partName).toBe("Alto");
    expect(seen[0]!.context.bars.map((b) => b.measure)).toEqual([1]);
  });

  it("carries no part name when the session had none", async () => {
    const seen: TipsContext[] = [];
    const tips: TipsHandler = { ask: async () => {}, stopped: async (_r, context) => void seen.push(context) };
    const h = await open({
      ...practiceScript(),
      toolResult: { structuredContent: { session_id: "s1", measure_count: 4 } },
      tips,
    });
    await h.coach.stop();
    expect(seen[0]?.partName).toBeUndefined();
  });

  it("does not tell the handler about a stop that produced no summary", async () => {
    let stopped = 0;
    const tips: TipsHandler = { ask: async () => {}, stopped: async () => void stopped++ };
    const h = await open({ ...practiceScript({ stop_monitoring: failure("SESSION_NOT_FOUND") }), tips });
    await h.coach.stop();
    expect(stopped).toBe(0);
  });

  it("asks once per press, with the report and the stop-time context", async () => {
    const asked: [number | null, string | undefined][] = [];
    const tips: TipsHandler = { ask: async (report, context) => void asked.push([report.avgCents, context.partName]) };
    const h = await open({ ...practiceScript(), tips });
    await h.coach.stop();
    await h.coach.askForTips();
    await h.coach.askForTips();
    expect(asked).toEqual([[12, "Alto"], [12, "Alto"]]);
  });

  it("sends nothing while an ask is still in flight, and lets a later press through", async () => {
    let releaseGate = () => {};
    const gate = new Promise<void>((resolve) => {
      releaseGate = () => resolve();
    });
    let asked = 0;
    const tips: TipsHandler = {
      ask: async () => {
        asked++;
        await gate;
      },
    };
    const h = await open({ ...practiceScript(), tips });
    await h.coach.stop();
    const inFlight = h.coach.askForTips();
    await h.coach.askForTips();
    expect(asked).toBe(1);
    releaseGate();
    await inFlight;
    expect(asked).toBe(1);
    await h.coach.askForTips();
    expect(asked).toBe(2);
  });

  it("says the tips were asked once the send succeeded", async () => {
    const h = await open({ ...practiceScript(), tips: { ask: async () => {} } });
    await h.coach.stop();
    await h.coach.askForTips();
    expect(h.ui.notice).toBe(NOTICES.tipsSent);
  });

  it("says the ask failed when the send throws, and lets a later press try again", async () => {
    let asked = 0;
    const tips: TipsHandler = {
      ask: async () => {
        asked++;
        throw new Error("the host refused the message");
      },
    };
    const h = await open({ ...practiceScript(), tips });
    await h.coach.stop();
    await h.coach.askForTips();
    expect(h.ui.notice).toBe(NOTICES.tipsFailed);
    await h.coach.askForTips();
    expect(asked).toBe(2);
  });

  it("does not ask when the take was re-opened, so a stale report cannot be sent", async () => {
    const asked: string[] = [];
    const tips: TipsHandler = { ask: async (report) => void asked.push(String(report.measuresCovered)) };
    const h = await open({ ...practiceScript(), tips });
    await h.coach.stop();
    await h.coach.practiceAgain();
    await h.coach.askForTips();
    expect(asked).toEqual([]);
  });

  it("shows the report when the handler's stopped() throws", async () => {
    const tips: TipsHandler = {
      ask: async () => {},
      stopped: () => {
        throw new Error("boom");
      },
    };
    const h = await open({ ...practiceScript(), tips });
    await h.coach.stop();
    expect(h.ui.reports).toHaveLength(1);
    expect(h.ui.mode).toBe("report");
  });

  it("shows the report when the handler's stopped() rejects", async () => {
    const tips: TipsHandler = { ask: async () => {}, stopped: async () => Promise.reject(new Error("host gone")) };
    const h = await open({ ...practiceScript(), tips });
    await h.coach.stop();
    expect(h.ui.reports).toHaveLength(1);
    expect(h.ui.mode).toBe("report");
  });
});

describe("visibility", () => {
  it("passes visibility changes to the poller", async () => {
    const h = await open(practiceScript());
    let notified = 0;
    h.poller().onVisibilityChange = () => void notified++;
    h.coach.onVisibilityChange();
    expect(notified).toBe(1);
  });
});
