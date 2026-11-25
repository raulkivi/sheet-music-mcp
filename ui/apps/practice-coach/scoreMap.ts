// Where a (bar, beat) lies in the rendered score. Pure: works on the MusicXML text and on the
// page SVGs, never on the DOM.

export interface ScoreStructure {
  /** Printed bar numbers of the first part, in score order. */
  measureNumbers: string[];
  beatsPerMeasure: number;
}

const DEFAULT_BEATS = 4;

export function parseScoreStructure(xml: string): ScoreStructure {
  const part = xml.match(/<part\b[^>]*>[\s\S]*?(?:<\/part>|$)/);
  const body = part?.[0] ?? xml;
  const measureNumbers = [...body.matchAll(/<measure\b[^>]*?\bnumber="([^"]*)"/g)].map((m) => m[1] as string);
  const beats = Number(xml.match(/<beats>\s*(\d+)\s*<\/beats>/)?.[1]);
  return { measureNumbers, beatsPerMeasure: beats > 0 ? beats : DEFAULT_BEATS };
}

/** How far into the bar a beat lies (0 to just under 1). Beats are 1-based, as the server counts. */
export function cursorFraction(beat: number, beatsPerMeasure: number): number {
  const raw = (beat - 1) / beatsPerMeasure;
  return Math.max(0, Math.min(0.98, raw));
}

/** Verovio draws each bar as one `<g class="measure">`. */
export function countMeasures(svg: string): number {
  return (svg.match(/class="measure"/g) ?? []).length;
}

export interface MeasureLocation {
  /** 1-based page. */
  page: number;
  /** Position among the page's bars, in document order. */
  index: number;
}

/** The page and the place on it of a printed bar number, given each page's bar count. */
export function locateMeasure(measure: number, measureNumbers: readonly string[], pageCounts: readonly number[]): MeasureLocation | undefined {
  let remaining = measureNumbers.findIndex((n) => Number(n) === measure);
  if (remaining < 0) return undefined;
  for (const [i, count] of pageCounts.entries()) {
    if (remaining < count) return { page: i + 1, index: remaining };
    remaining -= count;
  }
  return undefined;
}
