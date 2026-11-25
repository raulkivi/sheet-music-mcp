// Pure model of a compare_scores result: what the viewer lists, filters and says about it.
// No DOM, no host. Kinds come from the operations present in the result (G13), not a fixed list.

export interface NoteInfo {
  pitch: string;
  duration: number;
  is_rest: boolean;
}

export interface Change {
  operation: string;
  measure_number: number;
  beat: number;
  voice: number;
  part_name: string;
  reference: NoteInfo | null;
  target: NoteInfo | null;
  interval_error: number | null;
}

export interface Diff {
  similarity: number;
  summary: Record<string, unknown>;
  /** Absent when the detail level was `summary`. */
  changes?: Change[];
  report?: string;
  /** Opaque id of the comparison's scores; absent when the server has no viewer build. */
  diffId?: string;
}

export type ReadDiff = { ok: true; diff: Diff } | { ok: false };

export interface KindOption {
  kind: string;
  label: string;
  count: number;
}

// Wording for the operations the comparer knows today, in the order the filters show them. An
// operation not listed here still works: its label comes from its name.
const KNOWN: { kind: string; label: string; verb: string }[] = [
  { kind: "PITCH_CHANGE", label: "Pitch changed", verb: "pitch changed" },
  { kind: "DURATION_CHANGE", label: "Length changed", verb: "length changed" },
  { kind: "SUBSTITUTION", label: "Replaced", verb: "replaced" },
  { kind: "INSERTION", label: "Added", verb: "added" },
  { kind: "DELETION", label: "Removed", verb: "removed" },
];

function sentenceCase(kind: string): string {
  const words = kind.toLowerCase().replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

function asChange(value: unknown): Change | undefined {
  if (!isObject(value)) return undefined;
  if (typeof value.operation !== "string" || typeof value.measure_number !== "number") return undefined;
  return value as unknown as Change;
}

/** The `structuredContent` of compare_scores as a Diff; `{ ok: false }` when it is not one. */
export function readDiff(data: unknown): ReadDiff {
  if (!isObject(data) || typeof data.similarity_score !== "number" || !isObject(data.summary)) return { ok: false };
  const diff: Diff = { similarity: data.similarity_score, summary: data.summary };
  if (Array.isArray(data.changes)) {
    diff.changes = data.changes
      .map(asChange)
      .filter((change): change is Change => change !== undefined)
      .sort((a, b) => a.measure_number - b.measure_number || a.beat - b.beat);
  }
  if (typeof data.report === "string") diff.report = data.report;
  if (typeof data.diff_id === "string" && data.diff_id !== "") diff.diffId = data.diff_id;
  return { ok: true, diff };
}

/** The kinds that occur in `changes`, known ones first in a fixed order, then the rest by name. */
export function kindsPresent(changes: readonly Change[]): KindOption[] {
  const counts = new Map<string, number>();
  for (const change of changes) counts.set(change.operation, (counts.get(change.operation) ?? 0) + 1);
  const known = KNOWN.map((k) => k.kind);
  const kinds = [...counts.keys()].sort((a, b) => {
    const ia = known.indexOf(a);
    const ib = known.indexOf(b);
    if (ia >= 0 || ib >= 0) return (ia < 0 ? known.length : ia) - (ib < 0 ? known.length : ib) || a.localeCompare(b);
    return a.localeCompare(b);
  });
  return kinds.map((kind) => ({
    kind,
    label: KNOWN.find((k) => k.kind === kind)?.label ?? sentenceCase(kind),
    count: counts.get(kind) ?? 0,
  }));
}

/** `changes` of the selected kinds; with none selected, all of them. */
export function visibleChanges(changes: readonly Change[], selected: ReadonlySet<string>): Change[] {
  return selected.size === 0 ? [...changes] : changes.filter((change) => selected.has(change.operation));
}

const noteName = (note: NoteInfo | null): string => (note === null ? "" : note.is_rest ? "rest" : note.pitch);

function beatText(beat: number): string {
  return String(Math.round(beat * 100) / 100);
}

/** One line a person (or a screen reader) can read: where, what the note was and what it became. */
export function describeChange(change: Change): string {
  const where = `${change.part_name}, bar ${change.measure_number}, beat ${beatText(change.beat)}`;
  const verb = KNOWN.find((k) => k.kind === change.operation)?.verb ?? sentenceCase(change.operation).toLowerCase();
  const from = noteName(change.reference);
  const to = noteName(change.target);
  if (change.operation === "INSERTION") return `${where}: ${to} added`;
  if (change.operation === "DELETION") return `${where}: ${from} removed`;
  return `${where}: ${from} to ${to} (${verb})`;
}

/** The measure both panes scroll to for `change` (the comparer numbers both scores alike). */
export function measureTarget(change: Change): number {
  return change.measure_number;
}

/** Spoken when a change is selected (aria-live). `index` is zero-based. */
export function selectionSummary(change: Change, index: number, total: number): string {
  return `Change ${index + 1} of ${total}. ${describeChange(change)}. Both scores show bar ${measureTarget(change)}.`;
}

function percent(score: number): string {
  const tenths = score >= 1 ? 1000 : Math.floor(Math.max(0, score) * 1000 + 1e-9);
  const value = tenths / 10;
  return `${Number.isInteger(value) ? value : value.toFixed(1)}%`;
}

/** The headline under the title; `changeCount` is undefined when the result lists no changes. */
export function summaryLine(similarity: number, changeCount: number | undefined): string {
  const head = `${percent(similarity)} similar`;
  if (changeCount === undefined) return head;
  if (changeCount === 0) return `${head}, no changes`;
  return `${head}, ${changeCount} ${changeCount === 1 ? "change" : "changes"}`;
}
