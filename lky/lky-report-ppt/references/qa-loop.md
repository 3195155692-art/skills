# The QA loop

There is usually no PowerPoint or LibreOffice available to render the deck, so "look at it and
see" is not an option. Instead, verify the saved file by measurement: read the actual
geometry, run properties and glyph coverage out of the `.pptx`, and compare them against the
font metrics.

Three gates, in this order. The first two must report **zero blocking findings**.

## Gate 1 — layout (`check_layout.py`)

Re-measures every text box straight out of the package: it reads the shape geometry and run
properties, wraps the text with the same font file the deck requests, and compares the
required height against the box height.

| Finding | Meaning |
| --- | --- |
| `OVERFLOW` | text needs more room than the shape has — a real defect |
| `BOUNDS` | shape sits outside the slide |
| `COLLIDE` | two text boxes overlap; usually a band or footnote placed too low |
| `TIGHT` | less than 6% slack; review, not necessarily wrong |

Fix overflow by shortening the text, enlarging the box, or moving the element — not by
shrinking the type until the checker stops complaining.

The checker does not know which card a text box sits on, so it cannot tell that text spills
past a card's bottom edge rather than its own box. Check the tallest cards by eye in the
preview.

Two known false positives, both harmless but easy to chase for an hour:

- **Right-aligned text.** The collision check uses the box's full width, not the pixels the
  glyphs occupy, so a right-aligned tag ("全文", "摘要级", "临床可用") sharing a row with a
  left-aligned heading reports an overlap that does not exist. Look at the preview before
  "fixing" it.
- **A single-line box in a frame sized for older line spacing.** When the frame is invisible
  and the text is one line, `OVERFLOW` means "the file's numbers disagree", not "something
  looks wrong". Fixing it is still worth doing — a grown frame is self-consistent and easier
  for the next person to edit — but it is not a crisis.

## Gate 2 — fonts (`check_fonts.py`)

Four independent questions, all of which have failed in practice:

1. **Is every declared face installed?** A missing font is substituted silently.
2. **Does every run have an `<a:ea>` face?** A run with only `<a:latin>` inherits the theme's
   East Asian font and drifts from the design.
3. **Is any CJK text on a Latin-only face?** This renders as boxes.
4. **Does the deck use one CJK face throughout?** Editing a deck by hand and selecting "all
   text" on some slides but not others leaves a mixture; the pages then disagree with each
   other and it is invisible until the deck is projected.

## Gate 3 — preview (`render_deck.py`)

Rasterises the saved package with Pillow: shapes, fills, lines, pictures and every text run,
using the same font files the deck requests. It is a faithful read of the file, not a
redraw of the intent.

View the contact sheet first for rhythm and consistency, then open the densest pages at full
size. Things to look for that the checkers cannot see:

- a card that is visibly empty in its lower half;
- an accent that collides with a rounded corner;
- a table row whose text wraps to a second line and unbalances the row;
- a page that reads as a wall of text.

The renderer draws whatever the file says. If a glyph shows as a box in the preview, it will
show as a box in PowerPoint too.

## Gate 4 — package (`validate.py`)

Last, the non-executing ZIP/XML validator from the `pptx` skill:

```bash
python3 ~/.codex/skills/pptx/scripts/office/validate.py deck.pptx
```

It catches schema, relationship and content-type faults in a deck that renders perfectly.

## What this loop does not prove

Say this when handing over, so nobody over-trusts the result:

- **Text fit is measured against the font files on this machine.** If the presenting machine
  substitutes a different font, fit can change.
- **No check verifies scientific accuracy.** Numbers, citations and their qualifiers come from
  the source notes and must be read back against them by a human.
- **The preview is an approximation of PowerPoint's renderer.** Character positioning is
  close, not identical; kerning and vertical centring differ slightly.
- **Accessibility and print output are untested.** If the deck will be printed or exported to
  PDF, that export must be checked separately.

## When the user edits the deck by hand

Treat their file as the source of truth. Re-read it, and:

1. run the three gates against **their** file — a hand edit can introduce an overflow or a
   partial font change;
2. normalise whitespace before diffing text, or the re-wrap will bury the real edits;
3. keep their edits in any regeneration, or tell them explicitly that a fresh build would
   discard them.

Two more things learned the hard way, both of which change what you do next:

4. **Page numbers the user quotes may not be slide indices.** They are reading a viewer that
   numbers pages its own way (in this deck: one off, because the cover is not counted).
   Reconcile by *content* — match the concept or the paper they named against each slide's
   text — before editing anything, and say which slide you concluded they meant.
5. **Their file can change between turns.** Slides get deleted, reordered, duplicated; the
   font gets unified by a select-all. Re-inventory the deck at the start of every round
   (slide count, slide order, declared faces) instead of trusting the file you handed over.

## Changing typography on a finished deck

Any retrofit (size floor, line spacing, colour) is measured against a **baseline**: run the
gates on the user's file first and keep the count, then run them again afterwards. Report the
delta, and name the findings that pre-date the change instead of presenting a smaller number
as if you had fixed them. `references/deck-retrofit.md` has the full procedure;
`scripts/retrofit_typography.py` implements it.

One API trap, because it silently produces a no-op: `check_layout.analyse()` returns
`(findings, unmeasured_faces)` — the second value is a **set of face names that could not be
measured**, not the list of text rectangles. A fitter built on the assumption that it is a
list of boxes iterates an empty set, decides every box is fine, and changes nothing at all.
Compute the rectangles yourself (`retrofit_typography.rects()`), or import that module.

Also remember what a retrofit cannot see: if the requested size and spacing leave a page with
more words than room, the honest answer is a content edit. Offer it page by page instead of
quietly dropping the type back down.
