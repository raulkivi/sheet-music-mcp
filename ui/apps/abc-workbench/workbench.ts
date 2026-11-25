// ABC Workbench behavior. Depends only on the HostBridge and a WorkbenchUi, so it runs unchanged
// against FakeBridge in unit tests and against the real host. The UI receives one plain
// WorkbenchView per change; it decides nothing.

import type { HostBridge, HostContext, ToolInput, ToolResult } from "@sheet-music-mcp/ui-kit/host/HostBridge";
import { errorEnvelope } from "@sheet-music-mcp/ui-kit/host/toolErrors";
import {
  acceptContext,
  readConversion,
  readProposal,
  readStoredAbc,
  rejectContext,
  reviseMessage,
  type Conversion,
} from "./messages.ts";
import {
  acceptedIds,
  mergedText,
  newReview,
  rejectedHunks,
  reviewRows,
  selectAll,
  selectNone,
  toggleHunk,
  withProposed,
  type Layout,
  type Review,
  type Row,
} from "./review.ts";
import { LiveValidator, type ValidationState } from "./validation.ts";

export type Mode = "review" | "edit";

export interface Outcome {
  status: "idle" | "working" | "accepted" | "failed" | "rejected";
  text: string;
  /** Path of the MusicXML file the server wrote. */
  file?: string;
}

export interface WorkbenchView {
  mode: Mode;
  layout: Layout;
  subtitle: string;
  rows: Row[];
  /** Why there are no rows, when there are none. */
  empty?: string;
  summary: string;
  validation: ValidationState;
  warnings: string[];
  notice?: string;
  /** `text` is set into the editor only when `revision` changes, so typing is never overwritten. */
  editor: { text: string; revision: number; errorLines: number[] };
  canAccept: boolean;
  canReject: boolean;
  canRevise: boolean;
  outcome: Outcome;
  /** True when the converted MusicXML came inline and can be saved. */
  download: boolean;
}

export interface WorkbenchUi {
  render(view: WorkbenchView): void;
  applyHostContext(context: HostContext): void;
  download(filename: string, content: string, mime: string): void;
}

export const NOTICES = {
  noOriginal:
    "The original ABC from musicxml_to_abc is no longer available, so every line of the proposal shows as new. " +
    "Run musicxml_to_abc again to compare.",
  toolFailed: (code: string) => `The tool call failed (${code}).`,
};

const EMPTY_TEXT = "The assistant has not proposed a change yet. Choose Edit to change the ABC yourself.";
const NO_CHANGES_TEXT = "The proposal matches the original: there is nothing to review.";
const WAITING_TEXT = "Waiting for the assistant's ABC.";

const IDLE: Outcome = { status: "idle", text: "" };

type Source = "none" | "proposal" | "export";

export class Workbench {
  private review: Review = newReview("", "");
  private source: Source = "none";
  private mode: Mode = "review";
  private layout: Layout = "changes";
  private validation: ValidationState = { status: "idle" };
  /** Warnings of the export, of the model's conversion and of the user's own conversion. */
  private warningSets: { export: string[]; model: string[]; accepted: string[] } = { export: [], model: [], accepted: [] };
  private notice: string | undefined;
  private outcome: Outcome = IDLE;
  private converted: Extract<Conversion, { kind: "inline" }> | undefined;
  private editorRevision = 0;
  private work: Promise<void> = Promise.resolve();
  private readonly validator: LiveValidator;

  constructor(
    private readonly bridge: HostBridge,
    private readonly ui: WorkbenchUi,
  ) {
    this.validator = new LiveValidator(
      (abc) => bridge.callTool("validate_abc", { abc }),
      (state) => {
        this.validation = state;
        this.paint();
      },
    );
  }

  async start(): Promise<void> {
    this.bridge.onToolInput((input) => this.onToolInput(input));
    this.bridge.onToolResult((result) => this.onToolResult(result));
    this.bridge.onHostContext((context) => this.ui.applyHostContext(context));
    this.ui.applyHostContext(await this.bridge.connect());
    this.paint();
  }

  /** Resolves when queued host calls have finished, including work they queued. */
  async idle(): Promise<void> {
    let settled: Promise<void>;
    do {
      settled = this.work;
      await settled;
    } while (settled !== this.work);
  }

  setMode(mode: Mode): void {
    if (mode === this.mode) return;
    this.mode = mode;
    if (mode === "edit") this.editorRevision++;
    this.revalidate();
    this.paint();
  }

  setLayout(layout: Layout): void {
    this.layout = layout;
    this.paint();
  }

  /** The user typed in the editor. */
  edit(text: string): void {
    this.review = withProposed(this.review, text);
    this.outcome = IDLE;
    this.revalidate();
    this.paint();
  }

  toggleHunk(id: number): void {
    this.review = toggleHunk(this.review, id);
    this.afterSelection();
  }

  async acceptSelected(): Promise<void> {
    await this.accept();
  }

  async acceptAll(): Promise<void> {
    if (this.outcome.status === "working") return;
    this.review = selectAll(this.review);
    this.revalidate();
    await this.accept();
  }

  async rejectAll(): Promise<void> {
    if (this.outcome.status === "working" || this.review.hunks.length === 0) return;
    this.review = selectNone(this.review);
    this.outcome = { status: "rejected", text: "Rejected: the original score stays as it is." };
    this.converted = undefined;
    this.revalidate();
    this.paint();
    const total = this.review.hunks.length;
    this.enqueue(() => this.bridge.updateModelContext(rejectContext(total)));
    await this.idle();
  }

  async revise(): Promise<void> {
    if (this.review.hunks.length === 0) return;
    const text = reviseMessage(rejectedHunks(this.review), this.review.hunks.length);
    this.enqueue(() => this.bridge.sendMessage(text));
    await this.idle();
  }

  downloadResult(): void {
    if (this.converted) this.ui.download("from-abc.musicxml", this.converted.musicxml, "application/xml");
  }

  private async accept(): Promise<void> {
    if (!this.view().canAccept) return;
    const abc = mergedText(this.review);
    const kept = acceptedIds(this.review).size;
    const total = this.review.hunks.length;
    this.outcome = { status: "working", text: "Converting to MusicXML…" };
    this.converted = undefined;
    this.paint();
    const conversion = await this.convert(abc);
    if (conversion.kind === "error") {
      this.outcome = { status: "failed", text: `Conversion failed (${conversion.code}). ${conversion.message}`.trim() };
      return this.paint();
    }
    this.warningSets.accepted = conversion.warnings;
    if (conversion.kind === "file") {
      this.outcome = { status: "accepted", text: `Accepted ${kept} of ${total}: MusicXML saved.`, file: conversion.path };
    } else {
      this.converted = conversion;
      this.outcome = { status: "accepted", text: `Accepted ${kept} of ${total}: MusicXML ready.` };
    }
    this.paint();
    const path = conversion.kind === "file" ? conversion.path : undefined;
    const context = acceptContext(path === undefined ? { accepted: kept, total } : { accepted: kept, total, path });
    this.enqueue(() => this.bridge.updateModelContext(context));
    await this.idle();
  }

  private async convert(abc: string): Promise<Conversion> {
    try {
      return readConversion(await this.bridge.callTool("abc_to_musicxml", { abc, return: "auto" }));
    } catch {
      return { kind: "error", code: "UNREACHABLE", message: "The host could not run the conversion." };
    }
  }

  private onToolInput(input: ToolInput): void {
    const proposal = readProposal(input.arguments);
    if (proposal === undefined) return;
    this.enqueue(() => this.openProposal(proposal));
  }

  private onToolResult(result: ToolResult): void {
    const failure = errorEnvelope(result);
    if (failure) {
      this.notice = NOTICES.toolFailed(failure.code);
      return this.paint();
    }
    const exported = readStoredAbc(result);
    if (exported) return this.openExport(exported.abc, exported.warnings);
    const warnings = result.structuredContent?.warnings;
    if (Array.isArray(warnings)) this.warningSets.model = warnings.filter((w): w is string => typeof w === "string");
    this.paint();
  }

  private openExport(abc: string, warnings: string[]): void {
    this.source = "export";
    this.review = newReview(abc, abc);
    this.warningSets = { export: warnings, model: [], accepted: [] };
    this.reopened();
  }

  private async openProposal(proposal: string): Promise<void> {
    let original = "";
    this.notice = undefined;
    try {
      const fetched = readStoredAbc(await this.bridge.callTool("get_abc", {}));
      if (fetched) original = fetched.abc;
      else this.notice = NOTICES.noOriginal;
      this.warningSets.export = fetched?.warnings ?? [];
    } catch {
      this.notice = NOTICES.noOriginal;
    }
    this.source = "proposal";
    this.review = newReview(original, proposal);
    this.reopened();
  }

  private reopened(): void {
    this.outcome = IDLE;
    this.converted = undefined;
    this.warningSets.accepted = [];
    this.editorRevision++;
    this.revalidate();
    this.paint();
  }

  private afterSelection(): void {
    this.outcome = IDLE;
    this.converted = undefined;
    this.revalidate();
    this.paint();
  }

  /** The text that will be written when the user accepts, or the text being typed in the editor. */
  private target(): string {
    return this.mode === "edit" ? this.review.proposed : mergedText(this.review);
  }

  private revalidate(): void {
    if (this.source === "none") return;
    this.validator.input(this.target());
  }

  private enqueue(task: () => Promise<void>): void {
    this.work = this.work.then(task).catch(() => {});
  }

  private paint(): void {
    this.ui.render(this.view());
  }

  private view(): WorkbenchView {
    const { review, validation } = this;
    const total = review.hunks.length;
    const kept = acceptedIds(review).size;
    const working = this.outcome.status === "working";
    const rows = reviewRows(review, this.layout);
    const view: WorkbenchView = {
      mode: this.mode,
      layout: this.layout,
      subtitle: this.subtitle(),
      rows,
      summary: total === 0 ? "No changes" : `${total} ${total === 1 ? "change" : "changes"}, ${kept} kept`,
      validation,
      warnings: [...new Set([...this.warningSets.export, ...this.warningSets.model, ...this.warningSets.accepted])],
      editor: {
        text: review.proposed,
        revision: this.editorRevision,
        errorLines: this.mode === "edit" && validation.status === "invalid" ? lineNumbers(validation) : [],
      },
      canAccept: total > 0 && !working && validation.status !== "invalid",
      canReject: total > 0 && !working,
      canRevise: total > 0,
      outcome: this.outcome,
      download: this.converted !== undefined,
    };
    if (this.notice) view.notice = this.notice;
    if (total === 0) view.empty = this.source === "none" ? WAITING_TEXT : this.source === "export" && review.proposed === review.original ? EMPTY_TEXT : NO_CHANGES_TEXT;
    return view;
  }

  private subtitle(): string {
    if (this.source === "proposal") return "Proposed edit by the assistant";
    if (this.source === "export") return "ABC exported from MusicXML";
    return "";
  }
}

function lineNumbers(state: ValidationState): number[] {
  if (state.status !== "invalid") return [];
  return [...new Set(state.problems.flatMap((p) => (p.line === undefined ? [] : [p.line])))];
}
