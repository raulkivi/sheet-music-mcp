import { afterEach, describe, expect, it, vi } from "vitest";
import { AUDIVERIS_JOB, AUDIVERIS_RESULT, isOmrScenario, OEMER_JOB, OEMER_RESULT, OMR_OPENING, omrTools } from "./omr-tools.ts";

afterEach(() => vi.unstubAllGlobals());

const PNG = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 9, 8, 7, 6, 5]);

function stubFixtures() {
  vi.stubGlobal("fetch", async (url: string) => ({
    text: async () => `<score-partwise from="${url}"/>`,
    arrayBuffer: async () => PNG.buffer.slice(0),
  }));
}

const structured = (result: { structuredContent?: unknown }) => result.structuredContent as Record<string, unknown>;
const body = (result: { content?: unknown[] }) => JSON.parse((result.content![0] as { text: string }).text) as Record<string, unknown>;

describe("the recorded results", () => {
  it("oemer flattened the page: one part, staves estimated at 4, warnings", () => {
    expect(structured(OEMER_RESULT)).toMatchObject({
      job_id: OEMER_JOB,
      metadata: { engine: "oemer", staves_detected: 1, staff_systems_estimate: 4 },
    });
    expect((structured(OEMER_RESULT).warnings as unknown[]).length).toBeGreaterThan(0);
  });

  it("Audiveris kept four parts and has no warnings", () => {
    expect(structured(AUDIVERIS_RESULT)).toMatchObject({ job_id: AUDIVERIS_JOB, metadata: { engine: "audiveris", staves_detected: 4 }, warnings: [] });
  });

  it("the scenarios open on a warned result, a clean one and an error", () => {
    expect(OMR_OPENING.review).toBe(OEMER_RESULT);
    expect(OMR_OPENING["review-clean"]).toBe(AUDIVERIS_RESULT);
    expect(OMR_OPENING["review-error"].isError).toBe(true);
    expect(isOmrScenario("review-clean")).toBe(true);
    expect(isOmrScenario("diff")).toBe(false);
  });
});

describe("omrTools", () => {
  it("get_recognized_score answers per job: the flattened score for oemer, the four parts for Audiveris", async () => {
    stubFixtures();
    const flat = await omrTools.callTool({ name: "get_recognized_score", arguments: { job_id: OEMER_JOB } });
    const full = await omrTools.callTool({ name: "get_recognized_score", arguments: { job_id: AUDIVERIS_JOB } });
    expect(structured(flat).musicxml).toContain("recognition-flattened.musicxml");
    expect(structured(full).musicxml).toContain("satb-4bars.musicxml");
  });

  it("get_source_preview serves the photo in chunks of the length asked", async () => {
    stubFixtures();
    const first = structured(await omrTools.callTool({ name: "get_source_preview", arguments: { job_id: OEMER_JOB, page: 1, offset: 0, length: 4 } }));
    const last = structured(await omrTools.callTool({ name: "get_source_preview", arguments: { job_id: OEMER_JOB, page: 1, offset: 8, length: 4 } }));
    expect(first).toMatchObject({ offset: 0, length: 4, byte_length: 9, eof: false });
    expect(atob(first.data_b64 as string).length).toBe(4);
    expect(last).toMatchObject({ offset: 8, length: 1, eof: true });
  });

  it("recognize_sheet again picks the result by engine", async () => {
    const audiveris = await omrTools.callTool({ name: "recognize_sheet", arguments: { image: "/x.png", engine: "audiveris" } });
    const oemer = await omrTools.callTool({ name: "recognize_sheet", arguments: { image: "/x.png", engine: "oemer" } });
    expect(structured(audiveris).job_id).toBe(AUDIVERIS_JOB);
    expect(structured(oemer).job_id).toBe(OEMER_JOB);
  });

  it("returns the error envelope for an unknown job, a missing image or a page without a preview", async () => {
    stubFixtures();
    for (const [name, args] of [
      ["get_recognized_score", { job_id: "nope" }],
      ["get_source_preview", { job_id: "nope" }],
      ["get_source_preview", { job_id: OEMER_JOB, page: 2 }],
      ["recognize_sheet", { engine: "audiveris" }],
    ] as const) {
      const result = await omrTools.callTool({ name, arguments: args });
      expect(result.isError, name).toBe(true);
      expect(body(result)).toHaveProperty("error_code");
    }
  });

  it("knows no other tool", async () => {
    await expect(omrTools.callTool({ name: "render_page_svg", arguments: {} })).rejects.toThrow(/render_page_svg/);
  });
});
