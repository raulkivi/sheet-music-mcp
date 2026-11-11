import { describe, expect, it } from "vitest";
import { checkBudget, summarise, type Budget, type Measurements } from "./budget.ts";

const budget: Budget = {
  pageBytes: 1000,
  desktopFirstPageMs: 2000,
  phoneFirstPageMs: 6000,
  peakHeapBytes: 50_000_000,
};
const within: Measurements = {
  pageBytes: 900,
  desktopFirstPageMs: 1500,
  phoneFirstPageMs: 5000,
  peakHeapBytes: 40_000_000,
};

describe("checkBudget", () => {
  it("returns no breaches when every number is within its limit", () => {
    expect(checkBudget(within, budget)).toEqual([]);
  });

  it("accepts a value exactly at its limit", () => {
    expect(checkBudget(budget, budget)).toEqual([]);
  });

  it("names the metric, the measured value and the limit of one breach", () => {
    expect(checkBudget({ ...within, phoneFirstPageMs: 6001 }, budget)).toEqual([
      { metric: "phoneFirstPageMs", measured: 6001, limit: 6000 },
    ]);
  });

  it("reports every breach, in the budget's metric order", () => {
    const over: Measurements = { pageBytes: 2000, desktopFirstPageMs: 1, phoneFirstPageMs: 1, peakHeapBytes: 99_000_000 };
    expect(checkBudget(over, budget).map((b) => b.metric)).toEqual(["pageBytes", "peakHeapBytes"]);
  });

  it("treats a missing or non-finite measurement as a breach, never as a pass", () => {
    const broken = { ...within, desktopFirstPageMs: Number.NaN };
    expect(checkBudget(broken, budget)).toEqual([{ metric: "desktopFirstPageMs", measured: Number.NaN, limit: 2000 }]);
  });

  it("refuses a budget with a non-positive limit", () => {
    expect(() => checkBudget(within, { ...budget, pageBytes: 0 })).toThrow(/pageBytes/);
  });
});

describe("summarise", () => {
  const report = {
    size: { rawBytes: 1234, gzipBytes: 500 },
    results: [
      { profile: "desktop", hostToFirstPageMs: 800, peakJsHeapBytes: 30_000_000 },
      { profile: "phone, 4x CPU throttle", hostToFirstPageMs: 2500, peakJsHeapBytes: 35_000_000 },
    ],
  };

  it("maps a measure.mjs report to the budget's metrics, taking the larger heap", () => {
    expect(summarise(report)).toEqual({
      pageBytes: 1234,
      desktopFirstPageMs: 800,
      phoneFirstPageMs: 2500,
      peakHeapBytes: 35_000_000,
    });
  });

  it("leaves a metric NaN when its profile is absent, so the check flags it", () => {
    const m = summarise({ ...report, results: [report.results[0]!] });
    expect(m.phoneFirstPageMs).toBeNaN();
  });
});
