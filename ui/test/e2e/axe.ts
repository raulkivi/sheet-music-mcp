// The axe check at a stop, in a real browser, so colour contrast is measured too. WCAG 2.2 A/AA.
// Copied with attribution (MIT, Raul Kivi) from raulkivi/agent-cost-analyzer,
// packages/web/e2e/support/axe.ts; docs/research/ui-and-sound-testing-plan.md R4, decision 1.

import { createRequire } from "node:module";
import type { Frame, Page } from "@playwright/test";

const axePath = createRequire(import.meta.url).resolve("axe-core/axe.min.js");

/**
 * Every axe violation in the page or frame, one line per node. `exclude`: CSS selectors of parts
 * the check does not own, each with its reason at the call site (the score's SVG notation).
 */
export async function axeViolations(page: Page | Frame, options: { exclude?: string[] } = {}): Promise<string[]> {
  await page.addScriptTag({ path: axePath });
  return page.evaluate(async (exclude) => {
    const axe = (window as unknown as {
      axe: {
        run: (
          context: Document | object,
          options: object,
        ) => Promise<{ violations: { id: string; help: string; nodes: { target: string[] }[] }[] }>;
      };
    }).axe;
    const context = exclude.length === 0 ? document : { include: [document], exclude: exclude.map((selector) => [selector]) };
    const results = await axe.run(context, {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"] },
      resultTypes: ["violations"],
    });
    return results.violations.flatMap((violation) =>
      violation.nodes.map((node) => `${violation.id}: ${violation.help} — ${node.target.join(" ")}`),
    );
  }, options.exclude ?? []);
}
