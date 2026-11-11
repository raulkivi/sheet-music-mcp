import { afterEach, describe, expect, it, vi } from "vitest";
import { openingCall, PDF_RESULT } from "./scenarios.ts";
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
