import { describe, expect, it } from "vitest";
import {
  TEMPO_MAX,
  TEMPO_MIN,
  audioSeconds,
  clampTempo,
  countInSeconds,
  loopBounds,
  playbackRate,
  scoreSeconds,
  tempoPercent,
} from "./tempo.ts";

describe("clampTempo", () => {
  it("keeps the server's 25 % to 400 % range", () => {
    expect([TEMPO_MIN, TEMPO_MAX]).toEqual([0.25, 4]);
    expect(clampTempo(0.1)).toBe(0.25);
    expect(clampTempo(9)).toBe(4);
    expect(clampTempo(0.75)).toBe(0.75);
  });

  it("falls back to the score tempo for a value that is not a number", () => {
    expect(clampTempo(Number.NaN)).toBe(1);
  });
});

describe("tempoPercent", () => {
  it("rounds to whole percent", () => {
    expect(tempoPercent(0.755)).toBe(76);
    expect(tempoPercent(1)).toBe(100);
  });
});

describe("playbackRate", () => {
  it("is the wanted tempo over the tempo the track was rendered at", () => {
    expect(playbackRate(0.75, 1)).toBe(0.75);
    expect(playbackRate(1, 0.5)).toBe(2);
    expect(playbackRate(0.5, 0.5)).toBe(1);
  });

  it("clamps the wanted tempo first", () => {
    expect(playbackRate(10, 1)).toBe(4);
  });
});

describe("audioSeconds and scoreSeconds (AC-S5)", () => {
  it("a track rendered at tempo 0.5 places a loop start at 2x its score time", () => {
    expect(audioSeconds(4, 0.5, 0)).toBe(8);
  });

  it("adds the count-in before the music", () => {
    expect(audioSeconds(4, 1, 2)).toBe(6);
  });

  it("is the inverse of audioSeconds inside the music", () => {
    expect(scoreSeconds(8, 0.5, 0, 100)).toBe(4);
    expect(scoreSeconds(6, 1, 2, 100)).toBe(4);
  });

  it("is undefined during the count-in", () => {
    expect(scoreSeconds(1, 1, 2, 100)).toBeUndefined();
  });

  it("wraps into the music for a track that repeats it", () => {
    expect(scoreSeconds(12, 1, 2, 5)).toBe(0);
    expect(scoreSeconds(13, 1, 2, 5)).toBe(1);
  });
});

describe("loopBounds", () => {
  it("loops from the end of the count-in to the end of the audio", () => {
    expect(loopBounds(2.5, 20)).toEqual({ start: 2.5, end: 20 });
  });

  it("never starts after the end", () => {
    expect(loopBounds(30, 20)).toEqual({ start: 0, end: 20 });
  });
});

const xml = (time: string, tempo: string) =>
  `<score-partwise><part id="P1"><measure number="1"><attributes><time>${time}</time></attributes>${tempo}</measure></part></score-partwise>`;

describe("countInSeconds", () => {
  it("is bars x beats x seconds per beat at the rendered tempo", () => {
    const score = xml("<beats>4</beats><beat-type>4</beat-type>", '<sound tempo="120"/>');
    expect(countInSeconds(score, 1, 1)).toBe(2);
    expect(countInSeconds(score, 2, 1)).toBe(4);
    expect(countInSeconds(score, 1, 0.5)).toBe(4);
  });

  it("measures a bar in quarter notes: 6/8 is three of them", () => {
    const score = xml("<beats>6</beats><beat-type>8</beat-type>", '<sound tempo="60"/>');
    expect(countInSeconds(score, 1, 1)).toBe(3);
  });

  it("reads a metronome mark when there is no sound tempo, and assumes 120 BPM with neither", () => {
    expect(
      countInSeconds(xml("<beats>2</beats><beat-type>4</beat-type>", "<metronome><per-minute>60</per-minute></metronome>"), 1, 1),
    ).toBe(2);
    expect(countInSeconds(xml("<beats>4</beats><beat-type>4</beat-type>", ""), 1, 1)).toBe(2);
  });

  it("is zero without count-in bars, and assumes 4/4 without a time signature", () => {
    expect(countInSeconds(xml("<beats>4</beats><beat-type>4</beat-type>", ""), 0, 1)).toBe(0);
    expect(countInSeconds('<score-partwise><part id="P1"><measure number="1"/></part></score-partwise>', 1, 1)).toBe(2);
  });
});
