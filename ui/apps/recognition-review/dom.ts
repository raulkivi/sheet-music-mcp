// DOM implementation of ReviewUi. Knows the markup in index.html; no host or Verovio code.
// Text from the server only ever goes in through textContent.

import type { HostContext } from "@sheet-music-mcp/ui-kit/host/HostBridge";
import { applyTheme } from "@sheet-music-mcp/ui-kit/theme";
import { engineLabel } from "./advice.ts";
import type { Issue } from "./issues.ts";
import type { ReviewUi } from "./reviewer.ts";

export interface Controls {
  select(index: number): void;
  rerun(): Promise<void>;
  accept(): Promise<void>;
}

const BUSY_OFF = "aria-disabled";

export class DomUi implements ReviewUi {
  private items: HTMLButtonElement[] = [];
  private canRerun = false;
  private canAccept = false;
  private busy = false;
  private done = false;

  constructor(private readonly doc: Document) {}

  private el<T extends HTMLElement>(id: string): T {
    const found = this.doc.getElementById(id);
    if (!found) throw new Error(`index.html is missing #${id}`);
    return found as T;
  }

  bind(controls: Controls): void {
    // aria-disabled, not disabled: a control that is busy or done keeps keyboard focus.
    const press = (id: string, action: () => Promise<void>) =>
      this.el<HTMLButtonElement>(id).addEventListener("click", (event) => {
        if ((event.currentTarget as HTMLElement).getAttribute(BUSY_OFF) === "true") return;
        void action();
      });
    press("rerun", controls.rerun.bind(controls));
    press("accept", controls.accept.bind(controls));
    const list = this.el("issues");
    list.addEventListener("click", (event) => {
      const button = (event.target as Element).closest<HTMLButtonElement>("button[data-index]");
      if (button) controls.select(Number(button.dataset.index));
    });
    list.addEventListener("keydown", (event) => this.moveFocus(event));
  }

  showHeadline(text: string | undefined): void {
    this.el("headline").textContent = text ?? "Waiting for a recognition…";
  }

  showNotices(texts: string[]): void {
    const box = this.el("notices");
    box.replaceChildren(
      ...texts.map((text) => {
        const line = this.doc.createElement("p");
        line.textContent = text;
        return line;
      }),
    );
    box.hidden = texts.length === 0;
  }

  showAdvice(text: string | undefined): void {
    const advice = this.el("advice");
    advice.textContent = text ?? "";
    advice.hidden = text === undefined;
  }

  showIssues(issues: Issue[]): void {
    this.el("issue-count").textContent = `(${issues.length})`;
    this.el("no-issues").hidden = issues.length > 0;
    const list = this.el("issues");
    list.hidden = issues.length === 0;
    list.replaceChildren();
    this.items = issues.map((issue, index) => {
      const item = this.doc.createElement("li");
      const button = this.doc.createElement("button");
      button.type = "button";
      button.dataset.index = String(index);
      button.dataset.severity = issue.severity;
      // One tab stop for the list: the first item until a selection moves it.
      button.tabIndex = index === 0 ? 0 : -1;
      const tag = this.doc.createElement("span");
      tag.className = "tag";
      tag.textContent = issue.tag;
      const text = this.doc.createElement("span");
      text.className = "issue-text";
      text.textContent = issue.message;
      // Spaces between the parts: they are inline spans, so the accessible name reads as words.
      button.append(tag, this.doc.createTextNode(" "), text);
      if (issue.where) {
        const where = this.doc.createElement("span");
        where.className = "where";
        where.textContent = issue.where;
        button.append(this.doc.createTextNode(" "), where);
      }
      item.append(button);
      list.append(item);
      return button;
    });
  }

  showSelection(index: number | undefined, spoken: string): void {
    this.items.forEach((button, i) => {
      if (i === index) button.setAttribute("aria-current", "true");
      else button.removeAttribute("aria-current");
    });
    if (index !== undefined) this.items.forEach((button, i) => (button.tabIndex = i === index ? 0 : -1));
    this.el("selection").textContent = spoken;
  }

  showPhoto(url: string | undefined): void {
    const image = this.el<HTMLImageElement>("photo-img");
    if (url === undefined) image.removeAttribute("src");
    else image.src = url;
    image.hidden = url === undefined;
    this.el("photo-empty").hidden = url !== undefined;
  }

  showStatus(text: string): void {
    this.el("status").textContent = text;
  }

  showBusy(busy: boolean): void {
    this.busy = busy;
    this.paintActions();
  }

  showEngine(engine: string, other: string): void {
    this.el("engine").textContent = engineLabel(engine);
    this.el("rerun").textContent = `Recognize again with ${engineLabel(other)}`;
  }

  allow(actions: { rerun: boolean; accept: boolean }): void {
    this.canRerun = actions.rerun;
    this.canAccept = actions.accept;
    this.done = false;
    this.paintActions();
  }

  showAccepted(): void {
    this.done = true;
    this.showStatus("Score accepted. The assistant will continue with it.");
    this.paintActions();
  }

  applyHostContext(context: HostContext): void {
    applyTheme(this.doc.documentElement, context);
  }

  private paintActions(): void {
    const rerun = this.el<HTMLButtonElement>("rerun");
    const accept = this.el<HTMLButtonElement>("accept");
    // Not yet available: really disabled. Busy or done: aria-disabled, so focus stays put.
    rerun.disabled = !this.canRerun;
    accept.disabled = !this.canAccept;
    rerun.setAttribute(BUSY_OFF, String(this.busy));
    rerun.setAttribute("aria-busy", String(this.busy));
    accept.setAttribute(BUSY_OFF, String(this.done || this.busy));
    accept.textContent = this.done ? "Accepted" : "Accept score";
  }

  private moveFocus(event: KeyboardEvent): void {
    const current = this.items.indexOf(this.doc.activeElement as HTMLButtonElement);
    if (current < 0) return;
    const last = this.items.length - 1;
    const next =
      event.key === "ArrowDown" ? Math.min(last, current + 1)
      : event.key === "ArrowUp" ? Math.max(0, current - 1)
      : event.key === "Home" ? 0
      : event.key === "End" ? last
      : undefined;
    if (next === undefined) return;
    event.preventDefault();
    this.items.forEach((button, i) => (button.tabIndex = i === next ? 0 : -1));
    this.items[next]!.focus();
  }
}
