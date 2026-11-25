import { describe, expect, it, vi } from "vitest";
import { FakeBridge } from "@sheet-music-mcp/ui-kit/host/FakeBridge";
import type { ToolResult } from "@sheet-music-mcp/ui-kit/host/HostBridge";
import { SetupDoctor, NOTICES, type CopyFn, type DoctorUi } from "./doctor.ts";
import type { ViewModel } from "./report.ts";

const MIXED = {
  status: "not_ready",
  checks: [
    { name: "Verovio", status: "ok" },
    { name: "Soundfont", status: "fail", hint: "Missing", fix_snippet: "apt install x", doc_url: "https://example.org/sf" },
  ],
};
const READY = { status: "ready", checks: [{ name: "Verovio", status: "ok" }] };

const result = (structuredContent: Record<string, unknown>): ToolResult => ({ content: [{ type: "text", text: "report" }], structuredContent });

class FakeUi implements DoctorUi {
  events: string[] = [];
  model: ViewModel | undefined;
  error: string | undefined;
  copy: { result: string; text: string; what: string } | undefined;
  showLoading() {
    this.events.push("loading");
  }
  showReport(vm: ViewModel) {
    this.model = vm;
    this.error = undefined;
    this.events.push("report");
  }
  showError(message: string) {
    this.error = message;
    this.events.push("error");
  }
  setChecking(on: boolean) {
    this.events.push(on ? "checking" : "checked");
  }
  showCopyStatus(copyResult: "copied" | "manual", text: string, what: string) {
    this.copy = { result: copyResult, text, what };
  }
  showLinkFailed(url: string) {
    this.events.push(`link-failed ${url}`);
  }
  applyHostContext() {
    this.events.push("context");
  }
}

async function started(script: ConstructorParameters<typeof FakeBridge>[0], copyImpl: CopyFn = async () => "copied") {
  const bridge = new FakeBridge(script);
  const ui = new FakeUi();
  const doctor = new SetupDoctor(bridge, ui, copyImpl);
  await doctor.start();
  await bridge.settled();
  return { bridge, ui, doctor };
}

describe("SetupDoctor", () => {
  it("shows the loading state, then the report the host delivers", async () => {
    const { ui } = await started({ toolResult: result(MIXED) });
    expect(ui.events).toContain("loading");
    expect(ui.model?.rows.map((r) => r.name)).toEqual(["Soundfont", "Verovio"]);
    expect(ui.model?.headline).toBe("Not ready: 1 check must be fixed");
  });

  it("applies the host context at the handshake", async () => {
    const { ui } = await started({ context: { theme: "dark" } });
    expect(ui.events).toContain("context");
  });

  it("shows the server's error envelope when the health check failed", async () => {
    const failed: ToolResult = { isError: true, content: [{ type: "text", text: JSON.stringify({ error: "Boom", error_code: "PROCESSING_ERROR" }) }] };
    const { ui } = await started({ toolResult: failed });
    expect(ui.error).toBe(NOTICES.checkFailed("Boom", "PROCESSING_ERROR"));
  });

  it("says the report is unreadable when the result is not a health report", async () => {
    const { ui } = await started({ toolResult: result({ unrelated: true }) });
    expect(ui.error).toBe(NOTICES.unreadable);
  });

  it("Check again calls the server's own health_check and shows the new report", async () => {
    const { bridge, ui, doctor } = await started({ toolResult: result(MIXED), toolAnswers: { health_check: result(READY) } });
    await doctor.checkAgain();
    expect(bridge.calls.filter((c) => c.method === "tools/call")).toEqual([{ method: "tools/call", params: { name: "health_check", arguments: {} } }]);
    expect(ui.model?.headline).toBe("Everything is ready");
    expect(ui.events.slice(-3)).toEqual(["checking", "report", "checked"]);
  });

  it("Check again shows an error, and stops the busy state, when the call fails", async () => {
    const { ui, doctor } = await started({ toolResult: result(MIXED) });
    await doctor.checkAgain();
    expect(ui.error).toBe(NOTICES.callFailed);
    expect(ui.events.at(-1)).toBe("checked");
  });

  it("ignores a second Check again while one is running", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => (release = resolve));
    const { bridge, doctor } = await started({
      toolResult: result(MIXED),
      toolAnswers: { health_check: async () => (await gate, result(READY)) },
    });
    const first = doctor.checkAgain();
    await doctor.checkAgain();
    release();
    await first;
    expect(bridge.calls.filter((c) => c.method === "tools/call")).toHaveLength(1);
  });

  it("copies the report as plain text and says how it went", async () => {
    const copy = vi.fn(async () => "copied" as const);
    const { ui, doctor } = await started({ toolResult: result(MIXED) }, copy);
    await doctor.copyReport();
    expect(copy).toHaveBeenCalledOnce();
    const text = (copy.mock.calls[0] as unknown as [string])[0];
    expect(text).toContain("[FAIL] Soundfont");
    expect(ui.copy).toEqual({ result: "copied", text, what: "Report" });
  });

  it("copies one fix snippet", async () => {
    const copy = vi.fn(async () => "manual" as const);
    const { ui, doctor } = await started({ toolResult: result(MIXED) }, copy);
    await doctor.copySnippet("Soundfont", "apt install x");
    expect(copy).toHaveBeenCalledWith("apt install x");
    expect(ui.copy).toEqual({ result: "manual", text: "apt install x", what: "Fix for Soundfont" });
  });

  it("does nothing to copy before a report has arrived", async () => {
    const copy = vi.fn(async () => "copied" as const);
    const { doctor } = await started({}, copy);
    await doctor.copyReport();
    expect(copy).not.toHaveBeenCalled();
  });

  it("asks the host to open a doc link, and says so when the host refuses", async () => {
    const { bridge, ui, doctor } = await started({ toolResult: result(MIXED) });
    await doctor.openDoc("https://example.org/sf");
    expect(bridge.calls).toContainEqual({ method: "ui/open-link", params: { url: "https://example.org/sf" } });
    vi.spyOn(bridge, "openLink").mockRejectedValueOnce(new Error("refused"));
    await doctor.openDoc("https://example.org/sf");
    expect(ui.events).toContain("link-failed https://example.org/sf");
  });
});
