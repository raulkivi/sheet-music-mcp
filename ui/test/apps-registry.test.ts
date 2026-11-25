import { existsSync } from "node:fs";
import { describe, expect, it } from "vitest";
// @ts-expect-error -- plain .mjs without type declarations
import { APPS } from "../apps.config.mjs";
// @ts-expect-error -- plain .mjs without type declarations
import { appNames, assetDir, copyPlan, distFile, requireApp, selectApps, serversWithPages, validateRegistry } from "../scripts/lib/apps.mjs";

interface Target { server: string; pkg: string }
type Registry = Record<string, { targets: Target[] }>;
const apps = APPS as Registry;
const plan = copyPlan as (apps: Registry) => { from: string; to: string }[];
const validate = validateRegistry as (apps: unknown) => string[];

const viewer = { targets: [{ server: "render-mcp", pkg: "render_mcp" }] };

describe("the registry", () => {
  it("is valid", () => {
    expect(validate(APPS)).toEqual([]);
  });

  it("holds the Score Viewer for render-mcp", () => {
    expect(apps["score-viewer"]?.targets).toEqual([{ server: "render-mcp", pkg: "render_mcp" }]);
  });

  it("holds the Practice Player for synth-mcp", () => {
    expect(apps["practice-player"]?.targets).toEqual([{ server: "synth-mcp", pkg: "synth_mcp" }]);
  });

  it("holds the Recognition Review for omr-mcp", () => {
    expect(apps["recognition-review"]?.targets).toEqual([{ server: "omr-mcp", pkg: "omr_mcp" }]);
  });

  it("holds the Setup Doctor for all six servers, each from its own package", () => {
    expect(apps["setup-doctor"]?.targets).toEqual([
      { server: "render-mcp", pkg: "render_mcp" },
      { server: "synth-mcp", pkg: "synth_mcp" },
      { server: "omr-mcp", pkg: "omr_mcp" },
      { server: "musicxml-abc-mcp", pkg: "musicxml_abc_mcp" },
      { server: "pitch-mcp", pkg: "pitch_mcp" },
      { server: "comparer-mcp", pkg: "comparer_mcp" },
    ]);
  });

  it("has an apps/<name>/index.html for every entry", () => {
    for (const name of appNames(APPS) as string[]) {
      expect(existsSync(new URL(`../apps/${name}/index.html`, import.meta.url)), name).toBe(true);
    }
  });

  it("points every target at an existing server package", () => {
    for (const [name, app] of Object.entries(apps)) {
      for (const { server, pkg } of app.targets) {
        expect(existsSync(new URL(`../../${server}/src/${pkg}`, import.meta.url)), `${name} -> ${server}`).toBe(true);
      }
    }
  });
});

describe("validateRegistry", () => {
  it("rejects names that are not safe file names", () => {
    expect(validate({ "../evil": viewer })).toEqual([expect.stringContaining('"../evil"')]);
    expect(validate({ Upper: viewer })).toHaveLength(1);
  });

  it("rejects an app without targets or with a malformed target", () => {
    expect(validate({ a: { targets: [] } })).toEqual([expect.stringContaining("at least one target")]);
    expect(validate({ a: { targets: [{ server: "render-mcp" }] } })).toHaveLength(1);
    expect(validate({ a: { targets: [{ server: "x/../y", pkg: "p" }] } })).toHaveLength(1);
  });

  it("rejects two targets that write the same file", () => {
    const dup = { targets: [{ server: "s", pkg: "p" }, { server: "s", pkg: "p" }] };
    expect(validate({ a: dup })).toEqual([expect.stringContaining("twice")]);
  });

  it("accepts one page for several servers (Setup Doctor)", () => {
    const many = { targets: ["a-mcp", "b-mcp"].map((s) => ({ server: s, pkg: s.replace("-", "_") })) };
    expect(validate({ "setup-doctor": many })).toEqual([]);
  });
});

describe("paths", () => {
  it("names the built page dist/<name>.html", () => {
    expect(distFile("score-viewer")).toBe("dist/score-viewer.html");
  });

  it("puts a page under <server>/src/<pkg>/ui/assets", () => {
    expect(assetDir({ server: "render-mcp", pkg: "render_mcp" })).toBe("../render-mcp/src/render_mcp/ui/assets");
  });

  it("copyPlan maps each page to every one of its servers", () => {
    expect(
      plan({
        "score-viewer": viewer,
        "setup-doctor": { targets: [{ server: "a-mcp", pkg: "a_mcp" }, { server: "b-mcp", pkg: "b_mcp" }] },
      }),
    ).toEqual([
      { from: "dist/score-viewer.html", to: "../render-mcp/src/render_mcp/ui/assets/score-viewer.html" },
      { from: "dist/setup-doctor.html", to: "../a-mcp/src/a_mcp/ui/assets/setup-doctor.html" },
      { from: "dist/setup-doctor.html", to: "../b-mcp/src/b_mcp/ui/assets/setup-doctor.html" },
    ]);
  });

  it("requireApp names the registered apps when asked for an unknown one", () => {
    expect(requireApp(APPS, "score-viewer")).toBe("score-viewer");
    expect(() => requireApp(APPS, "nope")).toThrow(/Unknown app "nope".*score-viewer/);
  });
});

describe("selectApps", () => {
  const two = { a: viewer, b: viewer };
  it("selects every app when none is named", () => {
    expect(selectApps(two, [])).toEqual(["a", "b"]);
  });
  it("selects the named apps, rejecting unknown ones", () => {
    expect(selectApps(two, ["b"])).toEqual(["b"]);
    expect(() => selectApps(two, ["c"])).toThrow(/Unknown app "c"/);
  });
});

describe("serversWithPages", () => {
  it("lists each server once, in first-seen order", () => {
    const apps = {
      a: { targets: [{ server: "x-mcp", pkg: "x" }, { server: "y-mcp", pkg: "y" }] },
      b: { targets: [{ server: "x-mcp", pkg: "x" }] },
    };
    expect(serversWithPages(apps)).toEqual(["x-mcp", "y-mcp"]);
  });
});
