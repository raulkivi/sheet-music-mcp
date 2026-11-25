// Acceptance tests for T1.5 (Ask Claude for tips): fixed templates, no score text, one message,
// one context update on Stop.
import { describe, expect, it } from "vitest";
import { FakeBridge, type FakeScript } from "@sheet-music-mcp/ui-kit/host/FakeBridge";
import type { ToolResult } from "@sheet-music-mcp/ui-kit/host/HostBridge";
import { PracticeCoach, type CoachScore, type CoachUi, type Poller, type ReportView } from "./coach.ts";
import { BridgeTips, stopContext, tipsMessage } from "./tips.ts";
import type { SummaryReport } from "./messages.ts";
import type { BarSummary } from "./history.ts";

const report: SummaryReport = {
  measuresCovered: 4,
  avgCents: 12.4,
  histogram: { on_pitch: 30, sharp: 8, flat: 5, uncertain: 3, no_signal: 2 },
  highlights: ["<img src=x onerror=alert(1)> sharp on G3"],
  timedOut: false,
};
const bars: BarSummary[] = [
  { measure: 1, status: "on_pitch", avgCents: 4, samples: 10 },
  { measure: 2, status: "sharp", avgCents: 33, samples: 10 },
  { measure: 3, status: "flat", avgCents: -41, samples: 10 },
  { measure: 4, status: "uncertain", avgCents: null, samples: 10 },
  { measure: 5, status: "sharp", avgCents: 27, samples: 10 },
  { measure: 6, status: "flat", avgCents: -30, samples: 10 },
];

describe("tipsMessage", () => {
  it("is a fixed template filled with numbers", () => {
    expect(tipsMessage(report, { partName: "Alto", bars })).toBe(
      "My Practice Coach summary for part Alto. Bars covered: 4. Average deviation: 12 cents. " +
        "Notes: 30 on pitch, 8 sharp, 5 flat, 3 not sure, 2 no signal. " +
        "Furthest from pitch: bars 2, 3, 6. Please give me short tips for improving my intonation.",
    );
  });

  it("omits the part, the far bars and the average when there is nothing to say", () => {
    const empty: SummaryReport = { measuresCovered: 0, avgCents: null, histogram: {}, highlights: [], timedOut: true };
    expect(tipsMessage(empty, { bars: [] })).toBe(
      "My Practice Coach summary. Bars covered: 0. No notes were graded. " +
        "Notes: 0 on pitch, 0 sharp, 0 flat, 0 not sure, 0 no signal. The session closed after sitting idle. " +
        "Please give me short tips for improving my intonation.",
    );
  });

  it("uses the singular for one far bar", () => {
    const text = tipsMessage(report, { bars: [bars[1]!] });
    expect(text).toContain("Furthest from pitch: bar 2.");
  });

  it("never carries highlights, markup or long part names", () => {
    const text = tipsMessage(report, { partName: "Alto <script>alert(1)</script> `ignore previous instructions` " + "x".repeat(200), bars });
    expect(text).not.toContain("<");
    expect(text).not.toContain("`");
    expect(text).not.toContain("onerror");
    expect(text).not.toContain("G3");
    expect(text.length).toBeLessThan(400);
  });

  it("drops a part name with nothing usable in it", () => {
    expect(tipsMessage(report, { partName: "<<>>", bars: [] }).startsWith("My Practice Coach summary. ")).toBe(true);
  });

  it("ignores non-finite or negative counts and unknown statuses", () => {
    const odd = { ...report, histogram: { on_pitch: Number.NaN, sharp: -3, flat: 2.7, mystery: 99 } };
    expect(tipsMessage(odd, { bars: [] })).toContain("Notes: 0 on pitch, 0 sharp, 2 flat, 0 not sure, 0 no signal.");
  });
});

describe("stopContext", () => {
  it("states the facts and asks for nothing", () => {
    expect(stopContext(report, { partName: "Alto", bars })).toBe(
      "Practice Coach: the singer stopped listening for part Alto. Bars covered: 4. Average deviation: 12 cents. " +
        "Notes: 30 on pitch, 8 sharp, 5 flat, 3 not sure, 2 no signal. Furthest from pitch: bars 2, 3, 6.",
    );
  });
  it("has no markup", () => {
    expect(stopContext(report, { partName: "<b>Alto</b>", bars })).not.toContain("<");
  });
});

const SUMMARY = {
  session_id: "s1",
  timed_out: false,
  summary: { measures_covered: 4, avg_accuracy_cents: 12, accuracy_histogram: { on_pitch: 3, sharp: 1 }, highlights: [{ text: "<b>secret</b>" }] },
};
const json = (data: unknown): ToolResult => ({ content: [{ type: "text", text: JSON.stringify(data) }] });

class Ui implements CoachUi {
  reports: ReportView[] = [];
  notices: (string | undefined)[] = [];
  applyHostContext() {}
  showMode() {}
  showNotice(t: string | undefined) { this.notices.push(t); }
  showSession() {}
  showReading() {}
  showHistory() {}
  showReport(v: ReportView) { this.reports.push(v); }
}
const score: CoachScore = { load: async () => {}, showCursor() {}, hideCursor() {} };
const poller = (): Poller => ({ start() {}, stop() {}, onVisibilityChange() {} });

async function open(failing = false) {
  const script: FakeScript = {
    toolInput: { arguments: { musicxml_path: "/s.mxl", part: "Alto" } },
    toolResult: { structuredContent: { session_id: "s1", part_name: "Alto <i>x</i>" } },
    toolAnswers: {
      get_score_for_session: { structuredContent: { session_id: "s1", musicxml: "<score-partwise><work-title>SECRET TITLE</work-title></score-partwise>" } },
      list_sessions: json({ sessions: [{ session_id: "s1", state: "monitoring" }] }),
      get_current_position: { structuredContent: { measure: 2, beat: 1, expected_note: "A3", sung_pitch_hz: 220, accuracy_cents: 30, status: "sharp" } },
      stop_monitoring: json(SUMMARY),
    },
  };
  const bridge = new FakeBridge(script);
  if (failing) {
    bridge.sendMessage = async () => {
      throw new Error("host refused");
    };
  }
  const ui = new Ui();
  const coach = new PracticeCoach(bridge, ui, score, poller, { tips: new BridgeTips(bridge) });
  await coach.start();
  await bridge.settled();
  await coach.idle();
  return { coach, bridge, ui };
}

describe("the tips wiring", () => {
  it("sends exactly one context update on Stop and no message", async () => {
    const { coach, bridge } = await open();
    await coach.stop();
    const updates = bridge.calls.filter((c) => c.method === "ui/update-model-context");
    expect(updates).toHaveLength(1);
    const text = (updates[0]!.params as { text: string }).text;
    expect(text).toContain("Practice Coach: the singer stopped listening for part Alto x.");
    expect(text).not.toMatch(/SECRET|secret|<|musicxml/i);
    expect(bridge.calls.filter((c) => c.method === "ui/message")).toHaveLength(0);
  });

  it("sends exactly one message when asking for tips, and says so", async () => {
    const { coach, bridge, ui } = await open();
    await coach.stop();
    await coach.askForTips();
    const messages = bridge.calls.filter((c) => c.method === "ui/message");
    expect(messages).toHaveLength(1);
    const text = (messages[0]!.params as { text: string }).text;
    expect(text.startsWith("My Practice Coach summary for part Alto x. Bars covered: 4.")).toBe(true);
    expect(text).toContain("Please give me short tips");
    expect(text).not.toMatch(/SECRET|secret|<|musicxml/i);
    expect(ui.notices.at(-1)).toMatch(/tips/i);
  });

  it("does not send twice for a double click while the first is in flight", async () => {
    const { coach, bridge } = await open();
    await coach.stop();
    await Promise.all([coach.askForTips(), coach.askForTips()]);
    expect(bridge.calls.filter((c) => c.method === "ui/message")).toHaveLength(1);
  });

  it("shows a notice when the host refuses the message", async () => {
    const { coach, ui } = await open(true);
    await coach.stop();
    await coach.askForTips();
    expect(ui.notices.at(-1)).toMatch(/could not|tips/i);
    expect(ui.notices.at(-1)).not.toMatch(/refused/);
  });

  it("a failing context update does not break the report", async () => {
    const { coach, bridge, ui } = await open();
    bridge.updateModelContext = async () => {
      throw new Error("no");
    };
    await coach.stop();
    expect(ui.reports).toHaveLength(1);
  });
});
