// DOM implementation of WorkbenchUi. Knows the markup in index.html; no host code, no decisions.
// Every text it shows comes from the WorkbenchView; the only fixed texts are labels.

import type { HostContext } from "@sheet-music-mcp/ui-kit/host/HostBridge";
import { applyTheme } from "@sheet-music-mcp/ui-kit/theme";
import type { HunkRow, Layout, Row } from "./review.ts";
import type { ValidationState } from "./validation.ts";
import type { Mode, WorkbenchUi, WorkbenchView } from "./workbench.ts";

export interface Controls {
  setMode(mode: Mode): void;
  setLayout(layout: Layout): void;
  toggleHunk(id: number): void;
  edit(text: string): void;
  acceptSelected(): Promise<void>;
  acceptAll(): Promise<void>;
  rejectAll(): Promise<void>;
  revise(): Promise<void>;
  downloadResult(): void;
}

export function validationText(state: ValidationState): string {
  switch (state.status) {
    case "idle":
      return "Nothing to check yet";
    case "pending":
      return "Checking the ABC…";
    case "unavailable":
      return state.message;
    case "valid": {
      const n = state.warnings.length;
      return n === 0 ? "Valid ABC" : `Valid ABC, ${n} ${n === 1 ? "warning" : "warnings"}`;
    }
    case "invalid": {
      const n = state.errors.length;
      return `${n} ${n === 1 ? "error" : "errors"}: ${state.errors[0] ?? ""}`;
    }
  }
}

export class DomUi implements WorkbenchUi {
  private readonly el: ReturnType<DomUi["lookup"]>;
  private rowsKey = "";
  private revision = -1;

  constructor(private readonly doc: Document) {
    this.el = this.lookup();
  }

  private lookup() {
    const byId = <T extends HTMLElement>(id: string) => {
      const found = this.doc.getElementById(id);
      if (!found) throw new Error(`index.html is missing #${id}`);
      return found as T;
    };
    return {
      subtitle: byId("subtitle"),
      validation: byId("validation"),
      modeReview: byId<HTMLButtonElement>("mode-review"),
      modeEdit: byId<HTMLButtonElement>("mode-edit"),
      layoutGroup: byId("layout-group"),
      layoutChanges: byId<HTMLButtonElement>("layout-changes"),
      layoutFull: byId<HTMLButtonElement>("layout-full"),
      summary: byId("summary"),
      notice: byId("notice"),
      review: byId("review"),
      editor: byId("editor"),
      gutter: byId("gutter"),
      text: byId<HTMLTextAreaElement>("abc-text"),
      problems: byId("problems"),
      warnings: byId("warnings"),
      acceptSelected: byId<HTMLButtonElement>("accept-selected"),
      acceptAll: byId<HTMLButtonElement>("accept-all"),
      rejectAll: byId<HTMLButtonElement>("reject-all"),
      revise: byId<HTMLButtonElement>("revise"),
      outcome: byId("outcome"),
      file: byId("file"),
      filePath: byId("file-path"),
      download: byId<HTMLButtonElement>("download"),
    };
  }

  bind(controls: Controls): void {
    const { el } = this;
    el.modeReview.addEventListener("click", () => controls.setMode("review"));
    el.modeEdit.addEventListener("click", () => controls.setMode("edit"));
    el.layoutChanges.addEventListener("click", () => controls.setLayout("changes"));
    el.layoutFull.addEventListener("click", () => controls.setLayout("full"));
    el.acceptSelected.addEventListener("click", () => void controls.acceptSelected());
    el.acceptAll.addEventListener("click", () => void controls.acceptAll());
    el.rejectAll.addEventListener("click", () => void controls.rejectAll());
    el.revise.addEventListener("click", () => void controls.revise());
    el.download.addEventListener("click", () => controls.downloadResult());
    el.text.addEventListener("input", () => {
      this.drawGutter(el.text.value, []);
      controls.edit(el.text.value);
    });
    el.text.addEventListener("scroll", () => (el.gutter.scrollTop = el.text.scrollTop));
    // Delegated, because the hunks are rebuilt on every change.
    el.review.addEventListener("change", (event) => {
      const id = (event.target as HTMLElement).closest<HTMLElement>("[data-hunk]")?.dataset.hunk;
      if (id !== undefined) controls.toggleHunk(Number(id));
    });
    el.review.addEventListener("keydown", (event) => this.moveBetweenHunks(event));
  }

  showFatal(text: string): void {
    this.el.notice.textContent = text;
    this.el.notice.hidden = false;
  }

  applyHostContext(context: HostContext): void {
    applyTheme(this.doc.documentElement, context);
  }

  download(filename: string, content: string, mime: string): void {
    const url = URL.createObjectURL(new Blob([content], { type: mime }));
    const link = this.doc.createElement("a");
    link.href = url;
    link.download = filename;
    link.hidden = true;
    this.doc.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  }

  render(view: WorkbenchView): void {
    const { el } = this;
    el.subtitle.textContent = view.subtitle;
    el.summary.textContent = view.summary;
    this.pressed(el.modeReview, view.mode === "review");
    this.pressed(el.modeEdit, view.mode === "edit");
    this.pressed(el.layoutChanges, view.layout === "changes");
    this.pressed(el.layoutFull, view.layout === "full");
    el.layoutGroup.hidden = view.mode === "edit";
    el.review.hidden = view.mode === "edit";
    el.editor.hidden = view.mode !== "edit";

    el.validation.textContent = validationText(view.validation);
    el.validation.dataset.status = view.validation.status;
    el.notice.textContent = view.notice ?? "";
    el.notice.hidden = view.notice === undefined;
    this.list(el.problems, view.validation.status === "invalid" ? view.validation.errors : []);
    this.list(el.warnings, view.warnings);

    this.drawReview(view);
    this.drawEditor(view);

    el.acceptSelected.disabled = !view.canAccept;
    el.acceptAll.disabled = !view.canAccept;
    el.rejectAll.disabled = !view.canReject;
    el.revise.disabled = !view.canRevise;
    el.outcome.textContent = view.outcome.text;
    el.outcome.hidden = view.outcome.text === "";
    el.outcome.dataset.status = view.outcome.status;
    el.file.hidden = view.outcome.file === undefined;
    el.filePath.textContent = view.outcome.file ?? "";
    el.download.hidden = !view.download;
  }

  private pressed(button: HTMLButtonElement, on: boolean): void {
    button.setAttribute("aria-pressed", String(on));
  }

  private list(target: HTMLElement, items: string[]): void {
    target.replaceChildren(
      ...items.map((text) => {
        const item = this.doc.createElement("li");
        item.textContent = text;
        return item;
      }),
    );
    target.hidden = items.length === 0;
  }

  private drawReview(view: WorkbenchView): void {
    const key = JSON.stringify([view.layout, view.rows, view.empty]);
    if (key === this.rowsKey) return;
    this.rowsKey = key;
    const focused = this.doc.activeElement?.closest<HTMLElement>("[data-hunk]")?.dataset.hunk;
    const children: Node[] = view.rows.map((row) => this.row(row));
    if (view.rows.length === 0 && view.empty) {
      const empty = this.doc.createElement("p");
      empty.className = "empty";
      empty.textContent = view.empty;
      children.push(empty);
    }
    this.el.review.replaceChildren(...children);
    if (focused !== undefined) this.el.review.querySelector<HTMLElement>(`[data-hunk="${focused}"] input`)?.focus();
  }

  private row(row: Row): HTMLElement {
    if (row.kind === "context") {
      const line = this.doc.createElement("div");
      line.className = "context";
      line.append(this.span("num", String(row.line)), this.span("text", row.text));
      return line;
    }
    return this.hunk(row);
  }

  private hunk(row: HunkRow): HTMLElement {
    const article = this.doc.createElement("article");
    article.className = "hunk";
    article.dataset.hunk = String(row.id);
    article.dataset.kept = String(row.accepted);
    article.setAttribute("aria-label", `Change ${row.number} of ${row.total}`);

    const label = this.doc.createElement("label");
    label.className = "hunk-head";
    const box = this.doc.createElement("input");
    box.type = "checkbox";
    box.checked = row.accepted;
    box.setAttribute("aria-label", `Keep change ${row.number}`);
    const where = row.originalLines.length > 1 ? `lines ${row.firstLine} to ${row.firstLine + row.originalLines.length - 1}` : `line ${row.firstLine}`;
    label.append(box, this.span("", `Change ${row.number} of ${row.total}, ${where}`));

    const columns = this.doc.createElement("div");
    columns.className = "cols";
    columns.append(
      this.column("Original", "del", "−", "removed", row.originalLines, "Nothing in the original"),
      this.column("Proposed", "add", "+", "added", row.proposedLines, "These lines are removed"),
    );
    article.append(label, columns);
    return article;
  }

  private column(title: string, kind: "add" | "del", mark: string, word: string, lines: string[], none: string): HTMLElement {
    const column = this.doc.createElement("div");
    column.className = `col ${kind}`;
    column.append(this.span("col-title", title));
    if (lines.length === 0) column.append(this.span("none", none));
    for (const text of lines) {
      const line = this.doc.createElement("div");
      line.className = "line";
      const hidden = this.span("sr", `${word}: `);
      const marker = this.span("mark", mark);
      marker.setAttribute("aria-hidden", "true");
      line.append(marker, hidden, this.span("text", text));
      column.append(line);
    }
    return column;
  }

  private span(className: string, text: string): HTMLSpanElement {
    const span = this.doc.createElement("span");
    if (className) span.className = className;
    span.textContent = text;
    return span;
  }

  private drawEditor(view: WorkbenchView): void {
    const { text } = this.el;
    if (view.editor.revision !== this.revision) {
      this.revision = view.editor.revision;
      text.value = view.editor.text;
    }
    this.drawGutter(text.value, view.editor.errorLines);
  }

  /** One number per line; a line with an error carries a marker and `data-error`. */
  private drawGutter(value: string, errorLines: number[]): void {
    const count = value.split("\n").length;
    const bad = new Set(errorLines);
    this.el.gutter.replaceChildren(
      ...Array.from({ length: count }, (_, index) => {
        const number = index + 1;
        const line = this.doc.createElement("div");
        line.dataset.line = String(number);
        line.textContent = bad.has(number) ? `! ${number}` : String(number);
        if (bad.has(number)) line.dataset.error = "true";
        return line;
      }),
    );
  }

  /** Up and Down move between the "Keep change" checkboxes; Space toggles, as for any checkbox. */
  private moveBetweenHunks(event: KeyboardEvent): void {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    const boxes = [...this.el.review.querySelectorAll<HTMLInputElement>(".hunk input")];
    const at = boxes.indexOf(event.target as HTMLInputElement);
    if (at < 0) return;
    event.preventDefault();
    boxes[Math.min(boxes.length - 1, Math.max(0, at + (event.key === "ArrowDown" ? 1 : -1)))]?.focus();
  }
}
