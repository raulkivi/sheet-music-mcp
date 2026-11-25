import { describe, expect, it } from "vitest";
import { FakeBridge } from "@sheet-music-mcp/ui-kit/host/FakeBridge";
import type { BarSummary } from "./history.ts";
import type { SummaryReport } from "./messages.ts";
import { BridgeTips, stopContext, tipsMessage } from "./tips.ts";

const report = (overrides: Partial<SummaryReport> = {}): SummaryReport => ({
  measuresCovered: 4,
  avgCents: 12.4,
  histogram: { on_pitch: 30, sharp: 8, flat: 5, uncertain: 3, no_signal: 2 },
  highlights: [],
  timedOut: false,
  ...overrides,
});

const barsFor = (cents: (number | null)[]): BarSummary[] =>
  cents.map((avgCents, index) => ({ measure: index + 1, status: "on_pitch", avgCents, samples: 2 }));

/** The worked example from the spec: bars 1..6 with avgCents 4, 33, -41, null, 27, -30. */
const EXAMPLE = barsFor([4, 33, -41, null, 27, -30]);
const HIGHLIGHTS = ["sharp on G3 in m.3 (+33 cents avg)", "flat on C4 in m.5"];

describe("tipsMessage", () => {
  it("is the worked example word for word", () => {
    expect(tipsMessage(report({ highlights: HIGHLIGHTS }), { partName: "Alto", bars: EXAMPLE })).toBe(
      "My Practice Coach summary for part Alto. Bars covered: 4. Average deviation: 12 cents. " +
        "Notes: 30 on pitch, 8 sharp, 5 flat, 3 not sure, 2 no signal. " +
        "Furthest from pitch: bars 2, 3, 6. " +
        "Please give me short tips for improving my intonation.",
    );
  });

  it("drops the part when none is known", () => {
    expect(tipsMessage(report(), { bars: [] }).startsWith("My Practice Coach summary. Bars covered: 4.")).toBe(true);
  });

  it("rounds the average and says nothing was graded when there is no average", () => {
    expect(tipsMessage(report({ avgCents: -12.6 }), { bars: [] })).toContain("Average deviation: -13 cents.");
    const graded = tipsMessage(report({ avgCents: null, measuresCovered: 3 }), { bars: [] });
    expect(graded).toContain("Bars covered: 3. No notes were graded. Notes:");
    expect(graded).not.toContain("Average deviation");
  });

  it("mentions the idle timeout before the far bars", () => {
    expect(tipsMessage(report({ timedOut: true }), { partName: "Soprano", bars: barsFor([null, 40]) })).toBe(
      "My Practice Coach summary for part Soprano. Bars covered: 4. Average deviation: 12 cents. " +
        "Notes: 30 on pitch, 8 sharp, 5 flat, 3 not sure, 2 no signal. " +
        "The session closed after sitting idle. Furthest from pitch: bar 2. " +
        "Please give me short tips for improving my intonation.",
    );
  });

  it("names one bar as a bar and keeps the three furthest in bar order", () => {
    expect(tipsMessage(report(), { bars: barsFor([null, -26]) })).toContain("Furthest from pitch: bar 2.");
    expect(tipsMessage(report(), { bars: barsFor([null, -30, null, null, 30, null, null, null, 31, 1]) })).toContain(
      "Furthest from pitch: bars 2, 5, 9.",
    );
    expect(tipsMessage(report(), { bars: barsFor([24, -24.9]) })).not.toContain("Furthest from pitch");
  });

  it("leaves out the far bars when nothing is far", () => {
    expect(tipsMessage(report(), { bars: barsFor([5, null, -20]) })).toBe(
      "My Practice Coach summary. Bars covered: 4. Average deviation: 12 cents. " +
        "Notes: 30 on pitch, 8 sharp, 5 flat, 3 not sure, 2 no signal. " +
        "Please give me short tips for improving my intonation.",
    );
  });

  it("uses 0 for a missing, odd or nonsense histogram value and ignores other keys", () => {
    const histogram = { on_pitch: 3.7, sharp: -2, flat: Number.NaN, uncertain: Number.POSITIVE_INFINITY, bogus: 9 } as SummaryReport["histogram"];
    expect(tipsMessage(report({ histogram }), { bars: [] })).toContain("Notes: 3 on pitch, 0 sharp, 0 flat, 0 not sure, 0 no signal.");
    const notNumbers = { on_pitch: "seven", sharp: 5 } as unknown as SummaryReport["histogram"];
    expect(tipsMessage(report({ histogram: notNumbers }), { bars: [] })).toContain("Notes: 0 on pitch, 5 sharp, 0 flat, 0 not sure, 0 no signal.");
  });

  it("never carries the server's highlights or any other report text", () => {
    const message = tipsMessage(report({ highlights: HIGHLIGHTS }), { partName: "Alto", bars: EXAMPLE });
    for (const highlight of HIGHLIGHTS) expect(message).not.toContain(highlight);
    expect(message).not.toMatch(/G3|C4|lyric|m\.3/);
  });
});

describe("the part name", () => {
  const partIn = (name: string): string => {
    const message = tipsMessage(report(), { partName: name, bars: [] });
    const match = /^My Practice Coach summary(?: for part (.*?))?\./.exec(message);
    return match![1] ?? "";
  };

  it("strips tags and characters that are not letters, digits, spaces, hyphens, periods or apostrophes", () => {
    expect(partIn("Alto <i>x</i>")).toBe("Alto x");
    expect(partIn("Soprano <script>alert(1)</script>")).toBe("Soprano alert1");
    expect(partIn("Basses & \"Tenors\" (3/4)")).toBe("Basses Tenors 34");
    expect(partIn("Alté-Basse's 2nd")).toBe("Alté-Basse's 2nd");
    expect(partIn("Alté–Basse’s")).toBe("AltéBasses");
  });

  it("collapses spaces, trims, and cuts to 40 characters", () => {
    expect(partIn("  Alto    \t  II  ")).toBe("Alto II");
    expect(partIn("A".repeat(45))).toBe("A".repeat(40));
    expect(partIn("S".repeat(39) + " T")).toBe("S".repeat(39));
  });

  it("treats a name left empty after cleaning as absent", () => {
    expect(tipsMessage(report(), { partName: "<<>>", bars: [] }).startsWith("My Practice Coach summary.")).toBe(true);
    expect(tipsMessage(report(), { partName: "   \t ", bars: [] }).startsWith("My Practice Coach summary.")).toBe(true);
    expect(tipsMessage(report(), { partName: "!!!", bars: [] }).startsWith("My Practice Coach summary.")).toBe(true);
  });
});

describe("stopContext", () => {
  it("is the worked example word for word, with no ask", () => {
    expect(stopContext(report({ highlights: HIGHLIGHTS }), { partName: "Alto", bars: EXAMPLE })).toBe(
      "Practice Coach: the singer stopped listening for part Alto. Bars covered: 4. Average deviation: 12 cents. " +
        "Notes: 30 on pitch, 8 sharp, 5 flat, 3 not sure, 2 no signal. " +
        "Furthest from pitch: bars 2, 3, 6.",
    );
  });

  it("says which part was stopped, or none, and shares the far bars and the timeout", () => {
    expect(stopContext(report(), { bars: [] }).startsWith("Practice Coach: the singer stopped listening. Bars covered: 4.")).toBe(true);
    expect(stopContext(report({ timedOut: true }), { partName: "Bass", bars: barsFor([null, -40]) })).toBe(
      "Practice Coach: the singer stopped listening for part Bass. Bars covered: 4. Average deviation: 12 cents. " +
        "Notes: 30 on pitch, 8 sharp, 5 flat, 3 not sure, 2 no signal. " +
        "The session closed after sitting idle. Furthest from pitch: bar 2.",
    );
  });

  it("never carries the server's highlights", () => {
    const text = stopContext(report({ highlights: HIGHLIGHTS }), { bars: EXAMPLE });
    for (const highlight of HIGHLIGHTS) expect(text).not.toContain(highlight);
  });
});

describe("BridgeTips", () => {
  const textOf = (bridge: FakeBridge, method: string): string =>
    (bridge.calls.find((call) => call.method === method)?.params as { text: string }).text;

  it("asks with ui/message carrying the tips message", async () => {
    const bridge = new FakeBridge({});
    const tips = new BridgeTips(bridge);
    await tips.ask(report(), { partName: "Alto", bars: EXAMPLE });
    expect(bridge.calls).toEqual([{ method: "ui/message", params: { text: tipsMessage(report(), { partName: "Alto", bars: EXAMPLE }) } }]);
  });

  it("reports a stop with ui/update-model-context carrying the stop context", async () => {
    const bridge = new FakeBridge({});
    const tips = new BridgeTips(bridge);
    await tips.stopped!(report({ timedOut: true }), { bars: barsFor([-50, null]) });
    expect(bridge.calls).toEqual([
      { method: "ui/update-model-context", params: { text: stopContext(report({ timedOut: true }), { bars: barsFor([-50, null]) }) } },
    ]);
  });

  it("keeps the two channels separate when both are used", async () => {
    const bridge = new FakeBridge({});
    const tips = new BridgeTips(bridge);
    await tips.stopped!(report(), { bars: [] });
    await tips.ask(report(), { bars: [] });
    expect(textOf(bridge, "ui/message")).toContain("Please give me short tips");
    expect(textOf(bridge, "ui/update-model-context")).not.toContain("Please give me short tips");
    expect(bridge.calls.map((call) => call.method)).toEqual(["ui/update-model-context", "ui/message"]);
  });
});
