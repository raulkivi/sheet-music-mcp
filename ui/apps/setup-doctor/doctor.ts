// Setup Doctor behavior. Depends only on the HostBridge and a DoctorUi, so it runs against
// FakeBridge in unit tests. It shows the report of the server that serves the page (the host
// delivers that server's health_check result, and Check again calls the same server); it never
// reaches another server.

import { errorEnvelope } from "@sheet-music-mcp/ui-kit/host/toolErrors";
import type { HostBridge, HostContext, ToolResult } from "@sheet-music-mcp/ui-kit/host/HostBridge";
import { parseReport, reportText, viewModel, type Report, type ViewModel } from "./report.ts";

export interface DoctorUi {
  showLoading(): void;
  showReport(model: ViewModel): void;
  showError(message: string): void;
  setChecking(on: boolean): void;
  /** `text` is what the user copies by hand when `result` is "manual". */
  showCopyStatus(result: "copied" | "manual", text: string, what: string): void;
  showLinkFailed(url: string): void;
  applyHostContext(context: HostContext): void;
}

export type CopyFn = (text: string) => Promise<"copied" | "manual">;

export const NOTICES = {
  unreadable: "The health report could not be read.",
  callFailed: "The health check could not be run. Try again, or ask the assistant to run it.",
  checkFailed: (error: string, code: string) => (error ? `The health check failed: ${error} (${code}).` : `The health check failed (${code}).`),
};

export class SetupDoctor {
  private report: Report | undefined;
  private checking = false;

  constructor(
    private readonly bridge: HostBridge,
    private readonly ui: DoctorUi,
    private readonly copy: CopyFn,
  ) {}

  async start(): Promise<void> {
    this.ui.showLoading();
    this.bridge.onToolResult((result) => this.show(result));
    this.bridge.onHostContext((context) => this.ui.applyHostContext(context));
    this.ui.applyHostContext(await this.bridge.connect());
  }

  async checkAgain(): Promise<void> {
    if (this.checking) return;
    this.checking = true;
    this.ui.setChecking(true);
    try {
      this.show(await this.bridge.callTool("health_check", {}));
    } catch {
      this.ui.showError(NOTICES.callFailed);
    } finally {
      this.checking = false;
      this.ui.setChecking(false);
    }
  }

  async copyReport(): Promise<void> {
    if (!this.report) return;
    const text = reportText(this.report);
    this.ui.showCopyStatus(await this.copy(text), text, "Report");
  }

  async copySnippet(checkName: string, snippet: string): Promise<void> {
    this.ui.showCopyStatus(await this.copy(snippet), snippet, `Fix for ${checkName}`);
  }

  async openDoc(url: string): Promise<void> {
    try {
      await this.bridge.openLink(url);
    } catch {
      this.ui.showLinkFailed(url);
    }
  }

  private show(result: ToolResult): void {
    const failure = errorEnvelope(result);
    if (failure) return this.ui.showError(NOTICES.checkFailed(failure.error, failure.code));
    const report = parseReport(result.structuredContent);
    if (!report) return this.ui.showError(NOTICES.unreadable);
    this.report = report;
    this.ui.showReport(viewModel(report));
  }
}
