// Host side of MCP Apps postMessage JSON-RPC, written by hand from the 2026-01-26 spec rather
// than with the SDK's AppBridge, so it checks the app against the wire format independently.
//
// Query parameters:
//   scenario  inline-long | inline-satb | path-only        (default inline-long)
//   theme     light | dark                                 (default light)
//   csp       spec | spec-wasm                             (default spec-wasm; see server.mjs)
//   downloads 1 | 0   adds allow-downloads to the sandbox  (default 1)
//   modes     comma list of display modes the host offers  (default inline)
//   width     container width in CSS pixels                (default 1000)
//
// Tests read window.__host.log: every message in either direction, in order.

const params = new URLSearchParams(location.search);
const scenarioName = params.get("scenario") ?? "inline-long";
const theme = params.get("theme") === "dark" ? "dark" : "light";
const csp = params.get("csp") ?? "spec-wasm";
const downloads = params.get("downloads") !== "0";
const modes = (params.get("modes") ?? "inline").split(",");
const width = Number(params.get("width") ?? 1000);

const PDF_RESULT = {
  content: [{ type: "text", text: "Rendered 5 page(s) to /tmp/sheet-music-output/score.pdf" }],
  structuredContent: { pdf_path: "/tmp/sheet-music-output/score.pdf", page_count: 5, backend: "verovio" },
};

async function fixture(name) {
  const res = await fetch(`/fixtures/${name}`);
  return res.text();
}

const SCENARIOS = {
  "inline-long": async () => ({ input: { musicxml: await fixture("satb-long.musicxml") }, result: PDF_RESULT }),
  "inline-satb": async () => ({ input: { musicxml: await fixture("satb-4bars.musicxml") }, result: PDF_RESULT }),
  "path-only": async () => ({ input: { musicxml_path: "/home/user/scores/satb.musicxml" }, result: PDF_RESULT }),
};

const DARK_VARIABLES = {
  "--color-background-primary": "#131314",
  "--color-text-primary": "#f2f2f2",
};

const log = [];
let displayMode = "inline";
const box = document.getElementById("frame-box");
box.style.width = `${width}px`;
const frame = document.createElement("iframe");
frame.title = "Score Viewer";
frame.setAttribute("sandbox", downloads ? "allow-scripts allow-downloads" : "allow-scripts");

function record(direction, message) {
  log.push({ direction, t: performance.now(), ...message });
}

function send(message) {
  const full = { jsonrpc: "2.0", ...message };
  record("host->app", full);
  frame.contentWindow.postMessage(full, "*");
}

function hostContext() {
  return {
    theme,
    styles: theme === "dark" ? { variables: DARK_VARIABLES } : { variables: {} },
    displayMode,
    availableDisplayModes: modes,
    containerDimensions: { width: box.clientWidth, maxHeight: 6000 },
    locale: "en-US",
    platform: "web",
    toolInfo: { tool: { name: "render_to_pdf", inputSchema: { type: "object" } } },
  };
}

const scenario = await SCENARIOS[scenarioName]();

const handlers = {
  "ui/initialize": (msg) => ({
    protocolVersion: msg.params.protocolVersion,
    hostInfo: { name: "mock-host", version: "0.0.0" },
    hostCapabilities: {
      serverTools: {},
      logging: {},
      message: { text: {} },
      updateModelContext: { text: {} },
    },
    hostContext: hostContext(),
  }),
  "ui/message": () => ({}),
  "ui/update-model-context": () => ({}),
  "ui/request-display-mode": (msg) => {
    if (modes.includes(msg.params.mode)) displayMode = msg.params.mode;
    queueMicrotask(() => send({ method: "ui/notifications/host-context-changed", params: { displayMode } }));
    return { mode: displayMode };
  },
  "tools/call": (msg) => {
    throw { code: -32602, message: `mock host has no fixture for tool ${msg.params.name}` };
  },
  ping: () => ({}),
};

const notifications = {
  "ui/notifications/initialized": () => {
    send({ method: "ui/notifications/tool-input", params: { arguments: scenario.input } });
    send({ method: "ui/notifications/tool-result", params: scenario.result });
  },
  "ui/notifications/size-changed": (msg) => {
    if (msg.params.height > 0) frame.style.height = `${Math.min(msg.params.height, 6000)}px`;
  },
};

window.addEventListener("message", (event) => {
  if (event.source !== frame.contentWindow) return;
  const msg = event.data;
  if (!msg || msg.jsonrpc !== "2.0") return;
  record("app->host", msg);
  if (msg.id === undefined) {
    notifications[msg.method]?.(msg);
    return;
  }
  if (!msg.method) return; // a response to a host request; the mock host sends none
  const handler = handlers[msg.method];
  try {
    if (!handler) throw { code: -32601, message: `Method not found: ${msg.method}` };
    send({ id: msg.id, result: handler(msg) });
  } catch (error) {
    send({ id: msg.id, error: { code: error.code ?? -32603, message: String(error.message ?? error) } });
  }
});

window.__host = {
  log,
  /** Resizes the container like a host would and tells the app (containerDimensions). */
  resize(newWidth) {
    box.style.width = `${newWidth}px`;
    send({ method: "ui/notifications/host-context-changed", params: { containerDimensions: { width: newWidth, maxHeight: 6000 } } });
  },
  setTheme(name) {
    send({
      method: "ui/notifications/host-context-changed",
      params: { theme: name, styles: { variables: name === "dark" ? DARK_VARIABLES : {} } },
    });
  },
  messages(method) {
    return log.filter((m) => m.method === method);
  },
};

frame.src = `/app.html?csp=${encodeURIComponent(csp)}`;
box.append(frame);
