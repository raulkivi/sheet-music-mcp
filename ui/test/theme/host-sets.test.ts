import { describe, expect, it } from "vitest";
import { ALL_HOST_SETS, CLAUDE_SETS, FALLBACK_SETS } from "./host-sets.ts";

describe("host sets", () => {
  it("has Claude light and dark, with the recorded variables and the theme the host sent", () => {
    expect(CLAUDE_SETS.map((set) => [set.name, set.theme])).toEqual([
      ["Claude light (recorded)", "light"],
      ["Claude dark (recorded)", "dark"],
    ]);
    for (const set of CLAUDE_SETS) {
      expect(set.hostVars["--color-background-primary"]).toBe("light-dark(rgba(255, 255, 255, 1), rgba(48, 48, 46, 1))");
      expect(Object.keys(set.hostVars).length).toBeGreaterThan(70);
    }
  });

  it("has a fallback set per theme: a host that sends no variables", () => {
    expect(FALLBACK_SETS.map((set) => [set.name, set.theme, set.hostVars])).toEqual([
      ["Fallback light (host sends nothing)", "light", {}],
      ["Fallback dark (host sends nothing)", "dark", {}],
    ]);
  });

  it("lists every set once", () => {
    expect(ALL_HOST_SETS).toHaveLength(4);
  });
});
