// Pure math of the pitch meter: cents to a needle position, and the step between two samples.

/** The meter spans -50 to +50 cents around the expected pitch. */
export const METER_RANGE_CENTS = 50;

/** The server grades |cents| <= 25 as on pitch (pitch-mcp aligner `_classify`); the zone shows it. */
export const IN_TUNE_CENTS = 25;

/** Needle position in percent of the meter's width (0 = far flat, 100 = far sharp), or null without a reading. */
export function centsToNeedle(cents: number | null): number | null {
  if (cents === null || !Number.isFinite(cents)) return null;
  const clamped = Math.max(-METER_RANGE_CENTS, Math.min(METER_RANGE_CENTS, cents));
  return 50 + (clamped / METER_RANGE_CENTS) * 50;
}

/**
 * Where the needle is `elapsedMs` after it set off from `from` towards `to`. Samples arrive 5 to
 * 10 times a second; the needle covers the gap in a straight line, no easing (it tracks audio).
 * Reduced motion, or no duration, jumps straight to `to`.
 */
export function needleAt(from: number, to: number, elapsedMs: number, durationMs: number, reducedMotion: boolean): number {
  if (reducedMotion || durationMs <= 0 || elapsedMs >= durationMs) return to;
  const progress = Math.max(0, elapsedMs) / durationMs;
  return from + (to - from) * progress;
}

/** The cents text is read aloud and read by eye: it changes when the status does, else once a second. */
export function shouldRefreshText(last: { status: string; at: number } | undefined, status: string, now: number, minMs = 1000): boolean {
  return last === undefined || last.status !== status || now - last.at >= minMs;
}
