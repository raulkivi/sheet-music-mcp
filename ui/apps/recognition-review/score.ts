// The recognized score's pane: Verovio draws every page in one scrolling region; the selected
// bar is marked and scrolled into view. The only file of this app that touches Verovio.

import { ScoreView } from "@sheet-music-mcp/ui-kit/score/ScoreView";
import { measureIndex } from "./measures.ts";
import type { ScorePane } from "./reviewer.ts";

const SVG_NS = "http://www.w3.org/2000/svg";
const MIN_WIDTH = 200;

export class VerovioPane implements ScorePane {
  private view: ScoreView | undefined;
  private xml = "";
  private width = 0;
  private measure: number | undefined;

  constructor(private readonly body: HTMLElement) {
    let frame = 0;
    new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => this.relayout());
    }).observe(body);
  }

  async load(xml: string): Promise<void> {
    this.xml = xml;
    this.measure = undefined;
    this.view ??= await ScoreView.create();
    this.width = this.innerWidth();
    this.view.layout(this.width);
    this.view.load(xml);
    this.draw();
    performance.mark("review-first-score");
  }

  showMeasure(measure: number): void {
    this.measure = measure;
    this.body.querySelector(".measure-highlight")?.remove();
    const index = measureIndex(this.xml, measure);
    if (index === undefined) return;
    const target = this.body.querySelectorAll<SVGGElement>("g.measure")[index];
    if (!target?.parentNode) return;
    const box = target.getBBox();
    const mark = document.createElementNS(SVG_NS, "rect");
    mark.setAttribute("class", "measure-highlight");
    mark.setAttribute("x", String(box.x));
    mark.setAttribute("y", String(box.y));
    mark.setAttribute("width", String(box.width));
    mark.setAttribute("height", String(box.height));
    target.parentNode.insertBefore(mark, target);
    this.scrollTo(mark);
  }

  private relayout(): void {
    const width = this.innerWidth();
    if (!this.view || !this.xml || Math.abs(width - this.width) < 2) return;
    this.width = width;
    this.view.layout(width);
    this.draw();
    if (this.measure !== undefined) this.showMeasure(this.measure);
  }

  private draw(): void {
    const view = this.view!;
    const pages: string[] = [];
    for (let page = 1; page <= view.pageCount; page++) pages.push(view.svg(page));
    // Verovio escapes score text, and markup assigned through innerHTML never runs scripts.
    this.body.innerHTML = pages.join("");
  }

  private innerWidth(): number {
    const style = getComputedStyle(this.body);
    const padding = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight);
    return Math.max(MIN_WIDTH, this.body.clientWidth - padding);
  }

  // Instant, never smooth: nothing to switch off for prefers-reduced-motion.
  private scrollTo(mark: Element): void {
    const box = mark.getBoundingClientRect();
    const host = this.body.getBoundingClientRect();
    this.body.scrollTop += box.top - host.top - (host.height - box.height) / 2;
    this.body.scrollLeft += box.left - host.left - (host.width - box.width) / 2;
  }
}
