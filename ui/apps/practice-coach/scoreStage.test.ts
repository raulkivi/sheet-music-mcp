import { describe, expect, it } from "vitest";
import { RendererUnavailable, ScoreLoadError, type RenderedPage, type ScoreRenderer } from "@sheet-music-mcp/ui-kit/score/ScoreRenderer";
import { ScoreStage, type StageUi } from "./scoreStage.ts";

const XML = `<score-partwise><part id="P1">
<measure number="1"><attributes><time><beats>4</beats></time></attributes></measure>
<measure number="2"/><measure number="3"/><measure number="4"/><measure number="5"/>
</part></score-partwise>`;

/** Pages of two, two and one bars. */
const PAGES = [2, 2, 1].map((bars, i) => `<svg data-page="${i + 1}">${'<g class="measure"/>'.repeat(bars)}</svg>`);

class FakeRenderer implements ScoreRenderer {
  readonly engine = "wasm" as const;
  zoomFactor = 1;
  widths: number[] = [];
  loaded = 0;
  pageRequests: number[] = [];
  constructor(private readonly pages = PAGES) {}
  load() { this.loaded++; }
  layout(width: number) { this.widths.push(width); }
  zoom() {}
  async page(page: number): Promise<RenderedPage> {
    this.pageRequests.push(page);
    return { svg: this.pages[page - 1] as string, page, pageCount: this.pages.length };
  }
}

class FakeUi implements StageUi {
  shown: { svg: string; page: number; pageCount: number }[] = [];
  cursors: { index: number; fraction: number }[] = [];
  hidden = 0;
  width = 800;
  showPage(svg: string, page: number, pageCount: number) { this.shown.push({ svg, page, pageCount }); }
  containerWidth() { return this.width; }
  placeCursor(index: number, fraction: number) { this.cursors.push({ index, fraction }); }
  hideCursor() { this.hidden++; }
}

function stage(renderer: FakeRenderer = new FakeRenderer(), ui = new FakeUi()) {
  return { stage: new ScoreStage([async () => renderer], ui), renderer, ui };
}

describe("ScoreStage.load", () => {
  it("lays out at the container width, loads the score and shows the first page", async () => {
    const { stage: s, renderer, ui } = stage();
    await s.load(XML);
    expect(renderer.widths).toEqual([800]);
    expect(renderer.loaded).toBe(1);
    expect(ui.shown.at(-1)).toMatchObject({ page: 1, pageCount: 3 });
  });

  it("fetches each page once to count its bars", async () => {
    const { stage: s, renderer } = stage();
    await s.load(XML);
    expect(renderer.pageRequests.sort()).toEqual([1, 2, 3]);
  });

  it("falls back to the next renderer when the first cannot start", async () => {
    const ui = new FakeUi();
    const second = new FakeRenderer();
    const s = new ScoreStage(
      [
        async () => {
          throw new RendererUnavailable("no wasm");
        },
        async () => second,
      ],
      ui,
    );
    await s.load(XML);
    expect(second.loaded).toBe(1);
  });

  it("rejects an unreadable score", async () => {
    const bad = new FakeRenderer();
    bad.load = () => {
      throw new ScoreLoadError("bad");
    };
    await expect(stage(bad).stage.load(XML)).rejects.toBeInstanceOf(ScoreLoadError);
  });
});

describe("ScoreStage.showCursor", () => {
  it("places the cursor in the bar's place on the page, by beat", async () => {
    const { stage: s, ui } = stage();
    await s.load(XML);
    s.showCursor(2, 3);
    expect(ui.cursors.at(-1)).toEqual({ index: 1, fraction: 0.5 });
  });

  it("turns to the page that has the bar, keeping the other pages in the cache", async () => {
    const { stage: s, ui, renderer } = stage();
    await s.load(XML);
    const requests = renderer.pageRequests.length;
    s.showCursor(3, 1);
    expect(ui.shown.at(-1)).toMatchObject({ page: 2 });
    expect(ui.cursors.at(-1)).toEqual({ index: 0, fraction: 0 });
    s.showCursor(4, 1);
    expect(ui.shown.filter((p) => p.page === 2)).toHaveLength(1);
    expect(renderer.pageRequests.length).toBe(requests);
  });

  it("visits bars in order across pages", async () => {
    const { stage: s, ui } = stage();
    await s.load(XML);
    for (const bar of [1, 2, 3, 4, 5]) s.showCursor(bar, 1);
    expect(ui.shown.map((p) => p.page)).toEqual([1, 2, 3]);
  });

  it("hides the cursor for a bar the score does not have", async () => {
    const { stage: s, ui } = stage();
    await s.load(XML);
    s.showCursor(99, 1);
    expect(ui.hidden).toBeGreaterThan(0);
  });

  it("does nothing before a score is loaded", () => {
    const { stage: s, ui } = stage();
    s.showCursor(1, 1);
    expect(ui.cursors).toEqual([]);
  });

  it("hideCursor hides it", async () => {
    const { stage: s, ui } = stage();
    await s.load(XML);
    s.hideCursor();
    expect(ui.hidden).toBeGreaterThan(0);
  });
});

describe("ScoreStage.resize", () => {
  it("re-flows at the new width and keeps the cursor's bar", async () => {
    const { stage: s, ui, renderer } = stage();
    await s.load(XML);
    s.showCursor(3, 1);
    ui.width = 400;
    await s.resize(400);
    expect(renderer.widths.at(-1)).toBe(400);
    expect(ui.cursors.at(-1)).toEqual({ index: 0, fraction: 0 });
  });

  it("ignores a width that did not change", async () => {
    const { stage: s, renderer } = stage();
    await s.load(XML);
    const layouts = renderer.widths.length;
    await s.resize(800);
    expect(renderer.widths.length).toBe(layouts);
  });
});
