import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { themeVariables } from "../../packages/kit/src/theme.ts";
import { contrastRatio, type Rgb } from "./contrast.ts";
import { colorIn, declaredValue, parseRules, resolveColor } from "./css-vars.ts";
import { ALL_HOST_SETS, type HostSet } from "./host-sets.ts";

// U3 / R3 (docs/research/ui-and-sound-testing-plan.md): in each host set, light and dark, text
// reaches 4.5:1 and non-text marks 3:1 against the ground they are drawn on (WCAG 2.2 1.4.3,
// 1.4.11). The pairs are read from the real style.css, so a changed colour rule changes the
// check; the variables are what applyTheme (kit theme.ts) would put on <html> for the set.
// Modelled on raulkivi/agent-cost-analyzer packages/mcp-apps/test/theme/theme-contrast.test.ts.
//
// Not checked: disabled buttons (opacity .45; WCAG exempts inactive controls) and the toolbar's
// bottom border (a separator, not a mark needed to use the page). The viewer has no highlight or
// cursor colour yet; "every colour is a token" below makes one fail until it is given a pair.

const STYLE_CSS = readFileSync(fileURLToPath(new URL("../../apps/score-viewer/style.css", import.meta.url)), "utf8");

const TEXT = 4.5;
const MARK = 3;

interface Paint {
  /** The rule and property the colour is read from. */
  selector: string;
  property: string;
}

interface Pair {
  label: string;
  foreground: Paint;
  /** What it is drawn on. */
  ground: Paint;
  minimum: number;
}

const BODY = { selector: "body", property: "background" };
const TOOLBAR = { selector: ".toolbar", property: "background" };
const BUTTON = { selector: "button", property: "background" };
const color = (selector: string, property = "color"): Paint => ({ selector, property });

const PAIRS: Pair[] = [
  { label: "page text on the page", foreground: color("body"), ground: BODY, minimum: TEXT },
  { label: "page and zoom labels on the toolbar", foreground: color("#page-label"), ground: TOOLBAR, minimum: TEXT },
  { label: "zoom label on the toolbar", foreground: color("#zoom-label"), ground: TOOLBAR, minimum: TEXT },
  { label: "button text on its button", foreground: color("button"), ground: BUTTON, minimum: TEXT },
  { label: "notice on the page", foreground: color("#notice"), ground: BODY, minimum: TEXT },
  { label: "download fallback on the page", foreground: color("#fallback"), ground: BODY, minimum: TEXT },
  { label: "saved path on the page", foreground: color("#saved"), ground: BODY, minimum: TEXT },
  { label: "engine line on the page", foreground: color(".engine"), ground: BODY, minimum: TEXT },
  { label: "score text on the page", foreground: color("#score svg.definition-scale"), ground: BODY, minimum: TEXT },
  { label: "score notes and staff lines (currentColor) on the page", foreground: color("#score svg.definition-scale"), ground: BODY, minimum: MARK },
  { label: "button border on its button", foreground: color("button", "border"), ground: BUTTON, minimum: MARK },
  { label: "focus ring on the toolbar", foreground: color("button:focus-visible", "outline"), ground: TOOLBAR, minimum: MARK },
  { label: "focus ring on the page", foreground: color("button:focus-visible", "outline"), ground: BODY, minimum: MARK },
];

interface Evaluated {
  label: string;
  ratio: number;
  minimum: number;
}

function evaluate(set: HostSet): Evaluated[] {
  const vars = themeVariables({ theme: set.theme, styles: { variables: set.hostVars } });
  return PAIRS.map((pair) => {
    const ground = colorIn(declaredValue(STYLE_CSS, pair.ground.selector, pair.ground.property));
    const foreground = colorIn(declaredValue(STYLE_CSS, pair.foreground.selector, pair.foreground.property));
    const groundRgb: Rgb = resolveColor(ground, vars, set.theme);
    // A semi-transparent colour (the host's ring and border are) is painted over its ground.
    const foregroundRgb = resolveColor(foreground, vars, set.theme, groundRgb);
    return {
      label: pair.label,
      ratio: contrastRatio(foregroundRgb, groundRgb),
      minimum: pair.minimum,
    };
  });
}

describe.each(ALL_HOST_SETS)("contrast: $name", (set) => {
  const checks = evaluate(set);

  it.each(checks.map((check) => [`${check.label} (${check.minimum}:1)`, check] as const))("%s", (_name, check) => {
    expect(check.ratio, `${check.ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(check.minimum);
  });

  it("fails no pair (names the ones that do)", () => {
    const failing = checks.filter((check) => check.ratio < check.minimum).map((check) => `${check.label}: ${check.ratio.toFixed(2)}:1, needs ${check.minimum}:1`);
    expect(failing).toEqual([]);
  });
});

describe("what the checks cover", () => {
  it("has every colour in style.css as a theme token or currentColor, so no colour escapes a pair", () => {
    const literals = STYLE_CSS.match(/#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?)\(/g) ?? [];
    expect(literals).toEqual([]);
  });

  it("checks every colour declaration in style.css, bar the exemptions named here", () => {
    const EXEMPT: Record<string, string> = {
      ".toolbar border-bottom": "a separator, not a mark needed to use the page",
      "#score svg fill": "currentColor: the score's colour, checked as the svg's own colour",
    };
    const checked = new Set(PAIRS.flatMap((pair) => [pair.foreground, pair.ground]).map((paint) => `${paint.selector} ${paint.property}`));
    const unchecked: string[] = [];
    for (const rule of parseRules(STYLE_CSS)) {
      for (const [property] of rule.declarations.filter(([name]) => /^(color|background(-color)?|border(-\w+)?|outline|fill|stroke)$/.test(name) && name !== "border-radius")) {
        const keys = rule.selectors.map((selector) => `${selector} ${property}`);
        if (!keys.some((key) => checked.has(key) || key in EXEMPT)) unchecked.push(keys.join(", "));
      }
    }
    expect(unchecked).toEqual([]);
  });

  it("checks the score's own marks: notes and staff lines are filled with currentColor", () => {
    expect(declaredValue(STYLE_CSS, "#score svg", "fill")).toBe("currentColor");
  });

  it("runs on Claude light and dark and on a host that sends nothing", () => {
    expect(ALL_HOST_SETS.map((set) => set.name)).toEqual([
      "Fallback light (host sends nothing)",
      "Fallback dark (host sends nothing)",
      "Claude light (recorded)",
      "Claude dark (recorded)",
    ]);
  });
});
