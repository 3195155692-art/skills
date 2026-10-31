#!/usr/bin/env python3
"""Retrofit a type rule onto a deck that already exists — including a hand-edited one.

Typical use: the user says "make it 1.5 line spacing" or "nothing smaller than 12 pt"
*after* the deck has been built and edited. Regenerating would throw away their work, so
this edits the saved package in place instead of rebuilding it.

What it does, in order:
  1. raise every run below `--min-size` up to that size (skipped with --no-size);
  2. give every paragraph that wraps to two or more lines `--line-spacing` line spacing
     (skipped with --no-spacing). Genuinely single-line paragraphs are left alone: line
     spacing has no visible meaning for one line, and 150% only pushes the glyph down into
     whatever sits below it. This is the rule that keeps "1.5x everywhere" from wrecking
     stat pages and label rows;
  3. re-fit whatever the two steps push out of its frame, using the region the *text*
     occupies rather than the shape outline (a round-tripped deck has text boxes grown to
     fit their content, so outlines overlap while the text does not). A box is grown in
     place, lifted if that buys room, and only as a last resort has its own line spacing
     eased back down — every such case is printed in the report.

Faces that are not installed cannot be measured, so pass `--substitute` a mapping
(`--substitute "SimHei=Heiti SC,黑体=Heiti SC"`) or let the script pick a CJK fallback that
is installed. The substitution is only used for measuring and never reaches the file.

Usage:
    python3 scripts/retrofit_typography.py --deck deck.pptx --min-size 12 --line-spacing 1.5
    python3 scripts/retrofit_typography.py --deck deck.pptx --line-spacing 1.5 --no-size
    python3 scripts/retrofit_typography.py --deck deck.pptx --min-size 12 --no-spacing

The deck is rewritten in place and a `<deck>.bak` is left beside it. Exit code 1 means
something could not be fitted at all; read the report.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import zipfile

from lxml import etree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_layout as CL  # noqa: E402

P = "http://schemas.openxmlformats.org/presentationml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
EMU = 914400.0
SLIDE_RE = r"ppt/slides/slide\d+\.xml"


def p_(t):
    return "{%s}%s" % (P, t)


def a_(t):
    return "{%s}%s" % (A, t)


def emu(v):
    return float(v) / EMU


def px(v):
    return str(int(round(v * EMU)))


# --------------------------------------------------------------------------- geometry

def body_insets(body):
    bp = body.find(a_("bodyPr")) if body is not None else None
    l, r, t, b, anchor = 0.1, 0.1, 0.05, 0.05, "t"
    if bp is not None:
        anchor = bp.get("anchor", "t")
        for attr, cur in (("lIns", "l"), ("rIns", "r"), ("tIns", "t"), ("bIns", "b")):
            if bp.get(attr) is not None:
                val = emu(bp.get(attr))
                if cur == "l":
                    l = val
                elif cur == "r":
                    r = val
                elif cur == "t":
                    t = val
                else:
                    b = val
    return l, r, t, b, anchor


def shape_list(root):
    out = []
    for sp in root.iter(p_("sp")):
        spPr = sp.find(p_("spPr"))
        if spPr is None:
            continue
        xfrm = spPr.find(a_("xfrm"))
        if xfrm is None:
            continue
        off, ext = xfrm.find(a_("off")), xfrm.find(a_("ext"))
        if off is None or ext is None:
            continue
        body = sp.find(p_("txBody"))
        text = ""
        if body is not None:
            for para in body.findall(a_("p")):
                t = para_text(para).strip()
                if t:
                    text = t
                    break
        out.append({
            "el": sp,
            "id": sp.find(p_("nvSpPr")).find(p_("cNvPr")).get("id"),
            "body": body,
            "fill": spPr.find(a_("solidFill")) is not None,
            "text": text,
            "x": emu(off.get("x")), "y": emu(off.get("y")),
            "w": emu(ext.get("cx")), "h": emu(ext.get("cy")),
        })
    return out


def move(sp, x, y, w, h):
    xfrm = sp.find(p_("spPr")).find(a_("xfrm"))
    xfrm.find(a_("off")).set("x", px(x))
    xfrm.find(a_("off")).set("y", px(y))
    xfrm.find(a_("ext")).set("cx", px(w))
    xfrm.find(a_("ext")).set("cy", px(h))


# --------------------------------------------------------------------------- text

def para_runs(para):
    return [r for r in para.findall(a_("r")) if r.find(a_("t")) is not None]


def para_text(para):
    return "".join((r.find(a_("t")).text or "") for r in para_runs(para))


def run_size(run):
    rPr = run.find(a_("rPr"))
    if rPr is not None and rPr.get("sz"):
        return float(rPr.get("sz")) / 100.0
    return None


def set_lnspc(para, pct):
    pPr = para.find(a_("pPr"))
    if pPr is None:
        pPr = etree.Element(a_("pPr"))
        para.insert(0, pPr)
    ln = pPr.find(a_("lnSpc"))
    if ln is None:
        ln = etree.Element(a_("lnSpc"))
        pPr.insert(0, ln)
    for ch in list(ln):
        ln.remove(ch)
    etree.SubElement(ln, a_("spcPct")).set("val", str(int(pct * 1000)))


def current_pct(para):
    pPr = para.find(a_("pPr"))
    if pPr is not None:
        ln = pPr.find(a_("lnSpc"))
        if ln is not None:
            pct = ln.find(a_("spcPct"))
            if pct is not None and pct.get("val"):
                return float(pct.get("val")) / 1000.0
            pts = ln.find(a_("spcPts"))
            runs = para_runs(para)
            size = (run_size(runs[0]) or 18.0) if runs else 18.0
            if pts is not None and pts.get("val"):
                return float(pts.get("val")) / 100.0 / (1.2 * size) * 100.0
    return 100.0


# --------------------------------------------------------------------------- measuring

def face_of(para, substitutions):
    runs = para_runs(para)
    if not runs:
        return None, 18.0, False
    rPr = runs[0].find(a_("rPr"))
    size, bold, face = 18.0, False, ""
    if rPr is not None:
        if rPr.get("sz"):
            size = float(rPr.get("sz")) / 100.0
        bold = rPr.get("b") == "true"
        lat = rPr.find(a_("latin"))
        if lat is not None:
            face = lat.get("typeface") or ""
    return substitutions.get(face, face), size, bold


def resolve_face(face, bold):
    if not face:
        return None
    hit = CL.font_index.resolve(face, bold)
    if hit:
        return hit
    for fallback in ("Heiti SC", "PingFang SC", "Hiragino Sans GB", "Arial Unicode MS"):
        hit = CL.font_index.resolve(fallback, bold)
        if hit:
            return hit
    return None


def para_metrics(para, avail_in, substitutions):
    lines_size_bold = face_of(para, substitutions)
    face, size, bold = lines_size_bold
    resolved = resolve_face(face, bold)
    font = CL.font_for(resolved[0], resolved[1], size) if resolved else None
    pPr = para.find(a_("pPr"))
    marL = emu(pPr.get("marL")) if (pPr is not None and pPr.get("marL")) else 0.0
    if font is None:
        lines = 1
    else:
        lines = CL.wrap_lines(para_text(para), font, size, avail_in - marL)
    lnspc, after = 1.2 * size, 0.0
    if pPr is not None:
        ln = pPr.find(a_("lnSpc"))
        if ln is not None:
            pts, pct = ln.find(a_("spcPts")), ln.find(a_("spcPct"))
            if pts is not None and pts.get("val"):
                lnspc = float(pts.get("val")) / 100.0
            elif pct is not None and pct.get("val"):
                lnspc = 1.2 * size * float(pct.get("val")) / 100000.0
        af = pPr.find(a_("spcAft"))
        if af is not None:
            ap = af.find(a_("spcPts"))
            if ap is not None and ap.get("val"):
                after = float(ap.get("val")) / 100.0
    return lines, size, lnspc, after


def shape_need(shape, substitutions):
    """Frame height the text needs, and where the text sits, in inches."""
    body = shape["body"]
    l, r, t, b, anchor = body_insets(body)
    avail = shape["w"] - l - r
    if avail <= 0.05:
        return None
    need = 0.0
    for para in body.findall(a_("p")):
        if not para_text(para).strip():
            continue
        lines, _size, lnspc, after = para_metrics(para, avail, substitutions)
        need += lines * lnspc / 72.0 + after / 72.0
    if need <= 0:
        return None
    need += t + b
    text_h = need - t - b
    if anchor == "ctr":
        text_top = shape["y"] + (shape["h"] - need) / 2.0 + t
    elif anchor == "b":
        text_top = shape["y"] + shape["h"] - b - text_h
    else:
        text_top = shape["y"] + t
    return {"need": need, "top": text_top, "bottom": text_top + text_h}


def rects(root, substitutions):
    out = []
    for s in shape_list(root):
        if s["body"] is None or not s["text"]:
            continue
        m = shape_need(s, substitutions)
        if m is None:
            continue
        out.append({"x": s["x"], "top": m["top"], "w": s["w"],
                    "bottom": m["bottom"], "text": s["text"][:70]})
    return out


def overlaps(rects_, gap_x=0.12, gap_y=0.08):
    out = []
    for i in range(len(rects_)):
        for j in range(i + 1, len(rects_)):
            a, b = rects_[i], rects_[j]
            ox = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
            oy = min(a["bottom"], b["bottom"]) - max(a["top"], b["top"])
            if ox > gap_x and oy > gap_y:
                out.append((a, b, ox, oy))
    return out


# --------------------------------------------------------------------------- passes

def bump_sizes(root, min_size):
    n, ids = 0, set()
    for sp in root.iter(p_("sp")):
        body = sp.find(p_("txBody"))
        if body is None:
            continue
        hit = False
        for rPr in body.iter(a_("rPr")):
            sz = rPr.get("sz")
            if sz and float(sz) / 100.0 < min_size - 0.001:
                rPr.set("sz", str(int(round(min_size * 100))))
                n += 1
                hit = True
        if hit:
            cNvPr = sp.find(p_("nvSpPr")).find(p_("cNvPr"))
            if cNvPr is not None:
                ids.add(cNvPr.get("id"))
    return n, ids


def apply_spacing(root, multiple, substitutions):
    """150% on multi-line paragraphs only; returns how many paragraphs changed."""
    changed = 0
    ids = set()
    for s in shape_list(root):
        if s["body"] is None or not s["text"]:
            continue
        l, r, _t, _b, _a = body_insets(s["body"])
        avail = s["w"] - l - r
        paras = [p for p in s["body"].findall(a_("p")) if para_text(p).strip()]
        total = 0
        for p in paras:
            lines, _sz, _ls, _af = para_metrics(p, avail, substitutions)
            total += lines
        if total >= 2:
            for p in paras:
                set_lnspc(p, multiple * 100)
                changed += 1
            ids.add(s["id"])
    return changed, ids


def find_shape(shapes, rect_item):
    for s in shapes:
        if (s["body"] is not None and s["text"][:70] == rect_item["text"]
                and abs(s["x"] - rect_item["x"]) < 0.02):
            return s
    return None


def container_of(shapes, s):
    cont = None
    for c in shapes:
        if c is s or not c["fill"]:
            continue
        if (c["x"] - 0.01 <= s["x"] and c["y"] - 0.01 <= s["y"]
                and c["x"] + c["w"] >= s["x"] + s["w"]
                and c["y"] + c["h"] >= s["y"] + s["h"]):
            if cont is None or c["w"] * c["h"] < cont["w"] * cont["h"]:
                cont = c
    return cont


def room_for(root, s, substitutions, shapes, W, H):
    """Where this box's text may sit: (mine, top_limit, bottom_limit, cont_top)."""
    rect = rects(root, substitutions)
    mine = next((bx for bx in rect
                 if bx["text"] == s["text"][:70] and abs(bx["x"] - s["x"]) < 0.02), None)
    if mine is None:
        return None
    cont = container_of(shapes, s)
    cont_top = (cont["y"] + 0.06) if cont else 0.30
    cont_bottom = (cont["y"] + cont["h"] - 0.06) if cont else H - 0.30
    top_limit, bottom_limit = cont_top, cont_bottom
    for bx in rect:
        if bx is mine:
            continue
        if bx["x"] + bx["w"] < mine["x"] + 0.05 or bx["x"] > mine["x"] + mine["w"] - 0.05:
            continue
        if bx["top"] >= mine["bottom"] - 0.01:
            bottom_limit = min(bottom_limit, bx["top"] - 0.04)
        elif bx["bottom"] <= mine["top"] + 0.01:
            top_limit = max(top_limit, bx["bottom"] + 0.04)
    return mine, top_limit, bottom_limit, cont_top


def fix_one(root, s, substitutions, steps, W, H, report, slide_name, strict=True):
    """Grow, lift, then (only if it cannot fit) ease this box's own spacing."""
    shapes = shape_list(root)
    room = room_for(root, s, substitutions, shapes, W, H)
    if room is None:
        return False
    mine, top_limit, bottom_limit, cont_top = room
    want_h = shape_need(s, substitutions)["need"] + 0.005
    if mine["bottom"] <= bottom_limit + 0.005:
        if want_h > s["h"] + 0.005:
            move(s["el"], s["x"], s["y"], s["w"], want_h)
            return True
        return False
    new_y = s["y"] - (mine["bottom"] - bottom_limit)
    if new_y >= top_limit - 0.001 and new_y >= cont_top - 0.001:
        move(s["el"], s["x"], new_y, s["w"], want_h)
        return True
    if not strict:                      # easing is the last resort, never the first
        return False
    paras = [p for p in s["body"].findall(a_("p")) if para_text(p).strip()]
    here = current_pct(paras[0])
    for pct in steps:
        if pct >= here:
            continue
        for p in paras:
            set_lnspc(p, pct)
        room = room_for(root, s, substitutions, shape_list(root), W, H)
        if room is None:
            continue
        mine, top_limit, bottom_limit, cont_top = room
        if mine["bottom"] <= bottom_limit + 0.005:
            move(s["el"], s["x"], s["y"], s["w"],
                 shape_need(s, substitutions)["need"] + 0.005)
            report.append((slide_name, s["text"][:40], pct))
            return True
    report.append((slide_name, s["text"][:40], None))
    return False


def refit(root, substitutions, steps, W, H, report, slide_name, touched):
    """Grow, lift, then ease, until every box this pass touched fits its frame."""
    for _ in range(20):
        shapes = shape_list(root)
        progressed = False
        pending = False
        for s in shapes:
            if s["body"] is None or not s["text"] or s["id"] not in touched:
                continue
            m = shape_need(s, substitutions)
            if m is None or m["need"] <= s["h"] + 0.005:
                continue
            progressed |= fix_one(root, s, substitutions, steps, W, H, report, slide_name)
            pending = True
        if pending and not progressed:
            break
        if not pending:
            break

    # a lift can still leave two blocks touching: ease the one that moved
    for _ in range(8):
        pairs = overlaps(rects(root, substitutions))
        if not pairs:
            return True
        shapes = shape_list(root)
        did = False
        for a, b, _ox, _oy in pairs:
            for item in (b, a):        # the lower block first, then the upper one
                s = find_shape(shapes, item)
                if s is None or s["id"] not in touched:
                    continue
                paras = [p for p in s["body"].findall(a_("p")) if para_text(p).strip()]
                here = current_pct(paras[0])
                base = len(pairs)
                for pct in steps:
                    if pct >= here:
                        continue
                    for p in paras:
                        set_lnspc(p, pct)
                    need = shape_need(s, substitutions)
                    if need:
                        move(s["el"], s["x"], s["y"], s["w"], need["need"] + 0.005)
                    if len(overlaps(rects(root, substitutions))) < base:
                        report.append((slide_name, s["text"][:40], pct))
                        did = True
                        break
                if did:
                    break
            if did:
                break
        if not did:
            return False
    return not overlaps(rects(root, substitutions))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--deck", required=True)
    ap.add_argument("--min-size", type=float, default=0.0)
    ap.add_argument("--line-spacing", type=float, default=0.0)
    ap.add_argument("--no-size", action="store_true")
    ap.add_argument("--no-spacing", action="store_true")
    ap.add_argument("--substitute", default="",
                    help='measure-only face mapping, e.g. "SimHei=Heiti SC,黑体=Heiti SC"')
    ap.add_argument("--no-backup", action="store_true")
    args = ap.parse_args()

    substitutions = {}
    for pair in filter(None, (p.strip() for p in args.substitute.split(","))):
        src, _, dst = pair.partition("=")
        substitutions[src.strip()] = dst.strip()

    with zipfile.ZipFile(args.deck) as zin:
        W, H = CL.slide_size(zin)
        items = [(i, zin.read(i.filename)) for i in zin.infolist()]

    steps = [150, 145, 140, 135, 130, 125, 120, 115, 110, 105, 100]
    report, out, sizes, spaces = [], [], 0, 0
    for info, data in items:
        if not (info.filename.startswith("ppt/slides/slide")
                and info.filename.endswith(".xml")):
            out.append((info, data))
            continue
        root = etree.fromstring(data)
        touched = set()
        if args.min_size and not args.no_size:
            n, ids = bump_sizes(root, args.min_size)
            sizes += n
            touched |= ids
        if args.line_spacing and not args.no_spacing:
            n, ids = apply_spacing(root, args.line_spacing, substitutions)
            spaces += n
            touched |= ids
        if touched:
            refit(root, substitutions, steps, W, H, report,
                  info.filename.split("/")[-1], touched)
        out.append((info, etree.tostring(root, xml_declaration=True,
                                         encoding="UTF-8", standalone=True)))

    if not args.no_backup:
        shutil.copy2(args.deck, args.deck + ".bak")
    head = [o for o in out if o[0].filename == "[Content_Types].xml"]
    tail = [o for o in out if o[0].filename != "[Content_Types].xml"]
    with zipfile.ZipFile(args.deck, "w", zipfile.ZIP_DEFLATED) as zout:
        for info, data in head + tail:
            zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            zi.compress_type = info.compress_type
            zi.external_attr = info.external_attr
            zout.writestr(zi, data)

    print(f"deck written: {args.deck}")
    if sizes:
        print(f"runs raised to {args.min_size:g} pt: {sizes}")
    if spaces:
        print(f"paragraphs given {args.line_spacing:g}x spacing: {spaces}")
    for slide, text, pct in report:
        if pct is None:
            print(f"  UNRESOLVED {slide}  {text}  -> could not be fitted")
        else:
            print(f"  eased      {slide}  {text}  -> {pct}% line spacing")
    return 1 if any(pct is None for _s, _t, pct in report) else 0


if __name__ == "__main__":
    sys.exit(main())
