// DOM implementation of ViewerUi. Knows the markup in index.html; no host or Verovio code.

import type { HostContext } from "@sheet-music-mcp/ui-kit/host/HostBridge";
import type { RendererEngine } from "@sheet-music-mcp/ui-kit/score/ScoreRenderer";
import { applyTheme } from "@sheet-music-mcp/ui-kit/theme";
import type { ViewerUi } from "./viewer.ts";

export interface Controls {
  next(): void;
  prev(): void;
  zoomIn(): void;
  zoomOut(): void;
  resize(width: number): void;
  downloadSvg(): void;
  askForHelp(): Promise<void>;
  toggleFullscreen(): Promise<void>;
}

export const ENGINE_LABELS: Record<RendererEngine, string> = {
  wasm: "Notation rendered in this view (Verovio WebAssembly)",
  server: "Notation rendered by the server (Verovio)",
};

/** Marked once, when the first score page is on screen; read by scripts/measure.mjs. */
export const FIRST_PAGE_MARK = "score-first-page";

export class DomUi implements ViewerUi {
  private readonly el: {
    score: HTMLElement;
    notice: HTMLElement;
    pageLabel: HTMLElement;
    zoomLabel: HTMLElement;
    prev: HTMLButtonElement;
    next: HTMLButtonElement;
    zoomIn: HTMLButtonElement;
    zoomOut: HTMLButtonElement;
    download: HTMLButtonElement;
    fullscreen: HTMLButtonElement;
    saved: HTMLElement;
    savedPath: HTMLElement;
    fallback: HTMLElement;
    ask: HTMLButtonElement;
    engine: HTMLElement;
  };
  private firstPageShown = false;

  constructor(private readonly doc: Document) {
    const byId = <T extends HTMLElement>(id: string) => {
      const found = doc.getElementById(id);
      if (!found) throw new Error(`index.html is missing #${id}`);
      return found as T;
    };
    this.el = {
      score: byId("score"),
      notice: byId("notice"),
      pageLabel: byId("page-label"),
      zoomLabel: byId("zoom-label"),
      prev: byId("prev"),
      next: byId("next"),
      zoomIn: byId("zoom-in"),
      zoomOut: byId("zoom-out"),
      download: byId("download"),
      fullscreen: byId("fullscreen"),
      saved: byId("saved"),
      savedPath: byId("saved-path"),
      fallback: byId("fallback"),
      ask: byId("ask"),
      engine: byId("engine"),
    };
  }

  bind(controls: Controls): void {
    const { el } = this;
    el.prev.addEventListener("click", () => controls.prev());
    el.next.addEventListener("click", () => controls.next());
    el.zoomIn.addEventListener("click", () => controls.zoomIn());
    el.zoomOut.addEventListener("click", () => controls.zoomOut());
    el.download.addEventListener("click", () => controls.downloadSvg());
    el.fullscreen.addEventListener("click", () => void controls.toggleFullscreen());
    el.ask.addEventListener("click", () => {
      el.ask.disabled = true;
      controls.askForHelp().finally(() => (el.ask.disabled = false));
    });
    this.doc.addEventListener("keydown", (event) => {
      if (event.key === "ArrowRight" || event.key === "PageDown") controls.next();
      if (event.key === "ArrowLeft" || event.key === "PageUp") controls.prev();
    });
    let frame = 0;
    new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => controls.resize(this.containerWidth()));
    }).observe(el.score);
  }

  showPage(svg: string, page: number, pageCount: number): void {
    const { el } = this;
    // Verovio escapes score text, and markup assigned through innerHTML never runs scripts.
    el.score.innerHTML = svg;
    el.score.hidden = false;
    el.notice.hidden = true;
    el.pageLabel.textContent = `Page ${page} / ${pageCount}`;
    el.prev.disabled = page <= 1;
    el.next.disabled = page >= pageCount;
    for (const button of [el.zoomIn, el.zoomOut, el.download]) button.disabled = false;
    if (!this.firstPageShown) {
      this.firstPageShown = true;
      performance.mark(FIRST_PAGE_MARK);
    }
  }

  showNotice(text: string): void {
    this.el.notice.textContent = text;
    this.el.notice.hidden = false;
    this.el.score.hidden = true;
  }

  showZoom(factor: number): void {
    this.el.zoomLabel.textContent = `${Math.round(factor * 100)}%`;
  }

  showEngine(engine: RendererEngine): void {
    this.el.engine.textContent = ENGINE_LABELS[engine];
    this.el.engine.dataset.engine = engine;
    this.el.engine.hidden = false;
  }

  showSavedPath(path: string): void {
    this.el.savedPath.textContent = path;
    this.el.saved.hidden = false;
  }

  showDownloadFallback(path: string): void {
    this.showSavedPath(path);
    this.el.fallback.hidden = false;
  }

  showFullscreen(available: boolean, active: boolean): void {
    this.el.fullscreen.hidden = !available;
    this.el.fullscreen.textContent = active ? "Exit fullscreen" : "Fullscreen";
    this.el.fullscreen.setAttribute("aria-pressed", String(active));
  }

  applyHostContext(context: HostContext): void {
    applyTheme(this.doc.documentElement, context);
  }

  containerWidth(): number {
    const style = getComputedStyle(this.el.score);
    const padding = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight);
    return Math.max(0, this.el.score.clientWidth - padding);
  }

  download(filename: string, content: string, mime: string): void {
    const url = URL.createObjectURL(new Blob([content], { type: mime }));
    const link = this.doc.createElement("a");
    link.href = url;
    link.download = filename;
    link.hidden = true;
    this.doc.body.append(link);
    link.click();
    link.remove();
    // Revoking at once can cancel the download in some browsers.
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  }
}
