import { afterEach, describe, expect, it, vi } from "vitest";
import { HEALTH_REPORTS, openingCall, PDF_RESULT } from "./scenarios.ts";
import type { ToolBackend, ToolCall } from "./tool-backends.ts";

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

describe("ABC scenarios", () => {
  it("abc-edit opens on the model's abc_to_musicxml call, with the edit as its input", async () => {
    const opening = await openingCall("abc-edit");
    expect(opening.tool).toBe("abc_to_musicxml");
    expect(opening.input).toEqual({ abc: expect.stringContaining("X:1") });
  });

  it("abc-export opens on a musicxml_to_abc result with an abc_id", async () => {
    const opening = await openingCall("abc-export");
    expect(opening.tool).toBe("musicxml_to_abc");
    expect(opening.result.structuredContent).toMatchObject({ abc_id: expect.any(String) });
  });

  it("abc-error opens on a failed call", async () => {
    expect((await openingCall("abc-error")).result.isError).toBe(true);
  });

  it("does not run an ABC scenario against the real render-mcp", async () => {
    await expect(openingCall("abc-edit", { callTool: async () => ({ content: [] }) })).rejects.toThrow(/placeholder/);
  });
});

describe("the Practice Coach scenarios", () => {
  it("coach opens with start_practice for the Alto of the four-bar score and returns the session view", async () => {
    stubFixtures();
    expect((await openingCall("coach")).tool).toBe("start_practice");
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
    expect((await openingCall("inline-long")).tool).toBe("render_to_pdf");
  });

  it("coach-empty returns a result without a session, coach-error the server's error envelope", async () => {
    stubFixtures();
    expect((await openingCall("coach-empty")).result.structuredContent).toBeUndefined();
    const failed = (await openingCall("coach-error")).result;
    expect(failed.isError).toBe(true);
    expect(JSON.parse((failed.content![0] as { text: string }).text)).toMatchObject({ error_code: "PROCESSING_FAILED" });
  });
});
describe("diff scenarios", () => {
  const DIFF = { changes: [{ operation: "PITCH_CHANGE" }], count: 1, similarity_score: 0.9, diff_id: "d" };

  function stubDiffFixture() {
    vi.stubGlobal("fetch", async () => ({ text: async () => JSON.stringify(DIFF) }));
  }

  it("opens with compare_scores, the others with render_to_pdf", async () => {
    stubDiffFixture();
    expect((await openingCall("diff")).tool).toBe("compare_scores");
    expect((await openingCall("diff-error")).tool).toBe("compare_scores");
    expect((await openingCall("inline-satb")).tool).toBe("render_to_pdf");
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

