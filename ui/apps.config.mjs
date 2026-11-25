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
};
