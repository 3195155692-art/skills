---
name: lky-report-ppt
description: Build a Chinese group-meeting literature deck (组会汇报 / 文献汇报 PPTX) from local reading notes, a paper collection, or an existing generated deck. Covers the narrative structure, the rounded-card visual system, and a measurement-based QA loop that catches overflow, wrong fonts, and unrenderable glyphs without PowerPoint installed. Use when the user asks for 组会汇报 PPT, 文献汇报 slides, a research-talk deck, or wants such a deck revised. Do not use for one-page conference posters or for decks whose content is not grounded in source material.
license: MIT
metadata:
  version: "1.1.0"
---

# LKY report ppt

Produce a multi-slide PowerPoint report from local reading notes, and **verify the layout by
measurement rather than by hoping**. The deck is built by a script, then checked by three
independent programs before it is handed over.

The hard part of this job is not writing the slides. It is that a deck can look finished in
the generator and still be broken in three invisible ways: text that overflows its box, a
font the machine does not have, and Chinese text assigned to a Latin-only face. Those three
failures are what this skill exists to prevent.

## Non-negotiables

These have each caused a real defect. Do not relax them.

1. **Every declared font must be installed on the machine that will present the deck.** A
   font name written into a PPTX is a request, not a guarantee; an absent font is silently
   substituted and the layout you verified is no longer the layout they see. Check before
   designing, and tell the user plainly which face you used and why.
2. **Never put CJK text on a Latin-only face.** PowerPoint resolves East Asian glyphs from a
   run's `<a:ea>` face, and the generator sets that to the same name as `<a:latin>`. Chinese
   written with a Latin face renders as boxes. The kit's text helper guards this; keep the guard.
3. **Every number and claim in the deck traces to a source note.** Label your own reasoning
   as `本汇报推论` so it is never mistaken for an author's conclusion. Do not delete a note's
   honesty callouts (a weak control group, an internal numeric inconsistency, an abstract-only
   source) to make the story cleaner.
4. **Do not overwrite the user's edits.** After handing over a deck the user may edit it by
   hand. Re-read the existing file before regenerating, and reconcile rather than replace.
5. **Nothing smaller than 12 pt.** A deck is read from the back of a room, and the small
   text is the text that carries the caveats. Captions, footnotes, band lines, reference
   lists and source-status lines all sit at 12 pt or above; if the smallest text cannot fit
   at 12 pt, cut words, not points.
6. **Body text is 1.5 line spacing, and only text that wraps gets it.** Line spacing is what
   happens *between* lines: setting 150% on a one-line label has no typographic meaning and
   only drops the glyph a quarter of a line into whatever sits below it — which is how stat
   pages break. Multi-line paragraphs get 1.5; single-line labels keep their own spacing.

## Workflow

### 1. Inventory the sources

Read the notes, not just their titles. For a collection, extract per paper: the headline
numbers with their qualifiers, the authors' own stated limits, and the one-line takeaway.
Note which papers are abstract-only so the deck can say so.

### 2. Choose the narrative before the slides

A literature report is an argument, not a table of contents. Read
[references/narrative-structure.md](references/narrative-structure.md) and settle on the
through-line first; the slide list falls out of it. For a multi-paper report, prefer acts with
divider pages over a flat paper-by-paper sequence.

### 3. Confirm the environment before designing

```bash
python3 scripts/check_fonts.py --deck /dev/null --want "Heiti SC,Times New Roman" --list
```

Establish which CJK and Latin faces actually exist. Pick the closest installed face to what
the user asked for and say so explicitly. Then locate the bundled runtimes:
`load_workspace_dependencies` gives the Node and Python paths, and `pptxgenjs` lives in the
Node runtime's `node_modules`.

### 4. Build with the kit

```js
const pptxgen = require("<node-runtime>/node_modules/pptxgenjs");
const kit = require("./deck_kit")(pptxgen, { cjk: "Heiti SC", latin: "Times New Roman" });
```

`scripts/deck_kit.js` provides the presentation, the palette, the type scale, and the slide
helpers (rounded cards, capsule accents, act dividers, per-paper conclusion bands, headers,
bullets, speaker notes). Read [references/design-system.md](references/design-system.md)
before laying out pages, and [references/pptxgenjs-gotchas.md](references/pptxgenjs-gotchas.md)
before writing generator code — several of those traps corrupt the file silently.

Write the generator as a file in a tooling directory (a dot-prefixed folder inside the
project, or a directory outside the vault), never inline in a shell command: the user will
want to re-run it.

### 5. Run the three gates

```bash
python3 scripts/check_layout.py --deck deck.pptx     # overflow, out-of-bounds, collisions
python3 scripts/check_fonts.py  --deck deck.pptx     # declared faces, glyph coverage, consistency
python3 scripts/render_deck.py  --deck deck.pptx --out /tmp/preview
```

The first two must report zero blocking findings. The third produces one PNG per slide for a
human look — always view the contact sheet, then open the densest pages full size. See
[references/qa-loop.md](references/qa-loop.md) for what each gate does and does not prove,
and for the package check to run last.

### 6. Hand over

Report the deck path, the slide count, the font faces used and whether they are installed,
and what the checks did and did not verify. If a font the user asked for is unavailable, say
so and offer the one-line switch rather than substituting silently.

### 7. Retrofit rules onto a deck that already exists

When the user comes back *after* the build with a typographic rule — "1.5 line spacing",
"nothing smaller than 12" — do not regenerate: they have edited the file by hand by then and
a rebuild throws that away. Retrofit the saved package instead:

```bash
python3 scripts/retrofit_typography.py --deck deck.pptx \
    --min-size 12 --line-spacing 1.5 \
    --substitute "SimHei=Heiti SC,黑体=Heiti SC"      # measure-only, never written
```

It raises the runs, respaces the paragraphs that wrap, re-fits every box it moved, and prints
the boxes whose own spacing had to be eased. Read
[references/deck-retrofit.md](references/deck-retrofit.md) before running it; the order of
operations and what to report back are both there.

## Reference routing

| Read this | When |
| --- | --- |
| [references/narrative-structure.md](references/narrative-structure.md) | Before deciding the slide list |
| [references/design-system.md](references/design-system.md) | Before laying out any page |
| [references/pptxgenjs-gotchas.md](references/pptxgenjs-gotchas.md) | Before writing generator code, and whenever the file fails to open |
| [references/deck-retrofit.md](references/deck-retrofit.md) | Before changing type rules on a deck that already exists |
| [references/qa-loop.md](references/qa-loop.md) | Before declaring the deck finished, or when a check reports something |

## Scripts

```bash
# Reusable generator kit (rounded cards, capsule accents, act dividers, conclusion bands)
scripts/deck_kit.js

# Generate the neural-trace motif used as the deck's single repeating visual element
python3 scripts/make_motif.py --out assets

# Layout: text overflow, shapes outside the slide, text boxes overlapping each other
python3 scripts/check_layout.py --deck deck.pptx

# Fonts: <a:ea> coverage, CJK-on-Latin-face, non-installed faces, mixed CJK faces
python3 scripts/check_fonts.py --deck deck.pptx
python3 scripts/check_fonts.py --want "Heiti SC,Times New Roman" --list

# Retrofit a type rule (min size, line spacing) into an existing, hand-edited deck
python3 scripts/retrofit_typography.py --deck deck.pptx --min-size 12 --line-spacing 1.5

# Preview: rasterise the saved deck to one PNG per slide (no PowerPoint required)
python3 scripts/render_deck.py --deck deck.pptx --out /tmp/preview [--dpi 130]
```

All three checkers read the saved `.pptx` and never modify it. They require Pillow; the
preview renderer additionally needs the font files it is asked to draw with.

## Package sanity check

If the `pptx` skill is available, finish with its non-executing package validator, which
catches schema, relationship and content-type faults that a visually correct deck can still
carry:

```bash
python3 ~/.codex/skills/pptx/scripts/office/validate.py deck.pptx
```
