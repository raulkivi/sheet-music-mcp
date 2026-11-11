// Reads the viewer's real stylesheet for the contrast tests, since Node computes no styles:
// declared values by selector and property, the colour inside a shorthand, and a colour resolved
// through var(), light-dark() and rgba(). Parsing and normalising after raulkivi/agent-cost-analyzer,
// packages/mcp-apps/test/theme/css-vars.ts (MIT, Raul Kivi). Colour maths lives in contrast.ts.

import { resolveCssColor, splitArguments, type Rgb } from "./contrast.ts";

export type Theme = "light" | "dark";

export interface Rule {
  selectors: string[];
  declarations: [string, string][];
}

/** Flat rules only; the viewer's stylesheet has no nesting or at-rules. */
export function parseRules(css: string): Rule[] {
  const source = css.replace(/\/\*[\s\S]*?\*\//g, "");
  return [...source.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((match) => {
    const declarations: [string, string][] = [];
    for (const declaration of match[2]!.split(";")) {
      const colon = declaration.indexOf(":");
      if (colon > 0) declarations.push([declaration.slice(0, colon).trim(), declaration.slice(colon + 1).trim()]);
    }
    return { selectors: match[1]!.split(",").map((selector) => selector.trim()), declarations };
  });
}

/** The value `property` has on the rule for exactly `selector`; the last declaration wins. */
export function declaredValue(css: string, selector: string, property: string): string {
  let found: string | undefined;
  for (const rule of parseRules(css)) {
    if (!rule.selectors.includes(selector)) continue;
    for (const [name, value] of rule.declarations) if (name === property) found = value;
  }
  if (found === undefined) throw new Error(`No ${property} declared for ${selector}`);
  return found;
}

function closingParen(text: string, open: number): number {
  let depth = 0;
  for (let index = open; index < text.length; index++) {
    if (text[index] === "(") depth++;
    else if (text[index] === ")" && --depth === 0) return index;
  }
  throw new Error(`Unbalanced parenthesis in: ${text}`);
}

/** The colour inside a declaration such as `1px solid var(--x)`: a function call, hex or name. */
export function colorIn(value: string): string {
  const call = /(var|rgba|rgb|light-dark|color-mix)\(/.exec(value);
  if (call) return value.slice(call.index, closingParen(value, call.index + call[1]!.length) + 1);
  const plain = /#[0-9a-fA-F]{3,6}\b|\b(?:currentColor|white|black)\b/.exec(value);
  if (plain) return plain[0];
  throw new Error(`No colour in: ${value}`);
}

function toHex(channels: number[]): string {
  return `#${channels.map((c) => Math.round(c).toString(16).padStart(2, "0")).join("")}`;
}

/**
 * Rewrites light-dark(a, b) to the branch the document theme selects (the kit sets color-scheme
 * from the host theme) and rgb()/rgba() to #hex, or below full opacity a mix with transparent.
 */
export function normalizeColorFunctions(value: string, theme: Theme): string {
  const pattern = /(light-dark|rgba|rgb)\(/;
  let match = pattern.exec(value);
  while (match) {
    const open = match.index + match[1]!.length;
    const close = closingParen(value, open);
    const args = splitArguments(value.slice(open + 1, close));
    let replacement: string;
    if (match[1] === "light-dark") {
      replacement = normalizeColorFunctions(args[theme === "light" ? 0 : 1]!, theme);
    } else {
      const channels = args.slice(0, 3).map(Number);
      const alpha = args[3] === undefined ? 1 : Number(args[3]);
      replacement = alpha >= 1 ? toHex(channels) : `color-mix(in srgb, ${toHex(channels)} ${+(alpha * 100).toFixed(2)}%, transparent)`;
    }
    value = value.slice(0, match.index) + replacement + value.slice(close + 1);
    match = pattern.exec(value);
  }
  return value;
}

/** The colour `value` paints as, over `backdrop` where partly transparent. */
export function resolveColor(value: string, vars: Record<string, string>, theme: Theme, backdrop?: Rgb): Rgb {
  const normalized = Object.fromEntries(Object.entries(vars).map(([name, declared]) => [name, normalizeColorFunctions(declared, theme)]));
  return resolveCssColor(normalizeColorFunctions(value, theme), { vars: normalized, ...(backdrop ? { backdrop } : {}) });
}
