import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeBridge, type FakeScript } from "@sheet-music-mcp/ui-kit/host/FakeBridge";
import type { ToolResult } from "@sheet-music-mcp/ui-kit/host/HostBridge";
import { DEBOUNCE_MS } from "./validation.ts";
import { Workbench, type WorkbenchUi, type WorkbenchView } from "./workbench.ts";

const ORIGINAL = ["X:1", "T:Test", "K:C", "abc|", "def|"].join("\n");
const PROPOSED = ["X:1", "T:Test", "K:C", "abe|", "deg|"].join("\n");

const stored = (abc: string): ToolResult => ({
  content: [],
  structuredContent: { abc_id: "id-1", abc, parts_included: ["P1"], warnings: ["drops dynamics"] },
});
const validResult: ToolResult = { content: [], structuredContent: { valid: true, errors: [], warnings: [] } };
const inlineConversion: ToolResult = {
  content: [{ type: "text", text: JSON.stringify({ musicxml: "<score-partwise/>", warnings: [] }) }],
  structuredContent: { warnings: [], delivery: "inline", musicxml_bytes: 17 },
};
const fileConversion: ToolResult = {
  content: [{ type: "text", text: JSON.stringify({ musicxml_path: "/out/from-abc.musicxml", warnings: [] }) }],
  structuredContent: { warnings: [], delivery: "path", musicxml_bytes: 99999 },
};

class RecordingUi implements WorkbenchUi {
  views: WorkbenchView[] = [];
  downloads: string[] = [];
  get view(): WorkbenchView {
    return this.views.at(-1)!;
  }
  render(view: WorkbenchView): void {
    this.views.push(view);
  }
  applyHostContext(): void {}
  download(filename: string): void {
    this.downloads.push(filename);
  }
}

function setup(script: FakeScript) {
  const bridge = new FakeBridge(script);
  const ui = new RecordingUi();
  const workbench = new Workbench(bridge, ui);
  return { bridge, ui, workbench };
}

const toolCalls = (bridge: FakeBridge, name: string) =>
  bridge.calls.filter((c) => c.method === "tools/call" && (c.params as { name: string }).name === name).map((c) => (c.params as { arguments: unknown }).arguments);

const editOpening: FakeScript = {
  toolInput: { arguments: { abc: PROPOSED } },
  toolResult: inlineConversion,
  toolAnswers: { get_abc: stored(ORIGINAL), validate_abc: validResult, abc_to_musicxml: inlineConversion },
};

async function opened(script: FakeScript = editOpening) {
  const parts = setup(script);
  await parts.workbench.start();
  await vi.advanceTimersByTimeAsync(1);
  await parts.workbench.idle();
  return parts;
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("opening on abc_to_musicxml", () => {
  it("fetches the original with get_abc and shows the model's edit as hunks", async () => {
    const { bridge, ui } = await opened();
    expect(toolCalls(bridge, "get_abc")).toEqual([{}]);
    expect(ui.view.rows.filter((r) => r.kind === "hunk")).toHaveLength(1);
    expect(ui.view.summary).toBe("1 change, 1 kept");
    expect(ui.view.mode).toBe("review");
  });

  it("validates the result of the selection once, after the debounce", async () => {
    const { bridge, ui } = await opened();
    expect(toolCalls(bridge, "validate_abc")).toEqual([]);
    expect(ui.view.validation.status).toBe("pending");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    expect(toolCalls(bridge, "validate_abc")).toEqual([{ abc: PROPOSED }]);
    expect(ui.view.validation.status).toBe("valid");
  });

  it("says so when the original export is gone, and still shows the proposal", async () => {
    const gone: ToolResult = { isError: true, content: [{ type: "text", text: JSON.stringify({ error: "x", error_code: "NOT_FOUND" }) }] };
    const { ui } = await opened({ ...editOpening, toolAnswers: { ...editOpening.toolAnswers, get_abc: gone } });
    expect(ui.view.notice).toContain("original");
    expect(ui.view.rows.some((r) => r.kind === "hunk")).toBe(true);
  });

  it("shows the server's warnings from the export", async () => {
    const { ui } = await opened();
    expect(ui.view.warnings).toEqual(["drops dynamics"]);
  });
});

describe("opening on musicxml_to_abc", () => {
  const exportScript: FakeScript = {
    toolInput: { arguments: { musicxml_path: "/a.musicxml" } },
    toolResult: stored(ORIGINAL),
    toolAnswers: { validate_abc: validResult, abc_to_musicxml: inlineConversion },
  };

  it("shows the export, no changes yet, and cannot accept", async () => {
    const { bridge, ui } = await opened(exportScript);
    expect(toolCalls(bridge, "get_abc")).toEqual([]);
    expect(ui.view.rows).toEqual([]);
    expect(ui.view.empty).toBe("The assistant has not proposed a change yet. Choose Edit to change the ABC yourself.");
    expect(ui.view.canAccept).toBe(false);
  });

  it("turns edits into hunks and validates the edited text after 300 ms", async () => {
    const { bridge, ui, workbench } = await opened(exportScript);
    workbench.setMode("edit");
    expect(ui.view.editor.text).toBe(ORIGINAL);
    workbench.edit(PROPOSED);
    workbench.edit(PROPOSED + "\n");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    expect(toolCalls(bridge, "validate_abc")).toEqual([{ abc: PROPOSED + "\n" }]);
    workbench.setMode("review");
    expect(ui.view.rows.filter((r) => r.kind === "hunk")).toHaveLength(1);
  });

  it("marks the error line the server reports in edit mode", async () => {
    const invalid: ToolResult = { content: [], structuredContent: { valid: false, errors: ["Line 4: unexpected ?"], warnings: [] } };
    const { ui, workbench } = await opened({ ...exportScript, toolAnswers: { ...exportScript.toolAnswers, validate_abc: invalid } });
    workbench.setMode("edit");
    workbench.edit(ORIGINAL.replace("abc|", "a?c|"));
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    expect(ui.view.validation).toMatchObject({ status: "invalid", problems: [{ line: 4 }] });
    expect(ui.view.editor.errorLines).toEqual([4]);
  });
});

describe("accepting", () => {
  it("converts the selected hunks once with return auto and tells the model", async () => {
    const { bridge, ui, workbench } = await opened();
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    const first = workbench.acceptSelected();
    const second = workbench.acceptSelected();
    await Promise.all([first, second]);
    await workbench.idle();
    expect(toolCalls(bridge, "abc_to_musicxml")).toEqual([{ abc: PROPOSED, return: "auto" }]);
    expect(ui.view.outcome).toMatchObject({ status: "accepted" });
    expect(ui.view.download).toBe(true);
    const context = bridge.calls.filter((c) => c.method === "ui/update-model-context");
    expect(context).toHaveLength(1);
    expect(JSON.stringify(context[0])).toContain("accepted 1 of 1 proposed changes");
  });

  it("merges only the kept hunks", async () => {
    const { bridge, workbench } = await opened();
    workbench.toggleHunk(0);
    workbench.toggleHunk(0);
    await workbench.acceptSelected();
    expect(toolCalls(bridge, "abc_to_musicxml")).toEqual([{ abc: PROPOSED, return: "auto" }]);
  });

  it("shows a file chip when the server wrote a file", async () => {
    const { ui, workbench } = await opened({ ...editOpening, toolAnswers: { ...editOpening.toolAnswers, abc_to_musicxml: fileConversion } });
    await workbench.acceptAll();
    expect(ui.view.outcome).toMatchObject({ status: "accepted", file: "/out/from-abc.musicxml" });
    expect(ui.view.download).toBe(false);
  });

  it("shows the server's error and does not tell the model it was accepted", async () => {
    const failed: ToolResult = { isError: true, content: [{ type: "text", text: JSON.stringify({ error: "Bad ABC", error_code: "INVALID_INPUT" }) }] };
    const { bridge, ui, workbench } = await opened({ ...editOpening, toolAnswers: { ...editOpening.toolAnswers, abc_to_musicxml: failed } });
    await workbench.acceptSelected();
    await workbench.idle();
    expect(ui.view.outcome).toMatchObject({ status: "failed" });
    expect(ui.view.outcome.text).toContain("INVALID_INPUT");
    expect(bridge.calls.some((c) => c.method === "ui/update-model-context")).toBe(false);
  });

  it("cannot accept while the validator reports errors", async () => {
    const invalid: ToolResult = { content: [], structuredContent: { valid: false, errors: ["Line 4: bad"], warnings: [] } };
    const { bridge, ui, workbench } = await opened({ ...editOpening, toolAnswers: { ...editOpening.toolAnswers, validate_abc: invalid } });
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    expect(ui.view.canAccept).toBe(false);
    await workbench.acceptSelected();
    expect(toolCalls(bridge, "abc_to_musicxml")).toEqual([]);
  });

  it("downloads the inline MusicXML", async () => {
    const { ui, workbench } = await opened();
    await workbench.acceptSelected();
    workbench.downloadResult();
    expect(ui.downloads).toEqual(["from-abc.musicxml"]);
  });
});

describe("rejecting and revising", () => {
  it("reject all makes no conversion and tells the model", async () => {
    const { bridge, ui, workbench } = await opened();
    await workbench.rejectAll();
    await workbench.idle();
    expect(toolCalls(bridge, "abc_to_musicxml")).toEqual([]);
    expect(ui.view.outcome).toMatchObject({ status: "rejected" });
    expect(ui.view.summary).toBe("1 change, 0 kept");
    expect(JSON.stringify(bridge.calls.at(-1))).toContain("rejected all 1 proposed changes");
  });

  it("ask the assistant to revise sends a fixed message naming the rejected change", async () => {
    const { bridge, workbench } = await opened();
    workbench.toggleHunk(0);
    await workbench.revise();
    const message = bridge.calls.find((c) => c.method === "ui/message");
    expect(message?.params).toEqual({
      text: "I reviewed your ABC edit in the ABC Workbench and rejected 1 of 1 changes: change 1 (original line 4). Please revise it.",
    });
  });

  it("changing the selection clears an earlier outcome so it can be decided again", async () => {
    const { ui, workbench } = await opened();
    await workbench.rejectAll();
    workbench.toggleHunk(0);
    expect(ui.view.outcome.status).toBe("idle");
  });
});
