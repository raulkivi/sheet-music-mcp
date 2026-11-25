// The review of a proposed ABC edit: which hunks the user keeps. Immutable, pure, built on the
// kit's hunk model (AC-A1: all accepted = proposed, none = original).

import { computeHunks, mergeHunks, type Hunk } from "@sheet-music-mcp/ui-kit/abc/hunks";

export interface Review {
  readonly original: string;
  readonly proposed: string;
  readonly hunks: readonly Hunk[];
  /** Signatures of the hunks the user turned off. Keyed by content, so a rejection survives edits elsewhere. */
  readonly rejected: ReadonlySet<string>;
}

export type Layout = "changes" | "full";

export interface HunkRow {
  kind: "hunk";
  id: number;
  number: number;
  total: number;
  accepted: boolean;
  /** 1-based line in the original where the change starts. */
  firstLine: number;
  originalLines: string[];
  proposedLines: string[];
}

export interface ContextRow {
  kind: "context";
  /** 1-based line in the original. */
  line: number;
  text: string;
}

export type Row = HunkRow | ContextRow;

const signature = (hunk: Hunk): string => `${hunk.originalLines.join("\n")}\u0000${hunk.proposedLines.join("\n")}`;

export function newReview(original: string, proposed: string, rejected: ReadonlySet<string> = new Set()): Review {
  const hunks = computeHunks(original, proposed);
  const live = new Set(hunks.map(signature));
  return { original, proposed, hunks, rejected: new Set([...rejected].filter((s) => live.has(s))) };
}

/** The proposal was edited: recompute the hunks and keep the rejections that still apply. */
export function withProposed(review: Review, proposed: string): Review {
  return newReview(review.original, proposed, review.rejected);
}

export function acceptedIds(review: Review): ReadonlySet<number> {
  return new Set(review.hunks.filter((hunk) => !review.rejected.has(signature(hunk))).map((hunk) => hunk.id));
}

export function toggleHunk(review: Review, id: number): Review {
  const hunk = review.hunks.find((h) => h.id === id);
  if (!hunk) return review;
  const rejected = new Set(review.rejected);
  const key = signature(hunk);
  if (!rejected.delete(key)) rejected.add(key);
  return { ...review, rejected };
}

export const selectAll = (review: Review): Review => ({ ...review, rejected: new Set() });

export const selectNone = (review: Review): Review => ({ ...review, rejected: new Set(review.hunks.map(signature)) });

/** The text the accepted hunks produce. */
export function mergedText(review: Review): string {
  return mergeHunks(review.original, [...review.hunks], acceptedIds(review));
}

export function rejectedHunks(review: Review): { number: number; originalLine: number }[] {
  const accepted = acceptedIds(review);
  return review.hunks
    .filter((hunk) => !accepted.has(hunk.id))
    .map((hunk) => ({ number: hunk.id + 1, originalLine: hunk.originalStart + 1 }));
}

export function reviewRows(review: Review, layout: Layout): Row[] {
  const accepted = acceptedIds(review);
  const lines = review.original.split("\n");
  const rows: Row[] = [];
  let cursor = 0;
  const context = (to: number) => {
    if (layout !== "full") return;
    for (; cursor < to; cursor++) rows.push({ kind: "context", line: cursor + 1, text: lines[cursor] ?? "" });
  };
  for (const hunk of review.hunks) {
    context(hunk.originalStart);
    rows.push({
      kind: "hunk",
      id: hunk.id,
      number: hunk.id + 1,
      total: review.hunks.length,
      accepted: accepted.has(hunk.id),
      firstLine: hunk.originalStart + 1,
      originalLines: hunk.originalLines,
      proposedLines: hunk.proposedLines,
    });
    cursor = hunk.originalStart + hunk.originalLines.length;
  }
  context(lines.length);
  return rows;
}
