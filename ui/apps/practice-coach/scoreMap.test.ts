import { describe, expect, it } from "vitest";
import { countMeasures, cursorFraction, locateMeasure, parseScoreStructure } from "./scoreMap.ts";

const XML = `<score-partwise>
<part-list><score-part id="P1"/></part-list>
<part id="P1">
  <measure number="0"><attributes><time><beats>3</beats><beat-type>4</beat-type></time></attributes></measure>
  <measure number="1"/><measure number="2"/>
</part>
<part id="P2"><measure number="1"/></part>
</score-partwise>`;

describe("parseScoreStructure", () => {
  it("lists the first part's bar numbers in order and reads the beats per bar", () => {
    expect(parseScoreStructure(XML)).toEqual({ measureNumbers: ["0", "1", "2"], beatsPerMeasure: 3 });
  });

  it("defaults to four beats when no time signature is written", () => {
    expect(parseScoreStructure('<score-partwise><part id="P1"><measure number="1"/></part></score-partwise>')).toEqual({
      measureNumbers: ["1"],
      beatsPerMeasure: 4,
    });
  });

  it("finds nothing in text that is not a score", () => {
    expect(parseScoreStructure("hello")).toEqual({ measureNumbers: [], beatsPerMeasure: 4 });
  });
});

describe("cursorFraction", () => {
  it("is how far into the bar a beat lies", () => {
    expect(cursorFraction(1, 4)).toBe(0);
    expect(cursorFraction(3, 4)).toBe(0.5);
    expect(cursorFraction(2.5, 3)).toBe(0.5);
  });
  it("stays inside the bar", () => {
    expect(cursorFraction(0, 4)).toBe(0);
    expect(cursorFraction(9, 4)).toBeLessThan(1);
  });
});

describe("countMeasures", () => {
  it("counts Verovio's measure groups in a page", () => {
    const svg = '<svg><g class="system"><g id="m1" class="measure"/><g id="m2" class="measure"/><g class="measureXX"/></g></svg>';
    expect(countMeasures(svg)).toBe(2);
    expect(countMeasures("<svg/>")).toBe(0);
  });
});

describe("locateMeasure", () => {
  const numbers = ["1", "2", "3", "4", "5"];
  it("maps a printed bar number to its page and its place on the page", () => {
    expect(locateMeasure(1, numbers, [2, 3])).toEqual({ page: 1, index: 0 });
    expect(locateMeasure(2, numbers, [2, 3])).toEqual({ page: 1, index: 1 });
    expect(locateMeasure(3, numbers, [2, 3])).toEqual({ page: 2, index: 0 });
    expect(locateMeasure(5, numbers, [2, 3])).toEqual({ page: 2, index: 2 });
  });
  it("is undefined for a bar the score does not have or the pages do not show", () => {
    expect(locateMeasure(9, numbers, [2, 3])).toBeUndefined();
    expect(locateMeasure(5, numbers, [2, 2])).toBeUndefined();
    expect(locateMeasure(1, numbers, [])).toBeUndefined();
  });
  it("matches numbers as numbers, so a pickup bar 0 is found", () => {
    expect(locateMeasure(0, ["0", "1"], [2])).toEqual({ page: 1, index: 0 });
  });
});
