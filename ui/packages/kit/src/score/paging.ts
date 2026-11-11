// Pure page/zoom maths for score views. No DOM, no Verovio.

/** Zoom factors offered by the +/- buttons (1 = 100 %). */
export const ZOOM_STEPS: readonly number[] = [0.5, 0.67, 0.8, 1, 1.25, 1.5, 2, 3];

/** Verovio rejects scales outside this range (percent). */
const MIN_SCALE = 1;
const MAX_SCALE = 1000;

/**
 * Verovio scale (percent) shown as 100 %. Verovio's own 100 lays an A4 page out 2100 px wide,
 * which is about twice print size on screen.
 */
export const BASE_SCALE = 40;

/** Below this layout width (Verovio units) systems hold too few bars to read; shrink instead. */
export const MIN_LAYOUT_WIDTH = 1500;

/** A4 portrait, so pages look like the PDF from render_to_pdf. */
const PAGE_ASPECT = 1.414;

export interface Layout {
  /** Verovio `scale` option, percent. */
  scale: number;
  /** Verovio `pageWidth` option, layout units. */
  pageWidth: number;
  /** Verovio `pageHeight` option, layout units. */
  pageHeight: number;
}

export function clampPage(page: number, pageCount: number): number {
  const last = Number.isFinite(pageCount) && pageCount >= 1 ? Math.floor(pageCount) : 1;
  if (!Number.isFinite(page)) return 1;
  return Math.min(last, Math.max(1, Math.round(page)));
}

/** Next zoom step from `current` in `direction`; stays put at either end. */
export function stepZoom(current: number, direction: 1 | -1): number {
  const first = ZOOM_STEPS[0]!;
  const last = ZOOM_STEPS[ZOOM_STEPS.length - 1]!;
  if (direction > 0) return ZOOM_STEPS.find((z) => z > current) ?? last;
  return [...ZOOM_STEPS].reverse().find((z) => z < current) ?? first;
}

/** Percent scale at which `pageWidth` layout units fill `containerWidth` CSS pixels. */
export function fitWidthScale(containerWidth: number, pageWidth: number): number {
  if (!(containerWidth > 0) || !(pageWidth > 0)) return 100;
  const scale = (containerWidth / pageWidth) * 100;
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, Math.round(scale)));
}

/**
 * Verovio options that re-flow the score to the container: the page is laid out exactly as
 * wide as the container at the requested zoom, so zooming changes bars per system rather
 * than causing horizontal scrolling.
 */
export function layoutFor(containerWidth: number, zoom: number): Layout {
  const scale = Math.round(zoom * BASE_SCALE);
  const wanted = Math.round((containerWidth * 100) / scale);
  if (wanted >= MIN_LAYOUT_WIDTH) return withHeight({ scale, pageWidth: wanted });
  const fitted = Math.min(scale, fitWidthScale(containerWidth, MIN_LAYOUT_WIDTH));
  return withHeight({ scale: fitted, pageWidth: MIN_LAYOUT_WIDTH });
}

function withHeight(layout: Omit<Layout, "pageHeight">): Layout {
  return { ...layout, pageHeight: Math.round(layout.pageWidth * PAGE_ASPECT) };
}
