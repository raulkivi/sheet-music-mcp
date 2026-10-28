// The only host API apps see. Implementations: ExtAppsBridge (MCP Apps hosts), FakeBridge
// (unit tests) and, later, an HTTP bridge for the web PoC.

import type { ThemeName } from "../theme.ts";

export type DisplayMode = "inline" | "fullscreen" | "pip";

export interface HostContext {
  theme?: ThemeName;
  styles?: { variables?: Record<string, string | undefined> };
  displayMode?: DisplayMode;
  availableDisplayModes?: DisplayMode[];
  containerDimensions?: {
    width?: number;
    maxWidth?: number;
    height?: number;
    maxHeight?: number;
  };
  locale?: string;
  platform?: "web" | "desktop" | "mobile";
}

/** Arguments of the tool call that opened the app (`ui/notifications/tool-input`). */
export interface ToolInput {
  arguments: Record<string, unknown>;
}

/** An MCP `CallToolResult` (`ui/notifications/tool-result`, or a `tools/call` answer). */
export interface ToolResult {
  content?: unknown[];
  structuredContent?: Record<string, unknown>;
  isError?: boolean;
}

export interface Size {
  width?: number;
  height?: number;
}

export type Unsubscribe = () => void;

export interface HostBridge {
  /** Handshake with the host. Resolves with the initial host context. */
  connect(): Promise<HostContext>;
  onToolInput(listener: (input: ToolInput) => void): Unsubscribe;
  onToolResult(listener: (result: ToolResult) => void): Unsubscribe;
  /** Called with the full, merged context after every host change. */
  onHostContext(listener: (context: HostContext) => void): Unsubscribe;
  /** Calls a tool on the app's own server through the host. */
  callTool(name: string, args: Record<string, unknown>): Promise<ToolResult>;
  /** Posts a user chat message. Callers pass fixed templates only, never score text. */
  sendMessage(text: string): Promise<void>;
  /** Replaces what the model knows about the app's state; no follow-up turn. */
  updateModelContext(text: string): Promise<void>;
  notifySize(size: Size): void;
  /** Resolves with the mode the host actually granted. */
  requestDisplayMode(mode: DisplayMode): Promise<DisplayMode>;
}
