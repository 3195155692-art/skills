#!/usr/bin/env python3
"""Extract text and hashes for a collection's PDFs, and maintain manifest.json.

Text is written to a cache directory OUTSIDE the vault by default, so extracted
text never pollutes Obsidian search or the graph view.

Usage:
    python3 pdf_intake.py --collection "<collection folder>" [--pdf PDFs/x.pdf]
                          [--text-dir <dir>] [--force]

Existing manifest entries keep their provenance fields unless --force is given;
the script only refreshes file-derived fields (bytes, sha256, pages).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import logging
import re
import sys
from pathlib import Path

TEXT_CACHE_SUFFIX = "_text"

# pypdf warns loudly about optional font tables; the extracted text is still usable.
logging.getLogger("pypdf").setLevel(logging.ERROR)


def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def extract_text(pdf_path: Path):
    """Return (text, page_count, error). Text may be None when extraction fails."""
    try:
        from pypdf import PdfReader  # imported lazily so --hash-only works without it
    except ImportError:
        return None, None, "pypdf is not installed (pip install pypdf)"

    try:
        reader = PdfReader(str(pdf_path))
    except Exception as exc:  # noqa: BLE001 - report any reader failure verbatim
        return None, None, f"cannot open PDF: {exc}"

    pages = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            body = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001 - keep going, note the page
            body = f"<<EXTRACTION FAILED: {exc}>>"
        pages.append(f"\n<<<PAGE {index}>>>\n{body}")
    return "\n".join(pages), len(reader.pages), None


def load_manifest(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        sys.exit(f"manifest.json is not valid JSON ({exc}); fix it before rerunning")


def build_entry(existing: dict, pdf_path: Path, collection: Path, text_path, pages) -> dict:
    entry = dict(existing) if existing else {}
    try:
        rel = pdf_path.relative_to(collection).as_posix()
    except ValueError:
        rel = pdf_path.name
    entry["file"] = rel
    entry["note"] = entry.get("note") or f"{pdf_path.stem}.md"
    entry["format"] = "pdf"
    entry["mime"] = "application/pdf"
    entry["bytes"] = pdf_path.stat().st_size
    entry["sha256"] = sha256_of(pdf_path)
    if pages is not None:
        entry["pages"] = pages
    if text_path is not None:
        entry["textCache"] = str(text_path)
    entry.setdefault("status", "downloaded")
    return entry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", required=True, help="collection folder (contains PDFs/)")
    parser.add_argument("--pdf", action="append", default=None,
                        help="specific PDF (repeatable); default is every PDF under PDFs/")
    parser.add_argument("--text-dir", default=None,
                        help="where to write extracted text (default: /tmp/<collection>_text)")
    parser.add_argument("--force", action="store_true",
                        help="also overwrite provenance fields on existing manifest entries")
    parser.add_argument("--list", action="store_true", help="list files and hashes, write nothing")
    args = parser.parse_args()

    collection = Path(args.collection).expanduser().resolve()
    if not collection.is_dir():
        sys.exit(f"collection folder not found: {collection}")

    pdf_dir = collection / "PDFs"
    if args.pdf:
        pdfs = [Path(p).expanduser().resolve() for p in args.pdf]
    elif pdf_dir.is_dir():
        pdfs = sorted(pdf_dir.glob("*.pdf"))
    else:
        sys.exit(f"no PDFs/ directory under {collection}")

    if not pdfs:
        sys.exit("no PDFs found")

    text_dir = Path(args.text_dir).expanduser().resolve() if args.text_dir \
        else Path(f"/tmp/{collection.name}{TEXT_CACHE_SUFFIX}")
    if not args.list:
        text_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = collection / "manifest.json"
    manifest = load_manifest(manifest_path)
    results = manifest.get("results") or []
    # Key on file path, falling back to the note name so that entries without a
    # PDF (not yet obtained) survive a rewrite instead of collapsing together.
    by_file = {(entry.get("file") or entry.get("note") or f"__entry_{i}"): entry
               for i, entry in enumerate(results)}

    reports = []
    for pdf_path in pdfs:
        text, pages, error = (None, None, None) if args.list else extract_text(pdf_path)
        text_path = None
        if text is not None:
            text_path = text_dir / f"{pdf_path.stem}.txt"
            text_path.write_text(text, encoding="utf-8")

        try:
            rel = pdf_path.relative_to(collection).as_posix()
        except ValueError:
            rel = pdf_path.name

        existing = by_file.get(rel)
        if args.force and existing:
            existing = {k: v for k, v in existing.items()
                        if k in {"file", "note", "title", "doi", "status"}}
        entry = build_entry(existing or {}, pdf_path, collection, text_path, pages)
        by_file[rel] = entry
        reports.append((pdf_path.name, entry["bytes"], entry["sha256"], pages, error))

    if not args.list:
        manifest.setdefault("project", collection.name)
        manifest.setdefault("generatedAt", _dt.datetime.now().astimezone().isoformat(timespec="seconds"))
        manifest.setdefault("outputLayout", {"pdfs": "PDFs/", "notes": "*.md"})
        manifest["results"] = sorted(by_file.values(), key=lambda e: e.get("file") or "")
        downloaded = sum(1 for e in manifest["results"] if e.get("file"))
        pending = sum(1 for e in manifest["results"] if not e.get("file"))
        manifest["summary"] = {
            "total": len(manifest["results"]),
            "downloaded": downloaded,
            "pending_institutional_access": pending,
        }
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    width = max(len(name) for name, *_ in reports)
    for name, size, digest, pages, error in reports:
        page_note = f"{pages}p" if pages else "-"
        line = f"{name:<{width}}  {size:>9} B  {page_note:>4}  {digest[:16]}"
        print(line + (f"  ! {error}" if error else ""))
    print(f"\n{len(reports)} pdf(s); manifest: {'not written (--list)' if args.list else manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
