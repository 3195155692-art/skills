# Design system

The deck is "sandwich" structured: dark pages for the opening, the three act dividers and the
synthesis; light pages for content. One repeating element — a synthetic neural trace — binds
them, and every rectangle in the deck is rounded.

## Palette

```js
const C = {
  ink: "0A1A2F",       // dark slide background
  inkSoft: "13293F",   // card on a dark slide
  inkLine: "24405C",   // hairline on a dark slide
  navy: "17527A",      // primary
  navyDeep: "0F3A57",  // headings on light slides
  navyPale: "E7EFF6",  // tinted panel
  cyan: "2FB8C6",      // accent for engineering / method
  cyanDeep: "1B8C99",  // eyebrow text, emphasise on light
  cyanPale: "DCF1F3",
  amber: "D98A21",     // accent for clinical / human
  amberPale: "FCEEDA",
  paper: "F5F8FB",     // light slide background
  card: "FFFFFF",
  line: "DCE5EE",
  text: "16222E",
  sub: "5A6B7D",
  onDark: "EAF2F8",
  onDarkSub: "9FB4C7",
};
```

Reserve the two accents for meaning, not variety: cyan for method and engineering, amber for
clinical and human stakes, and one warm red (`E07A5F`) for the single most serious
distinction on a page. If a colour appears on every page it carries no information.

## Geometry

Slide 13.333 × 7.5 in (16:9). Side margin 0.62 in; content width 12.093 in.

- **Cards are rounded, with a radius of 0.13 in** — the macOS-window feel. Use the same
  radius everywhere; mixed radii read as a mistake.
- **Colour accents are capsules, not bars.** A rectangular strip flush with a rounded card's
  top edge pokes out past the corner. Draw accents as fully rounded capsules and inset them:
  top accent at `x+0.15, y+0.10, w-0.30, h 0.08`; left accent at `x+0.12, y+0.14, w 0.075,
  h-0.28`. Anything thinner than ~0.03 in should still be a capsule so no sharp corner
  survives anywhere in the deck.
- The only square-cornered element is the full-bleed strip at the very top of the cover and
  the act dividers, which must run edge to edge.
- Cards are white on light slides and `inkSoft` on dark ones, with a 1 pt border in `line`
  or `inkLine`. No shadows: they render inconsistently and buy nothing.

## Typography

Two faces, one job each: a CJK face for Chinese, a Latin face for English and numerals.
**Both must be installed on the presenting machine** — see `check_fonts.py`.

Anything the user asks for that is not installed should be reported, not silently swapped.
On macOS without Office, the available Simplified-Chinese hei faces are `Heiti SC` and
`Hiragino Sans GB`; `Microsoft YaHei` and `SimHei` are usually absent, and `Times New Roman`
is present.

The kit applies a global type scale (default 1.09) so that text fills its box rather than
floating in it. Keep text occupying well over half of its container: if a card is visibly
empty below the text, shrink the card rather than leaving a void.

**12 pt is the floor.** Nothing in a delivered deck goes below it — not captions, not band
lines, not the source-status footnote, not the reference list. The small text is the text
that carries the caveats, and it still has to be readable from the back of the room. When a
block cannot fit at 12 pt, the answer is fewer words, never 10 pt.

**Body text runs at 1.5 line spacing.** Set it as a percentage (`spcPct 150000`), not as
fixed points, so it scales with the type. Apply it to paragraphs that wrap to two or more
lines — and only to those. Line spacing is what happens *between* lines: a single-line label
has none, and setting 150% on one shifts the glyph down a quarter of a line into whatever
sits below it. That is how stat pages break, so the helpers skip single-line paragraphs.

Suggested sizes (before the scale multiplies them): slide title 27, section header 20–24,
card heading 12–16, body 12–13, caption 12. Big statistics 44–78 in the Latin face; the
statistic and its caption are the pair most often broken by a spacing change, so check them
by eye after any typography retrofit.

Two-column layouts beat four-column layouts for body text; four narrow columns are for
parallel short items only, and they need a shorter sentence than you think.

## Page archetypes

Every page should carry at least one non-text element. The recurring ones:

| Archetype | Use |
| --- | --- |
| Cover | Dark, motif across the lower third, title + one-line subtitle |
| Act divider | Dark, act number, name, English subtitle, one lead paragraph, a numbered list of what the act establishes |
| Outline | Three act cards with the move each act makes, and the through-line in a dark band |
| Stat page | One large number with its qualifier, supporting numbers beside it |
| Comparison | Two columns of equal weight; use a tinted card for the side the argument favours |
| Table | Two-column contrast tables for "old paradigm vs new"; alternate row tint, no gridlines |
| Flow | Capsule chain with `→` between steps; keep to five or six capsules |
| Ladder | Stacked rows for ordered levels, highlighting the rows the page is about |
| Close | Dark page with the conclusion band |

Per-paper slides end with a **conclusion band**: a `navyDeep` capsule card at y 6.14, height
0.90, with the label `汇报结论` in cyan and the line in bold white.

## Cover and headers

Cover: cyan full-bleed strip at the top, title 46, subtitle 21 in cyan, a short amber capsule,
then a meta line. Put the source/scope note in small dim text at the bottom.

Content pages: the neural-trace mark at the left of the header, eyebrow text in cyan, page
number at the right, title below, and a full-width hairline rule. Page numbers come from the
header helper, so act dividers and the cover stay unnumbered.

## Speaker notes

Write notes for every slide, including the ones that seem obvious. Notes carry what the slide
cannot: which numbers to read aloud, which caveat to state, which page to cut if time runs
short. Two to four sentences is right.
