// Position of a printed bar among the first part's measures. Verovio draws the measures in that
// order, so it is also the index among the rendered `g.measure` elements. Pure.

export function measureIndex(musicxml: string, number: number): number | undefined {
  const part = musicxml.match(/<part\b[^>]*>([\s\S]*?)<\/part>/);
  if (!part) return undefined;
  const numbers = [...part[1]!.matchAll(/<measure\b[^>]*?\bnumber="([^"]*)"/g)].map((m) => m[1]);
  const index = numbers.indexOf(String(number));
  return index < 0 ? undefined : index;
}
