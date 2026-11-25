// Composition root: real host bridge, the page's clipboard and DOM, wired into the SetupDoctor.

import { createExtAppsBridge } from "@sheet-music-mcp/ui-kit/host/ExtAppsBridge";
import { browserClipboard, copyText } from "./clipboard.ts";
import { DomUi } from "./dom.ts";
import { SetupDoctor } from "./doctor.ts";
import "./style.css";

const bridge = createExtAppsBridge({ name: "sheet-music-setup-doctor", version: "0.1.0" });
const ui = new DomUi(document);
const clipboard = browserClipboard(document);
const doctor = new SetupDoctor(bridge, ui, (text) => copyText(text, clipboard));
ui.bind(doctor);

doctor.start().catch((error: unknown) => {
  ui.showError("The Setup Doctor could not connect to the host.");
  console.error(error);
});
