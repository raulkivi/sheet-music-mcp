import { describe, expect, it } from "vitest";
import { engineLabel, otherEngine, staffAdvice } from "./advice.ts";

describe("staffAdvice (G2: only from the server's own numbers)", () => {
  it("AC-O3: the page looks like 4 staves, 1 part found with oemer: advises Audiveris", () => {
    expect(staffAdvice({ estimate: 4, detected: 1, engine: "oemer" })).toBe(
      "Detected 1 part, but the page looks like it has 4 staves. Try the Audiveris engine, which keeps SATB voices apart.",
    );
  });

  it("pluralizes parts", () => {
    expect(staffAdvice({ estimate: 4, detected: 2, engine: "oemer" })).toMatch(/^Detected 2 parts, but/);
  });

  it("with Audiveris already used, asks for a check against the photo instead", () => {
    expect(staffAdvice({ estimate: 4, detected: 3, engine: "audiveris" })).toBe(
      "Detected 3 parts, but the page looks like it has 4 staves. Audiveris was already used: check the voices against the photo.",
    );
  });

  it("says nothing when the counts agree, the estimate is lower, or a number is missing", () => {
    expect(staffAdvice({ estimate: 4, detected: 4, engine: "oemer" })).toBeUndefined();
    expect(staffAdvice({ estimate: 2, detected: 4, engine: "oemer" })).toBeUndefined();
    expect(staffAdvice({ estimate: undefined, detected: 1, engine: "oemer" })).toBeUndefined();
    expect(staffAdvice({ estimate: 4, detected: undefined, engine: "oemer" })).toBeUndefined();
    expect(staffAdvice({ estimate: 0, detected: 0, engine: "oemer" })).toBeUndefined();
  });
});

describe("engines", () => {
  it("switches between the two engines", () => {
    expect(otherEngine("oemer")).toBe("audiveris");
    expect(otherEngine("audiveris")).toBe("oemer");
    expect(otherEngine("something-new")).toBe("audiveris");
  });

  it("names them for people", () => {
    expect(engineLabel("audiveris")).toBe("Audiveris");
    expect(engineLabel("oemer")).toBe("oemer");
    expect(engineLabel("other")).toBe("other");
  });
});
