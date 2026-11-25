import { afterEach, describe, expect, it, vi } from "vitest";
import { openingCall, openingToolName, PDF_RESULT } from "./scenarios.ts";
import type { ToolBackend, ToolCall } from "./tool-backends.ts";

afterEach(() => vi.unstubAllGlobals());

function stubFixtures() {
  vi.stubGlobal("fetch", async (url: string) => ({ text: async () => `<score-partwise from="${url}"/>` }));
}

describe("openingCall", () => {
  it("pairs the scenario's score with the canned render_to_pdf result", async () => {
    stubFixtures();
    expect(await openingCall("inline-satb")).toEqual({
      input: { musicxml: '<score-partwise from="/fixtures/satb-4bars.musicxml"/>' },
      result: PDF_RESULT,
    });
    expect((await openingCall("path-only")).input).toEqual({ musicxml_path: "/home/user/scores/satb.musicxml" });
  });

  it("with a real server runs render_to_pdf there, saving under the server's output root", async () => {
    stubFixtures();
    const calls: ToolCall[] = [];
    const model: ToolBackend = {
      async callTool(call) {
        calls.push(call);
        return { content: [], structuredContent: { pdf_path: "/root/score.pdf" } };
      },
    };
    const opening = await openingCall("inline-long", model);
    const input = { musicxml: '<score-partwise from="/fixtures/satb-long.musicxml"/>', output_path: "score.pdf" };
    expect(calls).toEqual([{ name: "render_to_pdf", arguments: input }]);
    expect(opening).toEqual({ input, result: { content: [], structuredContent: { pdf_path: "/root/score.pdf" } } });
  });
});

describe("diff scenarios", () => {
  const DIFF = { changes: [{ operation: "PITCH_CHANGE" }], count: 1, similarity_score: 0.9, diff_id: "d" };

  function stubDiffFixture() {
    vi.stubGlobal("fetch", async () => ({ text: async () => JSON.stringify(DIFF) }));
  }

  it("opens with compare_scores, the others with render_to_pdf", () => {
    expect(openingToolName("diff")).toBe("compare_scores");
    expect(openingToolName("diff-error")).toBe("compare_scores");
    expect(openingToolName("inline-long")).toBe("render_to_pdf");
  });

  it("diff replays the recorded comparison", async () => {
    stubDiffFixture();
    const { input, result } = await openingCall("diff");
    expect(input).toMatchObject({ detail: "full" });
    expect(result.structuredContent).toEqual(DIFF);
  });

  it("diff-identical has no changes and similarity 1", async () => {
    stubDiffFixture();
    expect((await openingCall("diff-identical")).result.structuredContent).toMatchObject({
      similarity_score: 1,
      changes: [],
      count: 0,
    });
  });

  it("diff-error is an error envelope", async () => {
    const { result } = await openingCall("diff-error");
    expect(result.isError).toBe(true);
    expect(JSON.parse((result.content![0] as { text: string }).text).error_code).toBe("INVALID_INPUT");
  });
});
