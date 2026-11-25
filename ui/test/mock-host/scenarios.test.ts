import { afterEach, describe, expect, it, vi } from "vitest";
import { openingCall, openingTool, PDF_RESULT } from "./scenarios.ts";
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

describe("the Practice Coach scenarios", () => {
  it("coach opens with start_practice for the Alto of the four-bar score and returns the session view", async () => {
    stubFixtures();
    expect(openingTool("coach")).toBe("start_practice");
    const opening = await openingCall("coach");
    expect(opening.input).toEqual({ musicxml: '<score-partwise from="/fixtures/satb-4bars.musicxml"/>', part: "Alto" });
    expect(opening.result.structuredContent).toEqual({
      session_id: "mock-session",
      part_id: "P2",
      part_name: "Alto",
      measure_count: 4,
      duration_seconds: 16,
      tempo_bpm: 60,
    });
    expect(openingTool("inline-long")).toBe("render_to_pdf");
  });

  it("coach-empty returns a result without a session, coach-error the server's error envelope", async () => {
    stubFixtures();
    expect((await openingCall("coach-empty")).result.structuredContent).toBeUndefined();
    const failed = (await openingCall("coach-error")).result;
    expect(failed.isError).toBe(true);
    expect(JSON.parse((failed.content![0] as { text: string }).text)).toMatchObject({ error_code: "PROCESSING_FAILED" });
  });
});
