import { existsSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
// @ts-expect-error -- plain .mjs script without type declarations
import { externalReferences } from "../scripts/check-html.mjs";

const refs = externalReferences as (html: string) => string[];

describe("externalReferences (AC-R1)", () => {
  it("accepts a page whose script and style are inline", () => {
    const html = `<!doctype html><html><head><style>body{}</style>
      <script type="module">const a = '<script src="https://evil.example/x.js"></' + 'script>';</script>
      </head><body><a href="#top">top</a></body></html>`;
    expect(refs(html)).toEqual([]);
  });

  it("flags external scripts, stylesheets and other off-origin src/href", () => {
    const html = `<html><head>
      <script src="https://cdn.example/app.js"></script>
      <link rel="stylesheet" href="//fonts.example/a.css">
      <link rel="icon" href="favicon.ico">
      </head><body><img src="http://x.example/a.png"><iframe src='https://y.example'></iframe></body></html>`;
    expect(refs(html)).toEqual([
      '<script src="https://cdn.example/app.js">',
      '<link href="//fonts.example/a.css">',
      '<link href="favicon.ico">',
      '<img src="http://x.example/a.png">',
      '<iframe src="https://y.example">',
    ]);
  });

  it("allows data: URIs", () => {
    expect(refs(`<link rel="icon" href="data:image/png;base64,AAAA"><img src="data:,x">`)).toEqual([]);
  });

  it("flags a base element", () => {
    expect(refs(`<base href="https://x.example/">`)).toEqual(['<base href="https://x.example/">']);
  });
});

const BUILT = new URL("../dist/score-viewer.html", import.meta.url);

describe.runIf(existsSync(BUILT))("built score-viewer.html", () => {
  it("has no off-origin references", () => {
    expect(refs(readFileSync(BUILT, "utf8"))).toEqual([]);
  });
});
