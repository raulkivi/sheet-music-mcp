import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { FALLBACK_VARIABLES } from "../../packages/kit/src/theme.ts";
import { contrastRatio, parseColor, type Rgb } from "./contrast.ts";
import { declaredValue } from "./css-vars.ts";

// Kannel design tokens (docs/design/tokens.css, identity in docs/design/design-system.md).
// Checks the palette itself, before any page uses it:
//   - every colour key the kit reads has a light and a dark value (the identity is the fallback
//     a host without theme variables sees, so nothing may be missing);
//   - the Estonian flag blue is exact;
//   - the WCAG 2.2 pairs the design system promises hold in light and dark: text 4.5:1
//     (1.4.3), non-text marks 3:1 (1.4.11).

const TOKENS_CSS = readFileSync(fileURLToPath(new URL("../../../docs/design/tokens.css", import.meta.url)), "utf8");

const LIGHT = ":root";
const DARK = ':root[data-theme="dark"]';

function token(selector: string, name: string): string {
  return declaredValue(TOKENS_CSS, selector, name);
}

function rgb(selector: string, name: string): Rgb {
  return parseColor(token(selector, name));
}

const TEXT = 4.5;
const MARK = 3;

interface Pair {
  label: string;
  foreground: string;
  ground: string;
  minimum: number;
}

// Each pair is a token name on each side; resolved per theme below.
const PAIRS: Pair[] = [
  { label: "primary text on page", foreground: "--color-text-primary", ground: "--color-background-primary", minimum: TEXT },
  { label: "primary text on panel", foreground: "--color-text-primary", ground: "--color-background-secondary", minimum: TEXT },
  { label: "secondary text on page", foreground: "--color-text-secondary", ground: "--color-background-primary", minimum: TEXT },
  { label: "secondary text on panel", foreground: "--color-text-secondary", ground: "--color-background-secondary", minimum: TEXT },
  { label: "secondary text on tint", foreground: "--color-text-secondary", ground: "--kannel-tint", minimum: TEXT },
  { label: "accent text (links, active tab) on page", foreground: "--kannel-accent-text", ground: "--color-background-primary", minimum: TEXT },
  { label: "label on accent button", foreground: "--kannel-on-accent", ground: "--kannel-accent", minimum: TEXT },
  { label: "label on pressed accent button", foreground: "--kannel-on-accent", ground: "--kannel-accent-pressed", minimum: TEXT },
  { label: "success text on success tint", foreground: "--kannel-success-text", ground: "--kannel-success-tint", minimum: TEXT },
  { label: "warning text on warning tint", foreground: "--kannel-warning-text", ground: "--kannel-warning-tint", minimum: TEXT },
  { label: "danger text on danger tint", foreground: "--kannel-danger-text", ground: "--kannel-danger-tint", minimum: TEXT },
  { label: "button edge on page", foreground: "--color-text-secondary", ground: "--color-background-primary", minimum: MARK },
  { label: "focus ring on page", foreground: "--color-ring-primary", ground: "--color-background-primary", minimum: MARK },
  { label: "playhead marker on page", foreground: "--kannel-marker", ground: "--color-background-primary", minimum: MARK },
  { label: "staff lines on page (Score Viewer notes)", foreground: "--color-text-primary", ground: "--color-background-primary", minimum: MARK },
];

describe("Kannel tokens: coverage", () => {
  it.each(["light", "dark"] as const)("defines every kit fallback variable (%s)", (theme) => {
    const selector = theme === "light" ? LIGHT : DARK;
    for (const name of Object.keys(FALLBACK_VARIABLES[theme])) {
      expect(() => token(selector, name), name).not.toThrow();
    }
  });

  it("defines the brand tokens in both themes", () => {
    for (const selector of [LIGHT, DARK]) {
      for (const name of ["--kannel-accent", "--kannel-accent-text", "--kannel-tint", "--kannel-marker"]) {
        expect(() => token(selector, name), `${name} in ${selector}`).not.toThrow();
      }
    }
  });
});

describe("Kannel tokens: identity", () => {
  it("uses the Estonian flag blue (#0072CE) as the accent", () => {
    expect(token(LIGHT, "--kannel-flag-blue").toLowerCase()).toBe("#0072ce");
    expect(token(LIGHT, "--kannel-accent").toLowerCase()).toBe("#0072ce");
  });

  it("carries the flag's black and white as tokens", () => {
    expect(token(LIGHT, "--kannel-flag-white").toLowerCase()).toBe("#ffffff");
    expect(token(LIGHT, "--kannel-flag-black").toLowerCase()).toBe("#15171c");
  });
});

describe.each([
  { theme: "light", selector: LIGHT },
  { theme: "dark", selector: DARK },
])("Kannel tokens: contrast in $theme", ({ selector }) => {
  it.each(PAIRS)("$label reaches $minimum:1", ({ foreground, ground, minimum }) => {
    const ratio = contrastRatio(rgbOf(selector, foreground), rgbOf(selector, ground));
    expect(ratio, `${foreground} on ${ground}`).toBeGreaterThanOrEqual(minimum);
  });
});

function rgbOf(selector: string, name: string): Rgb {
  return rgb(selector, name);
}
