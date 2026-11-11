import { describe, expect, it } from "vitest";
import { noTools, placeholderTools, relayedTools } from "./tool-backends.ts";

const SCORE = "<score-partwise version='4.0'></score-partwise>";

describe("placeholderTools", () => {
  it("answers render_page_svg with a labelled placeholder page in the server's contract", async () => {
    const result = await placeholderTools.callTool({ name: "render_page_svg", arguments: { musicxml: SCORE, page: 2, width_px: 800, zoom: 1.25 } });
    expect(result.isError).toBeUndefined();
    expect(result.structuredContent).toMatchObject({ page: 2, page_count: 5 });
    const svg = (result.structuredContent as { svg: string }).svg;
    expect(svg).toContain('data-server-page="2"');
    expect(svg).toContain('data-zoom="1.25"');
    expect(svg).toContain('width="800px"');
  });

  it("returns the error envelope for a page past the end and for a non-score", async () => {
    const past = await placeholderTools.callTool({ name: "render_page_svg", arguments: { musicxml: SCORE, page: 6, width_px: 800, zoom: 1 } });
    expect(past.isError).toBe(true);
    expect(JSON.parse((past.content![0] as { text: string }).text)).toMatchObject({ error_code: "INVALID_PARAMETER" });
    const junk = await placeholderTools.callTool({ name: "render_page_svg", arguments: { musicxml: "hi", page: 1, width_px: 800, zoom: 1 } });
    expect(JSON.parse((junk.content![0] as { text: string }).text)).toMatchObject({ error_code: "INVALID_INPUT" });
  });

  it("knows no other tool", async () => {
    await expect(placeholderTools.callTool({ name: "render_to_pdf", arguments: {} })).rejects.toThrow(/render_to_pdf/);
  });
});

describe("noTools", () => {
  it("refuses every call", async () => {
    await expect(noTools.callTool({ name: "render_page_svg", arguments: {} })).rejects.toThrow(/render_page_svg/);
  });
});

describe("relayedTools", () => {
  it("sends tools/call through the relay and returns its answer", async () => {
    const seen: unknown[] = [];
    const tools = relayedTools(async (method, params) => {
      seen.push([method, params]);
      return { content: [], structuredContent: { ok: true } };
    });
    const result = await tools.callTool({ name: "render_page_svg", arguments: { page: 1 } });
    expect(seen).toEqual([["tools/call", { name: "render_page_svg", arguments: { page: 1 } }]]);
    expect(result.structuredContent).toEqual({ ok: true });
  });
});
