import { readFileSync } from "node:fs";
import { beforeAll, describe, expect, it } from "vitest";
import { ScoreLoadError, ScoreView } from "./ScoreView.ts";
import { ScoreLoadError as RendererScoreLoadError, type ScoreRenderer } from "./ScoreRenderer.ts";

const fixture = (name: string) =>
  readFileSync(new URL(`../../../../test/fixtures/${name}`, import.meta.url), "utf8");

const SATB = fixture("satb-4bars.musicxml");
const LONG = fixture("satb-long.musicxml");
const ANNOTATED = fixture("annotated-target.musicxml");

let view: ScoreView;

beforeAll(async () => {
  view = await ScoreView.create();
});

describe("ScoreView", () => {
  it("loads MusicXML and reports at least one page", () => {
    view.load(SATB);
    view.layout(1000);
    expect(view.pageCount).toBeGreaterThanOrEqual(1);
  });

  it("renders a page as SVG", () => {
    view.load(SATB);
    view.layout(1000);
    expect(view.svg(1)).toContain("<svg");
  });

  it("trims the page height to the music, so a short score leaves no blank page below", () => {
    view.load(SATB);
    view.layout(1000);
    const svg = view.svg(1);
    const width = Number(svg.match(/<svg[^>]* width="(\d+)px"/)?.[1]);
    const height = Number(svg.match(/<svg[^>]* height="(\d+)px"/)?.[1]);
    expect(height).toBeLessThan(width);
  });

  it("clamps out-of-range pages instead of failing", () => {
    view.load(SATB);
    view.layout(1000);
    expect(view.svg(99)).toBe(view.svg(view.pageCount));
  });

  it("zoom(2) increases the scale and changes the SVG", () => {
    view.load(SATB);
    view.layout(1000);
    const before = { scale: view.scale, svg: view.svg(1) };
    view.zoom(2);
    expect(view.zoomFactor).toBe(2);
    expect(view.scale).toBeGreaterThan(before.scale);
    expect(view.svg(1)).not.toBe(before.svg);
  });

  it("re-flows when the container width changes", () => {
    view.load(LONG);
    view.zoom(1);
    view.layout(1600);
    const wide = view.pageCount;
    view.layout(700);
    expect(view.pageCount).toBeGreaterThan(wide);
  });

  it("lays the long fixture out over at least five pages at the e2e width", () => {
    view.load(LONG);
    view.zoom(1);
    view.layout(1000);
    expect(view.pageCount).toBeGreaterThanOrEqual(5);
  });

  it("returns a timemap whose entries have tstamp, and note-on ids", () => {
    view.load(SATB);
    const map = view.timemap();
    expect(map.length).toBeGreaterThan(0);
    for (const entry of map) expect(typeof entry.tstamp).toBe("number");
    expect(map.some((e) => (e.on ?? []).length > 0)).toBe(true);
  });

  it("keeps MusicXML note colours in the SVG (comparer's annotated export)", () => {
    view.load(ANNOTATED);
    view.layout(1000);
    const pages = Array.from({ length: view.pageCount }, (_, i) => view.svg(i + 1)).join("");
    expect(pages).toMatch(/fill="#FF8800"/i);
  });

  it("rejects input that is not a score", () => {
    expect(() => view.load("not music")).toThrow(ScoreLoadError);
  });

  it("is the WASM ScoreRenderer: page() clamps and reports the page count", () => {
    const renderer: ScoreRenderer = view;
    expect(renderer.engine).toBe("wasm");
    view.load(LONG);
    view.zoom(1);
    view.layout(1000);
    const last = view.page(99);
    expect(last).toEqual({ svg: view.svg(view.pageCount), page: view.pageCount, pageCount: view.pageCount });
  });

  it("can be laid out before the first load, as openScore does", async () => {
    const fresh = await ScoreView.create();
    fresh.layout(700);
    fresh.load(LONG);
    expect(fresh.pageCount).toBeGreaterThanOrEqual(5);
  });

  it("throws the shared ScoreLoadError", () => {
    expect(ScoreLoadError).toBe(RendererScoreLoadError);
  });
});
