// Mixer state: per-part volume, mute and solo, and the presets (decision DA3). Pure and immutable.
// Every change ends in `effectiveGains`, which becomes synthesize's `part_gains`.

import type { TrackPart } from "./track.ts";

export const GAIN_MIN = 0;
/** synthesize's part_gains maximum. */
export const GAIN_MAX = 2;

export type PresetName = "equal" | "learning" | "karaoke";

export const PRESETS: readonly PresetName[] = ["equal", "learning", "karaoke"];

// The server's own preset gains (synth-mcp practice.resolve_gains), applied here so the sliders
// show them at once; the next render's `part_gains` carries them explicitly.
const LEARNING_FOCUS = 1.5;
const LEARNING_OTHERS = 0.5;

export interface MixerPart {
  id: string;
  name: string;
  /** Volume when audible; kept while muted so unmuting restores it. */
  volume: number;
  muted: boolean;
}

export interface MixerState {
  parts: readonly MixerPart[];
  /** Ids of soloed parts; when there are any, only they sound. */
  solo: readonly string[];
}

function clampGain(value: number): number {
  if (!Number.isFinite(value)) return 1;
  return Math.min(GAIN_MAX, Math.max(GAIN_MIN, value));
}

/** A part the track left out, or one the server set silent, starts muted at normal volume. */
export function fromTrackParts(parts: readonly TrackPart[]): MixerState {
  return {
    solo: [],
    parts: parts.map((part) => {
      const audible = part.included && part.gain > 0;
      return { id: part.id, name: part.name, volume: audible ? clampGain(part.gain) : 1, muted: !audible };
    }),
  };
}

function updatePart(state: MixerState, id: string, change: (part: MixerPart) => MixerPart): MixerState {
  return { ...state, parts: state.parts.map((part) => (part.id === id ? change(part) : part)) };
}

export function toggleMute(state: MixerState, id: string): MixerState {
  return updatePart(state, id, (part) => ({ ...part, muted: !part.muted }));
}

export function setVolume(state: MixerState, id: string, volume: number): MixerState {
  return updatePart(state, id, (part) => ({ ...part, volume: clampGain(volume) }));
}

export function toggleSolo(state: MixerState, id: string): MixerState {
  if (!state.parts.some((part) => part.id === id)) return state;
  const solo = state.solo.includes(id) ? state.solo.filter((soloed) => soloed !== id) : [...state.solo, id];
  return { ...state, solo };
}

/** Replaces every volume, mute and solo with the preset's; `focus` is the part id it is for. */
export function applyPreset(state: MixerState, preset: PresetName, focus: string): MixerState {
  const parts = state.parts.map((part): MixerPart => {
    const isFocus = part.id === focus;
    if (preset === "learning") return { ...part, muted: false, volume: isFocus ? LEARNING_FOCUS : LEARNING_OTHERS };
    if (preset === "karaoke") return { ...part, muted: isFocus, volume: 1 };
    return { ...part, muted: false, volume: 1 };
  });
  return { parts, solo: [] };
}

/** The gain each part has in the next render: 0 for a muted part or one outside the solo set. */
export function effectiveGains(state: MixerState): Record<string, number> {
  const soloing = state.solo.length > 0;
  return Object.fromEntries(
    state.parts.map((part) => {
      const audible = !part.muted && (!soloing || state.solo.includes(part.id));
      return [part.id, audible ? part.volume : 0];
    }),
  );
}
