// The issue list comes from the result's `warnings[]` and nothing else (gap G1): this page
// holds no list of known problems. Pure.

export type Severity = "error" | "warning" | "info";

/** One item of `warnings[]` as the server sends it (docs/conventions.md, Warnings). */
export interface Warning {
  code: string;
  severity: Severity;
  message: string;
  measure?: number;
  part?: string;
}

export interface Issue {
  code: string;
  severity: Severity;
  /** The severity in words: color is never the only signal. */
  tag: string;
  message: string;
  /** "Bar 12, part P2", or "" when the server named neither. */
  where: string;
  measure?: number;
  part?: string;
}

const TAGS: Record<Severity, string> = { error: "Must fix", warning: "Check", info: "Note" };
const ORDER: Severity[] = ["error", "warning", "info"];

const severity = (value: unknown): Severity => (value === "error" || value === "warning" ? value : "info");

/** Keeps well-formed items; the rest of the result is never trusted to be well formed. */
export function readWarnings(value: unknown): Warning[] {
  if (!Array.isArray(value)) return [];
  const warnings: Warning[] = [];
  for (const item of value) {
    if (typeof item !== "object" || item === null) continue;
    const raw = item as Record<string, unknown>;
    if (typeof raw.message !== "string" || typeof raw.code !== "string") continue;
    const warning: Warning = { code: raw.code, severity: severity(raw.severity), message: raw.message };
    if (typeof raw.measure === "number" && Number.isInteger(raw.measure) && raw.measure > 0) warning.measure = raw.measure;
    if (typeof raw.part === "string" && raw.part !== "") warning.part = raw.part;
    warnings.push(warning);
  }
  return warnings;
}

function where(warning: Warning): string {
  const bar = warning.measure !== undefined ? `Bar ${warning.measure}` : "";
  const part = warning.part !== undefined ? `part ${warning.part}` : "";
  return [bar, part].filter(Boolean).join(", ");
}

/** Errors first, then warnings, then notes; the server's order within each. */
export function toIssues(warnings: Warning[]): Issue[] {
  return ORDER.flatMap((level) =>
    warnings
      .filter((warning) => warning.severity === level)
      .map((warning): Issue => {
        const issue: Issue = {
          code: warning.code,
          severity: level,
          tag: TAGS[level],
          message: warning.message,
          where: where(warning),
        };
        if (warning.measure !== undefined) issue.measure = warning.measure;
        if (warning.part !== undefined) issue.part = warning.part;
        return issue;
      }),
  );
}

export function issueSummary(count: number): string {
  if (count === 0) return "Nothing to check.";
  return `${count} ${count === 1 ? "thing" : "things"} to check.`;
}

/** The live-region text after an issue is selected. */
export function selectionSummary(issue: Issue, index: number, total: number): string {
  const shows = issue.measure !== undefined ? `Showing bar ${issue.measure} in the score.` : "This applies to the whole page.";
  return `Issue ${index + 1} of ${total}. ${issue.tag}: ${issue.message.replace(/\.$/, "")}. ${shows}`;
}
