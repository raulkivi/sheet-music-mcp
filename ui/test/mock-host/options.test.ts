import { describe, expect, it } from "vitest";
import { hostOptions } from "./options.ts";

describe("hostOptions", () => {
  it("defaults to the long inline score, light theme, WASM allowed and placeholder pages", () => {
    expect(hostOptions("")).toEqual({
      scenario: "inline-long",
      theme: "light",
      csp: "spec-wasm",
      downloads: true,
      modes: ["inline"],
      width: 1000,
      tools: "placeholder",
      host: "default",
    });
  });

  it("host=claude applies the recorded Claude Desktop variables", () => {
    expect(hostOptions("?host=claude&theme=dark")).toMatchObject({ host: "claude", theme: "dark" });
    expect(() => hostOptions("?host=vscode")).toThrow(/Unknown host=vscode/);
  });

  it("reads every query parameter", () => {
    expect(
      hostOptions("?scenario=path-only&theme=dark&csp=spec&downloads=0&modes=inline,fullscreen&width=360&server=real"),
    ).toEqual({
      scenario: "path-only",
      theme: "dark",
      csp: "spec",
      downloads: false,
      modes: ["inline", "fullscreen"],
      width: 360,
      tools: "real",
      host: "default",
    });
  });

  it("maps server=0 to no tools and server=1 to placeholder pages", () => {
    expect(hostOptions("?server=0").tools).toBe("none");
    expect(hostOptions("?server=1").tools).toBe("placeholder");
  });

  it("rejects an unknown scenario or server value instead of guessing", () => {
    expect(() => hostOptions("?scenario=nope")).toThrow(/scenario/);
    expect(() => hostOptions("?server=maybe")).toThrow(/server/);
  });
});
