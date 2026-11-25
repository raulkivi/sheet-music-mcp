// Score Viewer behaviour. Depends only on the HostBridge, ScoreRenderer candidates and a
// ViewerUi, so it runs unchanged against FakeBridge in unit tests and against the real host.

import type { HostBridge, HostContext, ToolInput, ToolResult } from "@sheet-music-mcp/ui-kit/host/HostBridge";
import { openScore } from "@sheet-music-mcp/ui-kit/score/openScore";
import { clampPage, stepZoom } from "@sheet-music-mcp/ui-kit/score/paging";
import { dimmedStaffIndexes, filterParts, listParts, type ScorePart } from "@sheet-music-mcp/ui-kit/score/parts";
import {
  ScoreLoadError,
  type RendererEngine,
  type RendererFactory,
  type ScoreRenderer,
} from "@sheet-music-mcp/ui-kit/score/ScoreRenderer";
import { loadArtifact } from "@sheet-music-mcp/ui-kit/audio/loadAudio";
import { errorEnvelope } from "@sheet-music-mcp/ui-kit/host/toolErrors";
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
  /** A line for the polite live region: progress and outcome of a download. */
  /** The part choices: empty hides them; `shown` is the one part drawn (null = all), `highlighted` the bright one. */
  showParts(parts: { id: string; name: string }[], shown: string | null, highlighted: string | null): void;
  /** Dims the staves with these indexes (position among the staves of the drawn score). */
  showHighlight(dimmed: number[]): void;
  showStatus(text: string): void;
  download(filename: string, content: BlobPart, mime: string): void;
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
  pdfFailed: "The viewer could not make the PDF. The rendered file is listed below.",
  noScore: "This tool call did not include a score.",
  renderFailed: (code: string) => `Rendering failed (${code}).`,
};

const PDF_TOOL = "get_pdf";
const PDF_CHUNK_TOOL = { tool: "read_pdf_chunk", idArgument: "pdf_id" } as const;
const PDF_FILENAME = "score.pdf";

export class ScoreViewer {
  private renderer: ScoreRenderer | undefined;
  private page = 1;
  private pageCount = 1;
  private svg: string | undefined;
  /** The score as given, and the part choices it offers. */
  private sourceXml: string | undefined;
  private parts: ScorePart[] = [];
  private shownPart: string | null = null;
  private highlight: string | null = null;
  /** The score the pages show (the source cut to the shown part); the PDF is made from it. */
  private xml: string | undefined;
  private busy = false;
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

  /** Draws only this part (re-rendering), or all parts for null. Unknown IDs are ignored. */
  setPartFilter(id: string | null): void {
    if (!this.renderer || this.sourceXml === undefined) return;
    if (id !== null && !this.parts.some((part) => part.id === id)) return;
    this.shownPart = id;
    if (this.highlight !== null && id !== null && this.highlight !== id) this.highlight = null;
    const xml = filterParts(this.sourceXml, id === null ? [] : [id]);
    this.xml = xml;
    this.enqueue(async () => {
      try {
        await this.renderer?.load(xml);
      } catch {
        this.ui.showNotice(NOTICES.unreadable);
      }
    });
    this.render();
    this.showPartChoice();
    this.ui.showStatus(id === null ? "Showing all parts" : `Showing ${this.nameOf(id)} only`);
    this.enqueue(() => this.tellModel());
  }

  /** Dims every other part's staves, or none for null. Unknown IDs are ignored. */
  setHighlight(id: string | null): void {
    if (!this.renderer) return;
    if (id !== null && !this.shownParts().some((part) => part.id === id)) return;
    this.highlight = id;
    this.ui.showHighlight(this.dimmed());
    this.showPartChoice();
    this.ui.showStatus(id === null ? "Highlight off" : `Highlighting ${this.nameOf(id)}`);
    this.enqueue(() => this.tellModel());
  }

  /** App-only get_pdf makes the PDF; read_pdf_chunk streams it by id (no path reaches the page). */
  async downloadPdf(): Promise<void> {
    if (!this.xml || this.busy) return;
    this.busy = true;
    this.ui.showStatus("Preparing the PDF…");
    try {
      const made = await this.bridge.callTool(PDF_TOOL, { musicxml: this.xml });
      const pdfId = made.structuredContent?.pdf_id;
      if (errorEnvelope(made) || typeof pdfId !== "string") throw new Error("no PDF");
      const blob = await loadArtifact(this.bridge, PDF_CHUNK_TOOL, pdfId, { mimeType: "application/pdf" });
      this.ui.download(PDF_FILENAME, blob, "application/pdf");
      this.ui.showStatus(`PDF ready: ${PDF_FILENAME}`);
    } catch {
      this.ui.showStatus(NOTICES.pdfFailed);
    } finally {
      this.busy = false;
    }
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
    this.sourceXml = xml;
    this.xml = xml;
    this.parts = listParts(xml);
    this.shownPart = null;
    this.highlight = null;
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
    this.showPartChoice();
    this.ui.showZoom(this.renderer.zoomFactor);
    this.render();
  }

  private goTo(page: number): void {
    if (!this.renderer) return;
    const target = clampPage(page, this.pageCount);
    if (target === this.page) return;
    this.page = target;
    this.render();
    this.enqueue(() => this.tellModel());
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
        this.ui.showHighlight(this.dimmed());
      } catch {
        this.ui.showNotice(NOTICES.pageFailed);
      }
    });
  }

  private shownParts(): ScorePart[] {
    return this.shownPart === null ? this.parts : this.parts.filter((part) => part.id === this.shownPart);
  }

  private dimmed(): number[] {
    return dimmedStaffIndexes(listParts(this.xml ?? ""), this.highlight);
  }

  private nameOf(id: string): string {
    return this.parts.find((part) => part.id === id)?.name ?? id;
  }

  /** One part has nothing to choose between, so the choices are hidden. */
  private showPartChoice(): void {
    const choices = this.parts.length > 1 ? this.parts : [];
    this.ui.showParts(choices.map(({ id, name }) => ({ id, name })), this.shownPart, this.highlight);
  }

  private tellModel(): Promise<void> {
    return this.bridge.updateModelContext(pageContext(this.page, this.pageCount, this.highlight));
  }

  private enqueue(task: () => Promise<void>): void {
    this.work = this.work.then(task).catch(() => {});
  }
}
