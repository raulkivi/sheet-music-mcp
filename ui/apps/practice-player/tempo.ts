// Tempo and time mapping for the Practice Player. Pure. A track is rendered once at a
// `tempo_factor`; the page then changes speed locally with `playbackRate`, which leaves
// `audio.currentTime` in track time, so all mapping here is between score time and track time.

/** The server's tempo_factor range (synthesize, docs/requirements.md). */
export const TEMPO_MIN = 0.25;
export const TEMPO_MAX = 4;

const DEFAULT_BPM = 120;

export function clampTempo(factor: number): number {
  if (!Number.isFinite(factor)) return 1;
  return Math.min(TEMPO_MAX, Math.max(TEMPO_MIN, factor));
}

export function tempoPercent(factor: number): number {
  return Math.round(factor * 100);
}

/** What `audio.playbackRate` must be to sound at `wanted` when the track was rendered at `rendered`. */
export function playbackRate(wanted: number, rendered: number): number {
  return clampTempo(wanted) / rendered;
}

/** Track seconds at which a point `score` seconds into the music (at score tempo) sounds. */
export function audioSeconds(score: number, rendered: number, preRoll: number): number {
  return preRoll + score / rendered;
}

/**
 * Score seconds for a track position, wrapped into the music when the track repeats it;
 * undefined while the count-in plays.
 */
export function scoreSeconds(audio: number, rendered: number, preRoll: number, musicDuration: number): number | undefined {
  const inMusic = audio - preRoll;
  if (inMusic < 0) return undefined;
  const score = inMusic * rendered;
  return musicDuration > 0 ? score % musicDuration : score;
}

/** The loop: the music without its count-in, so a repeat pass never replays the clicks. */
export function loopBounds(preRoll: number, duration: number): { start: number; end: number } {
  return { start: preRoll < duration ? preRoll : 0, end: duration };
}

/** The tempo in force at bar one (quarter notes per minute), as the server reads it. */
function startBpm(xml: string): number {
  const sound = xml.match(/<sound[^>]*\btempo="([\d.]+)"/);
  const mark = xml.match(/<per-minute>\s*([\d.]+)\s*<\/per-minute>/);
  const bpm = Number(sound?.[1] ?? mark?.[1]);
  return bpm > 0 ? bpm : DEFAULT_BPM;
}

function quartersPerBar(xml: string): number {
  const beats = Number(xml.match(/<beats>\s*(\d+)\s*<\/beats>/)?.[1]);
  const unit = Number(xml.match(/<beat-type>\s*(\d+)\s*<\/beat-type>/)?.[1]);
  return beats > 0 && unit > 0 ? (beats * 4) / unit : 4;
}

/** Seconds of clicks `count_in_bars` adds before the music, in its first bar's meter and tempo. */
export function countInSeconds(xml: string, bars: number, rendered: number): number {
  if (bars <= 0) return 0;
  return (bars * quartersPerBar(xml) * 60) / (startBpm(xml) * rendered);
}
