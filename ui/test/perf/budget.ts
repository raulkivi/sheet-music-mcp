// U7: pure budget comparison. No I/O: measuring is scripts/measure.mjs, the limits are
// perf-budget.json, and scripts/perf.mjs joins the three.

export interface Measurements {
  /** Raw size of dist/score-viewer.html. */
  pageBytes: number;
  /** Host navigation to first rendered page, desktop profile. */
  desktopFirstPageMs: number;
  /** The same on the phone profile (4x CPU throttle). */
  phoneFirstPageMs: number;
  /** Largest JS heap seen in any profile. */
  peakHeapBytes: number;
}

export type Budget = Measurements;
export type Metric = keyof Measurements;

export interface Breach {
  metric: Metric;
  measured: number;
  limit: number;
}

const METRICS: readonly Metric[] = ["pageBytes", "desktopFirstPageMs", "phoneFirstPageMs", "peakHeapBytes"];

/** Breaches in metric order. A missing or non-finite measurement counts as a breach. */
export function checkBudget(measured: Measurements, budget: Budget): Breach[] {
  const breaches: Breach[] = [];
  for (const metric of METRICS) {
    const limit = budget[metric];
    if (!(limit > 0)) throw new Error(`budget limit for ${metric} must be a positive number, got ${limit}`);
    const value = measured[metric];
    if (!Number.isFinite(value) || value > limit) breaches.push({ metric, measured: value, limit });
  }
  return breaches;
}

interface MeasureReport {
  size: { rawBytes: number };
  results: { profile: string; hostToFirstPageMs: number; peakJsHeapBytes: number }[];
}

/** Maps the JSON that `measure.mjs --json` writes to the budget's metrics. */
export function summarise(report: MeasureReport): Measurements {
  const desktop = report.results.find((r) => r.profile === "desktop");
  const phone = report.results.find((r) => r.profile.startsWith("phone"));
  return {
    pageBytes: report.size.rawBytes,
    desktopFirstPageMs: desktop?.hostToFirstPageMs ?? Number.NaN,
    phoneFirstPageMs: phone?.hostToFirstPageMs ?? Number.NaN,
    peakHeapBytes: report.results.length ? Math.max(...report.results.map((r) => r.peakJsHeapBytes)) : Number.NaN,
  };
}
