// The score and its singing cursor. Renders every page once (a count of each page's bars is how a
// printed bar number finds its page), keeps the SVGs, and moves the cursor by turning to the
// page that has the bar. No host or Verovio imports: the renderers come in as factories.

import { openScore } from "@sheet-music-mcp/ui-kit/score/openScore";
import type { RendererFactory, ScoreRenderer } from "@sheet-music-mcp/ui-kit/score/ScoreRenderer";
import type { CoachScore } from "./coach.ts";
import { countMeasures, cursorFraction, locateMeasure, parseScoreStructure, type ScoreStructure } from "./scoreMap.ts";

export interface StageUi {
  showPage(svg: string, page: number, pageCount: number): void;
  containerWidth(): number;
  /** Places the cursor in the `index`th bar of the page on show, `fraction` (0 to 1) of the way along it. */
  placeCursor(index: number, fraction: number): void;
  hideCursor(): void;
}

/** A long score would cost a render per page up front; past this the later pages have no cursor. */
const MAX_PAGES = 40;

export class ScoreStage implements CoachScore {
  private renderer: ScoreRenderer | undefined;
  private structure: ScoreStructure = { measureNumbers: [], beatsPerMeasure: 4 };
  private xml: string | undefined;
  private width = 0;
  private pages: string[] = [];
  private pageCounts: number[] = [];
  private shown = 0;
  private cursor: { measure: number; beat: number } | undefined;

  constructor(
    private readonly factories: readonly RendererFactory[],
    private readonly ui: StageUi,
  ) {}

  async load(xml: string): Promise<void> {
    this.xml = xml;
    this.width = Math.round(this.ui.containerWidth());
    this.structure = parseScoreStructure(xml);
    this.renderer = await openScore(xml, this.width, this.factories);
    await this.renderAll();
  }

  /** Re-flows to a new container width; the cursor stays on its bar. */
  async resize(width: number): Promise<void> {
    const rounded = Math.round(width);
    if (!this.renderer || rounded <= 0 || rounded === this.width) return;
    this.width = rounded;
    this.renderer.layout(rounded);
    await this.renderAll();
    if (this.cursor) this.showCursor(this.cursor.measure, this.cursor.beat);
  }

  showCursor(measure: number, beat: number): void {
    this.cursor = { measure, beat };
    const where = locateMeasure(measure, this.structure.measureNumbers, this.pageCounts);
    if (!where) return this.ui.hideCursor();
    if (where.page !== this.shown) this.show(where.page);
    this.ui.placeCursor(where.index, cursorFraction(beat, this.structure.beatsPerMeasure));
  }

  hideCursor(): void {
    this.cursor = undefined;
    this.ui.hideCursor();
  }

  private async renderAll(): Promise<void> {
    const renderer = this.renderer;
    if (!renderer) return;
    this.pages = [];
    this.pageCounts = [];
    const first = await renderer.page(1);
    const total = Math.min(first.pageCount, MAX_PAGES);
    this.pages.push(first.svg);
    for (let page = 2; page <= total; page++) this.pages.push((await renderer.page(page)).svg);
    this.pageCounts = this.pages.map(countMeasures);
    this.shown = 0;
    this.show(1);
  }

  private show(page: number): void {
    this.shown = page;
    this.ui.showPage(this.pages[page - 1] as string, page, this.pages.length);
  }
}
