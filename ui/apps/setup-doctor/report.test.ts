import { describe, expect, it } from "vitest";
import { parseReport, reportText, viewModel, type Report } from "./report.ts";

const MIXED: Report = {
  status: "not_ready",
  checks: [
    { name: "Verovio", status: "ok", version: "4.3.1" },
    { name: "Soundfont", status: "fail", hint: "No soundfont found.", fixSnippet: "sudo apt install fluid-soundfont-gm", docUrl: "https://example.org/soundfont" },
    { name: "PortAudio", status: "warn", hint: "No input device." },
    { name: "FluidSynth", status: "ok" },
  ],
};

describe("parseReport", () => {
  it("reads the core's health report, mapping snake_case fields", () => {
    const parsed = parseReport({
      status: "degraded",
      checks: [{ name: "Soundfont", status: "warn", version: "2", hint: "h", fix_snippet: "s", doc_url: "https://example.org/x" }],
    });
    expect(parsed).toEqual({
      status: "degraded",
      checks: [{ name: "Soundfont", status: "warn", version: "2", hint: "h", fixSnippet: "s", docUrl: "https://example.org/x" }],
    });
  });

  it("omits fields the server left out", () => {
    expect(parseReport({ status: "ready", checks: [{ name: "A", status: "ok" }] })?.checks[0]).toEqual({ name: "A", status: "ok" });
  });

  it("derives the overall status from the checks when it is missing or unknown", () => {
    expect(parseReport({ checks: [{ name: "A", status: "warn" }] })?.status).toBe("degraded");
    expect(parseReport({ status: "weird", checks: [{ name: "A", status: "fail" }, { name: "B", status: "warn" }] })?.status).toBe("not_ready");
    expect(parseReport({ checks: [{ name: "A", status: "ok" }] })?.status).toBe("ready");
  });

  it("accepts an empty list of checks", () => {
    expect(parseReport({ status: "ready", checks: [] })).toEqual({ status: "ready", checks: [] });
  });

  it("returns undefined for anything that is not a report", () => {
    for (const bad of [undefined, null, "x", 3, [], {}, { checks: "no" }, { checks: [{ name: "", status: "ok" }] }, { checks: [{ name: "A", status: "meh" }] }, { checks: [null] }]) {
      expect(parseReport(bad), JSON.stringify(bad)).toBeUndefined();
    }
  });

  it("keeps only http(s) doc links, since the host opens them", () => {
    const check = (doc_url: unknown) => parseReport({ checks: [{ name: "A", status: "ok", doc_url }] })?.checks[0]?.docUrl;
    expect(check("https://example.org/a")).toBe("https://example.org/a");
    expect(check("http://example.org/a")).toBe("http://example.org/a");
    expect(check("javascript:alert(1)")).toBeUndefined();
    expect(check("file:///etc/passwd")).toBeUndefined();
    expect(check("not a url")).toBeUndefined();
    expect(check(5)).toBeUndefined();
  });

  it("ignores non-string optional fields", () => {
    expect(parseReport({ checks: [{ name: "A", status: "ok", version: 4, hint: {}, fix_snippet: null }] })?.checks[0]).toEqual({ name: "A", status: "ok" });
  });
});

describe("viewModel", () => {
  it("lists failures first, then warnings, then passes, keeping the server's order within a group", () => {
    expect(viewModel(MIXED).rows.map((r) => r.name)).toEqual(["Soundfont", "PortAudio", "Verovio", "FluidSynth"]);
  });

  it("counts each status and words the headline from them", () => {
    const vm = viewModel(MIXED);
    expect(vm.counts).toEqual({ ok: 2, warn: 1, fail: 1 });
    expect(vm.headline).toBe("Not ready: 1 check must be fixed");
  });

  it("words the headline for each overall status", () => {
    expect(viewModel({ status: "ready", checks: [{ name: "A", status: "ok" }] }).headline).toBe("Everything is ready");
    expect(viewModel({ status: "degraded", checks: [{ name: "A", status: "warn" }, { name: "B", status: "warn" }] }).headline).toBe(
      "Ready with 2 checks needing attention",
    );
    expect(viewModel({ status: "not_ready", checks: [{ name: "A", status: "fail" }, { name: "B", status: "fail" }] }).headline).toBe(
      "Not ready: 2 checks must be fixed",
    );
  });

  it("gives each row a plain label so color is never the only signal", () => {
    expect(viewModel(MIXED).rows.map((r) => r.label)).toEqual(["Must fix", "Needs attention", "Ready", "Ready"]);
  });

  it("marks an empty report", () => {
    const vm = viewModel({ status: "ready", checks: [] });
    expect(vm.empty).toBe(true);
    expect(vm.rows).toEqual([]);
    expect(viewModel(MIXED).empty).toBe(false);
  });
});

describe("reportText", () => {
  it("is plain text a user can paste into a chat or an issue", () => {
    expect(reportText(MIXED)).toBe(
      [
        "Setup report: Not ready: 1 check must be fixed",
        "",
        "[FAIL] Soundfont",
        "  No soundfont found.",
        "  Fix:",
        "    sudo apt install fluid-soundfont-gm",
        "  Docs: https://example.org/soundfont",
        "",
        "[WARN] PortAudio",
        "  No input device.",
        "",
        "[OK] Verovio (4.3.1)",
        "",
        "[OK] FluidSynth",
        "",
      ].join("\n"),
    );
  });

  it("indents every line of a multi-line fix", () => {
    const text = reportText({ status: "not_ready", checks: [{ name: "A", status: "fail", fixSnippet: "one\ntwo" }] });
    expect(text).toContain("  Fix:\n    one\n    two\n");
  });

  it("says so when there are no checks", () => {
    expect(reportText({ status: "ready", checks: [] })).toBe("Setup report: Everything is ready\n\nNo checks were reported.\n");
  });
});
