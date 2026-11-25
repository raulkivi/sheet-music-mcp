// Composition root: real host bridge and DOM, wired into the Workbench.

import { createExtAppsBridge } from "@sheet-music-mcp/ui-kit/host/ExtAppsBridge";
import { DomUi } from "./dom.ts";
import { Workbench } from "./workbench.ts";
import "./style.css";

const bridge = createExtAppsBridge({ name: "sheet-music-abc-workbench", version: "0.1.0", displayModes: ["inline"] });
const ui = new DomUi(document);
const workbench = new Workbench(bridge, ui);
ui.bind(workbench);

workbench.start().catch((error: unknown) => {
  ui.showFatal("The workbench could not connect to the host.");
  console.error(error);
});
