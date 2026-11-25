// Diff Viewer behavior. Depends only on the HostBridge, a DiffUi and ScorePanes, so it runs
// unchanged against FakeBridge in unit tests and against the real host.

import type { HostBridge, HostContext, ToolResult } from "@sheet-music-mcp/ui-kit/host/HostBridge";
import { errorEnvelope } from "@sheet-music-mcp/ui-kit/host/toolErrors";
import { fileName, openInScoreViewerMessage, readExported, readScores, type Exported } from "./messages.ts";
import {
  kindsPresent,
  measureTarget,
  readDiff,
  selectionSummary,
  summaryLine,
  visibleChanges,
  type Change,
  type Diff,
  type KindOption,
} from "./model.ts";

export interface DiffUi {
  showHeadline(text: string): void;
  showReport(text: string | undefined): void;
  showNotice(text: string | undefined): void;
  /** The (filtered) list, the kinds that can be filtered on and the selected ones. */
  showList(changes: Change[], kinds: KindOption[], selected: ReadonlySet<string>): void;
  /** `index` is the position in the shown list, undefined when nothing is selected. */
  showSelection(index: number | undefined, spoken: string): void;
  /** File names of the exported scores, or undefined to clear them. */
  showExported(names: string[] | undefined): void;
  showBusy(busy: boolean): void;
  /** The save and open buttons work only for a result that carries a diff_id. */
  allowExport(enabled: boolean): void;
  applyHostContext(context: HostContext): void;
}

/** The two score panes; the DOM implementation uses Verovio. */
export interface ScorePanes {
  /** Rejects when the notation engine cannot start or a score cannot be read. */
  load(reference: string, target: string, legend: Record<string, string>): Promise<void>;
  /** Marks the printed bar in both panes and scrolls it into view. */
  showMeasure(measure: number): void;
}

export const NOTICES = {
  identical: "The scores are identical: there are no differences to show.",
  noChanges:
    "This result has no list of changes. Ask for the changes, the report or the full comparison to see them here.",
  noScores: "This result does not include the scores, so only the list of changes is shown.",
  notAComparison: "This tool result is not a score comparison.",
  engineBlocked:
    "The viewer could not start the notation engine in this host (WebAssembly may be blocked). " +
    "The list of changes and the report still work.",
  compareFailed: (code: string) => `The comparison failed (${code}).`,
  scoresFailed: (code: string) => `The scores could not be loaded (${code}).`,
  exportFailed: (code: string) => `The scores could not be saved (${code}).`,
};

export class DiffViewer {
  private diff: Diff | undefined;
  private selected = new Set<string>();
  private shown: Change[] = [];
  private current: Change | undefined;
  private exported: Extract<Exported, { ok: true }> | undefined;
  private working: Promise<unknown> | undefined;
  private work: Promise<void> = Promise.resolve();

  constructor(
    private readonly bridge: HostBridge,
    private readonly ui: DiffUi,
    private readonly panes: ScorePanes,
  ) {}

  async start(): Promise<void> {
    this.bridge.onToolResult((result) => this.enqueue(() => this.onToolResult(result)));
    this.bridge.onHostContext((context) => this.ui.applyHostContext(context));
    this.ui.applyHostContext(await this.bridge.connect());
  }

  /** Resolves when queued loading has finished. */
  async idle(): Promise<void> {
    let settled: Promise<void>;
    do {
      settled = this.work;
      await settled;
    } while (settled !== this.work);
  }

  /** Selects the change at `index` of the shown list. */
  select(index: number): void {
    const change = this.shown[index];
    if (!change) return;
    this.current = change;
    this.announce();
    this.panes.showMeasure(measureTarget(change));
  }

  toggleKind(kind: string): void {
    if (!this.diff?.changes) return;
    if (!this.selected.delete(kind)) this.selected.add(kind);
    this.refreshList();
  }

  async exportScores(): Promise<void> {
    await this.ensureExported();
  }

  async openInScoreViewer(): Promise<void> {
    // One click, one message: a second click while the first is running joins it.
    this.working ??= this.sendToScoreViewer().finally(() => (this.working = undefined));
    await this.working;
  }

  private async sendToScoreViewer(): Promise<void> {
    const files = await this.ensureExported();
    if (files) await this.bridge.sendMessage(openInScoreViewerMessage(files.reference, files.target));
  }

  private async ensureExported(): Promise<Extract<Exported, { ok: true }> | undefined> {
    if (this.exported) return this.exported;
    const diffId = this.diff?.diffId;
    if (!diffId) return undefined;
    this.ui.showBusy(true);
    try {
      const result = readExported(await this.bridge.callTool("export_diff_scores", { diff_id: diffId }));
      if (!result.ok) {
        this.ui.showNotice(NOTICES.exportFailed(result.code));
        return undefined;
      }
      this.exported = result;
      this.ui.showExported([fileName(result.reference), fileName(result.target)]);
      return result;
    } catch {
      this.ui.showNotice(NOTICES.exportFailed("UNKNOWN_ERROR"));
      return undefined;
    } finally {
      this.ui.showBusy(false);
    }
  }

  private async onToolResult(result: ToolResult): Promise<void> {
    if (result.isError) {
      this.ui.showNotice(NOTICES.compareFailed(errorEnvelope(result)?.code ?? "UNKNOWN_ERROR"));
      return;
    }
    const read = readDiff(result.structuredContent);
    if (!read.ok) {
      this.ui.showNotice(NOTICES.notAComparison);
      return;
    }
    const { diff } = read;
    this.diff = diff;
    this.exported = undefined;
    this.selected.clear();
    this.current = undefined;
    this.ui.showExported(undefined);
    this.ui.allowExport(diff.diffId !== undefined);
    this.ui.showHeadline(summaryLine(diff.similarity, diff.changes?.length));
    this.ui.showReport(diff.report);
    if (diff.changes) this.refreshList();
    this.ui.showNotice(this.noticeFor(diff));
    if (diff.diffId) await this.loadScores(diff.diffId);
  }

  private noticeFor(diff: Diff): string | undefined {
    if (!diff.changes) return NOTICES.noChanges;
    if (diff.changes.length === 0) return NOTICES.identical;
    return diff.diffId ? undefined : NOTICES.noScores;
  }

  private async loadScores(diffId: string): Promise<void> {
    try {
      const scores = readScores(await this.bridge.callTool("get_diff_scores", { diff_id: diffId }));
      if (!scores.ok) {
        this.ui.showNotice(NOTICES.scoresFailed(scores.code));
        return;
      }
      await this.panes.load(scores.reference, scores.target, scores.legend);
    } catch {
      this.ui.showNotice(NOTICES.engineBlocked);
    }
  }

  private refreshList(): void {
    const changes = this.diff?.changes ?? [];
    this.shown = visibleChanges(changes, this.selected);
    if (this.current && !this.shown.includes(this.current)) this.current = undefined;
    this.ui.showList(this.shown, kindsPresent(changes), this.selected);
    this.announce();
  }

  private announce(): void {
    const index = this.current ? this.shown.indexOf(this.current) : -1;
    if (this.current && index >= 0) {
      this.ui.showSelection(index, selectionSummary(this.current, index, this.shown.length));
    } else {
      this.ui.showSelection(undefined, "");
    }
  }

  private enqueue(task: () => Promise<void>): void {
    this.work = this.work.then(task).catch(() => {});
  }
}
