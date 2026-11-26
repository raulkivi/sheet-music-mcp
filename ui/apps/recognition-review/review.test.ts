import { describe, expect, it } from "vitest";
import { headline, pageNote, readReview } from "./review.ts";

const RESULT = {
  job_id: "job-1",
  metadata: { engine: "oemer", staves_detected: 1, measures: 12, page_count: 1, staff_systems_estimate: 4 },
  pages: [{ index: 1, staves_detected: 1, measures: 12, has_preview: true }],
  warnings: [
    {
      code: "PARTS_FEWER_THAN_STAVES",
      severity: "info",
      message: "1 part recognized but the page has 4 staves per system; voices may be merged",
    },
  ],
};

describe("readReview", () => {
  it("reads the recognition structuredContent", () => {
    expect(readReview(RESULT)).toEqual({
      jobId: "job-1",
      engine: "oemer",
      parts: 1,
      measures: 12,
      estimate: 4,
      pages: [{ index: 1, hasPreview: true }],
      warnings: [
        {
          code: "PARTS_FEWER_THAN_STAVES",
          severity: "info",
          message: "1 part recognized but the page has 4 staves per system; voices may be merged",
        },
      ],
    });
  });

  it("copes with a result for a client without the app: no job id, no estimate, no previews", () => {
    const read = readReview({ metadata: { engine: "audiveris", staves_detected: 4 }, pages: [{ index: 1 }], warnings: [] });
    expect(read).toMatchObject({ engine: "audiveris", parts: 4, pages: [{ index: 1, hasPreview: false }], warnings: [] });
    expect(read?.jobId).toBeUndefined();
    expect(read?.estimate).toBeUndefined();
  });

  it("is undefined for a result that is not a recognition", () => {
    expect(readReview(undefined)).toBeUndefined();
    expect(readReview({ pdf_path: "/x.pdf" })).toBeUndefined();
  });

  it("names an engine the server did not report 'unknown'", () => {
    expect(readReview({ metadata: {} })?.engine).toBe("unknown");
  });
});

describe("headline", () => {
  it("states the engine, the counts and the issue count", () => {
    expect(headline({ engine: "oemer", parts: 1, measures: 12 }, 3)).toBe("Recognized with oemer: 1 part, 12 bars. 3 things to check.");
    expect(headline({ engine: "audiveris", parts: 4, measures: 1 }, 0)).toBe("Recognized with Audiveris: 4 parts, 1 bar. Nothing to check.");
  });

  it("leaves out counts the server did not give", () => {
    expect(headline({ engine: "oemer", parts: undefined, measures: undefined }, 1)).toBe("Recognized with oemer. 1 thing to check.");
  });
});

describe("pageNote (DA9: one page in v1)", () => {
  it("says nothing for one page and names the shown page for several", () => {
    expect(pageNote(1)).toBeUndefined();
    expect(pageNote(3)).toBe("This result has 3 pages; the review shows page 1.");
  });
});
