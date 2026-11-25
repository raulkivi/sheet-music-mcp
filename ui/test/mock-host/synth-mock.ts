// Stand-in for synth-mcp in the mock host: answers synthesize, the app-only read_audio_chunk and
// get_score_xml, and starting_pitches in the server's contract (structuredContent, error
// envelope), with a silent WAV of the right length. State lives per host page, like the server's
// artifact store lives per process. Runs in the browser: no Node APIs.

import type { CallToolResult } from "@modelcontextprotocol/client";
import type { ToolBackend, ToolCall } from "./tool-backends.ts";

export const SYNTH_TOOLS: ReadonlySet<string> = new Set(["synthesize", "read_audio_chunk", "get_score_xml", "starting_pitches"]);

const SAMPLE_RATE = 8000;
const HEADER_BYTES = 44;
const DEFAULT_BPM = 120;
const STARTING_PITCHES = ["D5", "A4", "F#4", "D3"];

interface Stored {
  wav: Uint8Array;
  musicxml: string;
}

function toolError(error: string, code: string): CallToolResult {
  return { isError: true, content: [{ type: "text", text: JSON.stringify({ error, error_code: code }) }] };
}

function base64(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}

/** 8 kHz, 8-bit, mono silence: small, and a real file the browser decodes. */
function silentWav(seconds: number): Uint8Array {
  const samples = Math.max(1, Math.round(seconds * SAMPLE_RATE));
  const wav = new Uint8Array(HEADER_BYTES + samples).fill(0x80, HEADER_BYTES);
  const view = new DataView(wav.buffer);
  const text = (offset: number, value: string) => [...value].forEach((char, i) => view.setUint8(offset + i, char.charCodeAt(0)));
  text(0, "RIFF");
  view.setUint32(4, 36 + samples, true);
  text(8, "WAVE");
  text(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, SAMPLE_RATE, true);
  view.setUint32(28, SAMPLE_RATE, true); // byte rate
  view.setUint16(32, 1, true); // block align
  view.setUint16(34, 8, true); // bits
  text(36, "data");
  view.setUint32(40, samples, true);
  return wav;
}

function scoreParts(xml: string): { id: string; name: string }[] {
  return [...xml.matchAll(/<score-part id="([^"]+)">\s*<part-name>([^<]*)<\/part-name>/g)].map((m) => ({ id: m[1] as string, name: m[2] as string }));
}

/** Seconds the first part lasts at score tempo, bar by bar, and the first bar's bar length. */
function musicSeconds(xml: string): { music: number; bar: number } {
  const part = xml.match(/<part\b[^>]*>([\s\S]*?)<\/part>/)?.[1] ?? "";
  const beats = Number(part.match(/<beats>(\d+)<\/beats>/)?.[1] ?? 4);
  const unit = Number(part.match(/<beat-type>(\d+)<\/beat-type>/)?.[1] ?? 4);
  const quarters = (beats * 4) / unit;
  let bpm = DEFAULT_BPM;
  let music = 0;
  let bar = 0;
  for (const measure of part.split(/<measure\b/).slice(1)) {
    bpm = Number(measure.match(/<sound[^>]*\btempo="([\d.]+)"/)?.[1] ?? bpm);
    if (bar === 0) bar = (quarters * 60) / bpm;
    music += (quarters * 60) / bpm;
  }
  return { music, bar };
}

export function createSynthMock(): ToolBackend {
  const store = new Map<string, Stored>();
  let counter = 0;

  function synthesize(args: Record<string, unknown>): CallToolResult {
    const musicxml = args.musicxml;
    if (typeof musicxml !== "string" || !musicxml.includes("<score-partwise")) {
      return toolError("Not a MusicXML score", "INVALID_INPUT");
    }
    const factor = typeof args.tempo_factor === "number" ? args.tempo_factor : 1;
    const repeat = typeof args.repeat === "number" ? args.repeat : 1;
    const countInBars = typeof args.count_in_bars === "number" ? args.count_in_bars : 0;
    const gains = (typeof args.part_gains === "object" && args.part_gains !== null ? args.part_gains : {}) as Record<string, number>;
    const { music, bar } = musicSeconds(musicxml);
    const duration = (countInBars * bar + music * repeat) / factor;
    const wav = silentWav(duration);
    const audioId = `audio-${++counter}`;
    store.set(audioId, { wav, musicxml });
    return {
      content: [{ type: "text", text: JSON.stringify({ format: "wav", duration_seconds: duration, tempo_factor: factor }) }],
      structuredContent: {
        audio_id: audioId,
        duration_seconds: Math.round(duration * 100) / 100,
        sample_rate: SAMPLE_RATE,
        channels: 1,
        byte_length: wav.length,
        parts: scoreParts(musicxml).map((part) => ({ ...part, included: true, gain: gains[part.id] ?? 1 })),
        tempo_factor: factor,
      },
    };
  }

  function readChunk(args: Record<string, unknown>): CallToolResult {
    const found = typeof args.audio_id === "string" ? store.get(args.audio_id) : undefined;
    if (!found) return toolError("Unknown or expired artifact id", "INVALID_PARAMETER");
    const offset = Number(args.offset);
    const length = Number(args.length);
    const slice = found.wav.subarray(offset, offset + length);
    return {
      content: [{ type: "text", text: `Audio bytes ${offset}-${offset + slice.length} of ${found.wav.length} sent to the Practice Player.` }],
      structuredContent: {
        artifact_id: args.audio_id,
        offset,
        length: slice.length,
        byte_length: found.wav.length,
        eof: offset + slice.length >= found.wav.length,
        data_b64: base64(slice),
      },
    };
  }

  function getScore(args: Record<string, unknown>): CallToolResult {
    const found = typeof args.audio_id === "string" ? store.get(args.audio_id) : undefined;
    if (!found) return toolError("Unknown or expired artifact id", "INVALID_PARAMETER");
    return {
      content: [{ type: "text", text: "Score fetched for the Practice Player." }],
      structuredContent: { audio_id: args.audio_id, musicxml: found.musicxml },
    };
  }

  function startingPitches(args: Record<string, unknown>): CallToolResult {
    const musicxml = typeof args.musicxml === "string" ? args.musicxml : "";
    const text = scoreParts(musicxml)
      .map((part, i) => `${part.name}: ${STARTING_PITCHES[i % STARTING_PITCHES.length]}`)
      .join(", ");
    return {
      content: [
        { type: "text", text: JSON.stringify({ text }) },
        { type: "audio", data: base64(silentWav(0.5)), mimeType: "audio/wav" },
      ],
    };
  }

  return {
    async callTool(call: ToolCall) {
      const args = call.arguments ?? {};
      if (call.name === "synthesize") return synthesize(args);
      if (call.name === "read_audio_chunk") return readChunk(args);
      if (call.name === "get_score_xml") return getScore(args);
      if (call.name === "starting_pitches") return startingPitches(args);
      throw new Error(`mock host has no fixture for tool ${call.name}`);
    },
  };
}
