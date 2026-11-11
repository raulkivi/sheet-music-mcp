// Records every JSON-RPC message between the host and the view, in order, for the specs'
// asserts (window.__host.log). LoggingTransport wraps the transport AppBridge talks over, so the
// log shows the wire as the view saw it, whatever the bridge does with each message.

import type { JSONRPCMessage, Transport, TransportSendOptions } from "@modelcontextprotocol/client";

export type Direction = "host->app" | "app->host";
export type LoggedMessage = { direction: Direction; t: number } & JSONRPCMessage;

export class MessageLog {
  readonly entries: LoggedMessage[] = [];

  constructor(private readonly now: () => number = () => performance.now()) {}

  record(direction: Direction, message: JSONRPCMessage): void {
    this.entries.push({ direction, t: this.now(), ...message });
  }

  messages(method: string): LoggedMessage[] {
    return this.entries.filter((m) => "method" in m && m.method === method);
  }
}

export class LoggingTransport implements Transport {
  onmessage?: Transport["onmessage"];
  onclose?: () => void;
  onerror?: (error: Error) => void;

  constructor(
    private readonly inner: Transport,
    private readonly log: MessageLog,
  ) {}

  async start(): Promise<void> {
    this.inner.onmessage = (message, extra) => {
      this.log.record("app->host", message);
      this.onmessage?.(message, extra);
    };
    this.inner.onclose = () => this.onclose?.();
    this.inner.onerror = (error) => this.onerror?.(error);
    await this.inner.start();
  }

  async send(message: JSONRPCMessage, options?: TransportSendOptions): Promise<void> {
    this.log.record("host->app", message);
    await this.inner.send(message, options);
  }

  async close(): Promise<void> {
    await this.inner.close();
  }
}
