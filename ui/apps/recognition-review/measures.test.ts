import { describe, expect, it } from "vitest";
import { measureIndex } from "./measures.ts";

const XML = '<score-partwise><part id="P1"><measure number="1"/><measure number="2" width="3"/><measure number="3"/></part><part id="P2"><measure number="9"/></part></score-partwise>';

describe("measureIndex", () => {
  it("finds a printed bar among the first part's measures", () => {
    expect(measureIndex(XML, 1)).toBe(0);
    expect(measureIndex(XML, 3)).toBe(2);
  });

  it("is undefined for a bar the first part does not have, or for no part", () => {
    expect(measureIndex(XML, 9)).toBeUndefined();
    expect(measureIndex("<score-partwise/>", 1)).toBeUndefined();
  });
});
