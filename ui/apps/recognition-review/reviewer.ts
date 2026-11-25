// Recognition Review behavior. Depends only on the HostBridge, a ReviewUi and a ScorePane, so it
// runs unchanged against FakeBridge in unit tests and against the real host.

import type { HostBridge, HostContext, ToolResult } from "@sheet-music-mcp/ui-kit/host/HostBridge";
import { errorEnvelope } from "@sheet-music-mcp/ui-kit/host/toolErrors";
import { otherEngine, staffAdvice } from "./advice.ts";
import { selectionSummary, toIssues, type Issue } from "./issues.ts";
import { ACCEPT_MESSAGE, acceptContext, rerunStatus } from "./messages.ts";
import { loadPreview, PreviewError } from "./preview.ts";
import { headline, pageNote, readReview, type Review } from "./review.ts";

export interface ReviewUi {
  showHeadline(text: string | undefined): void;
  /** Every standing notice, in order; an empty list clears them. */
  showNotices(texts: string[]): void;
  showAdvice(text: string | undefined): void;
  showIssues(issues: Issue[]): void;
  /** `index` is the position in the shown list, undefined when nothing is selected. */
  showSelection(index: number | undefined, spoken: string): void;
  /** A data URL, or undefined when there is no photo. */
  showPhoto(url: string | undefined): void;
  /** The polite live region for a re-run. */
  showStatus(text: string): void;
  showBusy(busy: boolean): void;
  /** The engine shown, and the one the re-run button would switch to. */
  showEngine(engine: string, other: string): void;
  allow(actions: { rerun: boolean; accept: boolean }): void;
  showAccepted(): void;
  applyHostContext(context: HostContext): void;
}

/** The recognized score's pane; the DOM implementation uses Verovio. */
export interface ScorePane {
  /** Rejects when the notation engine cannot start or the score cannot be read. */
  load(musicxml: string): Promise<void>;
  /** Marks the printed bar and scrolls it into view. */
  showMeasure(measure: number): void;
}

export const NOTICES = {
  failed: (code: string) => `The recognition failed (${code}).`,
  notARecognition: "This tool result is not a recognition result.",
  noReview:
    "This result has no review data, so the photo and the score are not shown. The issue list is still complete.",
  scoreFailed: (code: string) => `The recognized score could not be loaded (${code}).`,
  photoFailed: (code: string) => `The photo of the page could not be loaded (${code}).`,
  engineBlocked:
    "The viewer could not start the notation engine in this host (WebAssembly may be blocked). " +
    "The issue list and the photo still work.",
  noRequest: "The host did not pass the original request, so the page cannot recognize again.",
  acceptFailed: "Accepting did not reach the host. Try again.",
};

type Input = Record<string, unknown>;

export class RecognitionReview {
  private input: Input | undefined;
  private review: Review | undefined;
  private issues: Issue[] = [];
  private accepted = false;
  private generation = 0;
  private running: Promise<void> | undefined;
  private work: Promise<void> = Promise.resolve();

  constructor(
    private readonly bridge: HostBridge,
    private readonly ui: ReviewUi,
    private readonly pane: ScorePane,
  ) {}

  async start(): Promise<void> {
    this.bridge.onToolInput((input) => (this.input = input.arguments));
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

  /** Selects the issue at `index` of the list and shows its bar. */
  select(index: number): void {
    const issue = this.issues[index];
    if (!issue) return;
    this.ui.showSelection(index, selectionSummary(issue, index, this.issues.length));
    if (issue.measure !== undefined) this.pane.showMeasure(issue.measure);
  }

  /** Recognizes the same request again with the other engine. One run at a time. */
  rerun(): Promise<void> {
    this.running ??= this.runAgain().finally(() => (this.running = undefined));
    return this.running;
  }

  async accept(): Promise<void> {
    if (!this.review || this.accepted) return;
    this.accepted = true;
    try {
      await this.bridge.sendMessage(ACCEPT_MESSAGE);
    } catch {
      this.accepted = false;
      this.ui.showStatus(NOTICES.acceptFailed);
      return;
    }
    this.ui.showAccepted();
    try {
      await this.bridge.updateModelContext(
        acceptContext({
          engine: this.review.engine,
          parts: this.review.parts,
          measures: this.review.measures,
          openIssues: this.issues.length,
        }),
      );
    } catch {
      // Optional: the message already carries the user's decision.
    }
  }

  private async runAgain(): Promise<void> {
    const current = this.review;
    if (!current) return;
    if (!this.input || !hasRequest(this.input)) {
      this.ui.showStatus(NOTICES.noRequest);
      return;
    }
    const engine = otherEngine(current.engine);
    const tool = Array.isArray(this.input.images) ? "recognize_sheets" : "recognize_sheet";
    this.ui.showBusy(true);
    this.ui.showStatus(rerunStatus.running(engine));
    try {
      const result = await this.bridge.callTool(tool, { ...this.input, engine });
      const read = result.isError ? undefined : readReview(result.structuredContent);
      if (!read) {
        const code = errorEnvelope(result)?.code ?? "UNEXPECTED_RESULT";
        this.ui.showStatus(rerunStatus.failed(engine, code));
        return;
      }
      await this.display(read);
      this.ui.showStatus(rerunStatus.done(engine, read.parts, this.issues.length));
    } catch {
      this.ui.showStatus(rerunStatus.failed(engine, "UNKNOWN_ERROR"));
    } finally {
      this.ui.showBusy(false);
    }
  }

  private async onToolResult(result: ToolResult): Promise<void> {
    if (result.isError) {
      this.ui.showNotices([NOTICES.failed(errorEnvelope(result)?.code ?? "UNKNOWN_ERROR")]);
      this.ui.allow({ rerun: false, accept: false });
      return;
    }
    const read = readReview(result.structuredContent);
    if (!read) {
      this.ui.showNotices([NOTICES.notARecognition]);
      return;
    }
    await this.display(read);
  }

  /** Replaces everything on the page with this result. */
  private async display(review: Review): Promise<void> {
    const generation = ++this.generation;
    this.review = review;
    this.accepted = false;
    this.issues = toIssues(review.warnings);
    this.ui.showHeadline(headline(review, this.issues.length));
    this.ui.showAdvice(staffAdvice({ estimate: review.estimate, detected: review.parts, engine: review.engine }));
    this.ui.showIssues(this.issues);
    this.ui.showSelection(undefined, "");
    this.ui.showEngine(review.engine, otherEngine(review.engine));
    this.ui.allow({ rerun: this.input !== undefined && hasRequest(this.input), accept: true });
    const notices: string[] = [];
    const note = pageNote(review.pages.length);
    if (note) notices.push(note);
    if (!review.jobId) {
      this.ui.showNotices([...notices, NOTICES.noReview]);
      this.ui.showPhoto(undefined);
      return;
    }
    this.ui.showNotices(notices);
    const jobId = review.jobId;
    const page = review.pages.find((p) => p.index === 1);
    const outcomes = await Promise.all([this.loadScore(jobId), page?.hasPreview ? this.loadPhoto(jobId, generation) : undefined]);
    if (generation !== this.generation) return;
    this.ui.showNotices([...notices, ...outcomes.filter((o): o is string => typeof o === "string")]);
  }

  /** A notice when the score cannot be shown, else undefined. */
  private async loadScore(jobId: string): Promise<string | undefined> {
    let musicxml: unknown;
    try {
      const result = await this.bridge.callTool("get_recognized_score", { job_id: jobId });
      const failure = errorEnvelope(result);
      if (failure) return NOTICES.scoreFailed(failure.code);
      musicxml = result.structuredContent?.musicxml;
    } catch {
      return NOTICES.scoreFailed("UNKNOWN_ERROR");
    }
    if (typeof musicxml !== "string" || musicxml === "") return NOTICES.scoreFailed("UNEXPECTED_RESULT");
    try {
      await this.pane.load(musicxml);
    } catch {
      return NOTICES.engineBlocked;
    }
    return undefined;
  }

  private async loadPhoto(jobId: string, generation: number): Promise<string | undefined> {
    this.ui.showPhoto(undefined);
    try {
      const url = await loadPreview(this.bridge, jobId, 1);
      if (generation === this.generation) this.ui.showPhoto(url);
      return undefined;
    } catch (error) {
      return NOTICES.photoFailed(error instanceof PreviewError ? error.code : "UNKNOWN_ERROR");
    }
  }

  private enqueue(task: () => Promise<void>): void {
    this.work = this.work.then(task).catch(() => {});
  }
}

const hasRequest = (input: Input): boolean => typeof input.image === "string" || Array.isArray(input.images);
