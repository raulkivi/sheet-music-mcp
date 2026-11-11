// HostBridge over the MCP Apps SDK. The only kit file that imports @modelcontextprotocol/ext-apps,
// so an SDK API change stays contained here.

import { App } from "@modelcontextprotocol/ext-apps";
import type {
  DisplayMode,
  HostBridge,
  HostContext,
  Size,
  ToolInput,
  ToolResult,
  Unsubscribe,
} from "./HostBridge.ts";
import { Listeners } from "./listeners.ts";

export type AppEvent = "toolinput" | "toolresult" | "hostcontextchanged";

interface TextBlock {
  type: "text";
  text: string;
}

/** The slice of the SDK `App` this bridge uses; lets contract tests pass a mock. */
export interface AppLike {
  connect(): Promise<void>;
  addEventListener(event: AppEvent, handler: (params: never) => void): void;
  getHostContext(): object | undefined;
  callServerTool(params: { name: string; arguments?: Record<string, unknown> }): Promise<object>;
  sendMessage(params: { role: "user"; content: TextBlock[] }): Promise<{ isError?: boolean }>;
  updateModelContext(params: { content: TextBlock[] }): Promise<unknown>;
  sendSizeChanged(params: Size): Promise<void>;
  requestDisplayMode(params: { mode: DisplayMode }): Promise<{ mode: DisplayMode }>;
}

export interface AppInfo {
  name: string;
  version: string;
  /** Display modes the app can render in; the host offers a subset. */
  displayModes?: DisplayMode[];
}

/** Production bridge: talks postMessage JSON-RPC to `window.parent`. */
export function createExtAppsBridge(info: AppInfo): ExtAppsBridge {
  const app = new App(
    { name: info.name, version: info.version },
    { availableDisplayModes: info.displayModes ?? ["inline"] },
    // The SDK measures the document and sends ui/notifications/size-changed on every change.
    { autoResize: true },
  );
  return new ExtAppsBridge(app as unknown as AppLike);
}

export class ExtAppsBridge implements HostBridge {
  private context: HostContext = {};
  private readonly toolInputs = new Listeners<ToolInput>(true);
  private readonly toolResults = new Listeners<ToolResult>(true);
  private readonly contexts = new Listeners<HostContext>();

  constructor(private readonly app: AppLike) {
    // Registered before connect(): hosts may send tool-input right after ui/notifications/initialized.
    app.addEventListener("toolinput", ((params: { arguments?: Record<string, unknown> }) => {
      this.toolInputs.emit({ arguments: params.arguments ?? {} });
    }) as (p: never) => void);
    app.addEventListener("toolresult", ((params: ToolResult) => {
      this.toolResults.emit(params);
    }) as (p: never) => void);
    app.addEventListener("hostcontextchanged", ((params: HostContext) => {
      this.context = { ...this.context, ...params };
      this.contexts.emit({ ...this.context });
    }) as (p: never) => void);
  }

  async connect(): Promise<HostContext> {
    await this.app.connect();
    this.context = { ...((this.app.getHostContext() as HostContext | undefined) ?? {}) };
    return { ...this.context };
  }

  onToolInput(listener: (input: ToolInput) => void): Unsubscribe {
    return this.toolInputs.add(listener);
  }

  onToolResult(listener: (result: ToolResult) => void): Unsubscribe {
    return this.toolResults.add(listener);
  }

  onHostContext(listener: (context: HostContext) => void): Unsubscribe {
    return this.contexts.add(listener);
  }

  async callTool(name: string, args: Record<string, unknown>): Promise<ToolResult> {
    return (await this.app.callServerTool({ name, arguments: args })) as ToolResult;
  }

  async sendMessage(text: string): Promise<void> {
    const result = await this.app.sendMessage({ role: "user", content: [{ type: "text", text }] });
    if (result.isError) throw new Error("The host rejected the message.");
  }

  async updateModelContext(text: string): Promise<void> {
    await this.app.updateModelContext({ content: [{ type: "text", text }] });
  }

  notifySize(size: Size): void {
    void this.app.sendSizeChanged(size).catch(() => {});
  }

  async requestDisplayMode(mode: DisplayMode): Promise<DisplayMode> {
    return (await this.app.requestDisplayMode({ mode })).mode;
  }
}
