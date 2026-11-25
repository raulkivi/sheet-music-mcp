// The core's standard health report (sheet_music_mcp_core.health) as the page uses it. Pure: the
// wire shape in, a view model and a plain-text copy out. Nothing here knows the DOM or the host.

export type CheckStatus = "ok" | "warn" | "fail";
export type ReportStatus = "ready" | "degraded" | "not_ready";

export interface Check {
  name: string;
  status: CheckStatus;
  version?: string;
  hint?: string;
  fixSnippet?: string;
  docUrl?: string;
}

export interface Report {
  status: ReportStatus;
  checks: Check[];
}

const CHECK_STATUSES: readonly string[] = ["ok", "warn", "fail"];
const REPORT_STATUSES: readonly string[] = ["ready", "degraded", "not_ready"];

const text = (value: unknown): string | undefined => (typeof value === "string" ? value : undefined);

/** Only web links: the host opens them in the user's browser, so nothing else may reach it. */
function webUrl(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  try {
    const { protocol } = new URL(value);
    return protocol === "https:" || protocol === "http:" ? value : undefined;
  } catch {
    return undefined;
  }
}

function parseCheck(value: unknown): Check | undefined {
  if (typeof value !== "object" || value === null) return undefined;
  const raw = value as Record<string, unknown>;
  const name = text(raw.name);
  if (!name || name.trim() === "" || typeof raw.status !== "string" || !CHECK_STATUSES.includes(raw.status)) return undefined;
  const check: Check = { name, status: raw.status as CheckStatus };
  const version = text(raw.version);
  const hint = text(raw.hint);
  const fixSnippet = text(raw.fix_snippet);
  const docUrl = webUrl(raw.doc_url);
  if (version !== undefined) check.version = version;
  if (hint !== undefined) check.hint = hint;
  if (fixSnippet !== undefined) check.fixSnippet = fixSnippet;
  if (docUrl !== undefined) check.docUrl = docUrl;
  return check;
}

function overall(checks: readonly Check[]): ReportStatus {
  if (checks.some((c) => c.status === "fail")) return "not_ready";
  if (checks.some((c) => c.status === "warn")) return "degraded";
  return "ready";
}

/** A tool result's `structuredContent` as a report, or undefined when it is not one. */
export function parseReport(value: unknown): Report | undefined {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return undefined;
  const raw = value as Record<string, unknown>;
  if (!Array.isArray(raw.checks)) return undefined;
  const checks: Check[] = [];
  for (const item of raw.checks) {
    const check = parseCheck(item);
    if (!check) return undefined;
    checks.push(check);
  }
  const status = typeof raw.status === "string" && REPORT_STATUSES.includes(raw.status) ? (raw.status as ReportStatus) : overall(checks);
  return { status, checks };
}

export interface Row extends Check {
  /** Words for the status, so color is never the only signal. */
  label: string;
}

export interface ViewModel {
  status: ReportStatus;
  headline: string;
  counts: Record<CheckStatus, number>;
  rows: Row[];
  empty: boolean;
}

const LABELS: Record<CheckStatus, string> = { ok: "Ready", warn: "Needs attention", fail: "Must fix" };
const ORDER: Record<CheckStatus, number> = { fail: 0, warn: 1, ok: 2 };

const checks = (n: number) => `${n} ${n === 1 ? "check" : "checks"}`;

function headline(status: ReportStatus, counts: Record<CheckStatus, number>): string {
  if (status === "not_ready") return `Not ready: ${counts.fail === 1 ? "1 check must" : `${counts.fail} checks must`} be fixed`;
  if (status === "degraded") return `Ready with ${checks(counts.warn)} needing attention`;
  return "Everything is ready";
}

/** Rows worst first (the sort is stable, so the server's order holds within a status), with counts. */
export function viewModel(report: Report): ViewModel {
  const counts: Record<CheckStatus, number> = { ok: 0, warn: 0, fail: 0 };
  for (const check of report.checks) counts[check.status] += 1;
  const rows = report.checks
    .map((check): Row => ({ ...check, label: LABELS[check.status] }))
    .sort((a, b) => ORDER[a.status] - ORDER[b.status]);
  return { status: report.status, headline: headline(report.status, counts), counts, rows, empty: report.checks.length === 0 };
}

const indent = (block: string, pad: string) =>
  block
    .split("\n")
    .map((line) => (line === "" ? line : pad + line))
    .join("\n");

/** The report as plain text for a chat message or an issue; worst checks first, as on screen. */
export function reportText(report: Report): string {
  const vm = viewModel(report);
  const lines = [`Setup report: ${vm.headline}`, ""];
  if (vm.empty) lines.push("No checks were reported.");
  for (const row of vm.rows) {
    lines.push(`[${row.status === "ok" ? "OK" : row.status.toUpperCase()}] ${row.name}${row.version ? ` (${row.version})` : ""}`);
    if (row.hint) lines.push(indent(row.hint, "  "));
    if (row.fixSnippet) lines.push("  Fix:", indent(row.fixSnippet, "    "));
    if (row.docUrl) lines.push(`  Docs: ${row.docUrl}`);
    lines.push("");
  }
  return lines.join("\n") + (vm.empty ? "\n" : "");
}
