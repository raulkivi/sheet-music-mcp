// Picks the score renderer: the first candidate that starts and loads the score wins.

import { RendererUnavailable, ScoreLoadError, type RendererFactory, type ScoreRenderer } from "./ScoreRenderer.ts";

/**
 * Lays out and loads `xml` with the first candidate that works. An engine that cannot start
 * (CSP refusing WebAssembly) or reports RendererUnavailable passes to the next; an unreadable
 * score (ScoreLoadError) stops the search, since every engine reads it the same way.
 */
export async function openScore(
  xml: string,
  containerWidth: number,
  candidates: readonly RendererFactory[],
): Promise<ScoreRenderer> {
  const failures: string[] = [];
  for (const create of candidates) {
    try {
      const renderer = await create();
      renderer.layout(containerWidth);
      await renderer.load(xml);
      return renderer;
    } catch (error) {
      if (error instanceof ScoreLoadError) throw error;
      failures.push(error instanceof Error ? error.message : String(error));
    }
  }
  throw new RendererUnavailable(`No score renderer could start: ${failures.join("; ")}`);
}
