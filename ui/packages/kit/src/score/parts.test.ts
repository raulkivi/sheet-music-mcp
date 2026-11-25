import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { dimmedStaffIndexes, filterParts, listParts } from "./parts.ts";

const SATB = readFileSync(new URL("../../../../test/fixtures/satb-4bars.musicxml", import.meta.url), "utf8");

const PIANO_AND_VOICE = `<?xml version="1.0"?>
<score-partwise version="4.0">
  <part-list>
    <part-group type="start" number="1"/>
    <score-part id="P1"><part-name>Piano &amp; Keys</part-name></score-part>
    <score-part id="P2"><part-name>Voice</part-name></score-part>
    <part-group type="stop" number="1"/>
  </part-list>
  <part id="P1"><measure number="1"><attributes><staves>2</staves></attributes></measure></part>
  <part id="P2"><measure number="1"><attributes><clef><sign>G</sign></clef></attributes></measure></part>
</score-partwise>`;

describe("listParts", () => {
  it("lists the parts in score order with their names", () => {
    expect(listParts(SATB).map(({ id, name }) => [id, name])).toEqual([
      ["P1", "Soprano"],
      ["P2", "Alto"],
      ["P3", "Tenor"],
      ["P4", "Bass"],
    ]);
  });

  it("counts staves and numbers the first staff of each part from 0", () => {
    expect(listParts(PIANO_AND_VOICE)).toEqual([
      { id: "P1", name: "Piano & Keys", staves: 2, firstStaff: 0 },
      { id: "P2", name: "Voice", staves: 1, firstStaff: 2 },
    ]);
  });

  it("falls back to the id when a part has no name", () => {
    expect(listParts('<score-partwise><part-list><score-part id="X1"></score-part></part-list><part id="X1"><measure number="1"/></part></score-partwise>')).toEqual([
      { id: "X1", name: "X1", staves: 1, firstStaff: 0 },
    ]);
  });

  it("lists nothing for a timewise score, garbage or an empty string", () => {
    expect(listParts("<score-timewise><part-list><score-part id='P1'/></part-list></score-timewise>")).toEqual([]);
    expect(listParts("not xml")).toEqual([]);
    expect(listParts("")).toEqual([]);
  });
});

describe("filterParts", () => {
  it("keeps only the chosen parts, in both the part list and the music", () => {
    const filtered = filterParts(SATB, ["P2", "P4"]);
    expect(listParts(filtered).map((part) => part.id)).toEqual(["P2", "P4"]);
    expect(filtered).toContain('<part id="P2">');
    expect(filtered).not.toContain('<part id="P1">');
    expect(filtered).not.toContain("Soprano");
    expect(filtered).toContain("<step>A</step><octave>4</octave>");
  });

  it("keeps the score's own order whatever the order asked for", () => {
    expect(listParts(filterParts(SATB, ["P4", "P2"])).map((part) => part.id)).toEqual(["P2", "P4"]);
  });

  it("returns the score untouched for no choice, every part, or only unknown ids", () => {
    expect(filterParts(SATB, [])).toBe(SATB);
    expect(filterParts(SATB, ["P1", "P2", "P3", "P4"])).toBe(SATB);
    expect(filterParts(SATB, ["P9"])).toBe(SATB);
  });

  it("ignores unknown ids next to known ones", () => {
    expect(listParts(filterParts(SATB, ["P3", "P9"])).map((part) => part.id)).toEqual(["P3"]);
  });

  it("is not fooled by an id that only starts like another", () => {
    const xml = `<score-partwise><part-list><score-part id="P1"><part-name>A</part-name></score-part><score-part id="P10"><part-name>B</part-name></score-part></part-list><part id="P1"><measure number="1"/></part><part id="P10"><measure number="1"/></part></score-partwise>`;
    expect(listParts(filterParts(xml, ["P10"])).map((part) => part.id)).toEqual(["P10"]);
  });

  it("filters nothing out of a timewise score", () => {
    const xml = "<score-timewise><part-list><score-part id='P1'/></part-list></score-timewise>";
    expect(filterParts(xml, ["P1"])).toBe(xml);
  });
});

describe("dimmedStaffIndexes", () => {
  const parts = listParts(PIANO_AND_VOICE);

  it("dims every staff but the highlighted part's", () => {
    expect(dimmedStaffIndexes(parts, "P2")).toEqual([0, 1]);
    expect(dimmedStaffIndexes(parts, "P1")).toEqual([2]);
  });

  it("dims nothing without a highlight or for an unknown part", () => {
    expect(dimmedStaffIndexes(parts, null)).toEqual([]);
    expect(dimmedStaffIndexes(parts, "P9")).toEqual([]);
  });
});
