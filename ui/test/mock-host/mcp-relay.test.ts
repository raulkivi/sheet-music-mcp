import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { McpRelay, renderMcpLaunch, StderrTail, type ToolClient } from "./mcp-relay.ts";

class FakeClient implements ToolClient {
  calls: unknown[] = [];
  closed = false;
  async callTool(params: { name: string; arguments?: Record<string, unknown> }) {
    this.calls.push(params);
    return { content: [{ type: "text", text: `ran ${params.name}` }] };
  }
  async close() {
    this.closed = true;
  }
}

describe("McpRelay", () => {
  it("forwards tools/call to the server and records it", async () => {
    const client = new FakeClient();
    const relay = new McpRelay(client, "/out");
    const result = await relay.handle("tools/call", { name: "render_page_svg", arguments: { page: 1 } });
    expect(result).toEqual({ content: [{ type: "text", text: "ran render_page_svg" }] });
    expect(client.calls).toEqual([{ name: "render_page_svg", arguments: { page: 1 } }]);
    expect(relay.calls).toEqual([{ name: "render_page_svg", arguments: { page: 1 } }]);
  });

  it("refuses any other method", async () => {
    const relay = new McpRelay(new FakeClient(), "/out");
    await expect(relay.handle("resources/read", {})).rejects.toThrow(/resources\/read/);
  });

  it("closes the server", async () => {
    const client = new FakeClient();
    await new McpRelay(client, "/out").close();
    expect(client.closed).toBe(true);
  });
});

describe("renderMcpLaunch", () => {
  const dirs: string[] = [];
  afterEach(() => dirs.splice(0).forEach((d) => rmSync(d, { recursive: true, force: true })));

  it("runs render-mcp from its own venv with the output root in the environment", () => {
    const dir = mkdtempSync(join(tmpdir(), "relay-"));
    dirs.push(dir);
    mkdirSync(join(dir, ".venv/bin"), { recursive: true });
    writeFileSync(join(dir, ".venv/bin/render-mcp"), "");
    const launch = renderMcpLaunch(dir, "/tmp/out");
    expect(launch.command).toBe(join(dir, ".venv/bin/render-mcp"));
    expect(launch.cwd).toBe(dir);
    expect(launch.env.SHEET_MUSIC_OUTPUT_ROOT).toBe("/tmp/out");
    expect(launch.env.VIRTUAL_ENV).toBeUndefined();
  });

  it("says how to install render-mcp when its venv is missing", () => {
    const dir = mkdtempSync(join(tmpdir(), "relay-"));
    dirs.push(dir);
    expect(() => renderMcpLaunch(dir, "/tmp/out")).toThrow(/uv sync --frozen --extra dev/);
  });
});

describe("StderrTail", () => {
  it("drains a stream so a chatty server never blocks, keeping only the last bytes", async () => {
    const { PassThrough } = await import("node:stream");
    const stream = new PassThrough({ highWaterMark: 16 });
    const tail = new StderrTail(10);
    tail.drain(stream);
    // Far more than the stream buffers: write() only keeps returning true if someone reads.
    let accepted = true;
    for (let i = 0; i < 1000; i++) accepted = stream.write("0123456789") && accepted;
    stream.end("ABCDEFGHIJ-end");
    await new Promise((resolve) => stream.on("end", resolve));
    expect(tail.text()).toBe("EFGHIJ-end");
  });

  it("drains nothing when there is no stream", () => {
    const tail = new StderrTail(10);
    tail.drain(null);
    expect(tail.text()).toBe("");
  });
});
