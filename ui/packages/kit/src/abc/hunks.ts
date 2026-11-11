// Line-level hunks between an ABC text and a proposed edit, and a merge of a chosen subset.
// Pure: no DOM, no framework. Texts split on "\n", so a trailing newline is a final empty line.

export interface Hunk {
  id: number;
  originalLines: string[];
  proposedLines: string[];
  /** 0-based line index in the original where the hunk starts. */
  originalStart: number;
}

/** Returns lcs(i, j): length of the longest common subsequence of a[i..] and b[j..]. */
function lcsLengths(a: string[], b: string[]): (i: number, j: number) => number {
  const width = b.length + 1;
  const table = new Array<number>((a.length + 1) * width).fill(0);
  const at = (i: number, j: number): number => table[i * width + j] ?? 0;
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      table[i * width + j] = a[i] === b[j] ? at(i + 1, j + 1) + 1 : Math.max(at(i + 1, j), at(i, j + 1));
    }
  }
  return at;
}

export function computeHunks(original: string, proposed: string): Hunk[] {
  const a = original.split("\n");
  const b = proposed.split("\n");
  const lcs = lcsLengths(a, b);
  const hunks: Hunk[] = [];
  let open: Hunk | null = null;

  const change = (i: number): Hunk => {
    if (!open) {
      open = { id: hunks.length, originalLines: [], proposedLines: [], originalStart: i };
      hunks.push(open);
    }
    return open;
  };

  let i = 0;
  let j = 0;
  while (i < a.length || j < b.length) {
    if (i < a.length && j < b.length && a[i] === b[j]) {
      open = null;
      i++;
      j++;
    } else if (j >= b.length || (i < a.length && lcs(i + 1, j) >= lcs(i, j + 1))) {
      change(i).originalLines.push(a[i++] ?? "");
    } else {
      change(i).proposedLines.push(b[j++] ?? "");
    }
  }
  return hunks;
}

export function mergeHunks(original: string, hunks: Hunk[], accepted: ReadonlySet<number>): string {
  const lines = original.split("\n");
  const out: string[] = [];
  let cursor = 0;
  for (const hunk of hunks) {
    out.push(...lines.slice(cursor, hunk.originalStart));
    const keep = accepted.has(hunk.id);
    out.push(...(keep ? hunk.proposedLines : hunk.originalLines));
    cursor = hunk.originalStart + hunk.originalLines.length;
  }
  out.push(...lines.slice(cursor));
  return out.join("\n");
}
