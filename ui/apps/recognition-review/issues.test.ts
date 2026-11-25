import { describe, expect, it } from "vitest";
import { issueSummary, readWarnings, selectionSummary, toIssues } from "./issues.ts";

describe("readWarnings", () => {
  it("keeps well-formed items and drops everything else", () => {
    const read = readWarnings([
      { code: "EMPTY_MEASURE", severity: "warning", message: "Measure 3 has no notes or rests", measure: 3, part: "P2" },
      { code: "X", severity: "error", message: "No place" },
      "text",
      null,
      { code: "NO_MESSAGE", severity: "warning" },
    ]);
    expect(read).toEqual([
      { code: "EMPTY_MEASURE", severity: "warning", message: "Measure 3 has no notes or rests", measure: 3, part: "P2" },
      { code: "X", severity: "error", message: "No place" },
    ]);
  });

  it("reads an unknown severity as info and ignores a bad measure or part", () => {
    expect(readWarnings([{ code: "A", severity: "fatal", message: "m", measure: -1, part: 4 }])).toEqual([
      { code: "A", severity: "info", message: "m" },
    ]);
    expect(readWarnings([{ code: "A", severity: "info", message: "m", measure: 1.5 }])[0]).not.toHaveProperty("measure");
  });

  it("returns an empty list for a value that is not a list", () => {
    expect(readWarnings(undefined)).toEqual([]);
    expect(readWarnings({})).toEqual([]);
  });
});

describe("toIssues", () => {
  const warnings = readWarnings([
    { code: "N", severity: "info", message: "Staves differ" },
    { code: "E", severity: "warning", message: "Measure 5 has no notes or rests", measure: 5, part: "P3" },
    { code: "F", severity: "error", message: "Bad", measure: 12 },
    { code: "G", severity: "warning", message: "Low resolution" },
  ]);

  it("orders errors first, then warnings, then notes, keeping the server order within a severity", () => {
    expect(toIssues(warnings).map((i) => i.code)).toEqual(["F", "E", "G", "N"]);
  });

  it("labels the severity in words, never by color alone", () => {
    expect(toIssues(warnings).map((i) => i.tag)).toEqual(["Must fix", "Check", "Check", "Note"]);
  });

  it("says where the issue is from the bar and part the server gave", () => {
    const where = Object.fromEntries(toIssues(warnings).map((i) => [i.code, i.where]));
    expect(where).toEqual({ F: "Bar 12", E: "Bar 5, part P3", G: "", N: "" });
  });

  it("carries the measure so the score can scroll to it", () => {
    expect(toIssues(warnings).find((i) => i.code === "E")?.measure).toBe(5);
    expect(toIssues(warnings).find((i) => i.code === "G")?.measure).toBeUndefined();
  });

  it("invents nothing for an empty list", () => {
    expect(toIssues([])).toEqual([]);
  });
});

describe("issueSummary", () => {
  it("counts in words", () => {
    expect(issueSummary(0)).toBe("Nothing to check.");
    expect(issueSummary(1)).toBe("1 thing to check.");
    expect(issueSummary(3)).toBe("3 things to check.");
  });
});

describe("selectionSummary", () => {
  const [located, general] = toIssues(
    readWarnings([
      { code: "E", severity: "warning", message: "Measure 5 has no notes or rests", measure: 5 },
      { code: "G", severity: "info", message: "Staves differ" },
    ]),
  );

  it("speaks the position, the issue and what the score shows", () => {
    expect(selectionSummary(located!, 0, 2)).toBe("Issue 1 of 2. Check: Measure 5 has no notes or rests. Showing bar 5 in the score.");
  });

  it("says so when the issue belongs to no bar", () => {
    expect(selectionSummary(general!, 1, 2)).toBe("Issue 2 of 2. Note: Staves differ. This applies to the whole page.");
  });
});
