// Who answers the view's tools/call (the `server` query parameter). One interface, three
// implementations: placeholder pages (fast, no Python), none, and the real render-mcp through the
// Node relay that the Playwright fixture exposes as window.mcpHostRelay.

import type { CallToolResult } from "@modelcontextprotocol/client";

export interface ToolCall {
  name: string;
  arguments?: Record<string, unknown>;
}

export interface ToolBackend {
  callTool(call: ToolCall): Promise<CallToolResult>;
}

export type Relay = (method: string, params: unknown) => Promise<unknown>;

/** A JSON-RPC error the bridge sends back as such (code -32602, as the old mock did). */
class NoSuchTool extends Error {
  readonly code = -32602;
  constructor(name: string) {
    super(`mock host has no fixture for tool ${name}`);
  }
}

// Stand-in for render-mcp's render_page_svg: a five-page score of labelled placeholder pages,
// answered in the server's contract (structuredContent {svg, page, page_count}, error envelope).
const PLACEHOLDER_PAGES = 5;

function toolError(error: string, code: string, hint?: string): CallToolResult {
  const envelope = hint ? { error, error_code: code, hint } : { error, error_code: code };
  return { isError: true, content: [{ type: "text", text: JSON.stringify(envelope) }] };
}

function placeholderPage(args: Record<string, unknown>): CallToolResult {
  if (typeof args.musicxml !== "string" || !args.musicxml.includes("<score-partwise")) {
    return toolError("Not a MusicXML score", "INVALID_INPUT");
  }
  const page = Number(args.page);
  if (page > PLACEHOLDER_PAGES) {
    return toolError(`Page ${page} is out of range.`, "INVALID_PARAMETER", `This score has pages 1–${PLACEHOLDER_PAGES} at this width and zoom.`);
  }
  const w = Number(args.width_px);
  const h = Math.round(w * 1.414);
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="${w}px" height="${h}px" viewBox="0 0 ${w} ${h}" ` +
    `data-server-page="${page}" data-zoom="${args.zoom}"><text x="24" y="48" font-size="24">` +
    `Server page ${page}</text></svg>`;
  return {
    content: [{ type: "text", text: `Page ${page} of ${PLACEHOLDER_PAGES} rendered as SVG.` }],
    structuredContent: { svg, page, page_count: PLACEHOLDER_PAGES },
  };
}

export const placeholderTools: ToolBackend = {
  async callTool(call) {
    if (call.name === "render_page_svg") return placeholderPage(call.arguments ?? {});
    throw new NoSuchTool(call.name);
  },
};

export const noTools: ToolBackend = {
  async callTool(call) {
    throw new NoSuchTool(call.name);
  },
};

export function relayedTools(relay: Relay): ToolBackend {
  return {
    async callTool(call) {
      return (await relay("tools/call", call)) as CallToolResult;
    },
  };
}
