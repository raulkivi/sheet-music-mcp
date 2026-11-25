// DOM implementation of DiffUi. Knows the markup in index.html; no host or Verovio code.
// Text from the server only ever goes in through textContent.

import type { HostContext } from "@sheet-music-mcp/ui-kit/host/HostBridge";
import { applyTheme } from "@sheet-music-mcp/ui-kit/theme";
import { describeChange, type Change, type KindOption } from "./model.ts";
import type { DiffUi } from "./viewer.ts";

export interface Controls {
  select(index: number): void;
  toggleKind(kind: string): void;
  exportScores(): Promise<void>;
  openInScoreViewer(): Promise<void>;
}

const swatch = (doc: Document, kind: string): HTMLElement => {
  const dot = doc.createElement("span");
  dot.className = "swatch";
  dot.setAttribute("aria-hidden", "true");
  // Set by the score panes once the legend is known.
  dot.style.background = `var(--kind-${kind}, var(--color-text-secondary))`;
  return dot;
};

export class DomUi implements DiffUi {
  private readonly el: Record<
    "headline" | "notice" | "exported" | "filters" | "changes" | "selection" | "report",
    HTMLElement
  > & {
    tabScores: HTMLButtonElement;
    tabReport: HTMLButtonElement;
    panelScores: HTMLElement;
    panelReport: HTMLElement;
    exportButton: HTMLButtonElement;
    openViewer: HTMLButtonElement;
  };
  private kindsKey = "";
  private items: HTMLButtonElement[] = [];
  private hasScores = false;

  constructor(private readonly doc: Document) {
    const byId = <T extends HTMLElement>(id: string) => {
      const found = doc.getElementById(id);
      if (!found) throw new Error(`index.html is missing #${id}`);
      return found as T;
    };
    this.el = {
      headline: byId("headline"),
      notice: byId("notice"),
      exported: byId("exported"),
      filters: byId("filters"),
      changes: byId("changes"),
      selection: byId("selection"),
      report: byId("report"),
      tabScores: byId("tab-scores"),
      tabReport: byId("tab-report"),
      panelScores: byId("panel-scores"),
      panelReport: byId("panel-report"),
      exportButton: byId("export"),
      openViewer: byId("open-viewer"),
    };
  }

  bind(controls: Controls): void {
    const { el } = this;
    el.tabScores.addEventListener("click", () => this.showTab("scores"));
    el.tabReport.addEventListener("click", () => this.showTab("report"));
    for (const tab of [el.tabScores, el.tabReport]) {
      tab.addEventListener("keydown", (event) => {
        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
        const other = tab === el.tabScores ? el.tabReport : el.tabScores;
        if (other.disabled) return;
        event.preventDefault();
        other.focus();
        other.click();
      });
    }
    el.exportButton.addEventListener("click", () => void controls.exportScores());
    el.openViewer.addEventListener("click", () => void controls.openInScoreViewer());
    el.filters.addEventListener("click", (event) => {
      const button = (event.target as Element).closest<HTMLButtonElement>("button[data-kind]");
      if (button) controls.toggleKind(button.dataset.kind!);
    });
    el.changes.addEventListener("click", (event) => {
      const button = (event.target as Element).closest<HTMLButtonElement>("button[data-index]");
      if (button) controls.select(Number(button.dataset.index));
    });
    el.changes.addEventListener("keydown", (event) => this.moveFocus(event));
  }

  showHeadline(text: string): void {
    this.el.headline.textContent = text;
  }

  showReport(text: string | undefined): void {
    this.el.report.textContent = text ?? "";
    this.el.tabReport.disabled = text === undefined;
    if (text === undefined) this.showTab("scores");
  }

  showNotice(text: string | undefined): void {
    this.el.notice.textContent = text ?? "";
    this.el.notice.hidden = text === undefined;
  }

  showList(changes: Change[], kinds: KindOption[], selected: ReadonlySet<string>): void {
    this.renderFilters(kinds, selected);
    const list = this.el.changes;
    list.replaceChildren();
    this.items = changes.map((change, index) => {
      const item = this.doc.createElement("li");
      const button = this.doc.createElement("button");
      button.type = "button";
      button.dataset.index = String(index);
      button.tabIndex = index === 0 ? 0 : -1;
      button.append(swatch(this.doc, change.operation), this.doc.createTextNode(describeChange(change)));
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
    if (index !== undefined) {
      // One tab stop for the list, on the selected change.
      this.items.forEach((button, i) => (button.tabIndex = i === index ? 0 : -1));
    }
    this.el.selection.textContent = spoken || "Select a change to see it in both scores.";
  }

  showExported(names: string[] | undefined): void {
    this.el.exported.replaceChildren(
      ...(names ?? []).map((name) => {
        const chip = this.doc.createElement("li");
        chip.textContent = name;
        return chip;
      }),
    );
    this.el.exported.hidden = !names || names.length === 0;
  }

  showBusy(busy: boolean): void {
    this.el.exportButton.disabled = busy || !this.hasScores;
    this.el.openViewer.disabled = busy || !this.hasScores;
    this.el.exportButton.setAttribute("aria-busy", String(busy));
  }

  allowExport(enabled: boolean): void {
    this.hasScores = enabled;
    this.el.exportButton.disabled = this.el.openViewer.disabled = !enabled;
  }

  applyHostContext(context: HostContext): void {
    applyTheme(this.doc.documentElement, context);
  }

  private showTab(which: "scores" | "report"): void {
    const { el } = this;
    const scores = which === "scores";
    el.panelScores.hidden = !scores;
    el.panelReport.hidden = scores;
    for (const [tab, active] of [
      [el.tabScores, scores],
      [el.tabReport, !scores],
    ] as const) {
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
    }
  }

  private renderFilters(kinds: KindOption[], selected: ReadonlySet<string>): void {
    const key = kinds.map((k) => `${k.kind}:${k.count}`).join("|");
    if (key !== this.kindsKey) {
      this.kindsKey = key;
      this.el.filters.replaceChildren(
        ...kinds.map((kind) => {
          const button = this.doc.createElement("button");
          button.type = "button";
          button.dataset.kind = kind.kind;
          button.append(swatch(this.doc, kind.kind), this.doc.createTextNode(`${kind.label} (${kind.count})`));
          return button;
        }),
      );
    }
    this.el.filters.hidden = kinds.length < 2;
    for (const button of this.el.filters.querySelectorAll<HTMLButtonElement>("button[data-kind]")) {
      button.setAttribute("aria-pressed", String(selected.has(button.dataset.kind!)));
    }
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
