// Playhead position from Verovio's timemap. Pure: entries in, notes and bar out.

/** One row of `renderToTimemap({ includeMeasures: true })`; `tstamp` is milliseconds at score tempo. */
export interface TimemapEntry {
  tstamp: number;
  on?: string[];
  off?: string[];
  measureOn?: string;
}

export interface PlayheadPoint {
  /** Ids of the notes sounding. */
  notes: string[];
  /** Id of the bar that contains the time. */
  measure: string | undefined;
  /** Zero-based position of that bar in the music. */
  bar: number;
}

interface Snapshot extends PlayheadPoint {
  tstamp: number;
}

export class Playhead {
  private readonly snapshots: Snapshot[] = [];

  constructor(entries: readonly TimemapEntry[]) {
    const sounding = new Set<string>();
    let measure: string | undefined;
    let bar = -1;
    for (const entry of [...entries].sort((a, b) => a.tstamp - b.tstamp)) {
      for (const id of entry.off ?? []) sounding.delete(id);
      for (const id of entry.on ?? []) sounding.add(id);
      if (entry.measureOn !== undefined && entry.measureOn !== measure) {
        measure = entry.measureOn;
        bar += 1;
      }
      this.snapshots.push({ tstamp: entry.tstamp, notes: [...sounding], measure, bar: Math.max(bar, 0) });
    }
  }

  get durationMs(): number {
    return this.snapshots.at(-1)?.tstamp ?? 0;
  }

  /** The last entry at or before `ms`; the first one for a time before the music. */
  at(ms: number): PlayheadPoint | undefined {
    if (this.snapshots.length === 0) return undefined;
    let low = 0;
    let high = this.snapshots.length - 1;
    while (low < high) {
      const middle = Math.ceil((low + high) / 2);
      if ((this.snapshots[middle] as Snapshot).tstamp <= ms) low = middle;
      else high = middle - 1;
    }
    const { notes, measure, bar } = this.snapshots[low] as Snapshot;
    return { notes: [...notes], measure, bar };
  }
}

/** Printed bar numbers of the first part, in order: the labels for the playhead's bars. */
export function barNumbers(xml: string): string[] {
  const part = xml.match(/<part\b[^>]*>([\s\S]*?)<\/part>/)?.[1] ?? "";
  return [...part.matchAll(/<measure\b[^>]*\bnumber="([^"]*)"/g)].map((match) => match[1] as string);
}
