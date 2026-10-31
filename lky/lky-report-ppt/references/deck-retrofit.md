# Retrofitting a type rule onto a finished deck

The deck exists, the user has opened it, edited it, saved it, and now asks for a typographic
rule: "1.5 line spacing", "nothing smaller than 12 pt", "the text should fill the box more".
Regenerating is not an option — their file is the source of truth and a rebuild silently
discards everything they did. Retrofit the package instead.

`scripts/retrofit_typography.py` does the mechanical part. This file is the judgement that
surrounds it.

## Order of operations

1. **Re-read their file, and find out what they changed.** Diff the *text* of every slide and
   notes page against your last hand-over, whitespace-stripped and per slide. Not everything
   that changed is an edit (see `pptxgenjs-gotchas.md`) — but deletions, reordered slides, a
   unified font and a resized number are. Knowing this tells you which slides are safe to
   touch: a page they reorganised must not be re-flowed by accident.
2. **Re-baseline the gates.** Run `check_layout.py` on their file *before* changing anything
   and keep the count. Every finding after the retrofit is compared against that number;
   findings that were already there are theirs, not yours, and must be reported as
   pre-existing rather than "fixed".
3. **Pick a measurement substitution for faces that are not installed.** A face the machine
   lacks cannot be measured, so the retrofit would skip exactly the text it is meant to fix.
   `--substitute "SimHei=Heiti SC,黑体=Heiti SC"` maps them for measurement only; the file
   keeps the original names. Say plainly in the hand-over that the substitution was for
   measuring.
4. **Run the retrofit**, then re-run all the gates, then render.
5. **Look at every page the script reported**, plus the stat pages and the densest pages —
   those are where a spacing change shows.

## The rules that keep it from breaking the deck

- **Line spacing belongs to paragraphs that wrap.** A single-line label has no line spacing;
  150% on a one-line box only pushes the glyph down about a quarter of a line, into whatever
  sits below it. This is what wrecks stat pages: a 84 pt number in a 1.35 in frame needs
  2.11 in at 150% and collides with its own caption. Set the spacing on multi-line paragraphs
  and leave single-line labels alone; the file then reads as "1.5 spacing" to anyone who
  selects the body text, and nothing shifts.
- **Measure the region the text occupies, not the frame.** A top-anchored text box does not
  move its text when its frame grows, so enlarging a frame fixes the file's self-consistency
  and *never* relieves a collision. Only lifting the box (changing `y`) or easing its spacing
  moves the text.
- **Fit in this order, per box:** grow the frame → lift the box if there is room above →
  ease *that one box's* spacing (150 → 145 → … → 100) → report it as unresolved. Bound every
  move by the card the box sits in (the smallest filled shape containing it) and by the
  neighbouring text rectangles in the same column.
- **Never shrink type to silence a checker**, and never touch a box the pass did not change.
  A pre-existing `OVERFLOW` on a page the user hand-tuned is information, not a task.
- **Easing a box is a reportable event**, not a silent repair. Print the page, the text and
  the value it had to fall back to.

## What to report back

- the rule applied, and the counts: how many runs were raised, how many paragraphs respaced;
- every box that could not take the full spacing, with its page and its fallback value;
- the before/after gate counts, and which residual findings pre-date the change;
- that the text is unchanged (prove it: whitespace-stripped per-slide diff against the
  pre-retrofit file) and that only typography and box geometry moved;
- the backup path.

## When a page still does not fit

A page that cannot hold its text at the requested size and spacing is telling you it has too
many words. The fix is a content edit — drop a clause, move a row to its own page, cut one of
five bullets — and that is the user's call, not a silent font reduction. Offer it explicitly,
page by page, and let them choose.

## Retrofit vs. rebuild

Reach for the retrofit when the change is a *rule* (size, spacing, colour of a band, a
renamed section). Reach for a rebuild only when the change is a *structure* (new act,
re-ordered argument, a paper added or removed) — and even then, reconcile against their file
rather than starting from the notes again.
