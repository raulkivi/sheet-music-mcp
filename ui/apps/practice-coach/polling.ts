// Adaptive polling (decision D7): 10 Hz, backing off to 5 Hz while the median round trip is
// slow, and no request at all while the document is hidden. Pure: time, timers and visibility
// come in through PollEnv, so tests drive it with a fake clock.

export interface PollEnv {
  now(): number;
  /** Schedules `fn`; the returned function cancels it. */
  setTimeout(fn: () => void, ms: number): () => void;
  isHidden(): boolean;
}

export interface PollOptions {
  fastMs: number;
  slowMs: number;
  /** Median round trip above this backs off to `slowMs`. */
  backoffRttMs: number;
  /** Median round trip below this (and only then) returns to `fastMs`; the gap stops flapping. */
  recoverRttMs: number;
  /** How many recent round trips the median covers. */
  window: number;
}

export const DEFAULT_POLL: PollOptions = { fastMs: 100, slowMs: 200, backoffRttMs: 80, recoverRttMs: 60, window: 5 };

/** Fewer round trips than this decide nothing yet. */
const MIN_SAMPLES = 3;

export function median(values: readonly number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? (sorted[mid] as number) : ((sorted[mid - 1] as number) + (sorted[mid] as number)) / 2;
}

export class PollScheduler {
  private active = false;
  private paused = false;
  private cancelTimer: (() => void) | undefined;
  private interval: number;
  private readonly rtts: number[] = [];

  constructor(
    private readonly request: () => Promise<void>,
    private readonly env: PollEnv,
    private readonly options: PollOptions = DEFAULT_POLL,
  ) {
    this.interval = options.fastMs;
  }

  get running(): boolean {
    return this.active;
  }

  get intervalMs(): number {
    return this.interval;
  }

  start(): void {
    if (this.active) return;
    this.active = true;
    this.cycle();
  }

  stop(): void {
    this.active = false;
    this.paused = false;
    this.cancelTimer?.();
    this.cancelTimer = undefined;
  }

  /** Call when document visibility changes: resumes a paused loop. */
  onVisibilityChange(): void {
    if (this.active && this.paused && !this.env.isHidden()) {
      this.paused = false;
      this.cycle();
    }
  }

  private cycle(): void {
    this.cancelTimer = undefined;
    if (!this.active) return;
    if (this.env.isHidden()) {
      this.paused = true;
      return;
    }
    const sent = this.env.now();
    this.request()
      .catch(() => {})
      .then(() => {
        if (!this.active) return;
        const rtt = this.env.now() - sent;
        this.record(rtt);
        this.cancelTimer = this.env.setTimeout(() => this.cycle(), Math.max(0, this.interval - rtt));
      });
  }

  private record(rtt: number): void {
    this.rtts.push(rtt);
    if (this.rtts.length > this.options.window) this.rtts.shift();
    if (this.rtts.length < MIN_SAMPLES) return;
    const typical = median(this.rtts);
    if (typical > this.options.backoffRttMs) this.interval = this.options.slowMs;
    else if (typical < this.options.recoverRttMs) this.interval = this.options.fastMs;
  }
}
