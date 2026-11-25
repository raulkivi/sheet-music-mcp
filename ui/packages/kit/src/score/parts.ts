// Part filter and highlight for the Score Viewer (C6b): pure functions over a MusicXML string, so
// the same code serves both render paths (Verovio WASM in the page, render_page_svg on the server)
// and runs in Node tests. Parts are found by their `id` attributes, the way the server's part
// resolver ends up identifying them; only `score-partwise` is handled (timewise scores list no
// parts and are left untouched).

export interface ScorePart {
  id: string;
  name: string;
  /** Staves the part draws (`<staves>`, else 1). */
  staves: number;
  /** Position of the part's first staff among all staves of the score, from 0. */
  firstStaff: number;
}

const SCORE_PART = /<score-part\s[^>]*?>[\s\S]*?<\/score-part>|<score-part\s[^>]*?\/>/g;
// `<part-list>` and `<part-group>` have no whitespace after `<part`, so they never match here.
const PART = /<part\s[^>]*?\/>|<part\s[^>]*?>[\s\S]*?<\/part>/g;
const ID = /\sid\s*=\s*(?:"([^"]*)"|'([^']*)')/;
const ENTITIES: Record<string, string> = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'" };

const idOf = (block: string): string | undefined => {
  const tag = block.slice(0, block.indexOf(">") + 1);
  const found = ID.exec(tag);
  return found ? (found[1] ?? found[2]) : undefined;
};

const decode = (text: string): string =>
  text.replace(/&(?:#(\d+)|#x([0-9a-f]+)|(amp|lt|gt|quot|apos));/gi, (_all, dec, hex, name) =>
    name ? ENTITIES[name.toLowerCase()]! : String.fromCodePoint(Number.parseInt(dec ?? hex, dec ? 10 : 16)),
  );

const isPartwise = (xml: string): boolean => /<score-partwise[\s>]/.test(xml);

/** The parts of a partwise score in score order; empty for anything else. */
export function listParts(xml: string): ScorePart[] {
  if (!isPartwise(xml)) return [];
  const names = new Map<string, string>();
  for (const block of xml.match(SCORE_PART) ?? []) {
    const id = idOf(block);
    const name = /<part-name[^>]*>([\s\S]*?)<\/part-name>/.exec(block)?.[1];
    if (id !== undefined) names.set(id, name ? decode(name).trim() : "");
  }
  const parts: ScorePart[] = [];
  let firstStaff = 0;
  for (const block of xml.match(PART) ?? []) {
    const id = idOf(block);
    if (id === undefined) continue;
    const declared = Number(/<staves>\s*(\d+)\s*<\/staves>/.exec(block)?.[1]);
    const staves = declared >= 1 ? declared : 1;
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
  const keep = (block: string) => {
    const id = idOf(block);
    return id === undefined || wanted.has(id) ? block : "";
  };
  return xml.replace(SCORE_PART, keep).replace(PART, keep);
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
