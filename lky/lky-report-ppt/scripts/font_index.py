"""Locate the font files that a deck's declared typefaces actually resolve to.

A PPTX stores a font *name*; whether the machine has it is a separate question. Everything
in this skill that measures text has to start by answering "which file will PowerPoint use",
so that logic lives here.

Public API:
    index(...)                  -> {family_lower: {style: (path, index)}}
    resolve(family, bold)       -> (path, index) or None
    installed_families()        -> sorted list of family names
    has_glyph(font, char)       -> whether the font can draw that character
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache

from PIL import ImageFont

DEFAULT_DIRS = (
    "/System/Library/Fonts",
    "/System/Library/Fonts/Supplemental",
    "/Library/Fonts",
    os.path.expanduser("~/Library/Fonts"),
)

# Private-use code point: practically guaranteed to be absent, so its rendering is the
# font's .notdef and can be used as a reference for "this glyph does not exist".
PROBE_MISSING = "\ue001"

# Styles we ask for by name, in priority order.
BOLD_STYLES = ("bold", "semibold", "medium", "heavy", "black")
REGULAR_STYLES = ("regular", "book", "normal", "roman", "light", "" )


def _extra_dirs():
    extra = os.environ.get("LKY_FONT_DIRS", "")
    return tuple(d for d in extra.split(os.pathsep) if d)


def _probe_faces(path: str, limit: int = 12):
    """Yield (index, family, style) for each face inside a font file."""
    for i in range(limit):
        try:
            f = ImageFont.truetype(path, 24, index=i)
        except Exception:
            if i == 0:
                return
            break
        try:
            family, style = f.getname()
        except Exception:
            family, style = os.path.basename(path), ""
        yield i, (family or "").strip(), (style or "").strip().lower()


@lru_cache(maxsize=1)
def index(extra_dirs: tuple = ()):
    table: dict = {}
    for d in tuple(DEFAULT_DIRS) + tuple(extra_dirs) + _extra_dirs():
        if not os.path.isdir(d):
            continue
        for root, _dirs, files in os.walk(d):
            for name in sorted(files):
                if not name.lower().endswith((".ttf", ".ttc", ".otf")):
                    continue
                path = os.path.join(root, name)
                for idx, family, style in _probe_faces(path):
                    if not family:
                        continue
                    table.setdefault(family.lower(), {}).setdefault(style, (path, idx))
    return table


def resolve(family: str, bold: bool = False):
    """Return (path, index) for a family name, or None when it is not installed."""
    if not family:
        return None
    faces = index().get(family.strip().lower())
    if not faces:
        return None
    wanted = BOLD_STYLES if bold else REGULAR_STYLES
    for style in wanted:
        if style in faces:
            return faces[style]
    # Fall back to whichever face exists.
    return next(iter(faces.values()))


def installed_families():
    return sorted({fam for fam in index()})


@lru_cache(maxsize=256)
def _masks(path: str, index_: int):
    try:
        f = ImageFont.truetype(path, 40, index=index_)
    except Exception:
        return None
    def sig(ch):
        m = f.getmask(ch)
        try:
            return (m.size, bytes(m))
        except Exception:
            return (m.size, b"")
    return f, sig


def has_glyph(font, char: str) -> bool:
    """True when the font has a real glyph for `char` (not the .notdef box)."""
    try:
        def sig(ch):
            m = font.getmask(ch)
            return (m.size, bytes(m))
        missing = sig(PROBE_MISSING)
        blank = sig(" ")
        got = sig(char)
        return got != missing and got != blank
    except Exception:
        return False


def describe(path, idx):
    try:
        f = ImageFont.truetype(path, 24, index=idx)
        return " / ".join(f.getname())
    except Exception:
        return os.path.basename(str(path))


def main() -> int:
    """`python3 font_index.py [--cjk-only]` — print what this machine actually has."""
    cjk_only = "--cjk-only" in sys.argv
    rows = []
    for family in installed_families():
        face = resolve(family)
        if not face:
            continue
        f = _masks(face[0], face[1])
        if not f:
            continue
        font = f[0]
        if cjk_only and not has_glyph(font, "中"):
            continue
        rows.append((family, describe(*face)))
    for family, desc in rows:
        print(f"{family:32s} {desc}")
    print(f"\n{len(rows)} famil{'y' if len(rows) == 1 else 'ies'}"
          f"{' with CJK coverage' if cjk_only else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
