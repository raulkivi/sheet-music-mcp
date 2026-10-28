import { describe, expect, it } from "vitest";
import { FakeBridge } from "../host/FakeBridge.ts";
import type { ToolResult } from "../host/HostBridge.ts";
import { RendererUnavailable, ScoreLoadError } from "./ScoreRenderer.ts";
import { PAGE_SVG_TOOL, ServerScoreRenderer } from "./ServerScoreRenderer.ts";

interface PageArgs {
  musicxml: string;
  page: number;
  width_px: number;
  zoom: number;
}

const envelope = (code: string, error = "failed"): ToolResult => ({
  isError: true,
  content: [{ type: "text", text: JSON.stringify({ error, error_code: code }) }],
});

/** Answers like render-mcp: page count grows as the layout narrows or zooms in. */
function fakeServer(pagesAt: (args: PageArgs) => number = () => 5) {
  return (args: Record<string, unknown>): ToolResult => {
    const a = args as unknown as PageArgs;
    if (a.musicxml === "bad") return envelope("INVALID_INPUT");
    const count = pagesAt(a);
    if (a.page > count) return envelope("INVALID_PARAMETER", `Page ${a.page} is out of range.`);
    return {
      content: [{ type: "text", text: `Page ${a.page} of ${count}` }],
      structuredContent: { svg: `<svg data-page="${a.page}" data-width="${a.width_px}" data-zoom="${a.zoom}"/>`, page: a.page, page_count: count },
    };
  };
}

function setup(answer = fakeServer()) {
  const bridge = new FakeBridge({ toolAnswers: { [PAGE_SVG_TOOL]: answer } });
  const renderer = new ServerScoreRenderer(bridge);
  const calls = () => bridge.calls.filter((c) => c.method === "tools/call").map((c) => (c.params as { arguments: PageArgs }).arguments);
  return { bridge, renderer, calls };
}

describe("ServerScoreRenderer", () => {
  it("is the server engine", () => {
    expect(setup().renderer.engine).toBe("server");
  });

  it("load() asks render_page_svg for page 1 at the current width and zoom", async () => {
    const { renderer, calls } = setup();
    renderer.layout(812.4);
    await renderer.load("<score/>");
    expect(calls()).toEqual([{ musicxml: "<score/>", page: 1, width_px: 812, zoom: 1 }]);
  });

  it("returns the page and page count from structuredContent, reusing the page load fetched", async () => {
    const { renderer, calls } = setup();
    await renderer.load("<score/>");
    expect(await renderer.page(1)).toEqual({ svg: '<svg data-page="1" data-width="1000" data-zoom="1"/>', page: 1, pageCount: 5 });
    expect(calls()).toHaveLength(1);
  });

  it("clamps to the known page count without asking for pages that do not exist", async () => {
    const { renderer, calls } = setup();
    await renderer.load("<score/>");
    expect((await renderer.page(9)).page).toBe(5);
    expect((await renderer.page(0)).page).toBe(1);
    // Page 1 is fetched again: only the last page is kept.
    expect(calls().map((a) => a.page)).toEqual([1, 5, 1]);
  });

  it("sends a new width and zoom with the next page", async () => {
    const { renderer, calls } = setup();
    await renderer.load("<score/>");
    renderer.layout(600);
    renderer.zoom(1.25);
    expect(renderer.zoomFactor).toBe(1.25);
    await renderer.page(2);
    expect(calls().at(-1)).toMatchObject({ page: 2, width_px: 600, zoom: 1.25 });
  });

  it("ignores non-positive widths and zooms", async () => {
    const { renderer, calls } = setup();
    renderer.layout(0);
    renderer.zoom(-1);
    await renderer.load("<score/>");
    expect(calls()[0]).toMatchObject({ width_px: 1000, zoom: 1 });
  });

  it("after a re-flow shrinks the score, falls back to its new last page", async () => {
    const { renderer } = setup(fakeServer((a) => (a.width_px < 500 ? 8 : 3)));
    renderer.layout(400);
    await renderer.load("<score/>");
    expect((await renderer.page(7)).page).toBe(7);
    renderer.layout(900);
    expect(await renderer.page(7)).toMatchObject({ page: 3, pageCount: 3 });
  });

  it("rejects an unreadable score with ScoreLoadError", async () => {
    const { renderer } = setup();
    await expect(renderer.load("bad")).rejects.toBeInstanceOf(ScoreLoadError);
  });

  it("rejects with RendererUnavailable when the host cannot call the tool", async () => {
    const bridge = new FakeBridge({});
    await expect(new ServerScoreRenderer(bridge).load("<score/>")).rejects.toBeInstanceOf(RendererUnavailable);
  });

  it("rejects with RendererUnavailable on other tool errors, naming the code", async () => {
    const { renderer } = setup(() => envelope("PROCESSING_FAILED"));
    await expect(renderer.load("<score/>")).rejects.toThrow(/PROCESSING_FAILED/);
    await expect(renderer.load("<score/>")).rejects.toBeInstanceOf(RendererUnavailable);
  });

  it("rejects a result without the structured page", async () => {
    const { renderer } = setup(() => ({ content: [{ type: "text", text: "ok" }] }));
    await expect(renderer.load("<score/>")).rejects.toBeInstanceOf(RendererUnavailable);
  });

  it("refuses to render before a score is loaded", async () => {
    await expect(setup().renderer.page(1)).rejects.toThrow(/no score/i);
  });
});
