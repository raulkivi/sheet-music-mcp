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
  downloadPdf(): Promise<void>;
  setPartFilter(id: string | null): void;
  setHighlight(id: string | null): void;
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
    downloadPdf: HTMLButtonElement;
    status: HTMLElement;
    parts: HTMLElement;
    partFilter: HTMLSelectElement;
    partHighlight: HTMLSelectElement;
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
      downloadPdf: byId("download-pdf"),
      status: byId("status"),
      parts: byId("parts"),
      partFilter: byId("part-filter"),
      partHighlight: byId("part-highlight"),
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
    // Not disabled while it works: that would drop keyboard focus. The viewer ignores a second click.
    el.downloadPdf.addEventListener("click", () => {
      el.downloadPdf.setAttribute("aria-busy", "true");
      controls.downloadPdf().finally(() => el.downloadPdf.removeAttribute("aria-busy"));
    });
    el.partFilter.addEventListener("change", () => controls.setPartFilter(el.partFilter.value || null));
    el.partHighlight.addEventListener("change", () => controls.setHighlight(el.partHighlight.value || null));
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
    // A disabled button drops keyboard focus to the body; hand it to the other paging button.
    const focused = this.doc.activeElement;
    el.prev.disabled = page <= 1;
    el.next.disabled = page >= pageCount;
    if (focused === el.next && el.next.disabled && !el.prev.disabled) el.prev.focus();
    if (focused === el.prev && el.prev.disabled && !el.next.disabled) el.next.focus();
    for (const button of [el.zoomIn, el.zoomOut, el.download, el.downloadPdf]) button.disabled = false;
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

  showParts(parts: { id: string; name: string }[], shown: string | null, highlighted: string | null): void {
    const { el } = this;
    el.parts.hidden = parts.length === 0;
    const options = (select: HTMLSelectElement, first: string, list: { id: string; name: string }[], value: string | null) => {
      const wanted = [["", first], ...list.map((part) => [part.id, part.name] as const)];
      const current = [...select.options].map((option) => [option.value, option.textContent]);
      if (JSON.stringify(current) !== JSON.stringify(wanted)) {
        select.replaceChildren(...wanted.map(([id, label]) => new Option(label, id)));
      }
      select.value = value ?? "";
    };
    options(el.partFilter, "All parts", parts, shown);
    // Only a part that is drawn can be highlighted.
    options(el.partHighlight, "No highlight", shown === null ? parts : parts.filter((part) => part.id === shown), highlighted);
  }

  showHighlight(dimmed: number[]): void {
    const wanted = new Set(dimmed);
    for (const element of this.el.score.querySelectorAll(".dimmed")) element.classList.remove("dimmed");
    if (wanted.size === 0) return;
    // Verovio draws one staff group per staff in every measure, in score order; the system's
    // labels follow the same order when each staff has one.
    for (const system of this.el.score.querySelectorAll("svg .system")) {
      const labels = [...system.querySelectorAll(":scope > g.label, :scope > g.labelAbbr")];
      const staves = [...system.querySelectorAll(":scope > g.measure")].map((measure) => [...measure.querySelectorAll(":scope > g.staff")]);
      const perStaff = Math.max(0, ...staves.map((row) => row.length));
      for (const row of staves) row.forEach((staff, index) => wanted.has(index) && staff.classList.add("dimmed"));
      if (labels.length === perStaff) labels.forEach((label, index) => wanted.has(index) && label.classList.add("dimmed"));
    }
  }

  showStatus(text: string): void {
    this.el.status.textContent = text;
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

  download(filename: string, content: BlobPart, mime: string): void {
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
