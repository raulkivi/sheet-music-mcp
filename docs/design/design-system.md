# Kannel: visual identity and design system for the MCP Apps

**Last changed:** 2026-11-11
**Source:** https://github.com/raulkivi/sheet-music-mcp

**Status:** Proposal, with mockups and tokens. Not yet adopted by the shipped Score Viewer.
**Scope:** The seven MCP Apps in [docs/research/mcp-apps-ux-proposal.md](../research/mcp-apps-ux-proposal.md)
(Score Viewer, Practice Player, Recognition Review, ABC Workbench, Practice Coach, Diff Viewer, Setup Doctor).
**Files:**

| File | What it is |
|---|---|
| [tokens.css](tokens.css) | The design tokens. Source of truth for colour, type, radius. Tested by `ui/test/theme/brand-tokens.test.ts` |
| [interactive/](interactive/README.md) | **Canonical** mockups: clickable Design canvas source, one artboard per app |
| [mockups/index.html](mockups/index.html) | Gallery of the seven static mockups, light and dark. **Superseded** by `interactive/` |
| [mockups/mockup.css](mockups/mockup.css) | Shared chrome for the superseded static mockups (not part of any app) |
| `mockups/*.html` | Superseded: one static mockup per app, at phone width and desktop width |

---

## 1. The idea

**Kannel** is the working name for the family of apps. The *kannel* is the Estonian lyre, the instrument
that has accompanied sung folk poetry for centuries. It fits a choir tool: the score is the hero, the
voices are many and equal, and the singer's own voice is the thing the apps listen to.

Four principles follow from that:

1. **The score is the hero.** Chrome is quiet and flat. Colour goes to the things the singer acts on
   (play, the playhead, the in-tune marker, a change to review), never to decoration on the notation.
2. **Many voices, one system.** Parts (soprano, alto, tenor, bass) are equal citizens with the same
   chip, meter and mark. No part gets its own brand colour.
3. **Festival warmth in small doses.** The Song Festival is massed, joyful and public. The identity
   borrows its warmth from one gold marker, a linen ground and a single tricolour bar, not from
   large illustrations.
4. **Plain words, real text.** Every state has a word as well as a colour and a shape. Estonian
   diacritics (ä ö õ ü š ž) render in the system font, so Estonian labels work without a web font.

## 2. Inspirations and what we took from them

| Inspiration | What we took | Where it shows | What we did not take |
|---|---|---|---|
| **Estonian flag**: blue, black, white, in that order top to bottom | Flag blue `#0072CE` is the accent. Black becomes the ink (`#15171C`). White is the ground. The three-band tricolour is the top edge of every app. | Header bar, primary buttons, focus ring, links | The flag itself or its proportions as a logo. The state flag and arms are protected by Estonian law; check before any official or commercial use. |
| **Coat of arms**: three blue lions on gold | The gold, darkened to `#B7850F` on white and brightened to `#F2C14E` on dark, for the **playhead, the in-tune marker and the current note**. Gold means "here, now". | Practice Player playhead, Practice Coach meter centre, Score Viewer current page | The lions. No animal from the arms appears in any app. |
| **Cornflower** (*rukkilill*), national flower | The light blue tint `#EAF2FB` (dark `#1B2B40`) for selected rows, quiet panels and the "in tune" background. | Chip selected state, Diff Viewer selected change, Setup Doctor OK rows | The flower as an ornament. It is too literal for a score. |
| **Barn swallow** (*pääsuke*), national bird | The swallow is the **health and setup** mark: the Setup Doctor icon. Its forked tail reads as "check". | Setup Doctor header and icon | Any use as decoration. |
| **Kannel** (lyre) and the festival's **lyre motif** in the Song Festival emblems | The lyre is the family icon (Practice Player, the app launcher mark). | Practice Player icon, product mark | The Song Festival emblems themselves. Each festival commissions a new design, and those emblems are not ours to reuse. |
| **Folk ornament and brooch** (*rahvuslik ornament*, the brooch motif in the 2019 jubilee logo) | Geometry, not pictures: a small diamond-and-triangle repeat used as a divider at most once per app, on empty states and the end of a practice session. | Empty states, end-of-practice card, Setup Doctor footer | Full-width patterns. They compete with the score. |
| **Song Festival** (*Laulupidu*): massed choirs, the shell stage, the sung anthem | "Many voices, one system": equal part chips and meters. The festival's sense of a crowd singing together shows as a row of equal voice chips, not as a crowd. The festival's own colours and motifs are not reused. | Practice Player part row, Practice Coach part selector | Stage imagery and crowd photos. Apps do not need them and they cost bytes and CSP budget. |

## 3. Colour

### 3.1 Palette

Contrast is WCAG 2.2, computed for the values in [tokens.css](tokens.css). The test
`ui/test/theme/brand-tokens.test.ts` enforces the same pairs.

| Token | Light | Dark | Role |
|---|---|---|---|
| `--kannel-flag-blue` | `#0072CE` | `#0072CE` | Flag blue, the reference colour |
| `--kannel-flag-black` | `#15171C` | `#15171C` | Flag black, reference (used as light text) |
| `--kannel-flag-white` | `#FFFFFF` | `#FFFFFF` | Flag white, reference |
| `--kannel-accent` | `#0072CE` | `#0072CE` | Primary button fill (white label 4.89:1) |
| `--kannel-accent-pressed` | `#00508F` | `#00508F` | Pressed primary (white label 8.25:1) |
| `--kannel-accent-text` | `#005FAE` | `#7FBCF5` | Links and active tab text (6.47:1 and 9.29:1) |
| `--kannel-tint` | `#EAF2FB` | `#1B2B40` | Cornflower tint for selected rows and quiet panels |
| `--kannel-marker` | `#B7850F` | `#F2C14E` | Gold for playhead, in-tune and current note (3.29:1 and 11.16:1) |
| `--color-background-primary` | `#FFFFFF` | `#101217` | Page |
| `--color-background-secondary` | `#F4F6FA` | `#1A1E27` | Toolbar and panels |
| `--color-text-primary` | `#15171C` | `#EEF2F7` | Body text (17.93:1 and 16.66:1) |
| `--color-text-secondary` | `#4B5563` | `#B4BDCB` | Labels, captions, button edges (7.56:1 and 9.89:1) |
| `--color-border-primary` | `#D5DCE6` | `#2E3645` | Separators (not required to be a mark) |
| `--color-ring-primary` | `#0072CE` | `#6CB4F0` | Focus ring (4.89:1 and 8.41:1) |
| `--kannel-success-*` | text `#1E6B3A`, tint `#E4F2E8` | text `#8FD3A4`, tint `#17301F` | Pass, in tune in a report (5.64:1 and 8.13:1) |
| `--kannel-warning-*` | text `#7A5300`, tint `#FBF0D2` | text `#F2C14E`, tint `#3A2D0C` | Check this, a soft issue (6.04:1 and 8.02:1) |
| `--kannel-danger-*` | text `#A8322D`, tint `#F9E3E1` | text `#F09A94`, tint `#3A1C1A` | Error, must fix (5.41:1 and 7.17:1) |

### 3.2 Rules

- **Colour is never the only signal.** Every status pairs colour with a word and an icon or shape.
  Diff marks use a solid stroke for "only in edition A" and a dashed one for "only in edition B" as
  well as the two blues.
- **Text on tints uses the text token, never the accent.** `--kannel-accent` is a fill.
  `--kannel-accent-text` is the text colour for links.
- **Gold is a mark, not text.** It reaches 3:1 for shapes and lines. Use `--kannel-warning-text` for
  gold-coloured words.
- **Host colours win.** An MCP Apps host sends its own `--color-*` values. The Kannel values are the
  fallback for hosts that send none (see §8).

## 4. Typography

- **Family:** the system UI stack (`--font-sans`) and a monospace stack (`--font-mono`) for ABC text,
  MusicXML and IDs. **No web fonts.** MCP Apps pages are self-contained and the default CSP blocks
  external font files. System fonts carry Estonian diacritics.
- **Scale:** 12 · 14 · 16 · 20 · 24 · 32 px. Body is 14 px in tools and 16 px on phones. Line
  height 1.4 for body, 1.2 for headings.
- **Weights:** 400 for text, 600 for labels and headings, 700 only for the single number on a
  meter or a page counter.
- **Numbers:** `font-variant-numeric: tabular-nums` for page numbers, bar numbers, cents and BPM so
  they do not jitter while updating.

Specimen (Estonian diacritics must render): *Hääldus on õige. Šveits, Žanr, Mõõt 12, Jätka.*

## 5. Space, shape and motion

- **Spacing:** a 4 px base. Steps 4, 8, 12, 16, 24, 32. Panel padding 12 px on phones, 16 px on desktop.
- **Radius:** 6 px for controls (`--border-radius-md`), 10 px for panels, full round for chips and
  the playhead.
- **Touch targets:** 32 px minimum on pointer devices; 40 px when `deviceCapabilities.touch` is set.
  The Score Viewer's current 32 px buttons become 40 px on touch hosts.
- **Motion:** the playhead and the meter needle move without easing (they track audio). Other
  transitions are 120 ms. Under `prefers-reduced-motion: reduce` every transition is off and the
  playhead jumps by measure instead of sliding.

## 6. Iconography

- **Grid:** 24 px, 2 px padding, 1.75 px stroke, round caps and joins, `currentColor`. No fills except
  the playhead and the meter needle.
- **Set:** drawn for this system; the mockups inline them as SVG so they cost no request.

| Icon | Used for | App |
|---|---|---|
| Staff with notes | Score, page | Score Viewer, Recognition Review |
| Scan frame with note | Photo, recognition | Recognition Review |
| Kannel (lyre) | Practice, the product mark | Practice Player, launcher |
| Microphone | Live listening | Practice Coach |
| Two staves and an arrow | Compare, diff | Diff Viewer |
| `abc` in monospace | ABC text | ABC Workbench |
| Swallow | Health and setup | Setup Doctor |
| Cornflower (five petals) | Pitch, in tune | Practice Coach (reserved: not yet drawn in the mockups) |
| Waveform | Audio render | Practice Player (reserved: not yet drawn in the mockups) |

Music icons follow the same grid: note heads, stems, flags, rests, clefs. Use them for the score and
the part chips, not as decoration.

## 7. Motifs and ornament

- **Tricolour bar:** a 3 px bar across the top of every app: blue, black, white, top to bottom,
  as in the flag. It is the identity's signature and appears once per app.
- **Ornament band:** the diamond-and-triangle divider, 12 px tall, in `--kannel-tint`. Use at most
  once per app, on an empty state or the end of a practice session. Never behind the score.
- **Playhead and needle:** gold (`--kannel-marker`), 2 px, the only saturated element on the page
  besides the primary button.

## 8. How the tokens reach a host

1. The host sends its theme variables (`--color-background-primary`, `--font-sans`, …). They override
   the Kannel values with the same names.
2. The app reads only the host-compatible names for surfaces and text. Brand names (`--kannel-*`)
   are used for the accent, status, marker and tint. Hosts never send them, so they always apply.
3. With no host variables, the Kannel values in `tokens.css` apply. Those are the fallback values
   the kit's `theme.ts` should adopt (follow-up, see §11).
4. Dark mode: `data-theme="dark"` on `<html>` (set by the kit from `hostContext.theme`), with the
   `prefers-color-scheme` block as the fallback. The two blocks are identical in `tokens.css`.

## 9. Accessibility

- Text 4.5:1, marks and focus 3:1, in both themes (tested for every pair in §3.1).
- Visible focus ring on every control (`--color-ring-primary`, 2 px, 1 px offset).
- No sideways scroll at 360 px. Toolbars wrap; the score scrolls inside its own panel.
- Every icon-only button has an `aria-label`. Live values (page number, cents, status) use
  `aria-live="polite"`, and the meter's text (`+12 cents, sharp`) is what a screen reader reads.
- Keyboard: Tab reaches every control; Space and Enter activate; arrow keys step the playhead and
  the page.

## 10. Applying the system to each app

Each mockup shows one app at phone width (360 px) and desktop width (1280 px), in both themes.

| App | Mockup | Interactive source | Signature element |
|---|---|---|---|
| Score Viewer (built, render-mcp) | [score-viewer.html](mockups/score-viewer.html) | [ScoreViewer.dc.html](interactive/ScoreViewer.dc.html) | Page controls and the score panel |
| Practice Player (synth-mcp) | [practice-player.html](mockups/practice-player.html) | [PracticePlayer.dc.html](interactive/PracticePlayer.dc.html) | Part chips, gold playhead, tempo |
| Recognition Review (omr-mcp) | [recognition-review.html](mockups/recognition-review.html) | [RecognitionReview.dc.html](interactive/RecognitionReview.dc.html) | Scan beside score, issue list |
| ABC Workbench (musicxml-abc-mcp) | [abc-workbench.html](mockups/abc-workbench.html) | [AbcWorkbench.dc.html](interactive/AbcWorkbench.dc.html) | Original and proposed panes, change marks |
| Practice Coach (pitch-mcp) | [practice-coach.html](mockups/practice-coach.html) | [PracticeCoach.dc.html](interactive/PracticeCoach.dc.html) | Pitch meter with gold centre |
| Diff Viewer (comparer-mcp) | [diff-viewer.html](mockups/diff-viewer.html) | [DiffViewer.dc.html](interactive/DiffViewer.dc.html) | Change list with solid and dashed marks |
| Setup Doctor (all) | [setup-doctor.html](mockups/setup-doctor.html) | [SetupDoctor.dc.html](interactive/SetupDoctor.dc.html) | Swallow mark, fix-it steps |

Interactive sources need the Design runtime and do not render on GitHub. The static mockups open directly in a browser.

## 11. Decisions, open questions and follow-ups

| # | Item | Status |
|---|---|---|
| D1 | Working name **Kannel** for the family | Proposed. Rename freely; the tokens and file names do not depend on it |
| D2 | The wolf is not used as the national animal | Its status as national animal is unconfirmed (only one source, a travel guide). Excluded until checked against an official source |
| D3 | Kit fallback (`packages/kit/src/theme.ts`) adopts these values | Follow-up. Changing it moves the Score Viewer's contrast tests, so do it in its own change |
| D4 | Estonian UI labels | Open. The mockups use English labels with Estonian specimen text. Ask whether the apps should ship Estonian strings |
| D5 | Official use of the flag or arms | Excluded. Check Estonian law on state symbols first |
| D6 | Visual regression screenshots of the mockups | Not in scope here; the axe and contrast checks are automated |

**Follow-ups, in order:** adopt the tokens in the kit (D3); add the Kannel tricolour and focus ring to
the Score Viewer e2e chrome checks; then build the next app from the mockup, with its spec file
(ui/README.md, U8).

## 12. Sources

- Estonian national symbols (flag, arms, bird, flower):
  [Wikipedia: National symbols of Estonia](https://en.wikipedia.org/wiki/National_symbols_of_Estonia),
  [Baltic Guide: national symbols](https://balticguide.ee/en/estonias-national-symbols-also-tell-us-something-about-the-nature-of-the-people/).
  Selection dates for the bird and flower vary between sources; they are not used in the design.
- Song Festival visual identity:
  [2025 Song Festival: visuals and values](https://2025.laulupidu.ee/en/visuals-and-values),
  [2023 Song Festival: visual identity](https://2023.laulupidu.ee/en/newsletter/visual/),
  [Estonian Song Celebrations 1869–2019: commented emblem designs](https://etdm.ee/en/naitused/estonian-song-celebrations-1869-2019-commented-emblem-designs).
  These describe the lyre motif, the sequence-number ornament and the brooch reference in the emblems.
  The emblems themselves are not reused.
- Palette values and contrast: computed for [tokens.css](tokens.css) (WCAG 2.2 relative luminance); enforced by `ui/test/theme/brand-tokens.test.ts`.
