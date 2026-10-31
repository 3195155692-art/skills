#!/usr/bin/env python3
"""Check an Obsidian reading collection against the conventions in this skill.

Reports frontmatter gaps, filename violations, missing extraction layers, and
note/PDF stem mismatches. Exit code is 1 when any error was found.

Usage:
    python3 check_notes.py --collection "<collection folder>" [--quiet]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ILLEGAL_IN_NAME = set('\\/:*?"<>|')
FILENAME_RE = re.compile(r"^(\d{2,})_(.+)$")
EXTRACTION_HEADING = "关键句与核心论点"
REPORT_HEADING = "精读报告"
REQUIRED_KEYS = ("tags", "年份", "摘要")
MIN_ABSTRACT_CHARS = 80
MIN_ABSTRACT_CJK_RATIO = 0.45
PLACEHOLDER_RE = re.compile(r"<[^<>\n]{0,40}>")


def cjk_ratio(text: str) -> float:
    chars = [ch for ch in text if not ch.isspace()]
    if not chars:
        return 0.0
    return sum(1 for ch in chars if "\u4e00" <= ch <= "\u9fff") / len(chars)


def parse_frontmatter(text: str):
    """Return (fields, error). Only a tiny subset of YAML is needed here."""
    if not text.startswith("---\n"):
        return None, "missing YAML frontmatter"
    end = text.find("\n---", 4)
    if end == -1:
        return None, "frontmatter is not closed with ---"
    block = text[4:end]

    fields: dict[str, object] = {}
    current_list = None
    for raw in block.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("- ") and current_list is not None:
            current_list.append(line.lstrip()[2:].strip())
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            if value == "":
                current_list = []
                fields[key] = current_list
            else:
                current_list = None
                fields[key] = value.strip('"').strip("'")
    return (fields, text[end + 4:]), None


def check_note(path: Path, collection: Path, pdf_stems: set[str]):
    errors: list[str] = []
    warnings: list[str] = []
    text = path.read_text(encoding="utf-8")

    parsed, fm_error = parse_frontmatter(text)
    if fm_error:
        errors.append(fm_error)
        fields, body = {}, text
    else:
        fields, body = parsed

    for key in REQUIRED_KEYS:
        value = fields.get(key)
        if value is None:
            errors.append(f"frontmatter missing `{key}`")
        elif isinstance(value, list) and not value:
            errors.append(f"frontmatter `{key}` is empty")
        elif isinstance(value, str) and not value.strip():
            errors.append(f"frontmatter `{key}` is empty")

    year = str(fields.get("年份", "")).strip()
    if year and not re.fullmatch(r"\d{4}", year):
        errors.append(f"`年份` should be a 4-digit number, got `{year}`")

    abstract = fields.get("摘要")
    if isinstance(abstract, str) and 0 < len(abstract.strip()) < MIN_ABSTRACT_CHARS:
        warnings.append(f"`摘要` looks short ({len(abstract.strip())} chars); "
                        "it should be a full translation")
    if isinstance(abstract, str) and abstract.strip():
        if PLACEHOLDER_RE.search(abstract):
            errors.append("`摘要` still contains a <placeholder>")
        ratio = cjk_ratio(abstract)
        if ratio < MIN_ABSTRACT_CJK_RATIO:
            errors.append(
                f"`摘要` is only {ratio:.0%} Chinese — it must be a Chinese translation "
                "of the abstract, not the English abstract itself"
            )
        elif ratio < 0.6:
            warnings.append(
                f"`摘要` is only {ratio:.0%} Chinese; check that it is a translation "
                "rather than a summary with English terms left in"
            )

    tags = fields.get("tags")
    if isinstance(tags, list):
        if len(tags) < 2:
            warnings.append("only one tag; expected 领域 + 期刊 + 概念 (+ 缩写)")
        for tag in tags:
            if " " in tag:
                warnings.append(f"tag contains a space: `{tag}` (journal tags use hyphens)")

    match = FILENAME_RE.match(path.stem)
    if not match:
        errors.append("filename should look like `<NN>_<paper title>.md`")
    bad = sorted(ILLEGAL_IN_NAME.intersection(path.stem))
    if bad:
        errors.append("filename contains characters Obsidian forbids: " + " ".join(bad))

    if REPORT_HEADING not in text:
        errors.append(f"missing the `# {REPORT_HEADING} NN：<title>` heading")
    if EXTRACTION_HEADING not in text:
        errors.append(f"missing the `# 附：{EXTRACTION_HEADING}` extraction layer")
    if "> **核心论点**" not in text:
        errors.append("no `> **核心论点**` lines found")
    quote_count = len(re.findall(r'^\d+\.\s+"', body, flags=re.MULTILINE))
    if quote_count < 5 and "待补清单" not in text:
        warnings.append(f"only {quote_count} quoted key sentences; "
                        "an abstract-only note should carry a 待补清单")

    if path.stem not in pdf_stems:
        warnings.append("no matching PDFs/<stem>.pdf")

    return errors, warnings, quote_count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", required=True)
    parser.add_argument("--quiet", action="store_true", help="only print problems")
    args = parser.parse_args()

    collection = Path(args.collection).expanduser().resolve()
    if not collection.is_dir():
        sys.exit(f"collection folder not found: {collection}")

    pdf_stems = {p.stem for p in (collection / "PDFs").glob("*.pdf")} \
        if (collection / "PDFs").is_dir() else set()

    notes = [p for p in sorted(collection.glob("*.md"))
             if not p.name.startswith("00_") and "README" not in p.name.upper()]
    if not notes:
        sys.exit(f"no notes found in {collection}")

    total_errors = total_warnings = 0
    for note in notes:
        errors, warnings, quotes = check_note(note, collection, pdf_stems)
        total_errors += len(errors)
        total_warnings += len(warnings)
        if errors or warnings or not args.quiet:
            status = "FAIL" if errors else ("WARN" if warnings else "OK  ")
            print(f"{status} {note.name}  ({quotes} quoted sentences)")
            for item in errors:
                print(f"       error: {item}")
            for item in warnings:
                print(f"       warn : {item}")

    print(f"\n{len(notes)} note(s): {total_errors} error(s), {total_warnings} warning(s)")
    return 1 if total_errors else 0


if __name__ == "__main__":
    sys.exit(main())
