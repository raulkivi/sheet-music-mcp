// The one registry of MCP Apps pages. Adding a page = create apps/<name>/ and add ONE entry here;
// the vite config, build, check-html, copy-assets and the mock host all read this file.
//
//   <name>: {
//     targets: [{ server, pkg }, ...]   every server that serves the page; one page may have many
//   }
//
// The built page is dist/<name>.html and is copied to <server>/src/<pkg>/ui/assets/<name>.html
// (generated and gitignored, decision D1; each server's pyproject packages it via hatch `artifacts`).

/** @type {Record<string, { targets: { server: string, pkg: string }[] }>} */
export const APPS = {
  "score-viewer": {
    targets: [{ server: "render-mcp", pkg: "render_mcp" }],
  },
  "diff-viewer": {
    targets: [{ server: "comparer-mcp", pkg: "comparer_mcp" }],
  },
  // One page, six copies: each server serves it from its own package and shows only its own
  // health_check report (decision DA5), so nothing here knows another server exists.
  "setup-doctor": {
    targets: [
      { server: "render-mcp", pkg: "render_mcp" },
      { server: "synth-mcp", pkg: "synth_mcp" },
      { server: "omr-mcp", pkg: "omr_mcp" },
      { server: "musicxml-abc-mcp", pkg: "musicxml_abc_mcp" },
      { server: "pitch-mcp", pkg: "pitch_mcp" },
      { server: "comparer-mcp", pkg: "comparer_mcp" },
    ],
  },
  "practice-coach": {
    targets: [{ server: "pitch-mcp", pkg: "pitch_mcp" }],
  },
};
