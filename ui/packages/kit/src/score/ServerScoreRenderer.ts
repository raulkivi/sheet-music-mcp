// Renders pages on the server through render-mcp's app-only render_page_svg tool. Used where the
// host's CSP refuses WebAssembly, so Verovio cannot run in the page. No Verovio import.

import type { HostBridge, ToolResult } from "../host/HostBridge.ts";
import { errorEnvelope } from "../host/toolErrors.ts";
import { clampPage } from "./paging.ts";
import { RendererUnavailable, ScoreLoadError, type RenderedPage, type ScoreRenderer } from "./ScoreRenderer.ts";

export const PAGE_SVG_TOOL = "render_page_svg";

const DEFAULT_CONTAINER_WIDTH = 1000;

/** The server's answer for a page past the end of the current layout. */
class PageOutOfRange extends Error {}

export class ServerScoreRenderer implements ScoreRenderer {
  readonly engine = "server" as const;
  private xml: string | undefined;
  private width = DEFAULT_CONTAINER_WIDTH;
  private factor = 1;
  /** Undefined until the server reports it for the current layout. */
  private pageCount: number | undefined;
  /** The last page fetched, so load() followed by page(1) costs one call. */
  private last: { key: string; page: RenderedPage } | undefined;

  constructor(private readonly bridge: HostBridge) {}

  async load(xml: string): Promise<void> {
    this.xml = xml;
    this.pageCount = undefined;
    this.last = undefined;
    await this.page(1);
  }

  layout(containerWidth: number): void {
    const width = Math.round(containerWidth);
    if (width > 0 && width !== this.width) {
      this.width = width;
      this.pageCount = undefined;
    }
  }

  zoom(factor: number): void {
    if (factor > 0 && factor !== this.factor) {
      this.factor = factor;
      this.pageCount = undefined;
    }
  }

  get zoomFactor(): number {
    return this.factor;
  }

  async page(page: number): Promise<RenderedPage> {
    // With the count unknown (new layout), ask for the page and let the server say if it is gone.
    const wanted = clampPage(page, this.pageCount ?? Number.MAX_SAFE_INTEGER);
    try {
      return await this.fetch(wanted);
    } catch (error) {
      // A re-flow can shrink the score below the page shown; learn the new count from page 1.
      if (!(error instanceof PageOutOfRange) || wanted === 1) throw unavailable(error);
      const first = await this.fetch(1);
      return first.pageCount === 1 ? first : this.fetch(clampPage(page, first.pageCount));
    }
  }

  private async fetch(page: number): Promise<RenderedPage> {
    if (this.xml === undefined) throw new Error("ServerScoreRenderer has no score loaded.");
    const args = { musicxml: this.xml, page, width_px: this.width, zoom: this.factor };
    const key = `${page}|${this.width}|${this.factor}`;
    if (this.last?.key === key) return this.last.page;
    let result: ToolResult;
    try {
      result = await this.bridge.callTool(PAGE_SVG_TOOL, args);
    } catch (error) {
      throw unavailable(error);
    }
    const rendered = readPage(result, page);
    this.pageCount = rendered.pageCount;
    this.last = { key, page: rendered };
    return rendered;
  }
}

function readPage(result: ToolResult, requested: number): RenderedPage {
  const envelope = errorEnvelope(result);
  if (envelope?.code === "INVALID_INPUT") throw new ScoreLoadError(envelope.error || "The server could not read the score.");
  if (envelope?.code === "INVALID_PARAMETER" && requested > 1) throw new PageOutOfRange(envelope.error);
  if (envelope) throw new RendererUnavailable(`${PAGE_SVG_TOOL} failed (${envelope.code}).`);
  const data = result.structuredContent ?? {};
  const { svg, page, page_count: pageCount } = data;
  if (typeof svg !== "string" || typeof page !== "number" || typeof pageCount !== "number") {
    throw new RendererUnavailable(`${PAGE_SVG_TOOL} returned no page.`);
  }
  return { svg, page, pageCount };
}

function unavailable(error: unknown): Error {
  if (error instanceof ScoreLoadError || error instanceof RendererUnavailable) return error;
  const reason = error instanceof Error ? error.message : String(error);
  return new RendererUnavailable(`${PAGE_SVG_TOOL} is not available: ${reason}`);
}
