// DOM side of the score: the page on show and the gold cursor over it. Knows Verovio's markup
// (`g.measure`) and index.html; no host code.

import type { StageUi } from "./scoreStage.ts";

/** Keep the cursor this far from the edge of the scrolled score. */
const SCROLL_MARGIN = 40;

export class ScoreDom implements StageUi {
  private readonly wrap: HTMLElement;
  private readonly score: HTMLElement;
  private readonly cursor: HTMLElement;
  private readonly note: HTMLElement;

  constructor(doc: Document) {
    const byId = (id: string) => {
      const found = doc.getElementById(id);
      if (!found) throw new Error(`index.html is missing #${id}`);
      return found;
    };
    this.wrap = byId("score-wrap");
    this.score = byId("score");
    this.cursor = byId("cursor");
    this.note = byId("score-note");
  }

  showPage(svg: string, page: number, pageCount: number): void {
    // Verovio escapes score text, and markup assigned through innerHTML never runs scripts.
    this.score.innerHTML = svg;
    this.cursor.hidden = true;
    this.note.hidden = pageCount <= 1;
    this.note.textContent = `Page ${page} of ${pageCount}`;
    this.score.setAttribute("aria-label", pageCount > 1 ? `Score, page ${page} of ${pageCount}` : "Score");
  }

  containerWidth(): number {
    const style = getComputedStyle(this.wrap);
    const padding = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight);
    return Math.max(0, this.wrap.clientWidth - padding);
  }

  /** Observes the score area's width, in frames, so a host resize re-flows it once. */
  onResize(listener: (width: number) => void): void {
    let frame = 0;
    new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => listener(this.containerWidth()));
    }).observe(this.wrap);
  }

  placeCursor(index: number, fraction: number): void {
    const bar = this.score.querySelectorAll("svg g.measure")[index];
    if (!bar) return this.hideCursor();
    const barBox = bar.getBoundingClientRect();
    const wrapBox = this.wrap.getBoundingClientRect();
    const x = barBox.left - wrapBox.left + this.wrap.scrollLeft + fraction * barBox.width;
    const y = barBox.top - wrapBox.top + this.wrap.scrollTop;
    this.cursor.style.height = `${barBox.height}px`;
    this.cursor.style.transform = `translate(${x}px, ${y}px)`;
    this.cursor.dataset.index = String(index);
    this.cursor.hidden = false;
    this.keepInView(x);
  }

  hideCursor(): void {
    this.cursor.hidden = true;
  }

  private keepInView(x: number): void {
    const { scrollLeft, clientWidth } = this.wrap;
    if (x < scrollLeft + SCROLL_MARGIN || x > scrollLeft + clientWidth - SCROLL_MARGIN) {
      this.wrap.scrollLeft = Math.max(0, x - SCROLL_MARGIN);
    }
  }
}
