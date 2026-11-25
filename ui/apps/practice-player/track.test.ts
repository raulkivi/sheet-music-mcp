import { describe, expect, it } from "vitest";
import { fromTrackParts, setVolume, toggleMute } from "./mixer.ts";
import {
  barsLabel,
  contextMessage,
  readRequest,
  readStartingPitches,
  readTrack,
  renderArgs,

} from "./track.ts";

const PARTS = [
  { id: "P1", name: "Soprano", included: true, gain: 1 },
  { id: "P2", name: "Alto", included: true, gain: 1 },
];

function result(overrides: Record<string, unknown> = {}) {
  return {
    content: [{ type: "text", text: "{}" }],
    structuredContent: {
      audio_id: "a1",
      duration_seconds: 12.5,
      sample_rate: 44100,
      channels: 2,
      byte_length: 100,
      parts: PARTS,
      tempo_factor: 0.75,
      ...overrides,
    },
  };
}

describe("readTrack", () => {
  it("reads the synthesize result", () => {
    expect(readTrack(result())).toEqual({
      ok: true,
      track: { audioId: "a1", duration: 12.5, tempoFactor: 0.75, parts: PARTS },
    });
  });

  it("defaults the tempo to the score's", () => {
    const { tempo_factor: _, ...rest } = result().structuredContent;
    expect(readTrack({ structuredContent: rest })).toMatchObject({ ok: true, track: { tempoFactor: 1 } });
  });

  it("names the server's error code for a failed call", () => {
    const failed = {
      isError: true,
      content: [{ type: "text", text: JSON.stringify({ error: "No soundfont", error_code: "PROCESSING_FAILED" }) }],
    };
    expect(readTrack(failed)).toEqual({ ok: false, kind: "error", code: "PROCESSING_FAILED", message: "No soundfont" });
  });

  it("is empty when the result has no track", () => {
    expect(readTrack({ content: [{ type: "text", text: "hello" }] })).toEqual({ ok: false, kind: "empty" });
    expect(readTrack(result({ audio_id: "" }))).toEqual({ ok: false, kind: "empty" });
    expect(readTrack(result({ parts: [] }))).toEqual({ ok: false, kind: "empty" });
  });

  it("drops a part that lacks an id or a name", () => {
    const parsed = readTrack(result({ parts: [...PARTS, { id: 5 }, { name: "x" }, null] }));
    expect(parsed).toMatchObject({ ok: true, track: { parts: PARTS } });
  });
});

describe("readRequest", () => {
  it("reads the options the tool call was made with", () => {
    const request = readRequest({
      musicxml: "<score-partwise/>",
      measures: [17, 24],
      repeat: 2,
      count_in_bars: 1,
      timbre: "choir",
      tempo_factor: 0.75,
    });
    expect(request).toMatchObject({ measures: [17, 24], repeat: 2, countInBars: 1, timbre: "choir" });
  });

  it("defaults every option to the server's default", () => {
    expect(readRequest({ musicxml_path: "/s.xml" })).toMatchObject({
      measures: undefined,
      repeat: 1,
      countInBars: 0,
      timbre: "score",
    });
  });

  it("ignores a malformed measures range or an unknown timbre", () => {
    expect(readRequest({ measures: [3], timbre: "kazoo" })).toMatchObject({ measures: undefined, timbre: "score" });
    expect(readRequest({ measures: ["a", "b"] }).measures).toBeUndefined();
    expect(readRequest({ measures: [9, 2] }).measures).toBeUndefined();
  });

  it("carries the score and the options a re-render must keep, not the mix", () => {
    const request = readRequest({
      musicxml: "<x/>",
      parts: ["P1"],
      part_gains: { P1: 2 },
      preset: "learning",
      focus_part: "P1",
      output_path: "out.wav",
      tempo_factor: 0.5,
      measures: [1, 4],
      metronome: true,
    });
    expect(request.carried).toEqual({ musicxml: "<x/>", measures: [1, 4], metronome: true });
  });
});

describe("renderArgs", () => {
  const request = readRequest({ musicxml_path: "/s.xml", measures: [17, 24], repeat: 2, count_in_bars: 1, timbre: "choir" });

  it("repeats the original call with the mix, the tempo and the options", () => {
    const mixer = toggleMute(setVolume(fromTrackParts(PARTS), "P1", 1.5), "P2");
    expect(renderArgs(request, mixer, 0.75, { countInBars: 2, timbre: "piano" })).toEqual({
      musicxml_path: "/s.xml",
      measures: [17, 24],
      repeat: 2,
      part_gains: { P1: 1.5, P2: 0 },
      tempo_factor: 0.75,
      count_in_bars: 2,
      timbre: "piano",
    });
  });

  it("sends count_in_bars 0 explicitly, so a toggle off removes the clicks", () => {
    expect(renderArgs(request, fromTrackParts(PARTS), 1, { countInBars: 0, timbre: "score" })).toMatchObject({
      count_in_bars: 0,
      timbre: "score",
    });
  });

  it("clamps the tempo to the server's range", () => {
    expect(renderArgs(request, fromTrackParts(PARTS), 9, { countInBars: 0, timbre: "score" }).tempo_factor).toBe(4);
  });
});

describe("barsLabel", () => {
  it("names the measures the loop is bound to", () => {
    expect(barsLabel([17, 24])).toBe("bars 17 to 24");
    expect(barsLabel([5, 5])).toBe("bar 5");
    expect(barsLabel(undefined)).toBe("the whole piece");
  });
});

describe("contextMessage", () => {

  it("is a fixed template over ids and numbers, never score text", () => {
    const mixer = toggleMute(fromTrackParts(PARTS), "P2");
    const text = contextMessage({ mixer, tempo: 0.75, loop: true, measures: [17, 24], countInBars: 1 });
    expect(text).toBe(
      "Practice Player: tempo 75 %, loop on (bars 17 to 24), count-in 1 bar, parts playing: P1; muted: P2.",
    );
  });

  it("names the soloed parts", () => {
    const mixer = { ...fromTrackParts(PARTS), solo: ["P1"] };
    expect(contextMessage({ mixer, tempo: 1, loop: false, measures: undefined, countInBars: 0 })).toBe(
      "Practice Player: tempo 100 %, loop off, count-in off, solo: P1.",
    );
  });
});

describe("readStartingPitches", () => {
  it("takes the text and the inline clip", () => {
    const parsed = readStartingPitches({
      structuredContent: { text: "S: D5, A: A4" },
      content: [
        { type: "text", text: "{}" },
        { type: "audio", data: "AAAA", mimeType: "audio/wav" },
      ],
    });
    expect(parsed).toEqual({ text: "S: D5, A: A4", audioUrl: "data:audio/wav;base64,AAAA" });
  });

  it("reads the text from the JSON block when there is no structured content", () => {
    const parsed = readStartingPitches({ content: [{ type: "text", text: JSON.stringify({ text: "S: D5" }) }] });
    expect(parsed).toEqual({ text: "S: D5" });
  });

  it("has nothing for a result without a text", () => {
    expect(readStartingPitches({ content: [] })).toBeUndefined();
    expect(readStartingPitches({ isError: true, content: [] })).toBeUndefined();
  });
});
