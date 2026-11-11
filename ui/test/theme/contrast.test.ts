import { describe, expect, it } from "vitest";
import { contrastRatio, parseColor, resolveCssColor } from "./contrast.ts";

describe("parseColor", () => {
  it("reads #rgb, #rrggbb and the names white and black", () => {
    expect(parseColor("#fff")).toEqual([255, 255, 255]);
    expect(parseColor("#1c1c1E")).toEqual([28, 28, 30]);
    expect(parseColor("black")).toEqual([0, 0, 0]);
  });

  it("rejects what it cannot read, so a pair is never silently skipped", () => {
    expect(() => parseColor("hsl(0 0% 0%)")).toThrow(/Unsupported colour/);
  });
});

describe("contrastRatio", () => {
  it("is 21 for black on white and 1 for a colour on itself, in either order", () => {
    expect(contrastRatio([0, 0, 0], [255, 255, 255])).toBeCloseTo(21, 5);
    expect(contrastRatio([255, 255, 255], [0, 0, 0])).toBeCloseTo(21, 5);
    expect(contrastRatio([9, 9, 9], [9, 9, 9])).toBeCloseTo(1, 5);
  });

  it("matches the WCAG value for #767676 on white (4.54:1)", () => {
    expect(contrastRatio([0x76, 0x76, 0x76], [255, 255, 255])).toBeCloseTo(4.54, 2);
  });
});

describe("resolveCssColor", () => {
  it("follows var() to a declared value, then to the fallback", () => {
    expect(resolveCssColor("var(--a)", { vars: { "--a": "var(--b)", "--b": "#000" } })).toEqual([0, 0, 0]);
    expect(resolveCssColor("var(--missing, #fff)")).toEqual([255, 255, 255]);
  });

  it("throws on an undefined variable without a fallback", () => {
    expect(() => resolveCssColor("var(--missing)")).toThrow(/Undefined custom property --missing/);
  });

  it("mixes with transparent over the backdrop", () => {
    expect(resolveCssColor("color-mix(in srgb, #000000 50%, transparent)", { backdrop: [255, 255, 255] })).toEqual([127.5, 127.5, 127.5]);
    expect(() => resolveCssColor("color-mix(in srgb, #000 50%, transparent)")).toThrow(/needs a backdrop/);
  });
});
