import { describe, expect, it } from "vitest";
import { FALLBACK_VARIABLES, applyTheme, themeName, themeVariables } from "./theme.ts";

function fakeTarget() {
  const props = new Map<string, string>();
  return {
    props,
    style: { setProperty: (k: string, v: string) => void props.set(k, v) },
    dataset: {} as Record<string, string | undefined>,
  };
}

describe("themeName", () => {
  it("follows the host theme and defaults to light", () => {
    expect(themeName({ theme: "dark" })).toBe("dark");
    expect(themeName({ theme: "light" })).toBe("light");
    expect(themeName({})).toBe("light");
  });

  it("ignores unknown theme values", () => {
    expect(themeName({ theme: "sepia" as never })).toBe("light");
  });
});

describe("themeVariables", () => {
  it("uses the light fallback when the host sends nothing", () => {
    expect(themeVariables({})).toEqual(FALLBACK_VARIABLES.light);
  });

  it("uses the dark fallback for a dark host without style variables", () => {
    const vars = themeVariables({ theme: "dark" });
    expect(vars).toEqual(FALLBACK_VARIABLES.dark);
    expect(vars["--color-background-primary"]).not.toBe(
      FALLBACK_VARIABLES.light["--color-background-primary"],
    );
  });

  it("lets host style variables override the fallback", () => {
    const vars = themeVariables({
      theme: "dark",
      styles: { variables: { "--color-background-primary": "#101010", "--font-sans": "Inter" } },
    });
    expect(vars["--color-background-primary"]).toBe("#101010");
    expect(vars["--font-sans"]).toBe("Inter");
    expect(vars["--color-text-primary"]).toBe(FALLBACK_VARIABLES.dark["--color-text-primary"]);
  });

  it("skips empty, undefined and non-custom-property entries", () => {
    const vars = themeVariables({
      styles: {
        variables: {
          "--color-text-primary": "",
          "--color-background-primary": undefined,
          color: "red",
        } as Record<string, string | undefined>,
      },
    });
    expect(vars["--color-text-primary"]).toBe(FALLBACK_VARIABLES.light["--color-text-primary"]);
    expect(vars["--color-background-primary"]).toBe(
      FALLBACK_VARIABLES.light["--color-background-primary"],
    );
    expect(vars).not.toHaveProperty("color");
  });
});

describe("applyTheme", () => {
  it("writes every variable as a CSS custom property and marks the theme", () => {
    const target = fakeTarget();
    applyTheme(target, { theme: "dark" });
    for (const [k, v] of Object.entries(FALLBACK_VARIABLES.dark)) {
      expect(target.props.get(k)).toBe(v);
    }
    expect(target.props.get("color-scheme")).toBe("dark");
    expect(target.dataset.theme).toBe("dark");
  });
});
