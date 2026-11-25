// DOM implementation of DoctorUi. Knows the markup in index.html; no host code. Server text
// (names, hints, snippets) goes in through textContent only, never as markup.

import type { HostContext } from "@sheet-music-mcp/ui-kit/host/HostBridge";
import { applyTheme } from "@sheet-music-mcp/ui-kit/theme";
import type { DoctorUi } from "./doctor.ts";
import type { Row, ViewModel } from "./report.ts";

export interface Controls {
  checkAgain(): Promise<void>;
  copyReport(): Promise<void>;
  copySnippet(checkName: string, snippet: string): Promise<void>;
  openDoc(url: string): Promise<void>;
}

const SUMMARY_CLASS = { ready: "ok", degraded: "warn", not_ready: "fail" } as const;
const SUMMARY_TEXT = { ready: "Ready", degraded: "Needs attention", not_ready: "Not ready" } as const;

export class DomUi implements DoctorUi {
  private readonly el: {
    summary: HTMLElement;
    checkAgain: HTMLButtonElement;
    copyReport: HTMLButtonElement;
    status: HTMLElement;
    notice: HTMLElement;
    report: HTMLElement;
    headline: HTMLElement;
    checks: HTMLElement;
    empty: HTMLElement;
    manualBox: HTMLElement;
    manual: HTMLTextAreaElement;
  };
  private controls: Controls | undefined;

  constructor(private readonly doc: Document) {
    const byId = <T extends HTMLElement>(id: string) => {
      const found = doc.getElementById(id);
      if (!found) throw new Error(`index.html is missing #${id}`);
      return found as T;
    };
    this.el = {
      summary: byId("summary"),
      checkAgain: byId("check-again"),
      copyReport: byId("copy-report"),
      status: byId("status"),
      notice: byId("notice"),
      report: byId("report"),
      headline: byId("headline"),
      checks: byId("checks"),
      empty: byId("empty"),
      manualBox: byId("manual-box"),
      manual: byId("manual"),
    };
  }

  bind(controls: Controls): void {
    this.controls = controls;
    this.el.checkAgain.addEventListener("click", () => void controls.checkAgain());
    this.el.copyReport.addEventListener("click", () => void controls.copyReport());
  }

  showLoading(): void {
    this.showNotice("Waiting for the health report…", false);
  }

  showError(message: string): void {
    this.el.report.hidden = true;
    this.el.summary.hidden = true;
    this.el.copyReport.disabled = true;
    this.showNotice(message, true);
  }

  showReport(model: ViewModel): void {
    const { el } = this;
    el.notice.hidden = true;
    el.report.hidden = false;
    el.summary.hidden = false;
    el.summary.className = `pill ${SUMMARY_CLASS[model.status]}`;
    el.summary.textContent = SUMMARY_TEXT[model.status];
    el.headline.textContent = model.headline;
    el.empty.hidden = !model.empty;
    el.copyReport.disabled = false;
    el.checks.replaceChildren(...model.rows.map((row) => this.rowElement(row)));
    this.say(model.headline);
    this.clearManual();
  }

  setChecking(on: boolean): void {
    // aria-disabled, not disabled: a disabled button would drop keyboard focus to the body.
    this.el.checkAgain.setAttribute("aria-disabled", String(on));
    this.el.checkAgain.textContent = on ? "Checking…" : "Check again";
    if (on) this.say("Checking…");
  }

  showCopyStatus(result: "copied" | "manual", text: string, what: string): void {
    if (result === "copied") {
      this.clearManual();
      this.say(`${what} copied to the clipboard.`);
      return;
    }
    this.el.manual.value = text;
    this.el.manualBox.hidden = false;
    this.el.manual.select();
    this.say(`${what} could not be copied here. Select the text below and copy it.`);
  }

  showLinkFailed(url: string): void {
    this.say(`The host did not open the link. Address: ${url}`);
  }

  applyHostContext(context: HostContext): void {
    applyTheme(this.doc.documentElement, context);
  }

  private showNotice(text: string, isError: boolean): void {
    this.el.notice.textContent = text;
    this.el.notice.classList.toggle("error", isError);
    this.el.notice.hidden = false;
  }

  private say(text: string): void {
    this.el.status.textContent = text;
  }

  private clearManual(): void {
    this.el.manualBox.hidden = true;
    this.el.manual.value = "";
  }

  private rowElement(row: Row): HTMLElement {
    const make = <K extends keyof HTMLElementTagNameMap>(tag: K, className?: string, text?: string) => {
      const node = this.doc.createElement(tag);
      if (className) node.className = className;
      if (text !== undefined) node.textContent = text;
      return node;
    };
    const item = make("li", "check");
    const title = make("div", "title");
    title.append(make("span", `badge ${row.status}`, row.label), make("strong", undefined, row.name));
    if (row.version) title.append(make("span", "version", `Version ${row.version}`));
    item.append(title);
    if (row.hint) item.append(make("p", "hint", row.hint));
    if (row.fixSnippet) {
      const snippet = row.fixSnippet;
      const fix = make("div", "fix");
      const copy = make("button", "small", "Copy fix");
      copy.type = "button";
      copy.setAttribute("aria-label", `Copy fix for ${row.name}`);
      copy.addEventListener("click", () => void this.controls?.copySnippet(row.name, snippet));
      fix.append(make("pre", undefined, snippet), copy);
      item.append(fix);
    }
    if (row.docUrl) {
      const url = row.docUrl;
      const link = make("a", undefined, "Read the setup notes");
      link.href = url;
      link.setAttribute("aria-label", `Read the setup notes for ${row.name}`);
      // The sandboxed frame cannot navigate; the host opens the link.
      link.addEventListener("click", (event) => {
        event.preventDefault();
        void this.controls?.openDoc(url);
      });
      item.append(link);
    }
    return item;
  }
}
