import { describe, expect, it } from "vitest";
import {
  BASE_SCALE,
  MIN_LAYOUT_WIDTH,
  ZOOM_STEPS,
  clampPage,
  fitWidthScale,
  layoutFor,
  stepZoom,
} from "./paging.ts";

describe("clampPage", () => {
  it("keeps a page inside 1..pageCount", () => {
    expect(clampPage(3, 5)).toBe(3);
    expect(clampPage(0, 5)).toBe(1);
    expect(clampPage(-2, 5)).toBe(1);
    expect(clampPage(6, 5)).toBe(5);
  });

  it("maps NaN and non-finite pages to 1", () => {
    expect(clampPage(Number.NaN, 5)).toBe(1);
    expect(clampPage(Number.POSITIVE_INFINITY, 5)).toBe(1);
  });

  it("rounds fractional pages", () => {
    expect(clampPage(2.4, 5)).toBe(2);
    expect(clampPage(2.6, 5)).toBe(3);
  });

  it("treats an empty or invalid page count as one page", () => {
    expect(clampPage(3, 0)).toBe(1);
    expect(clampPage(3, Number.NaN)).toBe(1);
  });
});

describe("zoom steps", () => {
  it("are ascending and include 1 (100 %)", () => {
    expect(ZOOM_STEPS).toContain(1);
    expect([...ZOOM_STEPS].sort((a, b) => a - b)).toEqual([...ZOOM_STEPS]);
  });

  it("step to the neighbouring zoom level", () => {
    const i = ZOOM_STEPS.indexOf(1);
    expect(stepZoom(1, +1)).toBe(ZOOM_STEPS[i + 1]);
    expect(stepZoom(1, -1)).toBe(ZOOM_STEPS[i - 1]);
  });

  it("stop at both ends", () => {
    const min = ZOOM_STEPS[0]!;
    const max = ZOOM_STEPS[ZOOM_STEPS.length - 1]!;
    expect(stepZoom(min, -1)).toBe(min);
    expect(stepZoom(max, +1)).toBe(max);
  });

  it("snap an off-grid zoom to the next step in the requested direction", () => {
    expect(stepZoom(1.1, +1)).toBeGreaterThan(1.1);
    expect(stepZoom(1.1, -1)).toBe(1);
  });
});

describe("fitWidthScale", () => {
  it("returns the percentage scale that fits a page width into the container", () => {
    expect(fitWidthScale(800, 1600)).toBe(50);
    expect(fitWidthScale(1000, 1000)).toBe(100);
  });

  it("stays inside Verovio's scale range", () => {
    expect(fitWidthScale(10, 100_000)).toBe(1);
    expect(fitWidthScale(100_000, 10)).toBe(1000);
  });

  it("falls back to 100 for unusable sizes", () => {
    expect(fitWidthScale(0, 1000)).toBe(100);
    expect(fitWidthScale(800, 0)).toBe(100);
    expect(fitWidthScale(Number.NaN, 1000)).toBe(100);
  });
});

describe("layoutFor", () => {
  it("maps zoom 1 to the base Verovio scale, so 100 % reads like a printed page", () => {
    expect(layoutFor(1000, 1).scale).toBe(BASE_SCALE);
  });

  it("re-flows the page to the container width at the requested zoom", () => {
    expect(layoutFor(1000, 1)).toEqual({ scale: 40, pageWidth: 2500, pageHeight: 3535 });
    expect(layoutFor(1400, 2)).toEqual({ scale: 80, pageWidth: 1750, pageHeight: 2475 });
  });

  it("keeps a minimum layout width on narrow containers and scales it down instead", () => {
    const layout = layoutFor(300, 1);
    expect(layout.pageWidth).toBe(MIN_LAYOUT_WIDTH);
    expect(layout.scale).toBe(20);
  });
});
