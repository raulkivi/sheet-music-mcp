import { describe, expect, it } from "vitest";
import { colorIn, declaredValue, normalizeColorFunctions, parseRules, resolveColor } from "./css-vars.ts";

const CSS = `
/* a comment { with: braces; } */
button, .other { border: 1px solid var(--color-border-primary); color: var(--c); }
button:focus-visible { outline: 2px solid var(--color-ring-primary); }
#score svg { fill: currentColor; }
`;

describe("parseRules", () => {
  it("splits selectors and declarations and ignores comments", () => {
    expect(parseRules(CSS)[0]).toEqual({
      selectors: ["button", ".other"],
      declarations: [["border", "1px solid var(--color-border-primary)"], ["color", "var(--c)"]],
    });
    expect(parseRules(CSS)).toHaveLength(3);
  });
});

describe("declaredValue", () => {
  it("finds a property on an exact selector, last declaration winning", () => {
    expect(declaredValue(CSS, "button:focus-visible", "outline")).toBe("2px solid var(--color-ring-primary)");
    expect(declaredValue(CSS + "button { color: red; }", "button", "color")).toBe("red");
  });

  it("names the selector and property when there is none, so a renamed rule fails loudly", () => {
    expect(() => declaredValue(CSS, "button", "background")).toThrow(/No background declared for button/);
  });
});

describe("colorIn", () => {
  it("picks the colour out of a shorthand", () => {
    expect(colorIn("1px solid var(--color-border-primary)")).toBe("var(--color-border-primary)");
    expect(colorIn("2px solid #2563eb")).toBe("#2563eb");
    expect(colorIn("var(--color-text-primary)")).toBe("var(--color-text-primary)");
    expect(colorIn("1px solid rgba(0, 0, 0, 0.4)")).toBe("rgba(0, 0, 0, 0.4)");
  });

  it("returns currentColor as it is, for the caller to resolve", () => {
    expect(colorIn("currentColor")).toBe("currentColor");
  });
});

describe("normalizeColorFunctions", () => {
  it("picks the light-dark() branch for the theme and turns rgba() into hex or a transparent mix", () => {
    const value = "light-dark(rgba(255, 255, 255, 1), rgba(48, 48, 46, 0.5))";
    expect(normalizeColorFunctions(value, "light")).toBe("#ffffff");
    expect(normalizeColorFunctions(value, "dark")).toBe("color-mix(in srgb, #30302e 50%, transparent)");
  });
});

describe("resolveColor", () => {
  it("resolves a token through light-dark() and alpha over a backdrop", () => {
    const vars = { "--ring": "light-dark(rgba(20, 20, 19, 0.7), rgba(250, 249, 245, 0.7))" };
    expect(resolveColor("var(--ring)", vars, "light", [255, 255, 255]).map(Math.round)).toEqual([91, 91, 90]);
  });
});
