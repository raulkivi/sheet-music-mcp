// The recognition result as the page reads it (`recognize_sheet` / `recognize_sheets`
// structuredContent, omr-mcp presenter.py). Pure.

import { engineLabel } from "./advice.ts";
import { issueSummary, readWarnings, type Warning } from "./issues.ts";

export interface PageInfo {
  index: number;
  /** Whether `get_source_preview` can serve this page. */
  hasPreview: boolean;
}

export interface Review {
  /** Opaque handle for the app-only tools; absent for a client the server did not show the app to. */
  jobId?: string;
  engine: string;
  parts?: number;
  measures?: number;
  /** `metadata.staff_systems_estimate`. */
  estimate?: number;
  pages: PageInfo[];
  warnings: Warning[];
}

const count = (value: unknown): number | undefined =>
  typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : undefined;

function readPages(value: unknown): PageInfo[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item): PageInfo[] => {
    const page = (item ?? {}) as Record<string, unknown>;
    const index = count(page.index);
    return index === undefined ? [] : [{ index, hasPreview: page.has_preview === true }];
  });
}

/** The review model of a result, or undefined when the result is not a recognition. */
export function readReview(data: Record<string, unknown> | undefined): Review | undefined {
  const metadata = data?.metadata;
  if (typeof metadata !== "object" || metadata === null) return undefined;
  const meta = metadata as Record<string, unknown>;
  const review: Review = {
    engine: typeof meta.engine === "string" && meta.engine !== "" ? meta.engine : "unknown",
    pages: readPages(data?.pages),
    warnings: readWarnings(data?.warnings),
  };
  if (typeof data?.job_id === "string" && data.job_id !== "") review.jobId = data.job_id;
  const parts = count(meta.staves_detected);
  const measures = count(meta.measures);
  const estimate = count(meta.staff_systems_estimate);
  if (parts !== undefined) review.parts = parts;
  if (measures !== undefined) review.measures = measures;
  if (estimate !== undefined) review.estimate = estimate;
  return review;
}

const plural = (n: number, noun: string): string => `${n} ${noun}${n === 1 ? "" : "s"}`;

export function headline(
  review: Pick<Review, "engine" | "parts" | "measures">,
  issues: number,
): string {
  const facts = [
    review.parts === undefined ? undefined : plural(review.parts, "part"),
    review.measures === undefined ? undefined : plural(review.measures, "bar"),
  ].filter(Boolean);
  const detail = facts.length > 0 ? `: ${facts.join(", ")}` : "";
  return `Recognized with ${engineLabel(review.engine)}${detail}. ${issueSummary(issues)}`;
}

/** v1 reviews page 1 only (decision DA9). */
export function pageNote(pageCount: number): string | undefined {
  return pageCount > 1 ? `This result has ${pageCount} pages; the review shows page 1.` : undefined;
}
