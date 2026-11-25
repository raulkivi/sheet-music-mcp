import { describe, expect, it } from "vitest";
import { Playhead, barNumbers, type TimemapEntry } from "./playhead.ts";

// What Verovio's renderToTimemap({ includeMeasures: true }) returns for two bars of two notes.
const ENTRIES: TimemapEntry[] = [
  { tstamp: 0, measureOn: "m1", on: ["n1", "n2"] },
  { tstamp: 500, off: ["n1"], on: ["n3"] },
  { tstamp: 1000, off: ["n2", "n3"], measureOn: "m2", on: ["n4"] },
  { tstamp: 1500, off: ["n4"] },
];

describe("Playhead", () => {
  const playhead = new Playhead(ENTRIES);

  it("knows the length of the music", () => {
    expect(playhead.durationMs).toBe(1500);
  });

  it("reports the notes sounding and the bar at a time", () => {
    expect(playhead.at(0)).toEqual({ notes: ["n1", "n2"], measure: "m1", bar: 0 });
    expect(playhead.at(499)).toEqual({ notes: ["n1", "n2"], measure: "m1", bar: 0 });
    expect(playhead.at(500)).toEqual({ notes: ["n2", "n3"], measure: "m1", bar: 0 });
    expect(playhead.at(1200)).toEqual({ notes: ["n4"], measure: "m2", bar: 1 });
  });

  it("keeps the last bar once every note has ended", () => {
    expect(playhead.at(1500)).toEqual({ notes: [], measure: "m2", bar: 1 });
    expect(playhead.at(99999)).toEqual({ notes: [], measure: "m2", bar: 1 });
  });

  it("clamps a time before the music to its start", () => {
    expect(playhead.at(-5)?.measure).toBe("m1");
  });

  it("has no position for an empty timemap", () => {
    const empty = new Playhead([]);
    expect(empty.durationMs).toBe(0);
    expect(empty.at(10)).toBeUndefined();
  });

  it("sorts entries by time, so an unordered timemap still works", () => {
    expect(new Playhead([...ENTRIES].reverse()).at(1200)).toEqual(playhead.at(1200));
  });
});

describe("barNumbers", () => {
  it("lists the printed numbers of the first part's bars, pickup included", () => {
    const xml = `<score-partwise><part-list/>
      <part id="P1"><measure number="0"/><measure number="1"/><measure number="2a"/></part>
      <part id="P2"><measure number="0"/><measure number="9"/></part></score-partwise>`;
    expect(barNumbers(xml)).toEqual(["0", "1", "2a"]);
  });

  it("is empty for a score without bars", () => {
    expect(barNumbers("<score-partwise/>")).toEqual([]);
  });
});
