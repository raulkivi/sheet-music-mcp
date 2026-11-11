import { describe, expect, it, vi } from "vitest";
import { ExtAppsBridge, type AppLike, type AppEvent } from "./ExtAppsBridge.ts";
import type { DisplayMode } from "./HostBridge.ts";

class MockApp implements AppLike {
  listeners = new Map<AppEvent, ((p: never) => void)[]>();
  hostContext: Record<string, unknown> | undefined = { theme: "light", displayMode: "inline" };
  connect = vi.fn(async () => {});
  callServerTool = vi.fn(async (_p: { name: string; arguments?: Record<string, unknown> }) => ({
    content: [{ type: "text", text: "ok" }],
    structuredContent: { page_count: 3 },
  }));
  sendMessage = vi.fn(async (_p: unknown): Promise<{ isError?: boolean }> => ({}));
  updateModelContext = vi.fn(async (_p: unknown) => ({}));
  sendSizeChanged = vi.fn(async (_p: unknown) => {});
  requestDisplayMode = vi.fn(async (p: { mode: DisplayMode }) => ({ mode: p.mode }));

  addEventListener(event: AppEvent, handler: (p: never) => void): void {
    this.listeners.set(event, [...(this.listeners.get(event) ?? []), handler]);
  }
  getHostContext() {
    return this.hostContext;
  }
  emit(event: AppEvent, params: unknown): void {
    for (const h of this.listeners.get(event) ?? []) h(params as never);
  }
}

describe("ExtAppsBridge", () => {
  it("registers its SDK listeners before connecting, so early notifications are not lost", async () => {
    const app = new MockApp();
    new ExtAppsBridge(app);
    expect([...app.listeners.keys()].sort()).toEqual(["hostcontextchanged", "toolinput", "toolresult"]);
    expect(app.connect).not.toHaveBeenCalled();
  });

  it("connect performs the SDK handshake and returns the host context", async () => {
    const app = new MockApp();
    const bridge = new ExtAppsBridge(app);
    await expect(bridge.connect()).resolves.toEqual({ theme: "light", displayMode: "inline" });
    expect(app.connect).toHaveBeenCalledOnce();
  });

  it("forwards tool-input and tool-result notifications", async () => {
    const app = new MockApp();
    const bridge = new ExtAppsBridge(app);
    const inputs: unknown[] = [];
    const results: unknown[] = [];
    bridge.onToolInput((i) => inputs.push(i));
    bridge.onToolResult((r) => results.push(r));
    app.emit("toolinput", { arguments: { musicxml: "<x/>" } });
    app.emit("toolresult", { content: [], structuredContent: { page_count: 1 } });
    expect(inputs).toEqual([{ arguments: { musicxml: "<x/>" } }]);
    expect(results).toEqual([{ content: [], structuredContent: { page_count: 1 } }]);
  });

  it("replays a notification that arrived before anyone subscribed", () => {
    const app = new MockApp();
    const bridge = new ExtAppsBridge(app);
    app.emit("toolinput", { arguments: { musicxml: "<x/>" } });
    const inputs: unknown[] = [];
    bridge.onToolInput((i) => inputs.push(i));
    expect(inputs).toEqual([{ arguments: { musicxml: "<x/>" } }]);
  });

  it("treats tool-input without arguments as empty arguments", () => {
    const app = new MockApp();
    const bridge = new ExtAppsBridge(app);
    const inputs: unknown[] = [];
    bridge.onToolInput((i) => inputs.push(i));
    app.emit("toolinput", {});
    expect(inputs).toEqual([{ arguments: {} }]);
  });

  it("merges partial host-context-changed notifications into the full context", async () => {
    const app = new MockApp();
    const bridge = new ExtAppsBridge(app);
    await bridge.connect();
    const seen: unknown[] = [];
    bridge.onHostContext((c) => seen.push(c));
    app.emit("hostcontextchanged", { theme: "dark" });
    expect(seen).toEqual([{ theme: "dark", displayMode: "inline" }]);
  });

  it("forwards callTool as callServerTool", async () => {
    const app = new MockApp();
    const bridge = new ExtAppsBridge(app);
    const result = await bridge.callTool("get_pdf", { pdf_id: "abc" });
    expect(app.callServerTool).toHaveBeenCalledWith({ name: "get_pdf", arguments: { pdf_id: "abc" } });
    expect(result.structuredContent).toEqual({ page_count: 3 });
  });

  it("forwards sendMessage as a user text message", async () => {
    const app = new MockApp();
    const bridge = new ExtAppsBridge(app);
    await bridge.sendMessage("Please help");
    expect(app.sendMessage).toHaveBeenCalledWith({
      role: "user",
      content: [{ type: "text", text: "Please help" }],
    });
  });

  it("rejects when the host refuses the message", async () => {
    const app = new MockApp();
    app.sendMessage.mockResolvedValueOnce({ isError: true });
    const bridge = new ExtAppsBridge(app);
    await expect(bridge.sendMessage("x")).rejects.toThrow(/rejected/);
  });

  it("forwards updateModelContext as text content", async () => {
    const app = new MockApp();
    const bridge = new ExtAppsBridge(app);
    await bridge.updateModelContext("Viewing page 2 of 5.");
    expect(app.updateModelContext).toHaveBeenCalledWith({
      content: [{ type: "text", text: "Viewing page 2 of 5." }],
    });
  });

  it("forwards notifySize as sendSizeChanged", () => {
    const app = new MockApp();
    const bridge = new ExtAppsBridge(app);
    bridge.notifySize({ width: 640, height: 480 });
    expect(app.sendSizeChanged).toHaveBeenCalledWith({ width: 640, height: 480 });
  });

  it("returns the display mode the host granted", async () => {
    const app = new MockApp();
    app.requestDisplayMode.mockResolvedValueOnce({ mode: "inline" });
    const bridge = new ExtAppsBridge(app);
    await expect(bridge.requestDisplayMode("fullscreen")).resolves.toBe("inline");
    expect(app.requestDisplayMode).toHaveBeenCalledWith({ mode: "fullscreen" });
  });
});
