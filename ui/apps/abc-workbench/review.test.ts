import { describe, expect, it } from "vitest";
import {
  acceptedIds,
  mergedText,
  newReview,
  rejectedHunks,
  reviewRows,
  selectAll,
  selectNone,
  toggleHunk,
  withProposed,
} from "./review.ts";

const ORIGINAL = ["X:1", "K:C", "abc|", "def|", "ghi|", "z4|"].join("\n");
const PROPOSED = ["X:1", "K:C", "abe|", "def|", "ghi|", "z2G2|"].join("\n");

describe("review selection", () => {
  it("starts with every proposed change accepted", () => {
    const review = newReview(ORIGINAL, PROPOSED);
    expect(review.hunks).toHaveLength(2);
    expect([...acceptedIds(review)]).toEqual([0, 1]);
    expect(mergedText(review)).toBe(PROPOSED);
  });

  it("accepting none gives the original, and one toggle gives one change", () => {
    let review = selectNone(newReview(ORIGINAL, PROPOSED));
    expect(mergedText(review)).toBe(ORIGINAL);
    review = toggleHunk(review, 1);
    expect(mergedText(review)).toBe(["X:1", "K:C", "abc|", "def|", "ghi|", "z2G2|"].join("\n"));
    expect(mergedText(selectAll(review))).toBe(PROPOSED);
  });

  it("lists the rejected changes by number and original line", () => {
    const review = toggleHunk(newReview(ORIGINAL, PROPOSED), 1);
    expect(rejectedHunks(review)).toEqual([{ number: 2, originalLine: 6 }]);
  });

  it("has no changes when the proposal equals the original", () => {
    const review = newReview(ORIGINAL, ORIGINAL);
    expect(review.hunks).toEqual([]);
    expect(mergedText(review)).toBe(ORIGINAL);
  });

  it("keeps a rejection when the proposal is edited elsewhere", () => {
    const rejected = toggleHunk(newReview(ORIGINAL, PROPOSED), 1);
    const edited = withProposed(rejected, PROPOSED.replace("K:C", "K:C\nM:4/4"));
    expect(edited.hunks.length).toBe(2);
    expect(mergedText(edited)).toContain("z4|");
    expect(mergedText(edited)).toContain("abe|");
  });

  it("accepts a change that is new after an edit", () => {
    const review = withProposed(newReview(ORIGINAL, ORIGINAL), PROPOSED);
    expect([...acceptedIds(review)]).toEqual([0, 1]);
  });
});

describe("reviewRows", () => {
  it("shows only the changes, numbered, in 'changes' layout", () => {
    const rows = reviewRows(newReview(ORIGINAL, PROPOSED), "changes");
    expect(rows.map((row) => row.kind)).toEqual(["hunk", "hunk"]);
    expect(rows[1]).toMatchObject({ kind: "hunk", number: 2, total: 2, accepted: true, originalLines: ["z4|"], proposedLines: ["z2G2|"], firstLine: 6 });
  });

  it("interleaves the unchanged lines in 'full' layout", () => {
    const rows = reviewRows(newReview(ORIGINAL, PROPOSED), "full");
    expect(rows.map((row) => (row.kind === "context" ? row.text : `hunk ${row.number}`))).toEqual(["X:1", "K:C", "hunk 1", "def|", "ghi|", "hunk 2"]);
  });
});
