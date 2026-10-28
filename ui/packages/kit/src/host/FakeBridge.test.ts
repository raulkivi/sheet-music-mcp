import { describe, expect, it } from "vitest";
import { FakeBridge } from "./FakeBridge.ts";

describe("FakeBridge", () => {
  it("resolves connect with the scripted host context", async () => {
    const bridge = new FakeBridge({ context: { theme: "dark" } });
    await expect(bridge.connect()).resolves.toEqual({ theme: "dark" });
  });

  it("replays tool-input and then tool-result, in that order, after connect", async () => {
    const bridge = new FakeBridge({
      toolInput: { arguments: { musicxml: "<score/>" } },
      toolResult: { structuredContent: { page_count: 2 } },
    });
    const seen: string[] = [];
    bridge.onToolResult(() => seen.push("result"));
    bridge.onToolInput(() => seen.push("input"));

    await bridge.connect();
    expect(seen).toEqual([]);
    await bridge.settled();
    expect(seen).toEqual(["input", "result"]);
  });

  it("stops notifying a listener after unsubscribe", async () => {
    const bridge = new FakeBridge({ toolInput: { arguments: {} } });
    let calls = 0;
    const off = bridge.onToolInput(() => calls++);
    off();
    await bridge.connect();
    await bridge.settled();
    expect(calls).toBe(0);
  });

  it("merges host context changes and notifies with the full context", async () => {
    const bridge = new FakeBridge({ context: { theme: "light", displayMode: "inline" } });
    const seen: unknown[] = [];
    bridge.onHostContext((c) => seen.push(c));
    await bridge.connect();
    bridge.changeHostContext({ theme: "dark" });
    expect(seen).toEqual([{ theme: "dark", displayMode: "inline" }]);
  });

  it("answers callTool from scripted answers and records every outbound call", async () => {
    const bridge = new FakeBridge({ toolAnswers: { get_pdf: { structuredContent: { ok: true } } } });
    await bridge.connect();
    await expect(bridge.callTool("get_pdf", { pdf_id: "x" })).resolves.toEqual({
      structuredContent: { ok: true },
    });
    await bridge.sendMessage("hello");
    await bridge.updateModelContext("page 2");
    bridge.notifySize({ width: 10, height: 20 });
    expect(bridge.calls).toEqual([
      { method: "tools/call", params: { name: "get_pdf", arguments: { pdf_id: "x" } } },
      { method: "ui/message", params: { text: "hello" } },
      { method: "ui/update-model-context", params: { text: "page 2" } },
      { method: "ui/notifications/size-changed", params: { width: 10, height: 20 } },
    ]);
  });

  it("rejects callTool for a tool it has no answer for", async () => {
    const bridge = new FakeBridge({});
    await expect(bridge.callTool("nope", {})).rejects.toThrow(/nope/);
  });

  it("grants a display mode only when the host context lists it", async () => {
    const bridge = new FakeBridge({
      context: { displayMode: "inline", availableDisplayModes: ["inline", "fullscreen"] },
    });
    await bridge.connect();
    await expect(bridge.requestDisplayMode("fullscreen")).resolves.toBe("fullscreen");
    await expect(bridge.requestDisplayMode("pip")).resolves.toBe("fullscreen");
  });

  it("answers tool calls from a function of the arguments", async () => {
    const bridge = new FakeBridge({
      toolAnswers: { render_page_svg: (args) => ({ structuredContent: { page: args.page } }) },
    });
    await expect(bridge.callTool("render_page_svg", { page: 3 })).resolves.toEqual({ structuredContent: { page: 3 } });
    expect(bridge.calls).toEqual([{ method: "tools/call", params: { name: "render_page_svg", arguments: { page: 3 } } }]);
  });
});
