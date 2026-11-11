import { describe, expect, it } from "vitest";
import { hostStyleVariables } from "./host-styles.ts";

describe("hostStyleVariables", () => {
  it("sends a partial set by default: none in light, two grounds in dark", () => {
    expect(hostStyleVariables("default", "light")).toEqual({});
    expect(Object.keys(hostStyleVariables("default", "dark"))).toEqual(["--color-background-primary", "--color-text-primary"]);
  });

  it("sends the recorded Claude Desktop variables for either theme", () => {
    const light = hostStyleVariables("claude", "light");
    expect(light["--color-ring-primary"]).toBe("light-dark(rgba(20, 20, 19, 0.7), rgba(250, 249, 245, 0.7))");
    expect(hostStyleVariables("claude", "dark")).toEqual(light);
  });
});
