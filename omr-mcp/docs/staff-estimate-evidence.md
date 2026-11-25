# Staff estimate: real-sample evidence (T2.2)

**Last changed:** 2026-11-25 · **Source:** https://github.com/raulkivi/sheet-music-mcp

Evidence for `metadata.staff_systems_estimate` and the `PARTS_FEWER_THAN_STAVES` check
(`src/omr_mcp/staff_estimate.py`, plan task T2.2, acceptance AC-O3). Run on 2026-11-25.

## What changed

The first version counted every staff on the page. On real pages that broke the check:

- An SATB page with 3 systems counted 12, so even a correct 4-part recognition got the warning.
- A melody page with 3 one-staff systems (Saltarello) counted 3, a false warning for a 1-part result.
- On a page scanned 0.2° off square it found no staves on most pages: tilted lines spread over
  several rows.

The estimate now counts the staves of the largest system (see [architecture.md](architecture.md#staff-estimate)):

- Staves join into one system where a vertical system line, bracket or barline runs between them.
- The page is deskewed (up to ±3°) before the line search.
- Ink is set relative to the paper's shade, so gray (smoothed) lines and gray paper both work.
- Uneven or broken rows (title lettering, frame rules) are not staves, and a long beam between two
  lines does not hide a staff.

`PARTS_FEWER_THAN_STAVES` now has severity `info` (owner decision 2026-11-11) and says "the page has
N staves per system".

## Per-sample results

`tests/test_staff_estimate_samples.py` (integration) asserts the "Expected" column. Expected values
were read off each page by eye: the staves of the largest system, a piano part counting 2, an SA/TB
short score 2, a page without music 0. "Before" is the first version's count of all staves on the
page.

| Sample (pages) | Layout | Expected | Now | Before |
|---|---|---|---|---|
| CPDL Ave verum corpus, Byrd (p1–p4) | SATB, 1–3 systems | 4 | 4 | 8, 12, 8, 4 |
| CPDL If ye love me, Tallis (p1) | SATB, 4 systems | 4 | 4 | 16 |
| CPDL Locus iste, Bruckner (p1) | title page | 0 | 0 | 0 |
| CPDL Locus iste, Bruckner (p2–p3) | SA/TB short score, 5 systems | 2 | 2 | 10, 10 |
| CPDL Sicut cervus, Palestrina (p1–p4) | SATB, 2–3 systems | 4 | 4 | 8, 12, 12, 8 |
| musicxml.com Binchois | 2 staves, 2 systems | 2 | 2 | 4 |
| musicxml.com Chant | 1 staff | 1 | 1 | 1 |
| musicxml.com MozartPianoSonata | piano grand staff | 2 | 2 | 2 |
| musicxml.com MozartTrio | 5 staves, 2 systems | 5 | 5 | 10 |
| musicxml.com Saltarello | 1 staff, 3 systems | 1 | 1 | 3 |
| musicxml.com Telemann | voice + continuo, 3 systems | 3 | 3 | 9 |
| PDMX Qmb5Q3qc… (p1) | SATB, 3 systems | 4 | 4 | 12 |
| PDMX Qmb5f7tr… (p1) | SATB, 3 systems | 4 | 4 | 12 |
| PDMX Qmb6okFH… (p1–p3) | TTBB, 1–2 systems | 4 | 4 | 8, 8, 4 |
| PDMX Qmb6tNhk… (p1–p9) | 6 voices, 1–2 systems | 6 | 6 | 12 ×8, 6 |
| PDMX QmbLZoLJ… (p1) | SATB, 2 systems | 4 | 4 | 8 |
| PDMX QmbLZoLJ… (p2) | verses as text | 0 | 0 | 0 |
| PDMX QmbLrUid… (p1–p6) | SSATB, 2 systems | 5 | 5 | 10 ×6 |
| PDMX QmbbjE2Q… (p1–p4) | SATB + piano, empty staves hidden (systems of 3–6) | 6 | 6 | 10, 9, 12, 12 |
| PDMX QmbooFzW… (p1) | framed cover | 0 | 0 | 1 |
| PDMX QmbooFzW… (p2, p4, p11) | text, picture, copyright | 0 | 0 | 0 |
| PDMX QmbooFzW… (p3) | solo + SATB + piano, 2 systems | 7 | 7 | 14 |
| PDMX QmbooFzW… (p5–p10) | SATB + piano, 2 systems | 6 | 6 | 12 ×6 |
| PDMX QmbtpRoD… (p1–p3) | SATB, 1–3 systems | 4 | 4 | 8, 12, 8 |
| PDMX QmbuvFts… (p1–p2) | SATB, 1–3 systems | 4 | 4 | 12, 4 |

60 of 60 pages match. Before, 11 pages matched (the 1-system and no-music pages).

The first page of each musicxml.com PDF sample, rendered at 150 dpi with `pdftoppm` (not in the
test, since it needs poppler), also matches the staff count of its MusicXML: ActorPrelude 23
(orchestra), BrookeWest 2, Echigo-Jishi 1, and 3 (voice + piano) for the other nine songs.

## Degraded copies

The same 60 pages, changed before the estimate (script not committed; pages match the clean
result):

| Change | Match |
|---|---|
| Half size (about 620 px wide, 4–5 px line spacing) | 60/60 |
| 800 px wide | 60/60 |
| Rotated 0.2° | 59/60 |
| Rotated 0.5° | 59/60 |
| JPEG quality 40 | 60/60 |

The one miss in each rotated set is the framed cover (QmbooFzW… p1), which counts 1 instead of 0.
That cannot raise the warning against a recognized part.

## Limits

- Staves that an edition prints without a system line count as one-staff systems: no warning (a
  missed hint, never a false one).
- Phone photos with perspective or a curved page are not covered; only rotation is corrected.
- The estimate counts staves, not parts: a piano part has 2 staves, and a short score puts 2
  voices on one staff. That is why the warning is `info`.
- Each page takes about 50 ms (1240 × 1755 px).
