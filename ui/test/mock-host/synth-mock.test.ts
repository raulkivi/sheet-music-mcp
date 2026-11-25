import { describe, expect, it } from "vitest";
import { createSynthMock, SYNTH_TOOLS } from "./synth-mock.ts";

const SCORE = `<score-partwise>
  <part-list>
    <score-part id="P1"><part-name>Soprano</part-name></score-part>
    <score-part id="P2"><part-name>Alto</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1"><attributes><time><beats>4</beats><beat-type>4</beat-type></time></attributes><sound tempo="120"/></measure>
    <measure number="2"/>
  </part>
  <part id="P2"><measure number="1"/><measure number="2"/></part>
</score-partwise>`;

function data(result: { structuredContent?: unknown }) {
  return result.structuredContent as Record<string, any>;
}

async function chunkAll(mock: ReturnType<typeof createSynthMock>, id: string, length: number) {
  const bytes: number[] = [];
  for (let offset = 0; ; ) {
    const part = data(await mock.callTool({ name: "read_audio_chunk", arguments: { audio_id: id, offset, length } }));
    bytes.push(...Buffer.from(part.data_b64, "base64"));
    offset += part.length;
    if (part.eof) return Buffer.from(bytes);
  }
}

describe("synth mock", () => {
  it("lists the tools it answers", () => {
    expect([...SYNTH_TOOLS].sort()).toEqual(["get_score_xml", "read_audio_chunk", "starting_pitches", "synthesize"]);
  });

  it("synthesize answers in the server's structuredContent shape", async () => {
    const mock = createSynthMock();
    const track = data(await mock.callTool({ name: "synthesize", arguments: { musicxml: SCORE } }));
    expect(track).toMatchObject({
      sample_rate: 8000,
      channels: 1,
      tempo_factor: 1,
      parts: [
        { id: "P1", name: "Soprano", included: true, gain: 1 },
        { id: "P2", name: "Alto", included: true, gain: 1 },
      ],
    });
    expect(track.audio_id).toMatch(/^audio-/);
    expect(track.duration_seconds).toBe(4); // two 4/4 bars at 120 BPM
  });

  it("applies part_gains, tempo_factor, repeat and count-in to the answer", async () => {
    const mock = createSynthMock();
    const track = data(
      await mock.callTool({
        name: "synthesize",
        arguments: { musicxml: SCORE, part_gains: { P2: 0 }, tempo_factor: 0.5, repeat: 2, count_in_bars: 1 },
      }),
    );
    expect(track.parts.map((part: { gain: number; included: boolean }) => [part.gain, part.included])).toEqual([
      [1, true],
      [0, true],
    ]);
    expect(track.tempo_factor).toBe(0.5);
    expect(track.duration_seconds).toBe((2 + 4 * 2) / 0.5);
  });

  it("gives each render its own id, and serves a valid WAV in chunks that add up to it", async () => {
    const mock = createSynthMock();
    const first = data(await mock.callTool({ name: "synthesize", arguments: { musicxml: SCORE } }));
    const second = data(await mock.callTool({ name: "synthesize", arguments: { musicxml: SCORE } }));
    expect(second.audio_id).not.toBe(first.audio_id);
    const whole = await chunkAll(mock, first.audio_id, 1_000_000);
    const pieces = await chunkAll(mock, first.audio_id, 7_000);
    expect(pieces.equals(whole)).toBe(true);
    expect(whole.subarray(0, 4).toString()).toBe("RIFF");
    expect(whole.length).toBe(first.byte_length);
    expect(whole.readUInt32LE(24)).toBe(8000);
  });

  it("answers an unknown audio id with the server's INVALID_PARAMETER envelope", async () => {
    const mock = createSynthMock();
    for (const call of [
      { name: "read_audio_chunk", arguments: { audio_id: "nope", offset: 0, length: 10 } },
      { name: "get_score_xml", arguments: { audio_id: "nope" } },
    ]) {
      const result = await mock.callTool(call);
      expect(result.isError).toBe(true);
      expect(JSON.parse((result.content![0] as { text: string }).text)).toMatchObject({ error_code: "INVALID_PARAMETER" });
    }
  });

  it("get_score_xml returns the score the track was rendered from", async () => {
    const mock = createSynthMock();
    const track = data(await mock.callTool({ name: "synthesize", arguments: { musicxml: SCORE } }));
    const score = data(await mock.callTool({ name: "get_score_xml", arguments: { audio_id: track.audio_id } }));
    expect(score).toEqual({ audio_id: track.audio_id, musicxml: SCORE });
  });

  it("starting_pitches gives text and an inline clip", async () => {
    const result = await createSynthMock().callTool({ name: "starting_pitches", arguments: { musicxml: SCORE } });
    const blocks = result.content as { type: string; text?: string; mimeType?: string }[];
    expect(JSON.parse(blocks[0]?.text ?? "{}").text).toBe("Soprano: D5, Alto: A4");
    expect(blocks[1]).toMatchObject({ type: "audio", mimeType: "audio/wav" });
  });

  it("rejects a score that is not MusicXML like the server does", async () => {
    const result = await createSynthMock().callTool({ name: "synthesize", arguments: { musicxml: "hi" } });
    expect(JSON.parse((result.content![0] as { text: string }).text)).toMatchObject({ error_code: "INVALID_INPUT" });
  });
});
