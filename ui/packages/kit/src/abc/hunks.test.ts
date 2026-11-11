import { describe, expect, it } from "vitest";
import { computeHunks, mergeHunks } from "./hunks";

const all = (n: number) => new Set(Array.from({ length: n }, (_, i) => i));

function expectRoundTrip(original: string, proposed: string): void {
  const hunks = computeHunks(original, proposed);
  expect(mergeHunks(original, hunks, all(hunks.length))).toBe(proposed);
  expect(mergeHunks(original, hunks, new Set())).toBe(original);
}

describe("computeHunks", () => {
  it("returns no hunks for identical texts", () => {
    expect(computeHunks("X:1\nK:C\nCDEF", "X:1\nK:C\nCDEF")).toEqual([]);
  });

  it("describes a single changed line", () => {
    expect(computeHunks("a\nb\nc", "a\nB\nc")).toEqual([
      { id: 0, originalLines: ["b"], proposedLines: ["B"], originalStart: 1 },
    ]);
  });

  it("separates distant changes into several hunks with sequential ids", () => {
    const hunks = computeHunks("a\nb\nc\nd\ne", "A\nb\nc\nd\nE");
    expect(hunks.map((h) => [h.id, h.originalStart])).toEqual([[0, 0], [1, 4]]);
  });

  it("keeps adjacent changed lines in one hunk", () => {
    const hunks = computeHunks("a\nb\nc\nd", "a\nB\nC\nd");
    expect(hunks).toHaveLength(1);
    expect(hunks[0]?.originalLines).toEqual(["b", "c"]);
    expect(hunks[0]?.proposedLines).toEqual(["B", "C"]);
  });

  it("describes a pure insertion and a pure deletion", () => {
    expect(computeHunks("a\nc", "a\nb\nc")).toEqual([
      { id: 0, originalLines: [], proposedLines: ["b"], originalStart: 1 },
    ]);
    expect(computeHunks("a\nb\nc", "a\nc")).toEqual([
      { id: 0, originalLines: ["b"], proposedLines: [], originalStart: 1 },
    ]);
  });
});

describe("mergeHunks", () => {
  it("accepting all hunks equals the proposed text", () => {
    expectRoundTrip("a\nb\nc\nd\ne", "A\nb\nc\nd\nE");
  });

  it("accepting none equals the original text", () => {
    const original = "a\nb\nc";
    expect(mergeHunks(original, computeHunks(original, "x\ny"), new Set())).toBe(original);
  });

  it("applies only the accepted subset", () => {
    const original = "a\nb\nc\nd\ne";
    const hunks = computeHunks(original, "A\nb\nc\nd\nE");
    expect(mergeHunks(original, hunks, new Set([1]))).toBe("a\nb\nc\nd\nE");
    expect(mergeHunks(original, hunks, new Set([0]))).toBe("A\nb\nc\nd\ne");
  });

  it("handles identical texts", () => {
    expectRoundTrip("a\nb", "a\nb");
  });

  it("handles an empty original", () => {
    expectRoundTrip("", "X:1\nK:C");
  });

  it("handles an empty proposed text", () => {
    expectRoundTrip("X:1\nK:C", "");
  });

  it("handles trailing newline differences", () => {
    expectRoundTrip("a\nb", "a\nb\n");
    expectRoundTrip("a\nb\n", "a\nb");
  });

  it("handles adjacent and separated hunks together", () => {
    expectRoundTrip("a\nb\nc\nd\ne\nf", "a\nB\nC\nd\ne\nF\ng");
  });
});
