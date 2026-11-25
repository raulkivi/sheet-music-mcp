// The fixed text the page shows when the singer asks Claude for tips, and the handler that sends
// it. Only the page's own numbers go into the text: no score title, no lyrics, no server prose.

import type { HostBridge } from "@sheet-music-mcp/ui-kit/host/HostBridge";
import type { TipsContext, TipsHandler } from "./coach.ts";
import type { SummaryReport } from "./messages.ts";

/** A bar is called out when its mean deviation is at least this many cents off pitch. */
const FAR_CENTS = 25;
/** At most this many bars are called out. */
const FAR_BARS = 3;
/** The part name comes from the score, so it is cut short rather than dumped in. */
const MAX_PART_CHARS = 40;
const STATUS_COUNTS = ["on_pitch", "sharp", "flat", "uncertain", "no_signal"] as const;
const STATUS_WORDS = ["on pitch", "sharp", "flat", "not sure", "no signal"] as const;

// Repeat until stable: one pass over "<<b>b>" would leave a new tag behind.
const stripTags = (text: string): string => {
  let previous: string;
  let current = text;
  do {
    previous = current;
    current = current.replace(/<[^<>]*>/g, "");
  } while (current !== previous);
  return current;
};

const cleanPart = (name: string | undefined): string | undefined => {
  if (name === undefined) return undefined;
  const cleaned = stripTags(name)
    .replace(/[^\p{L}\p{N} .'-]/gu, "")
    .replace(/ +/g, " ")
    .trim()
    .slice(0, MAX_PART_CHARS)
    .trim();
  return cleaned === "" ? undefined : cleaned;
};

const countOf = (histogram: SummaryReport["histogram"] | undefined, status: string): number => {
  const value = histogram?.[status];
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? Math.floor(value) : 0;
};

/** The bars furthest from pitch: the worst three by deviation, named in bar order. */
function farBars(context: TipsContext): string | undefined {
  const bars = context.bars
    .filter((bar) => bar.avgCents !== null && Math.abs(bar.avgCents) >= FAR_CENTS)
    .sort((a, b) => Math.abs(b.avgCents ?? 0) - Math.abs(a.avgCents ?? 0) || a.measure - b.measure)
    .slice(0, FAR_BARS)
    .sort((a, b) => a.measure - b.measure);
  if (bars.length === 0) return undefined;
  const numbers = bars.map((bar) => bar.measure).join(", ");
  return bars.length === 1 ? `Furthest from pitch: bar ${numbers}.` : `Furthest from pitch: bars ${numbers}.`;
}

/** The sentences both texts share, in the order the singer would say them. */
function facts(report: SummaryReport, context: TipsContext, opening: string): string[] {
  const part = cleanPart(context.partName);
  const notes = STATUS_COUNTS.map((status, index) => `${countOf(report.histogram, status)} ${STATUS_WORDS[index]}`).join(", ");
  const sentences = [
    opening + (part ? ` for part ${part}` : "") + ".",
    `Bars covered: ${report.measuresCovered}.`,
    report.avgCents === null ? "No notes were graded." : `Average deviation: ${Math.round(report.avgCents)} cents.`,
    `Notes: ${notes}.`,
  ];
  if (report.timedOut) sentences.push("The session closed after sitting idle.");
  const far = farBars(context);
  if (far) sentences.push(far);
  return sentences;
}

/** The chat message sent when the singer presses "Ask Claude for tips". */
export function tipsMessage(report: SummaryReport, context: TipsContext): string {
  return [...facts(report, context, "My Practice Coach summary"), "Please give me short tips for improving my intonation."].join(" ");
}

/** What the model learns when a take ends; no chat message and no follow-up turn. */
export function stopContext(report: SummaryReport, context: TipsContext): string {
  return facts(report, context, "Practice Coach: the singer stopped listening").join(" ");
}

/** Tips over a host bridge: the ask goes to the chat, the stop goes to the model context. */
export class BridgeTips implements TipsHandler {
  constructor(private readonly bridge: Pick<HostBridge, "sendMessage" | "updateModelContext">) {}

  ask(report: SummaryReport, context: TipsContext): Promise<void> {
    return this.bridge.sendMessage(tipsMessage(report, context));
  }

  stopped(report: SummaryReport, context: TipsContext): Promise<void> {
    return this.bridge.updateModelContext(stopContext(report, context));
  }
}
