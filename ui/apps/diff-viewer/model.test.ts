import { describe, expect, it } from "vitest";
import {
  describeChange,
  kindsPresent,
  measureTarget,
  readDiff,
  selectionSummary,
  summaryLine,
  visibleChanges,
  type Change,
} from "./model.ts";

const note = (pitch: string) => ({ pitch, duration: 1, is_rest: false });

function change(over: Partial<Change> = {}): Change {
  return {
    operation: "PITCH_CHANGE",
    measure_number: 19,
    beat: 1,
    voice: 1,
    part_name: "Soprano",
    reference: note("E4"),
    target: note("A4"),
    interval_error: 5,
    ...over,
  };
}

const SUMMARY = { notes_identical: 380 };

describe("readDiff", () => {
  it("reads similarity, summary, changes, report and the id of the scores", () => {
    const result = readDiff({
      detail: "full",
      similarity_score: 0.984,
      summary: SUMMARY,
      changes: [change()],
      report: "Overall similarity: 98%",
      diff_id: "abc",
    });
    expect(result).toEqual({
      ok: true,
      diff: {
        similarity: 0.984,
        summary: SUMMARY,
        changes: [change()],
        report: "Overall similarity: 98%",
        diffId: "abc",
      },
    });
  });

  it("leaves out what the detail level did not return", () => {
    const result = readDiff({ detail: "summary", similarity_score: 1, summary: SUMMARY });
    expect(result).toEqual({ ok: true, diff: { similarity: 1, summary: SUMMARY } });
  });

  it("sorts changes by measure, then part order of arrival, then beat", () => {
    const late = change({ measure_number: 20 });
    const early = change({ measure_number: 3, beat: 2 });
    const earlier = change({ measure_number: 3, beat: 1 });
    const result = readDiff({ similarity_score: 0.5, summary: SUMMARY, changes: [late, early, earlier] });
    expect(result.ok && result.diff.changes).toEqual([earlier, early, late]);
  });

  it.each([undefined, null, "x", {}, { similarity_score: "1", summary: {} }, { similarity_score: 1 }])(
    "rejects %j",
    (data) => {
      expect(readDiff(data as never)).toEqual({ ok: false });
    },
  );

  it("drops changes that lack a measure or an operation", () => {
    const result = readDiff({
      similarity_score: 0.5,
      summary: SUMMARY,
      changes: [change(), { operation: "PITCH_CHANGE" }, "x", null],
    });
    expect(result.ok && result.diff.changes).toEqual([change()]);
  });
});

describe("kindsPresent", () => {
  it("lists only the operations that occur, with counts, known kinds first", () => {
    const changes = [
      change({ operation: "DELETION" }),
      change({ operation: "PITCH_CHANGE" }),
      change({ operation: "DELETION" }),
    ];
    expect(kindsPresent(changes)).toEqual([
      { kind: "PITCH_CHANGE", label: "Pitch changed", count: 1 },
      { kind: "DELETION", label: "Removed", count: 2 },
    ]);
  });

  it("labels an operation the viewer does not know from its name", () => {
    expect(kindsPresent([change({ operation: "TRANSPOSITION_SHIFT" })])).toEqual([
      { kind: "TRANSPOSITION_SHIFT", label: "Transposition shift", count: 1 },
    ]);
  });

  it("is empty for no changes", () => {
    expect(kindsPresent([])).toEqual([]);
  });
});

describe("visibleChanges", () => {
  const all = [change({ operation: "PITCH_CHANGE" }), change({ operation: "DELETION", measure_number: 4 })];

  it("shows everything while no kind is selected", () => {
    expect(visibleChanges(all, new Set())).toEqual(all);
  });

  it("shows only the selected kinds", () => {
    expect(visibleChanges(all, new Set(["DELETION"]))).toEqual([all[1]]);
  });
});

describe("describeChange", () => {
  it("says what the pitch was and became", () => {
    expect(describeChange(change())).toBe("Soprano, bar 19, beat 1: E4 to A4 (pitch changed)");
  });

  it("says a note was removed or added", () => {
    expect(describeChange(change({ operation: "DELETION", target: null }))).toBe(
      "Soprano, bar 19, beat 1: E4 removed",
    );
    expect(describeChange(change({ operation: "INSERTION", reference: null, target: note("G4") }))).toBe(
      "Soprano, bar 19, beat 1: G4 added",
    );
  });

  it("names a rest as a rest", () => {
    expect(
      describeChange(change({ operation: "SUBSTITUTION", reference: { pitch: "rest", duration: 1, is_rest: true } })),
    ).toBe("Soprano, bar 19, beat 1: rest to A4 (replaced)");
  });

  it("rounds a fractional beat", () => {
    expect(describeChange(change({ beat: 2.5 }))).toContain("beat 2.5");
    expect(describeChange(change({ beat: 1.3333333 }))).toContain("beat 1.33");
  });
});

describe("selection", () => {
  it("targets the measure of the change in both scores", () => {
    expect(measureTarget(change({ measure_number: 19 }))).toBe(19);
  });

  it("summarizes the selection for a screen reader", () => {
    expect(selectionSummary(change(), 1, 4)).toBe(
      "Change 2 of 4. Soprano, bar 19, beat 1: E4 to A4 (pitch changed). Both scores show bar 19.",
    );
  });
});

describe("summaryLine", () => {
  it("gives similarity and change count", () => {
    expect(summaryLine(0.984, 4)).toBe("98.4% similar, 4 changes");
    expect(summaryLine(1, 0)).toBe("100% similar, no changes");
    expect(summaryLine(0.5, 1)).toBe("50% similar, 1 change");
  });

  it("does not claim identity when rounding reaches 100", () => {
    expect(summaryLine(0.9996, 1)).toBe("99.9% similar, 1 change");
  });

  it("leaves the change count out when the detail level had no changes", () => {
    expect(summaryLine(0.75, undefined)).toBe("75% similar");
  });
});
