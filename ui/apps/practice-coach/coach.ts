// Practice Coach behavior. Depends only on the HostBridge and three ports (the DOM, the score
// stage and the poller), so it runs unchanged against FakeBridge in unit tests and in a host.
//
// Flow: the opening tool (start_practice, usually) gives the session; the page fetches the score
// (get_score_for_session, app-only), asks list_sessions whether the microphone is already on,
// polls get_current_position while listening, and on Stop calls stop_monitoring for the report.
// Microphone: the server's (decision DA7); the browser's microphone is a later step (T1.6).

import type { HostBridge, HostContext, ToolInput, ToolResult } from "@sheet-music-mcp/ui-kit/host/HostBridge";
import { HistoryBuffer, type BarSummary, type Sample } from "./history.ts";
import { centsToNeedle } from "./meter.ts";
import {
  NOTICES,
  practiceAgainArgs,
  readPosition,
  readScoreXml,
  readSession,
  readSessionState,
  readSummary,
  type SessionInfo,
  type SummaryReport,
} from "./messages.ts";
import { readingText, statusView, type StatusView } from "./status.ts";

export type Mode = "empty" | "ready" | "listening" | "stopping" | "report";

/** What the meter and the status line show for one polled position. */
export interface Reading {
  status: StatusView;
  /** The server's status word, for styling hooks and tests. */
  statusCode: string;
  /** What a screen reader reads: "+12 cents, sharp". */
  text: string;
  cents: number | null;
  hz: number | null;
  expectedNote: string;
  measure: number;
  beat: number;
  /** Needle position 0 to 100, or null when the frame was not graded. */
  needle: number | null;
}

export interface ReportView {
  report: SummaryReport;
  bars: BarSummary[];
  canPracticeAgain: boolean;
  canAskForTips: boolean;
}

export interface CoachUi {
  applyHostContext(context: HostContext): void;
  showMode(mode: Mode): void;
  /** Text under the toolbar; undefined hides it. */
  showNotice(text: string | undefined): void;
  showSession(session: SessionInfo | undefined): void;
  showReading(reading: Reading): void;
  showHistory(bars: BarSummary[]): void;
  showReport(view: ReportView): void;
}

export interface CoachScore {
  /** Draws the score; rejects if it cannot be shown. */
  load(xml: string): Promise<void>;
  showCursor(measure: number, beat: number): void;
  hideCursor(): void;
}

export interface Poller {
  start(): void;
  stop(): void;
  onVisibilityChange(): void;
}

export type PollerFactory = (request: () => Promise<void>) => Poller;

/** What the page knows at the moment the take ended: the part, and what each bar looked like. */
export interface TipsContext {
  partName?: string;
  bars: BarSummary[];
}

/** Seam for T1.5 ("Ask Claude for tips"): a handler sends the fixed-template messages. */
export interface TipsHandler {
  /** Sends the tips request to the chat. */
  ask(report: SummaryReport, context: TipsContext): Promise<void>;
  /** Tells the model what the take ended with; no chat message. Optional. */
  stopped?(report: SummaryReport, context: TipsContext): Promise<void>;
}

export interface CoachOptions {
  tips?: TipsHandler;
}

const LAST_BARS = 3;
/** This many failed polls in a row show the "lost contact" notice. */
const FAILURES_BEFORE_NOTICE = 3;

export class PracticeCoach {
  private input: Record<string, unknown> = {};
  private session: SessionInfo | undefined;
  private poller: Poller | undefined;
  private readonly history = new HistoryBuffer();
  private failures = 0;
  private lostNoticeShown = false;
  private stopping = false;
  private lastReport: SummaryReport | undefined;
  private lastContext: TipsContext | undefined;
  private tipsInFlight = false;
  private work: Promise<void> = Promise.resolve();

  constructor(
    private readonly bridge: HostBridge,
    private readonly ui: CoachUi,
    private readonly score: CoachScore,
    private readonly createPoller: PollerFactory,
    private readonly options: CoachOptions = {},
  ) {}

  async start(): Promise<void> {
    this.bridge.onToolInput((input) => this.onToolInput(input));
    this.bridge.onToolResult((result) => this.enqueue(() => this.onToolResult(result)));
    this.bridge.onHostContext((context) => this.ui.applyHostContext(context));
    this.ui.applyHostContext(await this.bridge.connect());
  }

  /** Resolves when queued opening and stopping work has finished, including work it queued. */
  async idle(): Promise<void> {
    let settled: Promise<void>;
    do {
      settled = this.work;
      await settled;
    } while (settled !== this.work);
  }

  onVisibilityChange(): void {
    this.poller?.onVisibilityChange();
  }

  async startListening(): Promise<void> {
    const session = this.session;
    if (!session) return;
    const result = await this.call("start_monitoring", { session_id: session.sessionId });
    if (result.isError) {
      const code = errorCode(result);
      this.ui.showNotice(NOTICES.startFailed(code));
      this.ui.showMode("ready");
      return;
    }
    this.ui.showNotice(undefined);
    this.beginListening();
  }

  async stop(): Promise<void> {
    const session = this.session;
    if (!session || this.stopping) return;
    this.stopping = true;
    this.poller?.stop();
    this.ui.showMode("stopping");
    this.score.hideCursor();
    try {
      const summary = readSummary(await this.call("stop_monitoring", { session_id: session.sessionId }));
      if (summary.kind === "summary") {
        // The part name comes from the session, which is dropped as soon as the take is over.
        const context: TipsContext = { partName: session.partName, bars: this.history.byMeasure() };
        this.session = undefined;
        this.ui.showReport({
          report: summary.report,
          bars: context.bars,
          canPracticeAgain: practiceAgainArgs(this.input) !== undefined,
          canAskForTips: this.options.tips !== undefined,
        });
        this.lastReport = summary.report;
        this.lastContext = context;
        this.ui.showMode("report");
        try {
          await this.options.tips?.stopped?.(summary.report, context);
        } catch {
          // The report is what the singer came for; a silent handler failure never takes it away.
        }
      } else {
        this.ui.showNotice(NOTICES.stopFailed(summary.kind === "error" ? summary.code : "UNREADABLE"));
        this.ui.showMode("empty");
      }
    } finally {
      this.stopping = false;
    }
  }

  async practiceAgain(): Promise<void> {
    const args = practiceAgainArgs(this.input);
    if (!args) return;
    this.ui.showNotice(undefined);
    await this.adopt(args, await this.call("start_practice", args));
  }

  async askForTips(): Promise<void> {
    const tips = this.options.tips;
    if (!tips || !this.lastReport || this.tipsInFlight) return;
    this.tipsInFlight = true;
    try {
      await tips.ask(this.lastReport, this.lastContext ?? { bars: [] });
      this.ui.showNotice(NOTICES.tipsSent);
    } catch {
      this.ui.showNotice(NOTICES.tipsFailed);
    } finally {
      this.tipsInFlight = false;
    }
  }

  private onToolInput(input: ToolInput): void {
    this.input = input.arguments;
  }

  private async onToolResult(result: ToolResult): Promise<void> {
    await this.adopt(this.input, result);
  }

  /** Takes the result of the tool that opens a session and brings the page to match it. */
  private async adopt(args: Record<string, unknown>, result: ToolResult): Promise<void> {
    const read = readSession(args, result);
    if (read.kind !== "session") {
      this.ui.showMode("empty");
      this.ui.showNotice(read.kind === "error" ? read.message : NOTICES.noSession);
      return;
    }
    this.poller?.stop();
    this.history.clear();
    this.failures = 0;
    this.lostNoticeShown = false;
    this.lastReport = undefined;
    this.lastContext = undefined;
    this.session = read.session;
    this.ui.showNotice(undefined);
    this.ui.showSession(read.session);
    this.ui.showHistory([]);
    const drawn = this.drawScore(read.session.sessionId);
    const listing = await this.call("list_sessions", {});
    if (readSessionState(listing, read.session.sessionId) === "monitoring") this.beginListening();
    else this.ui.showMode("ready");
    await drawn;
  }

  private async drawScore(sessionId: string): Promise<void> {
    const xml = readScoreXml(await this.call("get_score_for_session", { session_id: sessionId }));
    if (xml === undefined) return void this.ui.showNotice(NOTICES.scoreFailed);
    try {
      await this.score.load(xml);
    } catch {
      this.ui.showNotice(NOTICES.scoreEngine);
    }
  }

  private beginListening(): void {
    this.ui.showMode("listening");
    this.poller ??= this.createPoller(() => this.poll());
    this.poller.start();
  }

  /** One poll: a failure is counted, never thrown, so the scheduler keeps its rhythm. */
  private async poll(): Promise<void> {
    const session = this.session;
    if (!session) return;
    const read = readPosition(await this.call("get_current_position", { session_id: session.sessionId }));
    if (read.kind === "error" && read.code === "SESSION_NOT_FOUND") {
      this.poller?.stop();
      this.enqueue(async () => {
        await this.stop();
        this.ui.showNotice(NOTICES.sessionClosed);
      });
      return;
    }
    if (read.kind !== "position") return this.pollFailed();
    this.pollSucceeded();
    this.show(read.position);
  }

  private pollFailed(): void {
    if (++this.failures >= FAILURES_BEFORE_NOTICE && !this.lostNoticeShown) {
      this.lostNoticeShown = true;
      this.ui.showNotice(NOTICES.serverLost);
    }
  }

  private pollSucceeded(): void {
    this.failures = 0;
    if (this.lostNoticeShown) {
      this.lostNoticeShown = false;
      this.ui.showNotice(undefined);
    }
  }

  private show(position: Sample & { sung_pitch_hz: number | null }): void {
    this.history.push(position);
    const status = statusView(position.status, position.accuracy_cents);
    this.ui.showReading({
      status,
      statusCode: position.status,
      text: readingText(position.status, position.accuracy_cents),
      cents: position.accuracy_cents,
      hz: position.sung_pitch_hz,
      expectedNote: position.expected_note,
      measure: position.measure,
      beat: position.beat,
      needle: status.graded ? centsToNeedle(position.accuracy_cents) : null,
    });
    this.ui.showHistory(this.history.lastMeasures(LAST_BARS));
    this.score.showCursor(position.measure, position.beat);
  }

  /** A tool call that never throws: a host failure is a FAILED result. */
  private async call(name: string, args: Record<string, unknown>): Promise<ToolResult> {
    try {
      return await this.bridge.callTool(name, args);
    } catch {
      return FAILED;
    }
  }

  private enqueue(task: () => Promise<void>): void {
    this.work = this.work.then(task).catch(() => {});
  }
}

/** Stands for a call the host could not carry out; reads as the error envelope with this code. */
const FAILED: ToolResult = {
  isError: true,
  content: [{ type: "text", text: JSON.stringify({ error: "The host could not run the tool.", error_code: "HOST_UNAVAILABLE" }) }],
};

function errorCode(result: ToolResult): string {
  try {
    const text = (result.content?.[0] as { text?: string } | undefined)?.text;
    const code = (JSON.parse(text ?? "{}") as { error_code?: unknown }).error_code;
    return typeof code === "string" ? code : "UNKNOWN_ERROR";
  } catch {
    return "UNKNOWN_ERROR";
  }
}
