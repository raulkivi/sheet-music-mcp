// Every text the page sends to the model or announces for a re-run. Anything sent to the model
// is a fixed template filled with counts and a vetted engine token: no MusicXML, path or
// warning text ever reaches a message. Pure.

import { engineLabel } from "./advice.ts";
import { issueSummary } from "./issues.ts";

/** The one `ui/message` of Accept. */
export const ACCEPT_MESSAGE =
  "I checked the recognized score in the Recognition Review and accept it. Please continue with that score.";

export interface AcceptState {
  engine: string;
  parts: number | undefined;
  measures: number | undefined;
  openIssues: number;
}

const count = (n: number, noun: string): string => `${n} ${noun}${n === 1 ? "" : "s"}`;
const safeEngine = (engine: string): string => (/^[a-z][a-z0-9_-]{0,31}$/.test(engine) ? engine : "unknown");

/** The optional `ui/update-model-context` after Accept. */
export function acceptContext(state: AcceptState): string {
  const facts = [
    state.parts === undefined ? undefined : count(state.parts, "part"),
    state.measures === undefined ? undefined : count(state.measures, "bar"),
    count(state.openIssues, "open issue"),
  ].filter(Boolean);
  return `Recognition Review: the user accepted the score recognized with ${safeEngine(state.engine)} (${facts.join(", ")}).`;
}

export const rerunStatus = {
  running: (engine: string) => `Recognizing again with ${engineLabel(engine)}. This can take a few minutes.`,
  done: (engine: string, parts: number | undefined, issues: number) =>
    `Recognized again with ${engineLabel(engine)}:${parts === undefined ? "" : ` ${count(parts, "part")}.`} ${issueSummary(issues)}`,
  failed: (engine: string, code: string) =>
    `Recognizing again with ${engineLabel(engine)} failed (${code}). The earlier result is still shown.`,
};
