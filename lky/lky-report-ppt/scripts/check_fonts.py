#!/usr/bin/env python3
"""Font gate: the four font failures that silently ruin a deck.

  1. a declared face is not installed on this machine  (silently substituted)
  2. a run has <a:latin> but no <a:ea>                 (inherits the theme's CJK font)
  3. CJK text sits on a Latin-only face                (renders as boxes)
  4. more than one CJK face is used in the deck        (pages disagree with each other)

Usage:
    python3 check_fonts.py --deck deck.pptx
    python3 check_fonts.py --want "Heiti SC,Times New Roman"    # preflight, before designing
    python3 check_fonts.py --list [--cjk-only]                  # what this machine has
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from collections import Counter, defaultdict

from PIL import ImageFont

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import font_index  # noqa: E402

CJK_CHAR = re.compile(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]")
RUN = re.compile(r"<a:r>(.*?)</a:r>", re.S)
LATIN = re.compile(r'<a:latin typeface="([^"]*)"')
EAST = re.compile(r'<a:ea typeface="([^"]*)"')
TEXT = re.compile(r"<a:t>(.*?)</a:t>", re.S)


def face_supports_cjk(family: str) -> bool:
    face = font_index.resolve(family)
    if not face:
        return False
    lookup = font_index._masks(face[0], face[1])
    if not lookup:
        return False
    return font_index.has_glyph(lookup[0], "中")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--deck")
    ap.add_argument("--want", help="comma-separated family names that must be installed")
    ap.add_argument("--list", action="store_true", help="list installed families")
    ap.add_argument("--cjk-only", action="store_true", help="with --list, only CJK-capable")
    args = ap.parse_args()

    if args.list:
        return font_index.main() if args.cjk_only else _list_all()

    problems = 0

    if args.want:
        for name in [n.strip() for n in args.want.split(",") if n.strip()]:
            if font_index.resolve(name):
                print(f"ok      {name}  ->  {font_index.describe(*font_index.resolve(name))}")
            else:
                problems += 1
                print(f"MISSING {name} is not installed; PowerPoint would substitute it")

    if args.deck:
        with zipfile.ZipFile(args.deck) as z:
            slides = sorted(
                (n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                key=lambda n: int(re.findall(r"\d+", n)[-1]),
            )
            latin, east = Counter(), Counter()
            cjk_faces = Counter()
            missing_ea = 0
            on_latin = []
            chars_by_face: dict = defaultdict(set)

            for n in slides:
                xml = z.read(n).decode("utf-8")
                latin.update(LATIN.findall(xml))
                east.update(EAST.findall(xml))
                missing_ea += max(0, len(LATIN.findall(xml)) - len(EAST.findall(xml)))
                for run in RUN.findall(xml):
                    face = LATIN.search(run)
                    text = "".join(TEXT.findall(run))
                    if face and text:
                        chars_by_face[face.group(1)].update(text)
                    if not face or not CJK_CHAR.search(text):
                        continue
                    family = face.group(1)
                    cjk_faces[family] += 1
                    if not face_supports_cjk(family):
                        on_latin.append((n.split("/")[-1], family, text[:36]))

            print(f"\nslides: {len(slides)}")
            print(f"declared latin faces : {dict(latin)}")
            print(f"declared CJK   faces : {dict(east)}")

            if missing_ea:
                problems += 1
                print(f"ERROR   {missing_ea} run(s) have <a:latin> but no <a:ea>")

            if on_latin:
                problems += 1
                print(f"ERROR   {len(on_latin)} CJK run(s) sit on a face without CJK glyphs:")
                for slide, family, text in on_latin[:12]:
                    print(f"          {slide:16s} {family:18s} {text}")

            not_installed = sorted({f for f in list(latin) + list(east) if f and not font_index.resolve(f)})
            if not_installed:
                problems += 1
                print(f"ERROR   declared but not installed: {not_installed}")
                print("        the deck will be substituted; the verified layout is not what will show")

            used_cjk = [f for f in cjk_faces if face_supports_cjk(f)]
            if len(used_cjk) > 1:
                print(f"WARN    {len(used_cjk)} different CJK faces in one deck: {used_cjk}")
                print("        a hand edit that missed some runs leaves the pages inconsistent")

            # Characters the chosen face simply cannot draw. A glyph the font lacks becomes a
            # box on screen, and it is invisible until the deck is projected.
            for family, chars in sorted(chars_by_face.items()):
                resolved = font_index.resolve(family)
                if not resolved:
                    continue  # already reported as not installed
                lookup = font_index._masks(resolved[0], resolved[1])
                if not lookup:
                    continue
                missing = sorted(c for c in chars
                                 if c not in "\n\t " and not font_index.has_glyph(lookup[0], c))
                if missing:
                    problems += 1
                    print(f"ERROR   {family} cannot draw {len(missing)} character(s) used in the deck: "
                          f"{''.join(missing[:20])}")

    print(f"\n{problems} problem(s)")
    return 1 if problems else 0


def _list_all() -> int:
    for family in font_index.installed_families():
        face = font_index.resolve(family)
        print(f"{family:32s} {font_index.describe(*face) if face else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
