// In-memory HostBridge for unit tests: replays a scripted tool call and records what the app
// sends back, using the MCP Apps method names so assertions read like the wire log.

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

export interface FakeScript {
  context?: HostContext;
  toolInput?: ToolInput;
  toolResult?: ToolResult;
  toolAnswers?: Record<string, ToolResult>;
}

export interface RecordedCall {
  method: string;
  params: unknown;
}

export class FakeBridge implements HostBridge {
  readonly calls: RecordedCall[] = [];
  private context: HostContext;
  private replay: Promise<void> = Promise.resolve();
  private readonly toolInputs = new Listeners<ToolInput>();
  private readonly toolResults = new Listeners<ToolResult>();
  private readonly contexts = new Listeners<HostContext>();

  constructor(private readonly script: FakeScript) {
    this.context = { ...(script.context ?? {}) };
  }

  async connect(): Promise<HostContext> {
    this.replay = new Promise((resolve) =>
      setTimeout(() => {
        if (this.script.toolInput) this.toolInputs.emit(this.script.toolInput);
        if (this.script.toolResult) this.toolResults.emit(this.script.toolResult);
        resolve();
      }, 0),
    );
    return { ...this.context };
  }

  /** Resolves once the scripted notifications have been delivered. */
  settled(): Promise<void> {
    return this.replay;
  }

  changeHostContext(change: HostContext): void {
    this.context = { ...this.context, ...change };
    this.contexts.emit({ ...this.context });
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
    this.calls.push({ method: "tools/call", params: { name, arguments: args } });
    const answer = this.script.toolAnswers?.[name];
    if (!answer) throw new Error(`FakeBridge has no answer for tool ${name}`);
    return answer;
  }

  async sendMessage(text: string): Promise<void> {
    this.calls.push({ method: "ui/message", params: { text } });
  }

  async updateModelContext(text: string): Promise<void> {
    this.calls.push({ method: "ui/update-model-context", params: { text } });
  }

  notifySize(size: Size): void {
    this.calls.push({ method: "ui/notifications/size-changed", params: size });
  }

  async requestDisplayMode(mode: DisplayMode): Promise<DisplayMode> {
    this.calls.push({ method: "ui/request-display-mode", params: { mode } });
    if (this.context.availableDisplayModes?.includes(mode)) {
      this.changeHostContext({ displayMode: mode });
    }
    return this.context.displayMode ?? "inline";
  }
}
