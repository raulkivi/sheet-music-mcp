// The synth-mcp contract as the page sees it: the track `synthesize` returned, the options the
// call was made with, the arguments of a re-render, and the fixed texts sent to the model.
// Pure. Nothing from the MusicXML (titles, lyrics, part names) ever reaches a message.

import type { ToolResult } from "@sheet-music-mcp/ui-kit/host/HostBridge";
import { errorEnvelope } from "@sheet-music-mcp/ui-kit/host/toolErrors";
import { effectiveGains, type MixerState } from "./mixer.ts";
import { clampTempo, tempoPercent } from "./tempo.ts";

export interface TrackPart {
  id: string;
  name: string;
  included: boolean;
  gain: number;
}

export interface Track {
  audioId: string;
  duration: number;
  /** The tempo_factor the audio was rendered at. */
  tempoFactor: number;
  parts: TrackPart[];
}

export type TrackResult =
  | { ok: true; track: Track }
  | { ok: false; kind: "error"; code: string; message: string }
  | { ok: false; kind: "empty" };

function readPart(value: unknown): TrackPart | undefined {
  if (typeof value !== "object" || value === null) return undefined;
  const { id, name, included, gain } = value as Record<string, unknown>;
  if (typeof id !== "string" || typeof name !== "string") return undefined;
  return { id, name, included: included !== false, gain: typeof gain === "number" ? gain : 1 };
}

/** The `synthesize` result: `structuredContent` for the app, the error envelope when it failed. */
export function readTrack(result: ToolResult): TrackResult {
  const failure = errorEnvelope(result);
  if (failure) return { ok: false, kind: "error", code: failure.code, message: failure.error };
  const data = result.structuredContent ?? {};
  const parts = (Array.isArray(data.parts) ? data.parts : []).flatMap((part) => readPart(part) ?? []);
  if (typeof data.audio_id !== "string" || data.audio_id === "" || parts.length === 0) {
    return { ok: false, kind: "empty" };
  }
  return {
    ok: true,
    track: {
      audioId: data.audio_id,
      duration: typeof data.duration_seconds === "number" ? data.duration_seconds : 0,
      tempoFactor: typeof data.tempo_factor === "number" ? data.tempo_factor : 1,
      parts,
    },
  };
}

export const TIMBRES = ["score", "piano", "choir", "organ"] as const;
export type Timbre = (typeof TIMBRES)[number];

/** Arguments that describe a mix or the output file: the page sets these itself on a re-render. */
const SET_BY_PAGE = new Set([
  "parts",
  "part_ids",
  "part_gains",
  "preset",
  "focus_part",
  "output_path",
  "tempo_factor",
  "repeat",
  "count_in_bars",
  "timbre",
]);

export interface RenderRequest {
  /** Printed bar numbers [start, end] the track covers; undefined for the whole piece. */
  measures: [number, number] | undefined;
  repeat: number;
  countInBars: number;
  timbre: Timbre;
  /** The score and the other options, to send again. */
  carried: Record<string, unknown>;
}

function readMeasures(value: unknown): [number, number] | undefined {
  if (!Array.isArray(value) || value.length !== 2) return undefined;
  const [start, end] = value;
  if (!Number.isInteger(start) || !Number.isInteger(end) || start > end) return undefined;
  return [start, end];
}

/** The arguments of the call that opened the player. */
export function readRequest(args: Record<string, unknown>): RenderRequest {
  const timbre = TIMBRES.find((name) => name === args.timbre) ?? "score";
  return {
    measures: readMeasures(args.measures),
    repeat: Number.isInteger(args.repeat) && (args.repeat as number) >= 1 ? (args.repeat as number) : 1,
    countInBars: Number.isInteger(args.count_in_bars) && (args.count_in_bars as number) >= 0 ? (args.count_in_bars as number) : 0,
    timbre,
    carried: Object.fromEntries(Object.entries(args).filter(([key]) => !SET_BY_PAGE.has(key))),
  };
}

export interface RenderOptions {
  countInBars: number;
  timbre: Timbre;
}

/** The `synthesize` call that renders the same piece with this mix, tempo and options. */
export function renderArgs(
  request: RenderRequest,
  mixer: MixerState,
  tempo: number,
  options: RenderOptions,
): Record<string, unknown> {
  return {
    ...request.carried,
    repeat: request.repeat,
    part_gains: effectiveGains(mixer),
    tempo_factor: clampTempo(tempo),
    count_in_bars: options.countInBars,
    timbre: options.timbre,
  };
}

/** The bars a loop covers, for labels. */
export function barsLabel(measures: [number, number] | undefined): string {
  if (!measures) return "the whole piece";
  return measures[0] === measures[1] ? `bar ${measures[0]}` : `bars ${measures[0]} to ${measures[1]}`;
}

export interface PlayerState {
  mixer: MixerState;
  tempo: number;
  loop: boolean;
  measures: [number, number] | undefined;
  countInBars: number;
}

/** What the model is told after the user changed something, so "make it faster" works in chat. */
export function contextMessage(state: PlayerState): string {
  const gains = effectiveGains(state.mixer);
  const ids = state.mixer.parts.map((part) => part.id);
  const mix =
    state.mixer.solo.length > 0
      ? `solo: ${state.mixer.solo.join(", ")}`
      : [
          `parts playing: ${ids.filter((id) => (gains[id] ?? 0) > 0).join(", ") || "none"}`,
          ...(ids.some((id) => gains[id] === 0) ? [`muted: ${ids.filter((id) => gains[id] === 0).join(", ")}`] : []),
        ].join("; ");
  const loop = state.loop ? `loop on (${barsLabel(state.measures)})` : "loop off";
  const preRoll = state.countInBars > 0 ? `count-in ${state.countInBars} ${state.countInBars === 1 ? "bar" : "bars"}` : "count-in off";
  return `Practice Player: tempo ${tempoPercent(state.tempo)} %, ${loop}, ${preRoll}, ${mix}.`;
}

export interface StartingPitches {
  text: string;
  /** A data: URL for the short piano clip, when the server sent it inline. */
  audioUrl?: string;
}

/** `starting_pitches`: the note names and, when small enough to come inline, the clip. */
export function readStartingPitches(result: ToolResult): StartingPitches | undefined {
  if (result.isError) return undefined;
  const blocks = (result.content ?? []) as { type?: string; text?: string; data?: string; mimeType?: string }[];
  let text = typeof result.structuredContent?.text === "string" ? result.structuredContent.text : undefined;
  if (text === undefined) {
    for (const block of blocks) {
      if (block.type !== "text" || typeof block.text !== "string") continue;
      try {
        const parsed = JSON.parse(block.text) as { text?: unknown };
        if (typeof parsed.text === "string") text = parsed.text;
      } catch {
        // Not the JSON block; keep looking.
      }
    }
  }
  if (!text) return undefined;
  const audio = blocks.find((block) => block.type === "audio" && typeof block.data === "string");
  return audio ? { text, audioUrl: `data:${audio.mimeType ?? "audio/wav"};base64,${audio.data}` } : { text };
}
