// Part filter and highlight for the Score Viewer (C6b): pure functions over a MusicXML string, so
// the same code serves both render paths (Verovio WASM in the page, render_page_svg on the server)
// and runs in Node tests. Parts are found by their `id` attributes, the way the server's part
// resolver ends up identifying them; only `score-partwise` is handled (timewise scores list no
// parts and are left untouched).
//
// The scan uses indexOf, not regular expressions over the whole score: the input is a score of any
// size from any source, and a backtracking pattern over it can take quadratic time.

export interface ScorePart {
  id: string;
  name: string;
  /** Staves the part draws (`<staves>`, else 1). */
  staves: number;
  /** Position of the part's first staff among all staves of the score, from 0. */
  firstStaff: number;
}

/** One `<tag ...>...</tag>` (or `<tag .../>`) element of the score: its span and its opening tag. */
interface Block {
  start: number;
  end: number;
  open: string;
}

const ENTITIES: Record<string, string> = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'" };
const ATTRIBUTE_BOUNDARY = /[\s>/]/;

/** The elements named `tag`, in order. `<part>` does not match `<part-list>` or `<part-group>`. */
function blocks(xml: string, tag: string): Block[] {
  const found: Block[] = [];
  const opening = `<${tag}`;
  const closing = `</${tag}>`;
  let from = 0;
  for (;;) {
    const start = xml.indexOf(opening, from);
    if (start < 0) return found;
    const after = xml.charAt(start + opening.length);
    if (!ATTRIBUTE_BOUNDARY.test(after)) {
      from = start + opening.length;
      continue;
    }
    const tagEnd = xml.indexOf(">", start);
    if (tagEnd < 0) return found;
    const open = xml.slice(start, tagEnd + 1);
    let end = tagEnd + 1;
    if (!open.endsWith("/>")) {
      const close = xml.indexOf(closing, end);
      if (close < 0) return found;
      end = close + closing.length;
    }
    found.push({ start, end, open });
    from = end;
  }
}

function idOf(open: string): string | undefined {
  // Sticky, so each attribute is matched where the previous one ended; the id is never searched for elsewhere.
  const attribute = /\s+([A-Za-z_:][\w:.-]*)\s*=\s*(?:"([^"]*)"|'([^']*)')/y;
  attribute.lastIndex = Math.max(0, open.search(/\s/));
  for (let found = attribute.exec(open); found; found = attribute.exec(open)) {
    if (found[1] === "id") return found[2] ?? found[3];
  }
  return undefined;
}

function textOf(xml: string, tag: string): string | undefined {
  const start = xml.indexOf(`<${tag}`);
  if (start < 0) return undefined;
  const tagEnd = xml.indexOf(">", start);
  const close = xml.indexOf(`</${tag}>`, tagEnd);
  return tagEnd < 0 || close < 0 ? undefined : xml.slice(tagEnd + 1, close);
}

const decode = (text: string): string =>
  text.replace(/&(?:#(\d{1,7})|#x([0-9a-f]{1,6})|(amp|lt|gt|quot|apos));/gi, (_all, dec, hex, name) =>
    name ? ENTITIES[name.toLowerCase()]! : String.fromCodePoint(Number.parseInt(dec ?? hex, dec ? 10 : 16)),
  );

const isPartwise = (xml: string): boolean => xml.includes("<score-partwise");

/** The parts of a partwise score in score order; empty for anything else. */
export function listParts(xml: string): ScorePart[] {
  if (!isPartwise(xml)) return [];
  const names = new Map<string, string>();
  for (const block of blocks(xml, "score-part")) {
    const id = idOf(block.open);
    if (id !== undefined) names.set(id, decode(textOf(xml.slice(block.start, block.end), "part-name") ?? "").trim());
  }
  const parts: ScorePart[] = [];
  let firstStaff = 0;
  for (const block of blocks(xml, "part")) {
    const id = idOf(block.open);
    if (id === undefined) continue;
    const declared = Number(textOf(xml.slice(block.start, block.end), "staves")?.trim());
    const staves = Number.isInteger(declared) && declared >= 1 ? declared : 1;
    parts.push({ id, name: names.get(id) || id, staves, firstStaff });
    firstStaff += staves;
  }
  return parts;
}

/**
 * The score with only the parts in `ids`, kept in score order. Returns `xml` itself when nothing
 * would change: no ids, no known id, or every part chosen.
 */
export function filterParts(xml: string, ids: readonly string[]): string {
  const all = listParts(xml);
  const wanted = new Set(all.map((part) => part.id).filter((id) => ids.includes(id)));
  if (wanted.size === 0 || wanted.size === all.length) return xml;
  const dropped = [...blocks(xml, "score-part"), ...blocks(xml, "part")]
    .filter((block) => {
      const id = idOf(block.open);
      return id !== undefined && !wanted.has(id);
    })
    .sort((a, b) => a.start - b.start);
  let out = "";
  let from = 0;
  for (const block of dropped) {
    out += xml.slice(from, block.start);
    from = block.end;
  }
  return out + xml.slice(from);
}

/** Indexes of the staves to dim so that only `highlight`'s part stays bright; none for no highlight. */
export function dimmedStaffIndexes(parts: readonly ScorePart[], highlight: string | null): number[] {
  const bright = parts.find((part) => part.id === highlight);
  if (!bright) return [];
  const dimmed: number[] = [];
  for (const part of parts) {
    if (part === bright) continue;
    for (let staff = 0; staff < part.staves; staff++) dimmed.push(part.firstStaff + staff);
  }
  return dimmed;
}
