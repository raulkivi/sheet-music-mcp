import { describe, expect, it } from "vitest";
import { FakeBridge, type FakeScript } from "@sheet-music-mcp/ui-kit/host/FakeBridge";
import type { HostContext, ToolResult } from "@sheet-music-mcp/ui-kit/host/HostBridge";
import type { Change, KindOption } from "./model.ts";
import { DiffViewer, NOTICES, type DiffUi, type ScorePanes } from "./viewer.ts";

const note = (pitch: string) => ({ pitch, duration: 1, is_rest: false });
const change = (over: Partial<Change>): Change => ({
  operation: "PITCH_CHANGE",
  measure_number: 19,
  beat: 1,
  voice: 1,
  part_name: "Soprano",
  reference: note("E4"),
  target: note("A4"),
  interval_error: 5,
  ...over,
});

const CHANGES = [
  change({ measure_number: 7, part_name: "Alto" }),
  change({ measure_number: 12, operation: "DELETION", target: null, part_name: "Bass" }),
  change({ measure_number: 19 }),
];

const compared = (extra: Record<string, unknown> = {}): ToolResult => ({
  structuredContent: {
    detail: "full",
    similarity_score: 0.984,
    summary: {},
    changes: CHANGES,
    count: 3,
    report: "Overall similarity: 98%",
    diff_id: "d1",
    ...extra,
  },
});

const SCORES: ToolResult = {
  structuredContent: {
    diff_id: "d1",
    reference_musicxml: "<ref/>",
    target_musicxml: "<tgt/>",
    legend: { PITCH_CHANGE: "#FF8800" },
  },
};
const EXPORTED: ToolResult = {
  structuredContent: {
    reference_annotated_musicxml_path: "/out/ref.musicxml",
    target_annotated_musicxml_path: "/out/tgt.musicxml",
  },
};
const FAILURE: ToolResult = {
  isError: true,
  content: [{ type: "text", text: '{"error":"gone","error_code":"INVALID_PARAMETER"}' }],
};

class FakeUi implements DiffUi {
  headline: string | undefined;
  report: string | undefined;
  notice: string | undefined;
  list: { changes: Change[]; kinds: KindOption[]; selected: ReadonlySet<string> } | undefined;
  selection: { index: number | undefined; spoken: string } | undefined;
  exported: string[] | undefined;
  busy = false;
  exportAllowed: boolean | undefined;
  theme: HostContext | undefined;
  showHeadline(text: string) {
    this.headline = text;
  }
  showReport(text: string | undefined) {
    this.report = text;
  }
  showNotice(text: string | undefined) {
    this.notice = text;
  }
  showList(changes: Change[], kinds: KindOption[], selected: ReadonlySet<string>) {
    this.list = { changes, kinds, selected: new Set(selected) };
  }
  showSelection(index: number | undefined, spoken: string) {
    this.selection = { index, spoken };
  }
  showExported(names: string[] | undefined) {
    this.exported = names;
  }
  showBusy(busy: boolean) {
    this.busy = busy;
  }
  allowExport(enabled: boolean) {
    this.exportAllowed = enabled;
  }
  applyHostContext(context: HostContext) {
    this.theme = context;
  }
}

class FakePanes implements ScorePanes {
  loaded: [string, string, Record<string, string>] | undefined;
  shown: number[] = [];
  fail = false;
  async load(reference: string, target: string, legend: Record<string, string>) {
    if (this.fail) throw new Error("no engine");
    this.loaded = [reference, target, legend];
  }
  showMeasure(measure: number) {
    this.shown.push(measure);
  }
}

async function open(result: ToolResult, answers: FakeScript["toolAnswers"] = {}, panes = new FakePanes()) {
  const bridge = new FakeBridge({
    toolResult: result,
    toolAnswers: { get_diff_scores: SCORES, export_diff_scores: EXPORTED, ...answers },
  });
  const ui = new FakeUi();
  const viewer = new DiffViewer(bridge, ui, panes);
  await viewer.start();
  await bridge.settled();
  await viewer.idle();
  return { bridge, ui, viewer, panes };
}

const calls = (bridge: FakeBridge, method: string) => bridge.calls.filter((c) => c.method === method);

describe("DiffViewer: showing a comparison", () => {
  it("shows the headline, the report, the changes and the kinds present", async () => {
    const { ui } = await open(compared());
    expect(ui.headline).toBe("98.4% similar, 3 changes");
    expect(ui.report).toBe("Overall similarity: 98%");
    expect(ui.list?.changes).toEqual(CHANGES);
    expect(ui.list?.kinds.map((k) => k.kind)).toEqual(["PITCH_CHANGE", "DELETION"]);
    expect(ui.notice).toBeUndefined();
  });

  it("fetches both scores by diff_id and draws them with the legend", async () => {
    const { bridge, panes } = await open(compared());
    expect(calls(bridge, "tools/call")).toEqual([
      { method: "tools/call", params: { name: "get_diff_scores", arguments: { diff_id: "d1" } } },
    ]);
    expect(panes.loaded).toEqual(["<ref/>", "<tgt/>", { PITCH_CHANGE: "#FF8800" }]);
  });

  it("allows saving only when the result has a diff_id", async () => {
    expect((await open(compared())).ui.exportAllowed).toBe(true);
    expect((await open(compared({ diff_id: undefined }))).ui.exportAllowed).toBe(false);
  });

  it("says so when the scores are identical", async () => {
    const { ui } = await open(compared({ changes: [], count: 0, similarity_score: 1 }));
    expect(ui.headline).toBe("100% similar, no changes");
    expect(ui.notice).toBe(NOTICES.identical);
  });

  it("says which detail level lists changes when the result has none", async () => {
    const { ui } = await open({ structuredContent: { detail: "summary", similarity_score: 0.9, summary: {} } });
    expect(ui.headline).toBe("90% similar");
    expect(ui.notice).toBe(NOTICES.noChanges);
  });

  it("explains a result that has no diff_id and does not call the server", async () => {
    const { ui, bridge } = await open(compared({ diff_id: undefined }));
    expect(ui.notice).toBe(NOTICES.noScores);
    expect(calls(bridge, "tools/call")).toEqual([]);
  });

  it("shows the error code of a failed comparison", async () => {
    const { ui } = await open(FAILURE);
    expect(ui.notice).toBe(NOTICES.compareFailed("INVALID_PARAMETER"));
    expect(ui.list).toBeUndefined();
  });

  it("rejects a result that is not a comparison", async () => {
    const { ui } = await open({ structuredContent: { hello: 1 } });
    expect(ui.notice).toBe(NOTICES.notAComparison);
  });

  it("keeps the list when the scores cannot be fetched", async () => {
    const { ui } = await open(compared(), { get_diff_scores: FAILURE });
    expect(ui.notice).toBe(NOTICES.scoresFailed("INVALID_PARAMETER"));
    expect(ui.list?.changes).toEqual(CHANGES);
  });

  it("keeps the list when the notation engine cannot start", async () => {
    const panes = new FakePanes();
    panes.fail = true;
    const { ui } = await open(compared(), {}, panes);
    expect(ui.notice).toBe(NOTICES.engineBlocked);
    expect(ui.list?.changes).toEqual(CHANGES);
  });
});

describe("DiffViewer: selecting and filtering", () => {
  it("selecting a change scrolls both panes to its bar and announces it", async () => {
    const { ui, viewer, panes } = await open(compared());
    viewer.select(2);
    expect(panes.shown).toEqual([19]);
    expect(ui.selection).toEqual({
      index: 2,
      spoken: "Change 3 of 3. Soprano, bar 19, beat 1: E4 to A4 (pitch changed). Both scores show bar 19.",
    });
  });

  it("selecting an index that does not exist changes nothing", async () => {
    const { viewer, panes } = await open(compared());
    viewer.select(9);
    expect(panes.shown).toEqual([]);
  });

  it("a kind filter narrows the list and indexes follow the narrowed list", async () => {
    const { ui, viewer, panes } = await open(compared());
    viewer.toggleKind("DELETION");
    expect(ui.list?.changes).toEqual([CHANGES[1]]);
    expect([...(ui.list?.selected ?? [])]).toEqual(["DELETION"]);
    viewer.select(0);
    expect(panes.shown).toEqual([12]);
    expect(ui.selection?.spoken).toMatch(/^Change 1 of 1\./);
  });

  it("toggling a kind off again shows everything", async () => {
    const { ui, viewer } = await open(compared());
    viewer.toggleKind("DELETION");
    viewer.toggleKind("DELETION");
    expect(ui.list?.changes).toEqual(CHANGES);
  });

  it("clears the selection when its change is filtered out", async () => {
    const { ui, viewer } = await open(compared());
    viewer.select(0);
    viewer.toggleKind("DELETION");
    expect(ui.selection?.index).toBeUndefined();
  });

  it("keeps the selection when its change stays visible", async () => {
    const { ui, viewer } = await open(compared());
    viewer.select(1);
    viewer.toggleKind("DELETION");
    expect(ui.selection?.index).toBe(0);
  });
});

describe("DiffViewer: export and Open in Score Viewer", () => {
  it("exports through the app-only tool and shows the file names", async () => {
    const { bridge, ui, viewer } = await open(compared());
    await viewer.exportScores();
    expect(calls(bridge, "tools/call").at(-1)?.params).toEqual({
      name: "export_diff_scores",
      arguments: { diff_id: "d1" },
    });
    expect(ui.exported).toEqual(["ref.musicxml", "tgt.musicxml"]);
    expect(calls(bridge, "ui/message")).toEqual([]);
  });

  it("shows a failure to export", async () => {
    const { ui, viewer } = await open(compared(), { export_diff_scores: FAILURE });
    await viewer.exportScores();
    expect(ui.notice).toBe(NOTICES.exportFailed("INVALID_PARAMETER"));
    expect(ui.exported).toBeUndefined();
  });

  it("Open in Score Viewer exports once and posts one fixed message", async () => {
    const { bridge, viewer } = await open(compared());
    await viewer.exportScores();
    await viewer.openInScoreViewer();
    expect(calls(bridge, "tools/call").filter((c) => (c.params as { name: string }).name === "export_diff_scores")).toHaveLength(1);
    expect(calls(bridge, "ui/message")).toEqual([
      {
        method: "ui/message",
        params: {
          text:
            "Open the annotated target score `/out/tgt.musicxml` (and the annotated reference " +
            "`/out/ref.musicxml`) from the Diff Viewer in the Score Viewer: render it with " +
            "render-mcp, passing the path as musicxml_path.",
        },
      },
    ]);
  });

  it("Open in Score Viewer exports first when nothing was exported", async () => {
    const { bridge, viewer } = await open(compared());
    await viewer.openInScoreViewer();
    expect(calls(bridge, "ui/message")).toHaveLength(1);
  });

  it("posts no message when the export fails", async () => {
    const { bridge, viewer } = await open(compared(), { export_diff_scores: FAILURE });
    await viewer.openInScoreViewer();
    expect(calls(bridge, "ui/message")).toEqual([]);
  });

  it("a second click while one is running posts nothing more", async () => {
    const { bridge, viewer } = await open(compared());
    await Promise.all([viewer.openInScoreViewer(), viewer.openInScoreViewer()]);
    expect(calls(bridge, "ui/message")).toHaveLength(1);
  });
});

describe("DiffViewer: host context", () => {
  it("applies the host theme at start", async () => {
    const bridge = new FakeBridge({ context: { theme: "dark" } });
    const ui = new FakeUi();
    await new DiffViewer(bridge, ui, new FakePanes()).start();
    expect(ui.theme).toEqual({ theme: "dark" });
  });
});
