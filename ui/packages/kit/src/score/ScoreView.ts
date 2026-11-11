// Verovio WASM ScoreRenderer. The only kit file that imports Verovio.

import createVerovioModule, { type VerovioModule } from "verovio/wasm";
import { VerovioToolkit, enableLogToBuffer, type TimemapEntry } from "verovio/esm";
import { clampPage, layoutFor } from "./paging.ts";
import { ScoreLoadError, type RenderedPage, type ScoreRenderer } from "./ScoreRenderer.ts";

export type { TimemapEntry };
export { ScoreLoadError };

let modulePromise: Promise<VerovioModule> | undefined;

// The WASM module is several MB; compile it once per page, however many views exist.
function verovioModule(): Promise<VerovioModule> {
  modulePromise ??= createVerovioModule().then((module) => {
    // Keep layout warnings out of the host console; getLog() still has them.
    enableLogToBuffer(true, module);
    return module;
  });
  return modulePromise;
}

const DEFAULT_CONTAINER_WIDTH = 1000;

export class ScoreView implements ScoreRenderer {
  readonly engine = "wasm" as const;
  private loaded = false;
  private containerWidth = DEFAULT_CONTAINER_WIDTH;
  private factor = 1;
  private currentScale = 100;

  private constructor(private readonly toolkit: VerovioToolkit) {}

  /** Rejects when the browser refuses to compile WebAssembly (CSP without wasm-unsafe-eval). */
  static async create(): Promise<ScoreView> {
    return new ScoreView(new VerovioToolkit(await verovioModule()));
  }

  load(xml: string): void {
    this.applyLayout();
    this.loaded = this.toolkit.loadData(xml) && this.toolkit.getPageCount() >= 1;
    if (!this.loaded) {
      throw new ScoreLoadError(`Verovio could not read the score. ${this.toolkit.getLog()}`.trim());
    }
  }

  /** Re-flows the loaded score to a container width in CSS pixels. */
  layout(containerWidth: number): void {
    if (containerWidth > 0) this.containerWidth = containerWidth;
    this.applyLayout();
    // Before the first load the options are simply applied by load().
    if (this.loaded) this.toolkit.redoLayout();
  }

  /** Sets the zoom factor (1 = 100 %) and re-flows. */
  zoom(factor: number): void {
    if (factor > 0) this.factor = factor;
    this.layout(this.containerWidth);
  }

  get zoomFactor(): number {
    return this.factor;
  }

  /** Verovio scale actually used, percent. Lower than zoom × 100 on narrow containers. */
  get scale(): number {
    return this.currentScale;
  }

  get pageCount(): number {
    return Math.max(1, this.toolkit.getPageCount());
  }

  svg(page: number): string {
    return this.toolkit.renderToSVG(clampPage(page, this.pageCount));
  }

  page(page: number): RenderedPage {
    const pageCount = this.pageCount;
    const shown = clampPage(page, pageCount);
    return { svg: this.toolkit.renderToSVG(shown), page: shown, pageCount };
  }

  timemap(): TimemapEntry[] {
    return this.toolkit.renderToTimemap();
  }

  private applyLayout(): void {
    const { scale, pageWidth, pageHeight } = layoutFor(this.containerWidth, this.factor);
    this.currentScale = scale;
    this.toolkit.setOptions({
      scale,
      pageWidth,
      pageHeight,
      // Pages still break at pageHeight; this only drops the blank space below the last system.
      adjustPageHeight: true,
      breaks: "auto",
      footer: "none",
    });
  }
}
