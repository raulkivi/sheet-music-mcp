// DOM implementation of CoachUi: the chrome around the score (toolbar, meter, status, last bars,
// report). Knows the markup in index.html; no host code. Everything shown from the server is set
// with textContent, never innerHTML.

import type { HostContext } from "@sheet-music-mcp/ui-kit/host/HostBridge";
import { applyTheme } from "@sheet-music-mcp/ui-kit/theme";
import type { CoachUi, Mode, Reading, ReportView } from "./coach.ts";
import type { BarSummary } from "./history.ts";
import { METER_RANGE_CENTS, needleAt, shouldRefreshText } from "./meter.ts";
import type { SessionInfo } from "./messages.ts";
import { statusView, type Tone } from "./status.ts";

export interface Controls {
  startListening(): Promise<void>;
  stop(): Promise<void>;
  practiceAgain(): Promise<void>;
  askForTips(): Promise<void>;
  onVisibilityChange(): void;
}

/** The needle takes one poll interval to cover the gap between two samples. */
const SAMPLE_MS = 100;

const MODE_BADGE: Record<Mode, { text: string; tone: Tone }> = {
  empty: { text: "Not listening", tone: "neutral" },
  ready: { text: "Ready", tone: "neutral" },
  listening: { text: "Listening", tone: "ok" },
  stopping: { text: "Stopping", tone: "neutral" },
  report: { text: "Stopped", tone: "neutral" },
};

/** The order and wording of the report's histogram; an unlisted state follows, as "Unknown". */
const HISTOGRAM_ORDER = ["on_pitch", "sharp", "flat", "uncertain", "no_signal"];
const HISTOGRAM_LABELS: Record<string, string> = { uncertain: "Not sure (not graded)" };

export class DomUi implements CoachUi {
  private readonly el: Record<string, HTMLElement>;
  private lastText: { status: string; at: number } | undefined;
  private needle = { at: 50, visible: false };
  private frame = 0;

  constructor(
    private readonly doc: Document,
    private readonly reducedMotion: () => boolean = () => matchMedia("(prefers-reduced-motion: reduce)").matches,
    private readonly now: () => number = () => performance.now(),
  ) {
    const ids = [
      "session-label", "listen-badge", "start", "stop", "notice", "empty", "live", "meter-panel",
      "status", "note", "hz", "cents-text", "meter", "needle", "last-bars", "where", "report", "report-title",
      "report-avg", "report-timeout", "heat", "histogram", "highlights", "again", "tips",
    ];
    this.el = {};
    for (const id of ids) {
      const found = doc.getElementById(id);
      if (!found) throw new Error(`index.html is missing #${id}`);
      this.el[id] = found;
    }
  }

  bind(controls: Controls): void {
    const on = (id: string, action: () => Promise<void>) => {
      const button = this.el[id] as HTMLButtonElement;
      button.addEventListener("click", () => {
        void action();
      });
    };
    on("start", () => controls.startListening());
    on("stop", () => controls.stop());
    on("again", () => controls.practiceAgain());
    on("tips", () => controls.askForTips());
    this.doc.addEventListener("visibilitychange", () => controls.onVisibilityChange());
  }

  applyHostContext(context: HostContext): void {
    applyTheme(this.doc.documentElement, context);
  }

  showMode(mode: Mode): void {
    const { el } = this;
    const focused = this.doc.activeElement;
    el.empty!.hidden = mode !== "empty";
    el.live!.hidden = mode === "empty";
    el["meter-panel"]!.hidden = mode === "report";
    el.report!.hidden = mode !== "report";
    (el.start as HTMLButtonElement).disabled = mode !== "ready";
    (el.stop as HTMLButtonElement).disabled = mode !== "ready" && mode !== "listening";
    const badge = MODE_BADGE[mode];
    el["listen-badge"]!.textContent = badge.text;
    el["listen-badge"]!.className = `pill tone-${badge.tone}`;
    if (mode !== "listening") this.setNeedle(null);
    if (mode === "listening") this.resetReading();
    // A disabled button drops keyboard focus to the body; hand it on to where the user goes next.
    if (mode === "listening" && focused === el.start) el.stop!.focus();
    if (mode === "report" && (focused === el.stop || focused === this.doc.body)) el["report-title"]!.focus();
  }

  showNotice(text: string | undefined): void {
    this.el.notice!.textContent = text ?? "";
    this.el.notice!.hidden = text === undefined;
  }

  showSession(session: SessionInfo | undefined): void {
    const parts = [session?.partName, session?.measureCount === undefined ? undefined : `${session.measureCount} bars`, session?.tempoBpm === undefined ? undefined : `${Math.round(session.tempoBpm)} bpm`];
    this.el["session-label"]!.textContent = parts.filter(Boolean).join(" · ");
  }

  showReading(reading: Reading): void {
    const { el } = this;
    const at = this.now();
    el.where!.textContent = `Bar ${reading.measure} · beat ${reading.beat} · expected ${reading.expectedNote}`;
    el.where!.dataset.measure = String(reading.measure);
    el.where!.dataset.beat = String(reading.beat);
    el.note!.textContent = reading.expectedNote || "–";
    el.hz!.textContent = reading.hz === null ? "" : `${reading.hz.toFixed(1)} Hz`;
    el.status!.textContent = reading.status.label;
    el.status!.className = `pill tone-${reading.status.tone}`;
    el.status!.dataset.status = reading.statusCode;
    el.meter!.dataset.tone = reading.status.tone;
    el.meter!.dataset.status = reading.statusCode;
    const cents = reading.cents === null ? 0 : Math.max(-METER_RANGE_CENTS, Math.min(METER_RANGE_CENTS, Math.round(reading.cents)));
    el.meter!.setAttribute("aria-valuenow", String(cents));
    // Spoken and read text change with the status, else once a second (no chatter at 10 Hz).
    if (shouldRefreshText(this.lastText, reading.statusCode, at)) {
      this.lastText = { status: reading.statusCode, at };
      el["cents-text"]!.textContent = reading.text;
      el.meter!.setAttribute("aria-valuetext", reading.text);
    }
    this.setNeedle(reading.needle);
  }

  showHistory(bars: BarSummary[]): void {
    const list = this.el["last-bars"]!;
    list.replaceChildren(
      ...bars.map((bar) => {
        const view = statusView(bar.status, bar.avgCents);
        const item = this.doc.createElement("li");
        const name = this.doc.createElement("span");
        name.textContent = `Bar ${bar.measure}`;
        item.append(name, this.pill(view.label, view.tone));
        return item;
      }),
    );
  }

  showReport(view: ReportView): void {
    const { el } = this;
    const { report } = view;
    el["report-avg"]!.textContent =
      report.avgCents === null ? "Nothing was graded in this take." : `Average deviation: ${report.avgCents} cents, over ${report.measuresCovered} bars.`;
    el["report-timeout"]!.hidden = !report.timedOut;
    el["report-timeout"]!.textContent = "The session closed after sitting idle; this is the summary kept then.";
    el.heat!.replaceChildren(
      ...view.bars.map((bar) => {
        const status = statusView(bar.status, bar.avgCents);
        const cell = this.doc.createElement("li");
        cell.className = `tone-${status.tone}`;
        const name = this.doc.createElement("span");
        name.textContent = `Bar ${bar.measure}`;
        const word = this.doc.createElement("span");
        word.textContent = bar.avgCents === null ? status.label : `${status.label} (${bar.avgCents > 0 ? "+" : ""}${bar.avgCents})`;
        cell.append(name, word);
        return cell;
      }),
    );
    el.histogram!.replaceChildren(...this.histogramRows(report.histogram));
    el.highlights!.replaceChildren(
      ...(report.highlights.length === 0 ? ["No run of flat or sharp notes stood out."] : report.highlights).map((text) => {
        const item = this.doc.createElement("li");
        item.textContent = text;
        return item;
      }),
    );
    el.again!.hidden = !view.canPracticeAgain;
    el.tips!.hidden = !view.canAskForTips;
  }

  private histogramRows(histogram: Record<string, number>): HTMLElement[] {
    const states = [...HISTOGRAM_ORDER, ...Object.keys(histogram).filter((s) => !HISTOGRAM_ORDER.includes(s))];
    const total = Object.values(histogram).reduce((sum, n) => sum + n, 0);
    return states.map((state) => {
      const count = histogram[state] ?? 0;
      const row = this.doc.createElement("li");
      const label = this.doc.createElement("span");
      label.className = "label";
      label.textContent = HISTOGRAM_LABELS[state] ?? statusView(state, null).label;
      const track = this.doc.createElement("span");
      track.className = "track";
      track.setAttribute("aria-hidden", "true");
      const fill = this.doc.createElement("span");
      fill.className = "fill";
      fill.style.width = total === 0 ? "0%" : `${Math.round((count / total) * 100)}%`;
      track.append(fill);
      const number = this.doc.createElement("span");
      number.textContent = String(count);
      row.append(label, track, number);
      return row;
    });
  }

  private pill(text: string, tone: Tone): HTMLElement {
    const pill = this.doc.createElement("span");
    pill.className = `pill tone-${tone}`;
    pill.textContent = text;
    return pill;
  }

  /** A new take starts from a blank meter. */
  private resetReading(): void {
    this.lastText = undefined;
    this.el.status!.textContent = "No sound";
    this.el.status!.className = "pill tone-muted";
    this.el["cents-text"]!.textContent = "Waiting for you to sing";
    this.el.meter!.setAttribute("aria-valuetext", "Waiting for you to sing");
    this.el.meter!.setAttribute("aria-valuenow", "0");
    this.el.meter!.dataset.tone = "muted";
    this.el.hz!.textContent = "";
  }

  /** Moves the needle to `target` percent in a straight line over one sample interval; null hides it. */
  private setNeedle(target: number | null): void {
    const needle = this.el.needle!;
    cancelAnimationFrame(this.frame);
    if (target === null) {
      needle.hidden = true;
      this.needle = { at: this.needle.at, visible: false };
      return;
    }
    const from = this.needle.visible ? this.needle.at : target;
    const started = this.now();
    needle.hidden = false;
    const step = () => {
      const position = needleAt(from, target, this.now() - started, SAMPLE_MS, this.reducedMotion());
      needle.style.left = `${position}%`;
      this.needle = { at: position, visible: true };
      if (position !== target) this.frame = requestAnimationFrame(step);
    };
    step();
  }
}
