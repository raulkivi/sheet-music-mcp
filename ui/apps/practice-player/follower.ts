// Keeps the score on screen in step with the audio: turns the page, marks the notes sounding
// (or, with reduced motion, only the bar) and labels the bar. Knows the score engine and a small
// UI port, nothing about the host, the audio or the mixer.

import type { RenderedPage } from "@sheet-music-mcp/ui-kit/score/ScoreRenderer";
import { Playhead, barNumbers, type PlayheadPoint, type TimemapEntry } from "./playhead.ts";

/** The slice of ScoreView the follower needs, so tests need no Verovio. */
export interface ScoreEngine {
  load(xml: string): void | Promise<void>;
  layout(containerWidth: number): void;
  page(page: number): RenderedPage;
  timemap(): TimemapEntry[];
  pageOf(elementId: string): number;
}

export interface FollowerUi {
  showPage(svg: string): void;
  /** `null` clears the marker. */
  showPlayhead(point: PlayheadPoint | null): void;
}

export class ScoreFollower {
  private playhead = new Playhead([]);
  private bars: string[] = [];
  private width = 0;
  private page = 1;
  private shown: { bar: number; notes: string } | "none" | undefined;
  private last: PlayheadPoint | undefined;

  constructor(
    private readonly engine: ScoreEngine,
    private readonly ui: FollowerUi,
    private readonly reducedMotion: () => boolean,
  ) {}

  async open(xml: string, width: number): Promise<void> {
    this.width = Math.round(width);
    this.engine.layout(this.width);
    await this.engine.load(xml);
    this.playhead = new Playhead(this.engine.timemap());
    this.bars = barNumbers(xml);
    this.page = 1;
    this.shown = undefined;
    this.last = undefined;
    this.showPage(1);
  }

  /** Seconds the music lasts at score tempo. */
  get musicSeconds(): number {
    return this.playhead.durationMs / 1000;
  }

  resize(width: number): void {
    const rounded = Math.round(width);
    if (rounded <= 0 || rounded === this.width) return;
    this.width = rounded;
    this.engine.layout(rounded);
    this.showPage(this.page);
    this.mark(this.last);
  }

  /**
   * Moves the marker to `score` seconds into the music (undefined: count-in, no marker).
   * Returns the bar's label. `force` repeats an unchanged marker (after a seek).
   */
  update(score: number | undefined, force = false): string | undefined {
    if (score === undefined) {
      this.last = undefined;
      if (this.shown !== "none") this.ui.showPlayhead(null);
      this.shown = "none";
      return undefined;
    }
    const point = this.playhead.at(score * 1000);
    if (!point) return undefined;
    const label = `Bar ${this.bars[point.bar % Math.max(this.bars.length, 1)] ?? point.bar + 1}`;
    const reduced = this.reducedMotion();
    const next: PlayheadPoint = reduced ? { ...point, notes: [] } : point;
    const key = { bar: point.bar, notes: next.notes.join(" ") };
    const unchanged = typeof this.shown === "object" && this.shown.bar === key.bar && this.shown.notes === key.notes;
    if (unchanged && !force) return label;

    const barChanged = typeof this.shown !== "object" || this.shown.bar !== key.bar;
    this.shown = key;
    this.last = next;
    if (barChanged && next.measure !== undefined) {
      const wanted = this.engine.pageOf(next.measure);
      if (wanted !== this.page) {
        this.page = wanted;
        this.showPage(wanted);
      }
    }
    this.mark(next);
    return label;
  }

  private showPage(page: number): void {
    const shown = this.engine.page(page);
    this.page = shown.page;
    this.ui.showPage(shown.svg);
  }

  private mark(point: PlayheadPoint | undefined): void {
    if (point) this.ui.showPlayhead(point);
  }
}
