// What a score view renders with. Implementations: ScoreView (Verovio WASM in the page) and
// ServerScoreRenderer (render-mcp's render_page_svg, for hosts whose CSP refuses WebAssembly).
// No Verovio or host imports here.

export type RendererEngine = "wasm" | "server";

export interface RenderedPage {
  svg: string;
  /** The page actually rendered, after clamping to the page count. */
  page: number;
  /** Pages at the current width and zoom. */
  pageCount: number;
}

/** Methods may answer synchronously (WASM) or asynchronously (server); callers always await. */
export interface ScoreRenderer {
  readonly engine: RendererEngine;
  /** Rejects with ScoreLoadError for an unreadable score, RendererUnavailable if the engine cannot work. */
  load(xml: string): void | Promise<void>;
  /** Re-flows to a container width in CSS pixels; takes effect on the next page. */
  layout(containerWidth: number): void;
  /** Sets the zoom factor (1 = 100 %); takes effect on the next page. */
  zoom(factor: number): void;
  readonly zoomFactor: number;
  /** Renders `page`, clamped to the current page count. */
  page(page: number): RenderedPage | Promise<RenderedPage>;
}

export type RendererFactory = () => Promise<ScoreRenderer>;

/** The score itself is unreadable; another engine would not do better. */
export class ScoreLoadError extends Error {
  override name = "ScoreLoadError";
}

/** The engine cannot render here (WebAssembly refused, tool missing or failing). */
export class RendererUnavailable extends Error {
  override name = "RendererUnavailable";
}
