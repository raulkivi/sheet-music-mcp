import { describe, expect, it } from "vitest";
import { openScore } from "./openScore.ts";
import { RendererUnavailable, ScoreLoadError, type RenderedPage, type ScoreRenderer } from "./ScoreRenderer.ts";

class StubRenderer implements ScoreRenderer {
  zoomFactor = 1;
  width = 0;
  loaded: string | undefined;
  constructor(
    readonly engine: "wasm" | "server",
    private readonly failLoad?: Error,
  ) {}
  async load(xml: string) {
    if (this.failLoad) throw this.failLoad;
    this.loaded = xml;
  }
  layout(width: number) {
    this.width = width;
  }
  zoom(factor: number) {
    this.zoomFactor = factor;
  }
  async page(page: number): Promise<RenderedPage> {
    return { svg: "<svg/>", page, pageCount: 1 };
  }
}

describe("openScore", () => {
  it("uses the first renderer that starts and loads, laid out before loading", async () => {
    const wasm = new StubRenderer("wasm");
    const renderer = await openScore("<score/>", 640, [async () => wasm, async () => new StubRenderer("server")]);
    expect(renderer).toBe(wasm);
    expect(wasm.width).toBe(640);
    expect(wasm.loaded).toBe("<score/>");
  });

  it("falls back when the first engine cannot start (WebAssembly refused by CSP)", async () => {
    const server = new StubRenderer("server");
    const renderer = await openScore("<score/>", 640, [
      async () => {
        throw new WebAssembly.CompileError("Refused to compile or instantiate WebAssembly module");
      },
      async () => server,
    ]);
    expect(renderer.engine).toBe("server");
    expect(server.loaded).toBe("<score/>");
  });

  it("falls back when an engine starts but is unavailable for loading", async () => {
    const renderer = await openScore("<score/>", 640, [
      async () => new StubRenderer("wasm", new RendererUnavailable("no tool")),
      async () => new StubRenderer("server"),
    ]);
    expect(renderer.engine).toBe("server");
  });

  it("does not try another engine for an unreadable score", async () => {
    let triedServer = false;
    const attempt = openScore("bad", 640, [
      async () => new StubRenderer("wasm", new ScoreLoadError("not music")),
      async () => {
        triedServer = true;
        return new StubRenderer("server");
      },
    ]);
    await expect(attempt).rejects.toBeInstanceOf(ScoreLoadError);
    expect(triedServer).toBe(false);
  });

  it("rejects with RendererUnavailable carrying every failure when no engine works", async () => {
    const attempt = openScore("<score/>", 640, [
      async () => {
        throw new Error("wasm refused");
      },
      async () => new StubRenderer("server", new RendererUnavailable("tools/call rejected")),
    ]);
    await expect(attempt).rejects.toBeInstanceOf(RendererUnavailable);
    await expect(attempt).rejects.toThrow(/wasm refused.*tools\/call rejected/s);
  });
});
