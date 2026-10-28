// Score Viewer behaviour. Depends only on the HostBridge, a Renderer and a ViewerUi, so it runs
// unchanged against FakeBridge in unit tests and against the real host in the built page.

import type { HostBridge, HostContext, ToolInput, ToolResult } from "@sheet-music-mcp/ui-kit/host/HostBridge";
import { clampPage, stepZoom } from "@sheet-music-mcp/ui-kit/score/paging";
import { helpMessage, pageContext, readSavedFile, readScoreInput } from "./messages.ts";

/** The part of ScoreView the viewer needs. */
export interface Renderer {
  load(xml: string): void;
  layout(containerWidth: number): void;
  zoom(factor: number): void;
  readonly zoomFactor: number;
  readonly pageCount: number;
  svg(page: number): string;
}

export interface ViewerUi {
  showPage(svg: string, page: number, pageCount: number): void;
  showNotice(text: string): void;
  showZoom(factor: number): void;
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
  noScore: "This tool call did not include a score.",
  renderFailed: (code: string) => `Rendering failed (${code}).`,
};

export class ScoreViewer {
  private renderer: Renderer | undefined;
  private page = 1;
  private width = 0;
  private savedPath: string | undefined;
  private context: HostContext = {};
  private work: Promise<void> = Promise.resolve();

  constructor(
    private readonly bridge: HostBridge,
    private readonly createRenderer: () => Promise<Renderer>,
    private readonly ui: ViewerUi,
  ) {}

  async start(): Promise<void> {
    this.bridge.onToolInput((input) => this.onToolInput(input));
    this.bridge.onToolResult((result) => this.onToolResult(result));
    this.bridge.onHostContext((context) => this.onHostContext(context));
    this.onHostContext(await this.bridge.connect());
  }

  /** Resolves when queued rendering and host calls have finished. */
  idle(): Promise<void> {
    return this.work;
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
    if (!this.renderer) return;
    this.ui.download(`score-page-${this.page}.svg`, this.renderer.svg(this.page), "image/svg+xml");
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
    let renderer: Renderer;
    try {
      renderer = this.renderer ?? (await this.createRenderer());
    } catch {
      return this.ui.showNotice(NOTICES.engineBlocked);
    }
    try {
      renderer.load(xml);
    } catch {
      return this.ui.showNotice(NOTICES.unreadable);
    }
    this.renderer = renderer;
    this.width = Math.round(this.ui.containerWidth());
    renderer.layout(this.width);
    this.page = 1;
    this.ui.showZoom(renderer.zoomFactor);
    this.render();
  }

  private goTo(page: number): void {
    if (!this.renderer) return;
    const target = clampPage(page, this.renderer.pageCount);
    if (target === this.page) return;
    this.page = target;
    this.render();
    const text = pageContext(this.page, this.renderer.pageCount);
    this.enqueue(() => this.bridge.updateModelContext(text));
  }

  private setZoom(direction: 1 | -1): void {
    if (!this.renderer) return;
    this.renderer.zoom(stepZoom(this.renderer.zoomFactor, direction));
    this.ui.showZoom(this.renderer.zoomFactor);
    this.render();
  }

  private render(): void {
    if (!this.renderer) return;
    this.page = clampPage(this.page, this.renderer.pageCount);
    this.ui.showPage(this.renderer.svg(this.page), this.page, this.renderer.pageCount);
  }

  private enqueue(task: () => Promise<void>): void {
    this.work = this.work.then(task).catch(() => {});
  }
}
