// Server grading state to the words and color class the page shows. The states are pitch-mcp's
// aligner.STATUSES; a state added there shows as "Unknown" (neutral) until it gets a row here.
// An uncertain frame is never an error: it is neutral and carries no grade.

export type Tone = "ok" | "warn" | "danger" | "neutral" | "muted";

export interface StatusView {
  label: string;
  tone: Tone;
  /** True when the server graded the frame against the expected note. */
  graded: boolean;
}

/** Beyond this many cents a flat or sharp frame is a clear miss, not a near one. */
const DANGER_CENTS = 50;

export function statusView(status: string, cents: number | null): StatusView {
  switch (status) {
    case "on_pitch":
      return { label: "On pitch", tone: "ok", graded: true };
    case "sharp":
    case "flat": {
      const far = cents !== null && Math.abs(cents) > DANGER_CENTS;
      return { label: status === "sharp" ? "Sharp" : "Flat", tone: far ? "danger" : "warn", graded: true };
    }
    case "uncertain":
      return { label: "Not sure", tone: "neutral", graded: false };
    case "no_signal":
      return { label: "No sound", tone: "muted", graded: false };
    default:
      return { label: "Unknown", tone: "neutral", graded: false };
  }
}

/** The meter's text, which is what a screen reader reads: "+12 cents, sharp". */
export function readingText(status: string, cents: number | null): string {
  if (status === "uncertain") return "Not graded: the pitch was unclear";
  if (status === "no_signal") return "No sound heard";
  const word = status.replace(/_/g, " ");
  if (cents === null) return `${word}, no cents value`;
  const signed = cents > 0 ? `+${cents}` : `${cents}`;
  return `${signed} cents, ${word}`;
}
