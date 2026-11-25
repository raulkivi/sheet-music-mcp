// The positions polled during a take, kept in a bounded buffer and summarized per bar for the
// "last bars" list and the Report mode heat strip. The server's summary has no per-bar data, so
// the page builds it from what it saw.

import { IN_TUNE_CENTS } from "./meter.ts";

/** The fields of a get_current_position result the history needs. */
export interface Sample {
  measure: number;
  beat: number;
  expected_note: string;
  accuracy_cents: number | null;
  status: string;
}

export type BarStatus = "on_pitch" | "sharp" | "flat" | "uncertain" | "no_signal";

export interface BarSummary {
  /** Printed bar number. */
  measure: number;
  status: BarStatus;
  /** Mean of the graded samples; null when none was graded. */
  avgCents: number | null;
  /** Every sample in the bar, graded or not. */
  samples: number;
}

const GRADED = new Set(["on_pitch", "sharp", "flat"]);

/** About three minutes at 10 Hz. */
export const DEFAULT_LIMIT = 2000;

export class HistoryBuffer {
  private items: Sample[] = [];

  constructor(private readonly limit = DEFAULT_LIMIT) {}

  push(sample: Sample): void {
    this.items.push(sample);
    if (this.items.length > this.limit) this.items.splice(0, this.items.length - this.limit);
  }

  clear(): void {
    this.items = [];
  }

  samples(): readonly Sample[] {
    return this.items;
  }

  /** One summary per bar, in the order the singer first reached it. */
  byMeasure(): BarSummary[] {
    const groups = new Map<number, Sample[]>();
    for (const sample of this.items) {
      const group = groups.get(sample.measure);
      if (group) group.push(sample);
      else groups.set(sample.measure, [sample]);
    }
    return [...groups].map(([measure, samples]) => summarize(measure, samples));
  }

  lastMeasures(count: number): BarSummary[] {
    return this.byMeasure().slice(-count);
  }
}

function summarize(measure: number, samples: Sample[]): BarSummary {
  const cents = samples.flatMap((s) => (GRADED.has(s.status) && s.accuracy_cents !== null ? [s.accuracy_cents] : []));
  if (cents.length === 0) {
    const status: BarStatus = samples.some((s) => s.status === "uncertain") ? "uncertain" : "no_signal";
    return { measure, status, avgCents: null, samples: samples.length };
  }
  const avgCents = Math.round(cents.reduce((sum, c) => sum + c, 0) / cents.length);
  const status: BarStatus = Math.abs(avgCents) <= IN_TUNE_CENTS ? "on_pitch" : avgCents > 0 ? "sharp" : "flat";
  return { measure, status, avgCents, samples: samples.length };
}
