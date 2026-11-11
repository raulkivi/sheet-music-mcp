// The Node half of the host: the real render-mcp over stdio. The host page's AppBridge has no MCP
// client of its own; what the view asks for reaches here through window.mcpHostRelay (exposed by
// test/e2e/host-fixture.ts), is recorded, and goes to the server. Runs in Node only.

import { existsSync } from "node:fs";
import { join } from "node:path";
import { Client } from "@modelcontextprotocol/client";
import { getDefaultEnvironment, StdioClientTransport } from "@modelcontextprotocol/client/stdio";
import type { CallToolResult } from "@modelcontextprotocol/client";

/** The slice of the SDK Client the relay uses; unit tests pass a fake. */
export interface ToolClient {
  callTool(params: { name: string; arguments?: Record<string, unknown> }): Promise<CallToolResult | object>;
  close(): Promise<void>;
}

export interface RelayedCall {
  name: string;
  arguments?: Record<string, unknown>;
}

export interface Launch {
  command: string;
  args: string[];
  cwd: string;
  env: Record<string, string>;
}

/** How to start render-mcp from its own uv venv (never a shared one), writing under outputRoot. */
export function renderMcpLaunch(renderMcpDir: string, outputRoot: string): Launch {
  const command = join(renderMcpDir, ".venv", "bin", "render-mcp");
  if (!existsSync(command)) {
    throw new Error(`render-mcp is not installed at ${command}: run \`uv sync --frozen --extra dev\` in ${renderMcpDir}`);
  }
  const env: Record<string, string> = { ...getDefaultEnvironment(), SHEET_MUSIC_OUTPUT_ROOT: outputRoot };
  delete env.VIRTUAL_ENV;
  return { command, args: [], cwd: renderMcpDir, env };
}

/**
 * Reads the server's stderr as it comes, so a chatty server never blocks on a full pipe, and
 * keeps only the last `limit` characters to explain a server that fails to start.
 */
export class StderrTail {
  private buffer = "";

  constructor(private readonly limit = 8192) {}

  drain(stream: NodeJS.ReadableStream | null): void {
    stream?.on("data", (chunk: Buffer | string) => {
      this.buffer = (this.buffer + chunk.toString()).slice(-this.limit);
    });
  }

  text(): string {
    return this.buffer;
  }
}

export class McpRelay {
  /** Every tool call made on the server, in order: the host's own and the view's. */
  readonly calls: RelayedCall[] = [];

  constructor(
    private readonly client: ToolClient,
    /** Where the server writes its files (SHEET_MUSIC_OUTPUT_ROOT). */
    readonly outputRoot: string,
  ) {}

  static async start(launch: Launch, outputRoot: string): Promise<McpRelay> {
    const client = new Client({ name: "sheet-music-mock-host", version: "0.0.0" });
    const transport = new StdioClientTransport({ ...launch, stderr: "pipe" });
    // The transport hands out the pipe before start, so nothing the server writes is missed.
    const stderr = new StderrTail();
    stderr.drain(transport.stderr as NodeJS.ReadableStream | null);
    try {
      await client.connect(transport);
    } catch (error) {
      throw new Error(`render-mcp did not start: ${String(error)}\n${stderr.text()}`);
    }
    return new McpRelay(client, outputRoot);
  }

  /** Answers one request the view (or the host page, playing the model) relayed. */
  async handle(method: string, params: unknown): Promise<unknown> {
    if (method !== "tools/call") throw new Error(`The relay forwards tools/call only, not ${method}`);
    const call = params as RelayedCall;
    this.calls.push(call);
    return this.client.callTool({ name: call.name, arguments: call.arguments ?? {} });
  }

  async close(): Promise<void> {
    await this.client.close();
  }
}
