import { describe, expect, it } from "vitest";
import { FakeBridge, type FakeScript } from "@sheet-music-mcp/ui-kit/host/FakeBridge";
import type { HostContext, ToolResult } from "@sheet-music-mcp/ui-kit/host/HostBridge";
import type { Issue } from "./issues.ts";
import { ACCEPT_MESSAGE } from "./messages.ts";
import { NOTICES, RecognitionReview, type ReviewUi, type ScorePane } from "./reviewer.ts";

const PNG_B64 = btoa(String.fromCharCode(0x89, 0x50, 0x4e, 0x47, 1, 2));

const recognition = (over: Record<string, unknown> = {}): ToolResult => ({
  structuredContent: {
    job_id: "job-1",
    metadata: { engine: "oemer", staves_detected: 1, measures: 4, page_count: 1, staff_systems_estimate: 4 },
    pages: [{ index: 1, staves_detected: 1, measures: 4, has_preview: true }],
    warnings: [
      { code: "EMPTY_MEASURE", severity: "warning", message: "Measure 3 has no notes or rests", measure: 3, part: "P1" },
      {
        code: "PARTS_FEWER_THAN_STAVES",
        severity: "info",
        message: "1 part recognized but the page has 4 staves per system; voices may be merged",
      },
    ],
    ...over,
  },
});

const CLEAN = recognition({
  job_id: "job-2",
  metadata: { engine: "audiveris", staves_detected: 4, measures: 4, page_count: 1, staff_systems_estimate: 4 },
  warnings: [],
});

const failure = (code: string): ToolResult => ({
  isError: true,
  content: [{ type: "text", text: JSON.stringify({ error: "nope", error_code: code }) }],
});

const SCORE: ToolResult = { structuredContent: { job_id: "job-1", musicxml: "<score-partwise/>" } };
const PREVIEW: ToolResult = {
  structuredContent: { job_id: "job-1", page: 1, artifact_id: "a", offset: 0, length: 6, byte_length: 6, eof: true, data_b64: PNG_B64 },
};

class FakeUi implements ReviewUi {
  headline: string | undefined;
  notices: string[] = [];
  advice: string | undefined;
  issues: Issue[] = [];
  selection: { index: number | undefined; spoken: string } | undefined;
  photo: string | undefined;
  status = "";
  busy = false;
  engine: { engine: string; other: string } | undefined;
  actions: { rerun: boolean; accept: boolean } = { rerun: false, accept: false };
  accepted = false;
  context: HostContext | undefined;
  showHeadline(text: string | undefined) { this.headline = text; }
  showNotices(texts: string[]) { this.notices = texts; }
  showAdvice(text: string | undefined) { this.advice = text; }
  showIssues(issues: Issue[]) { this.issues = issues; }
  showSelection(index: number | undefined, spoken: string) { this.selection = { index, spoken }; }
  showPhoto(url: string | undefined) { this.photo = url; }
  showStatus(text: string) { this.status = text; }
  showBusy(busy: boolean) { this.busy = busy; }
  showEngine(engine: string, other: string) { this.engine = { engine, other }; }
  allow(actions: { rerun: boolean; accept: boolean }) { this.actions = actions; }
  showAccepted() { this.accepted = true; }
  applyHostContext(context: HostContext) { this.context = context; }
}

class FakePane implements ScorePane {
  loaded: string[] = [];
  measures: number[] = [];
  fail = false;
  async load(xml: string) {
    if (this.fail) throw new Error("no wasm");
    this.loaded.push(xml);
  }
  showMeasure(measure: number) {
    this.measures.push(measure);
  }
}

async function open(script: FakeScript = {}, pane = new FakePane()) {
  const ui = new FakeUi();
  const bridge = new FakeBridge({
    toolInput: { arguments: { image: "/scans/p1.png" } },
    toolResult: recognition(),
    toolAnswers: {
      get_recognized_score: SCORE,
      get_source_preview: PREVIEW,
      recognize_sheet: CLEAN,
      ...(script.toolAnswers ?? {}),
    },
    ...(script.toolResult ? { toolResult: script.toolResult } : {}),
    ...(script.toolInput ? { toolInput: script.toolInput } : {}),
  });
  const review = new RecognitionReview(bridge, ui, pane);
  await review.start();
  await bridge.settled();
  await review.idle();
  return { ui, bridge, review, pane };
}

const tools = (bridge: FakeBridge) => bridge.calls.filter((c) => c.method === "tools/call").map((c) => (c.params as { name: string }).name);

describe("RecognitionReview showing a result", () => {
  it("lists only the server's warnings, warnings first and notes last, and says what it found", async () => {
    const { ui } = await open();
    expect(ui.headline).toBe("Recognized with oemer: 1 part, 4 bars. 2 things to check.");
    expect(ui.issues.map((i) => [i.tag, i.message])).toEqual([
      ["Check", "Measure 3 has no notes or rests"],
      ["Note", "1 part recognized but the page has 4 staves per system; voices may be merged"],
    ]);
  });

  it("G2: advises Audiveris from the estimate and the detected parts", async () => {
    const { ui } = await open();
    expect(ui.advice).toBe(
      "Detected 1 part, but the page looks like it has 4 staves per system. Try the Audiveris engine, which keeps SATB voices apart.",
    );
  });

  it("fetches the score and the photo by job id and draws them", async () => {
    const { ui, bridge, pane } = await open();
    expect(bridge.calls.filter((c) => c.method === "tools/call").map((c) => c.params)).toEqual([
      { name: "get_recognized_score", arguments: { job_id: "job-1" } },
      { name: "get_source_preview", arguments: { job_id: "job-1", page: 1, offset: 0, length: 524288 } },
    ]);
    expect(pane.loaded).toEqual(["<score-partwise/>"]);
    expect(ui.photo).toMatch(/^data:image\/png;base64,/);
  });

  it("a clean result has no issues and no advice", async () => {
    const { ui } = await open({ toolResult: CLEAN });
    expect(ui.issues).toEqual([]);
    expect(ui.advice).toBeUndefined();
    expect(ui.headline).toBe("Recognized with Audiveris: 4 parts, 4 bars. Nothing to check.");
  });

  it("an error result shows its code and offers nothing", async () => {
    const { ui, bridge } = await open({ toolResult: failure("INVALID_INPUT") });
    expect(ui.notices).toEqual([NOTICES.failed("INVALID_INPUT")]);
    expect(ui.actions).toEqual({ rerun: false, accept: false });
    expect(tools(bridge)).toEqual([]);
  });

  it("a result without a job id still lists the issues but says the score cannot be shown", async () => {
    const { ui, bridge } = await open({ toolResult: recognition({ job_id: undefined }) });
    expect(ui.issues).toHaveLength(2);
    expect(ui.notices).toEqual([NOTICES.noReview]);
    expect(tools(bridge)).toEqual([]);
  });

  it("a result that is not a recognition is reported as such", async () => {
    const { ui } = await open({ toolResult: { structuredContent: { pdf_path: "/x" } } });
    expect(ui.notices).toEqual([NOTICES.notARecognition]);
  });

  it("notes that only page 1 is reviewed for a multi-page result (DA9)", async () => {
    const { ui } = await open({
      toolResult: recognition({ pages: [{ index: 1, has_preview: true }, { index: 2, has_preview: true }] }),
    });
    expect(ui.notices).toEqual(["This result has 2 pages; the review shows page 1."]);
  });

  it("keeps working when the notation engine cannot start", async () => {
    const pane = new FakePane();
    pane.fail = true;
    const { ui } = await open({}, pane);
    expect(ui.notices).toEqual([NOTICES.engineBlocked]);
    expect(ui.issues).toHaveLength(2);
    expect(ui.photo).toBeDefined();
  });

  it("names a failed score or photo fetch by its code", async () => {
    const { ui } = await open({ toolAnswers: { get_recognized_score: failure("INVALID_PARAMETER"), get_source_preview: failure("NOT_FOUND") } });
    expect(ui.notices).toEqual([NOTICES.scoreFailed("INVALID_PARAMETER"), NOTICES.photoFailed("NOT_FOUND")]);
  });

  it("skips the photo for a page without a preview", async () => {
    const { bridge } = await open({
      toolResult: recognition({ pages: [{ index: 1, has_preview: false }] }),
    });
    expect(tools(bridge)).toEqual(["get_recognized_score"]);
  });
});

describe("RecognitionReview selecting an issue (AC-O: scrolls the score to its bar)", () => {
  it("shows the issue's bar in the score and announces it", async () => {
    const { ui, review, pane } = await open();
    review.select(0);
    expect(pane.measures).toEqual([3]);
    expect(ui.selection).toEqual({
      index: 0,
      spoken: "Issue 1 of 2. Check: Measure 3 has no notes or rests. Showing bar 3 in the score.",
    });
  });

  it("an issue without a bar leaves the score where it is", async () => {
    const { ui, review, pane } = await open();
    review.select(1);
    expect(pane.measures).toEqual([]);
    expect(ui.selection?.spoken).toMatch(/This applies to the whole page\.$/);
  });

  it("ignores an index outside the list", async () => {
    const { ui, review } = await open();
    review.select(9);
    expect(ui.selection?.index).toBeUndefined();
  });
});

describe("RecognitionReview engine switch", () => {
  it("offers the other engine, and one call re-runs the original request with it", async () => {
    const { ui, review, bridge } = await open();
    expect(ui.engine).toEqual({ engine: "oemer", other: "audiveris" });
    await review.rerun();
    const call = bridge.calls.find((c) => (c.params as { name?: string }).name === "recognize_sheet");
    expect(call?.params).toEqual({ name: "recognize_sheet", arguments: { image: "/scans/p1.png", engine: "audiveris" } });
  });

  it("shows the new result, announces the run and clears the old selection", async () => {
    const { ui, review, bridge } = await open({ toolAnswers: { get_recognized_score: SCORE } });
    review.select(1);
    await review.rerun();
    await review.idle();
    expect(ui.headline).toBe("Recognized with Audiveris: 4 parts, 4 bars. Nothing to check.");
    expect(ui.status).toBe("Recognized again with Audiveris: 4 parts. Nothing to check.");
    expect(ui.issues).toEqual([]);
    expect(ui.selection?.index).toBeUndefined();
    expect(ui.engine).toEqual({ engine: "audiveris", other: "oemer" });
    expect(ui.busy).toBe(false);
    expect(tools(bridge).filter((n) => n === "get_recognized_score")).toHaveLength(2);
  });

  it("announces the run while it is going", async () => {
    let release!: (result: ToolResult) => void;
    const pending = new Promise<ToolResult>((resolve) => (release = resolve));
    const { ui, review } = await open({ toolAnswers: { recognize_sheet: () => pending } });
    const run = review.rerun();
    expect(ui.status).toBe("Recognizing again with Audiveris. This can take a few minutes.");
    expect(ui.busy).toBe(true);
    release(CLEAN);
    await run;
  });

  it("one run at a time: a second click joins the first", async () => {
    const { review, bridge } = await open();
    await Promise.all([review.rerun(), review.rerun()]);
    expect(tools(bridge).filter((n) => n === "recognize_sheet")).toHaveLength(1);
  });

  it("keeps the earlier result and says why when the run fails", async () => {
    const { ui, review } = await open({ toolAnswers: { recognize_sheet: failure("PROCESSING_FAILED") } });
    await review.rerun();
    expect(ui.status).toBe("Recognizing again with Audiveris failed (PROCESSING_FAILED). The earlier result is still shown.");
    expect(ui.headline).toBe("Recognized with oemer: 1 part, 4 bars. 2 things to check.");
    expect(ui.busy).toBe(false);
  });

  it("uses recognize_sheets for a multi-image request", async () => {
    const { review, bridge } = await open({
      toolInput: { arguments: { images: ["/a.png", "/b.png"] } },
      toolAnswers: { recognize_sheets: CLEAN },
    });
    await review.rerun();
    expect(tools(bridge)).toContain("recognize_sheets");
  });

  it("cannot re-run without the original request", async () => {
    const { ui, review } = await open({ toolInput: { arguments: {} } });
    expect(ui.actions.rerun).toBe(false);
    await review.rerun();
    expect(ui.status).toBe(NOTICES.noRequest);
  });
});

describe("RecognitionReview accept", () => {
  it("sends one fixed message, then the counts as model context", async () => {
    const { ui, review, bridge } = await open();
    await review.accept();
    await review.accept();
    const sent = bridge.calls.filter((c) => c.method === "ui/message" || c.method === "ui/update-model-context");
    expect(sent).toEqual([
      { method: "ui/message", params: { text: ACCEPT_MESSAGE } },
      {
        method: "ui/update-model-context",
        params: { text: "Recognition Review: the user accepted the score recognized with oemer (1 part, 4 bars, 2 open issues)." },
      },
    ]);
    expect(ui.accepted).toBe(true);
  });

  it("is not offered before there is a result", async () => {
    const { ui } = await open({ toolResult: failure("X") });
    expect(ui.actions.accept).toBe(false);
  });

  it("a new result makes accept available again", async () => {
    const { ui, review } = await open();
    await review.accept();
    await review.rerun();
    expect(ui.actions.accept).toBe(true);
  });
});
