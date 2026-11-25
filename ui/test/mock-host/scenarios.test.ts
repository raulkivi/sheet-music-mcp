import { afterEach, describe, expect, it, vi } from "vitest";
import { HEALTH_REPORTS, openingCall, PDF_RESULT } from "./scenarios.ts";
import { placeholderTools, type ToolBackend, type ToolCall } from "./tool-backends.ts";

afterEach(() => vi.unstubAllGlobals());

function stubFixtures() {
  vi.stubGlobal("fetch", async (url: string) => ({ text: async () => `<score-partwise from="${url}"/>` }));
}

describe("openingCall", () => {
  it("pairs the scenario's score with the canned render_to_pdf result", async () => {
    stubFixtures();
    expect(await openingCall("inline-satb")).toEqual({
      tool: "render_to_pdf",
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
    expect(opening).toEqual({ tool: "render_to_pdf", input, result: { content: [], structuredContent: { pdf_path: "/root/score.pdf" } } });
  });
});

describe("health scenarios", () => {
  it("open with the server's own health_check and a report built like the core's", async () => {
    const mixed = await openingCall("health-mixed");
    expect(mixed.tool).toBe("health_check");
    expect(mixed.input).toEqual({});
    const report = mixed.result.structuredContent as { status: string; checks: { status: string }[] };
    expect(report.status).toBe("not_ready");
    expect(new Set(report.checks.map((c) => c.status))).toEqual(new Set(["ok", "warn", "fail"]));
  });

  it("covers the ready, empty and error states", async () => {
    expect((await openingCall("health-ready")).result.structuredContent).toEqual(HEALTH_REPORTS.ready);
    expect((await openingCall("health-empty")).result.structuredContent).toEqual({ status: "ready", checks: [] });
    const failed = (await openingCall("health-error")).result;
    expect(failed.isError).toBe(true);
    expect(JSON.stringify(failed.content)).toContain("error_code");
  });

  it("never asks the real server to play the model for a health scenario", async () => {
    const model: ToolBackend = {
      async callTool() {
        throw new Error("not called");
      },
    };
    await expect(openingCall("health-ready", model)).resolves.toMatchObject({ tool: "health_check" });
  });
});

const SCORE =
  '<score-partwise><part-list><score-part id="P1"><part-name>Soprano</part-name></score-part></part-list><part id="P1"><measure number="1"/></part></score-partwise>';

describe("Practice Player scenarios", () => {
  it("run synthesize on the given backend with a counted-in four-bar track", async () => {
    vi.stubGlobal("fetch", async () => ({ text: async () => SCORE }));
    const opening = await openingCall("practice", placeholderTools);
    expect(opening.tool).toBe("synthesize");
    expect(opening.input).toMatchObject({ musicxml: SCORE, measures: [1, 4], count_in_bars: 1 });
    expect(opening.result.structuredContent).toMatchObject({ audio_id: expect.stringMatching(/^audio-/), tempo_factor: 1 });
  });

  it("practice-empty returns a result without a track", async () => {
    vi.stubGlobal("fetch", async () => ({ text: async () => SCORE }));
    expect((await openingCall("practice-empty", placeholderTools)).result.structuredContent).toBeUndefined();
  });

  it("practice-unknown-audio returns a track whose audio id the server does not know", async () => {
    vi.stubGlobal("fetch", async () => ({ text: async () => SCORE }));
    const opening = await openingCall("practice-unknown-audio", placeholderTools);
    expect(opening.result.structuredContent).toMatchObject({ audio_id: "unknown-audio-id" });
    const chunk = await placeholderTools.callTool({ name: "read_audio_chunk", arguments: { audio_id: "unknown-audio-id", offset: 0, length: 1 } });
    expect(chunk.isError).toBe(true);
  });

  it("need a backend to run synthesize on", async () => {
    await expect(openingCall("practice")).rejects.toThrow(/needs a tool backend/);
  });
});
