// Score Viewer behaviour. Depends only on the HostBridge, ScoreRenderer candidates and a
// ViewerUi, so it runs unchanged against FakeBridge in unit tests and against the real host.

import type { HostBridge, HostContext, ToolInput, ToolResult } from "@sheet-music-mcp/ui-kit/host/HostBridge";
import { openScore } from "@sheet-music-mcp/ui-kit/score/openScore";
import { clampPage, stepZoom } from "@sheet-music-mcp/ui-kit/score/paging";
import {
  ScoreLoadError,
  type RendererEngine,
  type RendererFactory,
  type ScoreRenderer,
} from "@sheet-music-mcp/ui-kit/score/ScoreRenderer";
import { helpMessage, pageContext, readSavedFile, readScoreInput } from "./messages.ts";

export interface ViewerUi {
  showPage(svg: string, page: number, pageCount: number): void;
  showNotice(text: string): void;
  showZoom(factor: number): void;
  /** Which engine renders the pages (the manual host checks record it). */
  showEngine(engine: RendererEngine): void;
  showSavedPath(path: string): void;
  showDownloadFallback(path: string): void;
  showFullscreen(available: boolean, active: boolean): void;
  applyHostContext(context: HostContext): void;
  containerWidth(): number;
  download(filename: string, content: string, mime: string): void;
}

export const NOTICES = {
  pathOnly:
    "The inline viewer needs the score inline (the musicxml argument). This call passed a file " +
    "path, so the score was only rendered to the file listed below.",
  engineBlocked:
    "The viewer could not start the notation engine in this host (WebAssembly may be blocked). " +
    "The rendered file is listed below.",
  unreadable: "The viewer could not read this score.",
  pageFailed: "The viewer could not render this page. The rendered file is listed below.",
  noScore: "This tool call did not include a score.",
  renderFailed: (code: string) => `Rendering failed (${code}).`,
};

export class ScoreViewer {
  private renderer: ScoreRenderer | undefined;
  private page = 1;
  private pageCount = 1;
  private svg: string | undefined;
  private width = 0;
  private savedPath: string | undefined;
  private context: HostContext = {};
  private work: Promise<void> = Promise.resolve();
  /** Bumped by every render request, so a page superseded while waiting is skipped. */
  private renderRequest = 0;

  /** `renderers` in order of preference: Verovio WASM first, the server second. */
  constructor(
    private readonly bridge: HostBridge,
    private readonly renderers: readonly RendererFactory[],
    private readonly ui: ViewerUi,
  ) {}

  async start(): Promise<void> {
    this.bridge.onToolInput((input) => this.onToolInput(input));
    this.bridge.onToolResult((result) => this.onToolResult(result));
    this.bridge.onHostContext((context) => this.onHostContext(context));
    this.onHostContext(await this.bridge.connect());
  }

  /** Resolves when queued rendering and host calls have finished, including work they queued. */
  async idle(): Promise<void> {
    let settled: Promise<void>;
    do {
      settled = this.work;
      await settled;
    } while (settled !== this.work);
  }

  next(): void {
    this.goTo(this.page + 1);
  }

  prev(): void {
    this.goTo(this.page - 1);
  }

  zoomIn(): void {
    this.setZoom(+1);
  }

  zoomOut(): void {
    this.setZoom(-1);
  }

  resize(width: number): void {
    if (!this.renderer || Math.round(width) === this.width || width <= 0) return;
    this.width = Math.round(width);
    this.renderer.layout(this.width);
    this.render();
  }

  downloadSvg(): void {
    // The page on screen, so the click needs no render call and keeps its user activation.
    if (!this.svg) return;
    this.ui.download(`score-page-${this.page}.svg`, this.svg, "image/svg+xml");
    // A sandbox without allow-downloads drops the click silently, so always offer the fallback.
    if (this.savedPath) this.ui.showDownloadFallback(this.savedPath);
  }

  async askForHelp(): Promise<void> {
    if (!this.savedPath) return;
    await this.bridge.sendMessage(helpMessage(this.savedPath));
  }

  async toggleFullscreen(): Promise<void> {
    const target = this.context.displayMode === "fullscreen" ? "inline" : "fullscreen";
    const granted = await this.bridge.requestDisplayMode(target);
    this.onHostContext({ ...this.context, displayMode: granted });
  }

  private onToolInput(input: ToolInput): void {
    const score = readScoreInput(input.arguments);
    if (score.kind === "path") return this.ui.showNotice(NOTICES.pathOnly);
    if (score.kind === "none") return this.ui.showNotice(NOTICES.noScore);
    this.enqueue(() => this.open(score.xml));
  }

  private onToolResult(result: ToolResult): void {
    const saved = readSavedFile(result);
    if (saved.error) this.ui.showNotice(NOTICES.renderFailed(saved.error));
    if (saved.path) {
      this.savedPath = saved.path;
      this.ui.showSavedPath(saved.path);
    }
  }

  private onHostContext(context: HostContext): void {
    this.context = context;
    this.ui.applyHostContext(context);
    const available = context.availableDisplayModes?.includes("fullscreen") ?? false;
    this.ui.showFullscreen(available, context.displayMode === "fullscreen");
  }

  private async open(xml: string): Promise<void> {
    this.width = Math.round(this.ui.containerWidth());
    try {
      if (this.renderer) {
        this.renderer.layout(this.width);
        await this.renderer.load(xml);
      } else {
        this.renderer = await openScore(xml, this.width, this.renderers);
      }
    } catch (error) {
      return this.ui.showNotice(error instanceof ScoreLoadError ? NOTICES.unreadable : NOTICES.engineBlocked);
    }
    this.ui.showEngine(this.renderer.engine);
    this.page = 1;
    this.ui.showZoom(this.renderer.zoomFactor);
    this.render();
  }

  private goTo(page: number): void {
    if (!this.renderer) return;
    const target = clampPage(page, this.pageCount);
    if (target === this.page) return;
    this.page = target;
    this.render();
    this.enqueue(() => this.bridge.updateModelContext(pageContext(this.page, this.pageCount)));
  }

  private setZoom(direction: 1 | -1): void {
    if (!this.renderer) return;
    this.renderer.zoom(stepZoom(this.renderer.zoomFactor, direction));
    this.ui.showZoom(this.renderer.zoomFactor);
    this.render();
  }

  private render(): void {
    const request = ++this.renderRequest;
    this.enqueue(async () => {
      if (!this.renderer || request !== this.renderRequest) return;
      try {
        const shown = await this.renderer.page(this.page);
        if (request !== this.renderRequest) return;
        this.page = shown.page;
        this.pageCount = shown.pageCount;
        this.svg = shown.svg;
        this.ui.showPage(shown.svg, shown.page, shown.pageCount);
      } catch {
        this.ui.showNotice(NOTICES.pageFailed);
      }
    });
  }

  private enqueue(task: () => Promise<void>): void {
    this.work = this.work.then(task).catch(() => {});
  }
}
