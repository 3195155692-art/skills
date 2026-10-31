#!/usr/bin/env python3
"""Layout gate: re-measure every text box in a saved deck.

There is usually no PowerPoint or LibreOffice on the machine, so this reads the real
geometry and run properties out of the .pptx, wraps the text with the same font file the
deck requests, and compares the height the text needs against the height the box has.

Findings:
  OVERFLOW  text needs more vertical room than the shape has        (blocking)
  BOUNDS    shape sits outside the slide                           (blocking)
  COLLIDE   two text boxes overlap each other                      (blocking)
  TIGHT     less than 6% vertical slack                            (review)

Usage:
    python3 check_layout.py --deck deck.pptx [--slack 0.06] [--verbose]
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from xml.etree import ElementTree as ET

from PIL import ImageFont

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import font_index  # noqa: E402

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
}
EMU = 914400.0
DEFAULT_W, DEFAULT_H = 13.333, 7.5
SUPERSAMPLE = 4

_cache: dict = {}


def font_for(path: str, idx: int, size_pt: float):
    px = max(6, int(round(size_pt * SUPERSAMPLE)))
    key = (path, idx, px)
    if key not in _cache:
        try:
            _cache[key] = ImageFont.truetype(path, px, index=idx)
        except Exception:
            return None
    return _cache[key]


def text_width_in(text: str, font, size_pt: float) -> float:
    return (font.getlength(text) / SUPERSAMPLE) / 72.0


def wrap_lines(text: str, font, size_pt: float, avail_in: float) -> int:
    if not text.strip():
        return 1
    total = 0
    for hard in text.split("\n"):
        if not hard.strip():
            total += 1
            continue
        line, n = "", 1
        for ch in hard:
            trial = line + ch
            if text_width_in(trial, font, size_pt) > avail_in and line:
                n += 1
                line = ch
            else:
                line = trial
        total += n
    return total


def emu(v):
    return float(v) / EMU


def slide_size(zf) -> tuple[float, float]:
    try:
        root = ET.fromstring(zf.read("ppt/presentation.xml"))
        ext = root.find(".//p:sldSz", NS)
        if ext is not None:
            return emu(ext.get("cx")), emu(ext.get("cy"))
    except Exception:
        pass
    return DEFAULT_W, DEFAULT_H


def preview(body) -> str:
    for para in body.findall("a:p", NS):
        txt = "".join(
            (r.find("a:t", NS).text or "")
            for r in para.findall("a:r", NS)
            if r.find("a:t", NS) is not None
        )
        if txt.strip():
            return txt.strip().replace("\n", " ")[:70]
    return ""


def analyse(xml: str, W: float, H: float, slack: float):
    root = ET.fromstring(xml)
    findings, boxes = [], []
    unmeasured: set[str] = set()

    for sp in root.iter("{%s}sp" % NS["p"]):
        xfrm = sp.find(".//a:xfrm", NS)
        body = sp.find(".//p:txBody", NS)
        if xfrm is None or body is None:
            continue
        off, ext = xfrm.find("a:off", NS), xfrm.find("a:ext", NS)
        if off is None or ext is None:
            continue
        x, y, w, h = emu(off.get("x")), emu(off.get("y")), emu(ext.get("cx")), emu(ext.get("cy"))

        if x < -0.4 or y < -0.4 or x + w > W + 0.4 or y + h > H + 0.4:
            findings.append(("BOUNDS", f"({x:.2f},{y:.2f}) to ({x+w:.2f},{y+h:.2f})", ""))

        bodyPr = body.find("a:bodyPr", NS)
        lIns, rIns, tIns, bIns = 0.1, 0.1, 0.05, 0.05
        anchor = "t"
        if bodyPr is not None:
            anchor = bodyPr.get("anchor", "t")
            for attr, key in (("lIns", "l"), ("rIns", "r"), ("tIns", "t"), ("bIns", "b")):
                if bodyPr.get(attr) is not None:
                    val = emu(bodyPr.get(attr))
                    if key == "l":
                        lIns = val
                    elif key == "r":
                        rIns = val
                    elif key == "t":
                        tIns = val
                    else:
                        bIns = val
        avail = w - lIns - rIns
        if avail <= 0.05:
            continue

        need, has_text = 0.0, False
        for para in body.findall("a:p", NS):
            runs = para.findall("a:r", NS)
            if not runs:
                continue
            para_text = "".join(
                (r.find("a:t", NS).text or "") for r in runs if r.find("a:t", NS) is not None
            )
            if not para_text.strip():
                continue
            has_text = True
            pPr = para.find("a:pPr", NS)
            marL = emu(pPr.get("marL")) if (pPr is not None and pPr.get("marL")) else 0.0

            rPr = runs[0].find("a:rPr", NS)
            size, bold, face = 18.0, False, ""
            if rPr is not None:
                if rPr.get("sz"):
                    size = float(rPr.get("sz")) / 100.0
                bold = rPr.get("b") == "1"
                lat = rPr.find("a:latin", NS)
                if lat is not None:
                    face = lat.get("typeface") or ""

            lnspc = 1.2 * size
            if pPr is not None:
                sp_pts = pPr.find("a:lnSpc/a:spcPts", NS)
                if sp_pts is not None and sp_pts.get("val"):
                    lnspc = float(sp_pts.get("val")) / 100.0
                else:
                    # PowerPoint writes percentage line spacing after a round-trip
                    # (<a:spcPct val="100000"/> = 100% of the font's line height).
                    sp_pct = pPr.find("a:lnSpc/a:spcPct", NS)
                    if sp_pct is not None and sp_pct.get("val"):
                        lnspc = 1.2 * size * float(sp_pct.get("val")) / 100000.0
            after = 0.0
            if pPr is not None:
                sp_after = pPr.find("a:spcAft/a:spcPts", NS)
                if sp_after is not None and sp_after.get("val"):
                    after = float(sp_after.get("val")) / 100.0

            face_path = font_index.resolve(face, bold)
            font = font_for(face_path[0], face_path[1], size) if face_path else None
            if font is None:
                # The face is not installed, so this text cannot be measured. Say so rather
                # than counting it as zero-height and reporting a clean slide.
                unmeasured.add(face or "(no face)")
                line = 0.0
            else:
                line = wrap_lines(para_text, font, size, avail - marL) * lnspc / 72.0
            need += line + after / 72.0

        if not has_text:
            continue
        need += tIns + bIns

        # Compare the region the text actually occupies, not the shape's outline.
        # PowerPoint and WPS grow text boxes to fit their content on re-save, so two
        # transparent, top-anchored boxes can overlap while their text never does.
        text_h = max(need - tIns - bIns, 0.02)
        if anchor == "ctr":
            text_top = y + (h - need) / 2.0 + tIns
        elif anchor == "b":
            text_top = y + h - bIns - text_h
        else:
            text_top = y + tIns
        boxes.append((x, text_top, w, text_h, preview(body)))

        if need > h + 0.005:
            findings.append(("OVERFLOW", f"needs {need:.3f}in, box {h:.2f}in", preview(body)))
        elif need > h * (1 - slack):
            findings.append(("TIGHT", f"slack {h-need:.3f}in", preview(body)))

    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i], boxes[j]
            ox = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
            oy = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
            if ox > 0.12 and oy > 0.08:
                findings.append(("COLLIDE", f"overlap {ox:.2f}x{oy:.2f}in", f"{a[4][:26]} | {b[4][:26]}"))
    return findings, unmeasured


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--deck", required=True)
    ap.add_argument("--slack", type=float, default=0.06, help="TIGHT threshold (default 0.06)")
    ap.add_argument("--verbose", action="store_true", help="also print TIGHT findings")
    args = ap.parse_args()

    blocking = 0
    unmeasured: set[str] = set()
    with zipfile.ZipFile(args.deck) as z:
        W, H = slide_size(z)
        slides = sorted(
            (n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
            key=lambda n: int(re.findall(r"\d+", n)[-1]),
        )
        for n in slides:
            idx = int(re.findall(r"\d+", n)[-1])
            findings, missing = analyse(z.read(n).decode("utf-8"), W, H, args.slack)
            unmeasured |= missing
            hard = [f for f in findings if f[0] != "TIGHT"]
            soft = [f for f in findings if f[0] == "TIGHT"]
            if not hard and not (args.verbose and soft):
                continue
            print(f"--- slide {idx}")
            for kind, detail, text in hard + (soft if args.verbose else []):
                blocking += 1 if kind != "TIGHT" else 0
                tail = f"  | {text}" if text else ""
                print(f"    {kind:9s} {detail}{tail}")
    if unmeasured:
        print(f"\nWARN    text using a font that is not installed could not be measured: "
              f"{sorted(unmeasured)}")
        print("        install the face or switch the deck to an installed one, then re-run")
    print(f"\n{len(slides)} slide(s) scanned; {blocking} blocking finding(s)")
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
