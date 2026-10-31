# pptxgenjs gotchas

Traps that produced a broken or wrong file during this workflow. Each one failed quietly, so
read this before writing generator code.

## Fonts

- **`fontFace` sets only `<a:latin>`.** pptxgenjs copies the same name into `<a:ea>` and
  `<a:cs>`. A Chinese string on a Latin-only face (Arial, Times New Roman) therefore asks
  PowerPoint for Chinese glyphs from a font that has none, and renders boxes. Guard every
  text helper: if the string contains `[\u4e00-\u9fff]` and the requested face is the Latin
  one, promote it to the CJK face. `check_fonts.py` catches regressions.
- A missing font is substituted silently. Verify the face is installed before choosing it.

## Colour

- **Never** write `#` in a hex colour, and never bake alpha into a hex string like
  `"00000020"` — an 8-digit value corrupts the file. Translucency goes through
  `transparency: 0-100` for fills and images, `opacity` for shadows, and each is ignored on
  the other.

## Text boxes

- A text box has internal padding. Pass `margin: 0` whenever text must line up with a shape
  or a rule at the same x.
- Set the slide size with `pres.defineLayout({name, width, height})` **before** adding
  slides. The default `LAYOUT_16x9` is 10 × 5.625 in, not 13.333; coordinates past the edge
  are written, not clamped, so the shape simply is not on the slide.
- `shrinkText: false` keeps the size you asked for. Relying on autofit to rescue a too-small
  box makes the deck look different on every machine.
- Bullets: pass `bullet: true` (or a bullet object) per paragraph, never a literal `•`.
- **A trailing empty bullet appears if the last paragraph of a bullet list sets
  `breakLine: true`.** Set `breakLine` on every item except the last.

## Shapes

- `rectRadius` applies only to `roundRect`. pptxgenjs converts it to an `adj` value of
  `radius / min(w,h) * 100000`, clamped at 50000 — so a capsule is
  `rectRadius: min(w, h) / 2`, and a rounded accent thinner than about 0.03 in becomes a
  stadium rather than a rounded rectangle.
- `rectRadius` is not relative to the shape size in any useful way; a radius larger than half
  the short side is clamped, which is why the accent capsules in this system are inset
  instead of sitting flush on a rounded card's edge.

## Charts

- Keep charts native (`addChart`). A rendered image of a chart cannot be edited and is not
  searchable.
- Default charts render bare: set `showTitle`, a `title`, `chartColors`, and quiet the axes
  (`valGridLine`, `catGridLine: {style: "none"}`, label colours).
- `dataLabelPosition: "outEnd"` **corrupts the file on a stacked bar or column chart**. Use
  `ctr`, `inEnd` or `inBase` there.
- A combo chart using `secondaryValAxis` needs both `valAxes` and `catAxes`, two entries
  each; otherwise the library writes axis ids it never declares and PowerPoint discards the
  chart.

## Package

- One `new pptxgen()` per output file.
- pptxgenjs mutates the option objects you pass (converting to EMU on first use). Build a
  fresh object per call; never share one across two `add*` calls.
- Never reorder the children of `<p:presentation>`. pptxgenjs writes `<p:notesMasterIdLst>`
  immediately after `<p:sldIdLst>` and PowerPoint reads that happily; move it and the same
  deck stops opening.
- After `writeFile()`, run the package validator (see `qa-loop.md`). It reports the chart
  faults above and the slide-XML defects PowerPoint refuses to open.

## Working with a deck the user has already edited

**A face the machine does not have cannot be measured.** `font_index.resolve()` returns
`None`, the checkers report the text as unmeasurable and warn — and an auto-fit built on top
of them then silently skips exactly the text it was supposed to fix. Map the missing name to
an installed face *for measurement only* (`--substitute "SimHei=Heiti SC,黑体=Heiti SC"`);
the file keeps the original name, and the hand-over says so.

A round-trip through PowerPoint or WPS changes the file in ways that are not edits:

- paragraphs are re-wrapped into more `<a:t>` runs, so a naive text diff reports thousands of
  changes that are not changes. **Compare whitespace-stripped, per-slide concatenated text**
  instead.
- identical images are de-duplicated, so the media count drops sharply. That is normal.
- shape order inside a slide can change.
- **text boxes are grown to fit their content**, so a box that was 0.62 in tall comes back
  2.10 in tall. The text does not move (it stays top-anchored), but the boxes now overlap.
  Any collision check must therefore compare the region the *text* occupies, not the shape
  outline, or a clean deck reports a dozen phantom collisions.
- paragraphs come back with real indents: `<a:pPr marL="342900">` is **EMU (0.375 in)**, not
  points and not pixels. A renderer that treats `marL` as pixels computes a negative wrap
  width, puts one character per line, and draws the whole block off the right edge of the
  slide. This only surfaces on round-tripped files, so it is easy to ship a renderer that
  silently blanks out bulleted lists.
- line spacing becomes a percentage (`<a:spcPct val="100000"/>`) instead of point spacing.
  Treat 100000 as 100% of the font's natural line height (~1.2 em) when measuring.

To find real edits, compare normalised text, and treat anything that survives normalisation as
intentional.

## Glyph coverage

A font is not guaranteed to contain every character the deck uses. Small marks are the usual
culprits: `▸ ▪ ✓ ✕ ▍ ① ②`. A missing glyph renders as a box, and no layout check will catch
it — only comparing each character against the resolved font file will. `check_fonts.py` does
this per face; run it after changing a font, and again after any round-trip, because a
substituted face may lack something the original had.
