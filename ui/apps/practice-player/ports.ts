// What the Practice Player controller needs from its surroundings, as small interfaces: the
// audio output, the frame clock and the screen. Real implementations are in audio.ts and dom.ts;
// unit tests use fakes, so the controller never touches a browser.

import type { HostContext } from "@sheet-music-mcp/ui-kit/host/HostBridge";
import type { FollowerUi } from "./follower.ts";
import type { PresetName } from "./mixer.ts";
import type { Timbre } from "./track.ts";

export interface AudioPort {
  /** Resolves when the audio can play; rejects if the browser cannot decode or is not allowed to. */
  load(blob: Blob): Promise<void>;
  play(): Promise<void>;
  pause(): void;
  /** Seconds into the track, whatever the playback rate. */
  readonly position: number;
  seek(seconds: number): void;
  /** Local speed change; the pitch stays (decision DA4). */
  setRate(rate: number): void;
  /** Called when the track plays to its end. */
  onEnded(listener: () => void): void;
}

export interface FrameClock {
  /** Calls `callback` before the next paint. */
  request(callback: () => void): void;
}

export interface PartView {
  id: string;
  name: string;
  volume: number;
  muted: boolean;
  solo: boolean;
}

/** Everything the screen shows apart from the score and the position, as plain data. */
export interface PlayerView {
  phase: "empty" | "loading" | "ready" | "error";
  /** Shown as a notice: why the page is empty or failed, or a warning that does not stop playback. */
  notice?: string;
  /** A new mix is being rendered; the old one keeps playing. */
  busy: boolean;
  parts: PartView[];
  preset: PresetName | "";
  focus: string;
  /** Tempo as a percentage of the score's. */
  tempoPercent: number;
  playing: boolean;
  loop: boolean;
  loopLabel: string;
  countInOn: boolean;
  timbre: Timbre;
  durationSeconds: number;
  /** Note names from `starting_pitches`, once asked for. */
  startingPitches?: string;
}

export interface PlayerPosition {
  seconds: number;
  duration: number;
  /** "Bar 17", "Count-in", or empty. */
  label: string;
}

export interface PlayerUi extends FollowerUi {
  render(view: PlayerView): void;
  showPosition(position: PlayerPosition): void;
  /** A polite screen-reader announcement. */
  announce(text: string): void;
  applyHostContext(context: HostContext): void;
  containerWidth(): number;
  prefersReducedMotion(): boolean;
  playClip(url: string): void;
}
