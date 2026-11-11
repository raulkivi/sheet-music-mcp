import type { JSONRPCMessage, Transport } from "@modelcontextprotocol/client";
import { describe, expect, it } from "vitest";
import { LoggingTransport, MessageLog } from "./message-log.ts";

class FakeTransport implements Transport {
  sent: JSONRPCMessage[] = [];
  started = false;
  closed = false;
  onmessage?: (message: JSONRPCMessage) => void;
  onclose?: () => void;
  onerror?: (error: Error) => void;
  async start() {
    this.started = true;
  }
  async send(message: JSONRPCMessage) {
    this.sent.push(message);
  }
  async close() {
    this.closed = true;
    this.onclose?.();
  }
}

function setup() {
  let now = 0;
  const log = new MessageLog(() => ++now);
  const inner = new FakeTransport();
  const transport = new LoggingTransport(inner, log);
  return { log, inner, transport };
}

describe("LoggingTransport", () => {
  it("records what the host sends and passes it on", async () => {
    const { log, inner, transport } = setup();
    await transport.start();
    const msg: JSONRPCMessage = { jsonrpc: "2.0", method: "ui/notifications/tool-input", params: { arguments: {} } };
    await transport.send(msg);
    expect(inner.started).toBe(true);
    expect(inner.sent).toEqual([msg]);
    expect(log.entries).toEqual([{ direction: "host->app", t: 1, ...msg }]);
  });

  it("records what the app sends before the protocol handles it", async () => {
    const { log, inner, transport } = setup();
    const received: JSONRPCMessage[] = [];
    transport.onmessage = (m) => {
      expect(log.entries).toHaveLength(1);
      received.push(m);
    };
    await transport.start();
    const msg: JSONRPCMessage = { jsonrpc: "2.0", id: 1, method: "ui/initialize", params: { protocolVersion: "x" } };
    inner.onmessage!(msg);
    expect(received).toEqual([msg]);
    expect(log.entries).toEqual([{ direction: "app->host", t: 1, ...msg }]);
  });

  it("passes close and errors through", async () => {
    const { inner, transport } = setup();
    let closed = false;
    let error: Error | undefined;
    transport.onclose = () => (closed = true);
    transport.onerror = (e) => (error = e);
    await transport.start();
    inner.onerror!(new Error("boom"));
    await transport.close();
    expect(inner.closed).toBe(true);
    expect(closed).toBe(true);
    expect(error?.message).toBe("boom");
  });
});

describe("MessageLog", () => {
  it("filters by method", () => {
    const log = new MessageLog(() => 0);
    log.record("app->host", { jsonrpc: "2.0", method: "a" });
    log.record("app->host", { jsonrpc: "2.0", id: 2, method: "b", params: {} });
    log.record("host->app", { jsonrpc: "2.0", id: 2, result: {} });
    expect(log.messages("b")).toEqual([{ direction: "app->host", t: 0, jsonrpc: "2.0", id: 2, method: "b", params: {} }]);
  });
});
