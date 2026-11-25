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

