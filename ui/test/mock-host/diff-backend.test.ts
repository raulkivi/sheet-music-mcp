import { afterEach, describe, expect, it, vi } from "vitest";
import { DIFF_ID, diffTools } from "./diff-backend.ts";

afterEach(() => vi.unstubAllGlobals());

function stubFixtures() {
  vi.stubGlobal("fetch", async (url: string) => ({
    text: async () => (url.endsWith(".json") ? '{"PITCH_CHANGE":"#FF8800"}' : `<score-partwise from="${url}"/>`),
  }));
}

describe("diffTools", () => {
  it("answers get_diff_scores with both annotated fixtures and the legend", async () => {
    stubFixtures();
    const result = await diffTools.callTool({ name: "get_diff_scores", arguments: { diff_id: DIFF_ID } });
    expect(result.structuredContent).toEqual({
      diff_id: DIFF_ID,
      reference_musicxml: '<score-partwise from="/fixtures/diff-reference-annotated.musicxml"/>',
      target_musicxml: '<score-partwise from="/fixtures/diff-target-annotated.musicxml"/>',
      legend: { PITCH_CHANGE: "#FF8800" },
    });
  });

  it("answers export_diff_scores with two file paths", async () => {
    const result = await diffTools.callTool({ name: "export_diff_scores", arguments: { diff_id: DIFF_ID } });
    expect(result.structuredContent).toMatchObject({
      reference_annotated_musicxml_path: expect.stringMatching(/reference.*\.musicxml$/),
      target_annotated_musicxml_path: expect.stringMatching(/target.*\.musicxml$/),
    });
  });

  it("returns the error envelope for an unknown diff_id", async () => {
    for (const name of ["get_diff_scores", "export_diff_scores"]) {
      const result = await diffTools.callTool({ name, arguments: { diff_id: "nope" } });
      expect(result.isError).toBe(true);
      expect(JSON.parse((result.content![0] as { text: string }).text)).toMatchObject({ error_code: "INVALID_PARAMETER" });
    }
  });

  it("knows no other tool", async () => {
    await expect(diffTools.callTool({ name: "render_page_svg", arguments: {} })).rejects.toThrow(/render_page_svg/);
  });
});
