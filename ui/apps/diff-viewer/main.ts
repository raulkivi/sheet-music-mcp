// Composition root: real host bridge, Verovio panes and DOM, wired into the DiffViewer.

import { createExtAppsBridge } from "@sheet-music-mcp/ui-kit/host/ExtAppsBridge";
import { DomUi } from "./dom.ts";
import { VerovioPanes } from "./panes.ts";
import { DiffViewer } from "./viewer.ts";
import "./style.css";

const bridge = createExtAppsBridge({ name: "sheet-music-diff-viewer", version: "0.1.0", displayModes: ["inline"] });
const ui = new DomUi(document);
const byId = (id: string) => document.getElementById(id)!;
const panes = new VerovioPanes(byId("pane-reference"), byId("pane-target"), document.documentElement);
const viewer = new DiffViewer(bridge, ui, panes);
ui.bind(viewer);

viewer.start().catch((error: unknown) => {
  ui.showNotice("The viewer could not connect to the host.");
  console.error(error);
});
