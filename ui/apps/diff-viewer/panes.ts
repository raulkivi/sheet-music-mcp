// The two score panes: Verovio draws every page of each annotated score in its own scrolling
// pane; the selected bar is marked and scrolled into view in both. The only file of this app that
// touches Verovio. The diff colors are already in the MusicXML (Verovio draws noteheads in them).

import { ScoreView } from "@sheet-music-mcp/ui-kit/score/ScoreView";
import { measureIndex } from "./messages.ts";
import type { ScorePanes } from "./viewer.ts";

const SVG_NS = "http://www.w3.org/2000/svg";
const MIN_WIDTH = 200;

class Pane {
  private view: ScoreView | undefined;
  private xml = "";
  private width = 0;

  constructor(private readonly body: HTMLElement) {}

  async load(xml: string): Promise<void> {
    this.xml = xml;
    this.view ??= await ScoreView.create();
    this.width = this.innerWidth();
    this.view.layout(this.width);
    this.view.load(xml);
    this.draw();
  }

  /** Re-flows when the pane's width changed; true if it redrew. */
  relayout(): boolean {
    const width = this.innerWidth();
    if (!this.view || !this.xml || Math.abs(width - this.width) < 2) return false;
    this.width = width;
    this.view.layout(width);
    this.draw();
    return true;
  }

  showMeasure(measure: number): void {
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

export class VerovioPanes implements ScorePanes {
  private readonly reference: Pane;
  private readonly target: Pane;
  private measure: number | undefined;

  constructor(
    private readonly referenceBody: HTMLElement,
    private readonly targetBody: HTMLElement,
    private readonly root: HTMLElement,
  ) {
    this.reference = new Pane(referenceBody);
    this.target = new Pane(targetBody);
    let frame = 0;
    new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => this.relayout());
    }).observe(referenceBody);
  }

  async load(reference: string, target: string, legend: Record<string, string>): Promise<void> {
    for (const [kind, color] of Object.entries(legend)) {
      if (/^[A-Z_]+$/.test(kind) && /^#[0-9a-fA-F]{6}$/.test(color)) this.root.style.setProperty(`--kind-${kind}`, color);
    }
    await this.reference.load(reference);
    await this.target.load(target);
    performance.mark("diff-first-scores");
    if (this.measure !== undefined) this.showMeasure(this.measure);
  }

  showMeasure(measure: number): void {
    this.measure = measure;
    this.reference.showMeasure(measure);
    this.target.showMeasure(measure);
  }

  private relayout(): void {
    const redrew = [this.reference.relayout(), this.target.relayout()].some(Boolean);
    if (redrew && this.measure !== undefined) this.showMeasure(this.measure);
  }
}
