// Live validation of the ABC: reads validate_abc's result and runs the debounce state machine.
// Pure TypeScript with injected timers and tool call, so it is unit-tested with fake timers.
// The page shows what the server says; nothing here decides that ABC is valid.

import type { ToolResult } from "@sheet-music-mcp/ui-kit/host/HostBridge";
import { errorEnvelope } from "@sheet-music-mcp/ui-kit/host/toolErrors";

/** Quiet time after the last keystroke before validate_abc is called (plan T2.7). */
export const DEBOUNCE_MS = 300;

export interface ValidationReport {
  valid: boolean;
  errors: string[];
  warnings: string[];
}

export interface Problem {
  /** 1-based line the message names, when it names one. */
  line?: number;
  message: string;
}

export type ValidationState =
  | { status: "idle" }
  | { status: "pending" }
  | { status: "valid" | "invalid"; errors: string[]; warnings: string[]; problems: Problem[] }
  | { status: "unavailable"; message: string };

const strings = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];

export function readValidation(result: ToolResult): ValidationReport | { unavailable: string } {
  const failure = errorEnvelope(result);
  if (failure) return { unavailable: failure.code };
  const data = result.structuredContent;
  if (!data || typeof data.valid !== "boolean") return { unavailable: "MALFORMED_RESULT" };
  return { valid: data.valid, errors: strings(data.errors), warnings: strings(data.warnings) };
}

const LINE = /\bline\s+(\d+)\b/i;

/** Each error message with the line it names ("Line 3: ..."), if any. */
export function problemsOf(errors: string[]): Problem[] {
  return errors.map((message) => {
    const line = Number(LINE.exec(message)?.[1]);
    return line > 0 ? { line, message } : { message };
  });
}

export interface Timers {
  setTimeout(handler: () => void, ms: number): unknown;
  clearTimeout(handle: unknown): void;
}

export class LiveValidator {
  private sequence = 0;
  private timer: unknown;
  private last: { text: string; state: ValidationState } | undefined;

  constructor(
    private readonly validate: (abc: string) => Promise<ToolResult>,
    private readonly onChange: (state: ValidationState) => void,
    private readonly delayMs: number = DEBOUNCE_MS,
    private readonly timers: Timers = globalThis as unknown as Timers,
  ) {}

  /** The text changed. Validation of any older text is abandoned. */
  input(text: string): void {
    const mine = ++this.sequence;
    this.timers.clearTimeout(this.timer);
    if (text.trim() === "") return this.onChange({ status: "idle" });
    if (this.last?.text === text) return this.onChange(this.last.state);
    this.onChange({ status: "pending" });
    this.timer = this.timers.setTimeout(() => void this.run(mine, text), this.delayMs);
  }

  private async run(mine: number, text: string): Promise<void> {
    const state = await this.check(text);
    if (mine !== this.sequence) return;
    this.last = { text, state };
    this.onChange(state);
  }

  private async check(text: string): Promise<ValidationState> {
    let result: ToolResult;
    try {
      result = await this.validate(text);
    } catch {
      return { status: "unavailable", message: "The validator could not be reached." };
    }
    const report = readValidation(result);
    if ("unavailable" in report) {
      return { status: "unavailable", message: `The validator is not available (${report.unavailable}).` };
    }
    return {
      status: report.valid ? "valid" : "invalid",
      errors: report.errors,
      warnings: report.warnings,
      problems: problemsOf(report.errors),
    };
  }
}
