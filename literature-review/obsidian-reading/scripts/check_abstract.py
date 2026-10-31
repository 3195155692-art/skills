#!/usr/bin/env python3
"""Verify that each note's frontmatter `摘要` is a full translation of the paper's abstract.

The frontmatter abstract is the one field where "close enough" is not good enough: it is a
translation, so it carries every sentence and every statistic of the source abstract. This
script compares the two mechanically. It cannot judge prose quality, but it catches the
failure modes that actually happen: a condensed summary, a dropped sentence, a mistyped
number, or English left in place.

Usage:
    python3 check_abstract.py --note "<note.md>" --abstract "<abstract.txt>"
    python3 check_abstract.py --collection "<collection folder>" --abstract-dir "<dir>"

In collection mode, files are matched on the numeric prefix: note `03_....md` pairs with
`03.txt` (or any file in the abstract directory whose name starts with `03`).

Exit code is 1 when any note fails.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PLACEHOLDER_RE = re.compile(r"<[^<>\n]{0,40}>")
MIN_CJK_RATIO = 0.45
MIN_ABSTRACT_CHARS = 80

# Tokens worth checking: p-values, sample sizes, percentages, decimals, and integer runs of
# three or more digits. The three-digit floor deliberately ignores citation superscripts
# such as "1-3", which never belong in an abstract translation.
STAT_RE = re.compile(
    r"""
    (?:p\s*[=<>]\s*\d+(?:\.\d+)?)   # p = 0.007
    |(?:[Nn]\s*=\s*\d+)              # N = 44
    |(?:\d+(?:[.,]\d+)?\s*%)         # 65%
    |(?:\d+\.\d+)                    # 7.9
    |(?:\d{3,})                      # 353
    """,
    re.VERBOSE,
)

FULLWIDTH = str.maketrans("０１２３４５６７８９％．，－～", "0123456789%.,-~")

# A period only ends a sentence when what precedes it is a real word. These are the
# abbreviations that would otherwise split a source abstract mid-sentence.
ABBREVIATIONS = {
    "al", "e.g", "i.e", "vs", "no", "nos", "fig", "figs", "approx", "ca", "cf",
    "dr", "mr", "mrs", "ms", "prof", "st", "inc", "ltd", "co", "u.s", "u.k", "etc",
    "eq", "ref", "refs", "suppl", "extended",
}


def normalise(text: str) -> str:
    text = text.translate(FULLWIDTH)
    text = re.sub(r"[–—−ー]", "-", text)
    text = re.sub(r"\s+", "", text)
    return text


def parse_frontmatter(text: str):
    """Return the frontmatter fields, or None when there is no frontmatter."""
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    fields: dict[str, str] = {}
    for raw in text[4:end].splitlines():
        if ":" not in raw or raw.lstrip().startswith("- "):
            continue
        key, _, value = raw.partition(":")
        fields[key.strip()] = value.strip().strip('"').strip("'")
    return fields


def cjk_ratio(text: str) -> float:
    chars = [ch for ch in text if not ch.isspace()]
    if not chars:
        return 0.0
    cjk = sum(1 for ch in chars if "\u4e00" <= ch <= "\u9fff")
    return cjk / len(chars)


def count_sentences(text: str) -> int:
    """Split a Chinese translation on Chinese terminators, a source abstract on Latin ones."""
    if re.search(r"[\u4e00-\u9fff]", text):
        # A trailing "）" left over after a final "。）" is not its own sentence.
        return sum(
            1 for p in re.split(r"[。！？]", text)
            if re.search(r"[\u4e00-\u9fffA-Za-z0-9]", p)
        )

    ends = 0
    # A terminator counts when a capital letter follows, allowing for an opening bracket or
    # a stray closing quote between them (PDF extraction often leaves `decoding. ” Redeﬁning`).
    for m in re.finditer(r"[.!?](?=\s+[\"'\u201c\u201d\u2018\u2019(\[]*\s*[A-Z])", text):
        j = m.start()
        k = j
        while k > 0 and not text[k - 1].isspace():
            k -= 1
        token = text[k:j].strip("()[]{}\"'\u201c\u201d")
        token = re.sub(r"[\u2013\u2014\u2212]", "-", token).lower()
        # Skip initials ("James S.") and abbreviations ("et al."); everything else — including
        # "(EEG).", "35%." and "text1-3." — ends a sentence.
        if re.fullmatch(r"[a-z]", token) or token in ABBREVIATIONS:
            continue
        ends += 1
    return ends + 1 if text.strip() else 0


def stat_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for m in STAT_RE.finditer(text):
        token = normalise(m.group(0))
        tokens.add(token)
        bare = re.sub(r"^[Nnp=<>]+", "", token)
        if bare:
            tokens.add(bare)
    return tokens


def check(note: Path, abstract_path: Path):
    errors: list[str] = []
    warnings: list[str] = []

    fields = parse_frontmatter(note.read_text(encoding="utf-8"))
    if fields is None:
        return ["missing YAML frontmatter"], []

    abstract = (fields.get("摘要") or "").strip()
    if not abstract:
        return ["frontmatter `摘要` is empty"], []
    if PLACEHOLDER_RE.search(abstract):
        errors.append("`摘要` still contains a <placeholder>")
    if len(abstract) < MIN_ABSTRACT_CHARS:
        errors.append(f"`摘要` is only {len(abstract)} chars, too short to be a full translation")
    ratio = cjk_ratio(abstract)
    if ratio < MIN_CJK_RATIO:
        errors.append(f"`摘要` is only {ratio:.0%} Chinese; a translation should be near 100%")

    source = abstract_path.read_text(encoding="utf-8") if abstract_path.exists() else ""
    if not source.strip():
        warnings.append(f"no source abstract at {abstract_path}; only format was checked")
        return errors, warnings

    src_sent, tgt_sent = count_sentences(source), count_sentences(abstract)
    if abs(src_sent - tgt_sent) > 1:
        errors.append(
            f"sentence count {tgt_sent} vs source {src_sent}; a translation keeps one "
            "target sentence per source sentence"
        )
    elif src_sent != tgt_sent:
        warnings.append(f"sentence count {tgt_sent} vs source {src_sent} (off by one)")

    haystack = normalise(abstract)
    missing = sorted(t for t in stat_tokens(source) if t not in haystack)
    if missing:
        errors.append("numbers in the source abstract missing from `摘要`: " + ", ".join(missing))

    return errors, warnings


def pair_up(collection: Path, abstract_dir: Path):
    pairs = []
    for note in sorted(p for p in collection.glob("*.md") if re.match(r"^\d{2,}_", p.name)):
        # The collection README/MOC is an index, not a paper note; it has no frontmatter.
        if note.name.split("_", 1)[0] == "00":
            continue
        prefix = note.name.split("_", 1)[0]
        candidates = sorted(abstract_dir.glob(f"{prefix}*"))
        pairs.append((note, candidates[0] if candidates else abstract_dir / f"{prefix}.txt"))
    return pairs


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--note")
    parser.add_argument("--abstract")
    parser.add_argument("--collection")
    parser.add_argument("--abstract-dir")
    args = parser.parse_args()

    if args.note:
        pairs = [(Path(args.note), Path(args.abstract) if args.abstract else Path("/nonexistent"))]
    elif args.collection and args.abstract_dir:
        pairs = pair_up(Path(args.collection), Path(args.abstract_dir))
    else:
        parser.error("give either --note/--abstract or --collection/--abstract-dir")

    failed = 0
    for note, abstract_path in pairs:
        errors, warnings = check(note, abstract_path)
        if errors:
            failed += 1
            print(f"FAIL  {note.name}")
            for e in errors:
                print(f"        {e}")
        else:
            print(f"ok    {note.name}")
        for w in warnings:
            print(f"        warn: {w}")

    print(f"\n{len(pairs)} note(s); {failed} failing")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
