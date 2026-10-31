#!/usr/bin/env python3
"""Preview gate: rasterise a saved .pptx to one PNG per slide.

There is usually no PowerPoint or LibreOffice available, so this reads the actual package and
redraws it with Pillow: shape geometry (including the real corner radius), fills, lines,
pictures and every text run, using the font files the deck requests.

It is a faithful read of the file, not a redraw of the author's intent. If a glyph shows as a
box here, it will show as a box in PowerPoint.

Usage:
    python3 render_deck.py --deck deck.pptx --out /tmp/preview [--dpi 130]
    python3 render_deck.py --deck deck.pptx --out /tmp/preview --contact-sheet
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import zipfile
from io import BytesIO
from xml.etree import ElementTree as ET

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import font_index  # noqa: E402

CJK_CHAR = re.compile(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]")

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
EMU = 914400.0

_fcache: dict = {}
SUBSTITUTED: set = set()


class Render:
    def __init__(self, dpi: int, w_in: float, h_in: float, cjk_fallback: str = "Heiti SC"):
        self.scale = dpi
        self.w = int(w_in * dpi)
        self.h = int(h_in * dpi)
        self.cjk_fallback = cjk_fallback

    def px(self, v):
        return float(v) / EMU * self.scale

    def font(self, family: str, bold: bool, size_pt: float, ch: str = ""):
        px = max(6, int(round(size_pt * self.scale / 72.0)))
        # Anything past ASCII should come from the CJK fallback: the substituted face is a
        # CJK one and carries the symbols (▍ → ≠) that a Latin-first fallback would box up.
        non_ascii = bool(ch) and ord(ch[0]) > 127
        key = (family, bold, px, non_ascii)
        if key in _fcache:
            return _fcache[key]
        face = font_index.resolve(family, bold)
        if not face:
            if family:
                SUBSTITUTED.add(family)
            # A missing face is substituted by the real PowerPoint too. Draw Chinese with an
            # installed CJK face so the preview stays readable instead of showing boxes.
            face = (
                font_index.resolve(self.cjk_fallback, bold)
                if key[3]
                else None
            ) or font_index.resolve("Helvetica")
        try:
            f = ImageFont.truetype(face[0], px, index=face[1])
        except Exception:
            f = ImageFont.load_default()
        _fcache[key] = f
        return f


def solid(el):
    if el is None:
        return None
    srgb = el.find(".//a:srgbClr", {"a": A})
    if srgb is not None and srgb.get("val"):
        return "#" + srgb.get("val")
    return None


def runs_of(para):
    out = []
    for r in para.findall("a:r", {"a": A}):
        t = r.find("a:t", {"a": A})
        rPr = r.find("a:rPr", {"a": A})
        size, bold, color, face = 18.0, False, "#16222E", "Helvetica"
        if rPr is not None:
            if rPr.get("sz"):
                size = float(rPr.get("sz")) / 100.0
            bold = rPr.get("b") == "1"
            c = solid(rPr.find("a:solidFill", {"a": A}))
            if c:
                color = c
            lat = rPr.find("a:latin", {"a": A})
            if lat is not None and lat.get("typeface"):
                face = lat.get("typeface")
        out.append({"text": (t.text or "") if t is not None else "", "size": size,
                    "bold": bold, "color": color, "face": face})
    return out


def para_props(para):
    """Paragraph properties. `marL` is returned in EMU — convert before using it as pixels."""
    pPr = para.find("a:pPr", {"a": A})
    d = {"align": "l", "marL": 0.0, "lnSpc": None, "after": 0.0, "bullet": None}
    if pPr is None:
        return d
    d["align"] = pPr.get("algn", "l")
    if pPr.get("marL"):
        d["marL"] = float(pPr.get("marL"))  # EMU
    sp = pPr.find("a:lnSpc/a:spcPts", {"a": A})
    if sp is not None and sp.get("val"):
        d["lnSpc"] = float(sp.get("val")) / 100.0
    af = pPr.find("a:spcAft/a:spcPts", {"a": A})
    if af is not None and af.get("val"):
        d["after"] = float(af.get("val")) / 100.0
    bu = pPr.find("a:buChar", {"a": A})
    if bu is not None:
        d["bullet"] = bu.get("char") or "\u2022"
    return d


def wrap(r, runs, avail_px):
    chars = [(ch, run) for run in runs for ch in run["text"]]
    lines, cur, curw = [], [], 0.0
    for ch, run in chars:
        if ch == "\n":
            lines.append(cur)
            cur, curw = [], 0.0
            continue
        w = r.font(run["face"], run["bold"], run["size"], ch).getlength(ch)
        if curw + w > avail_px and cur:
            lines.append(cur)
            cur, curw = [], 0.0
            if ch == " ":
                continue
        cur.append((ch, run))
        curw += w
    lines.append(cur)
    return lines


def draw_text(r, draw, sp, x, y, w, h):
    tx = sp.find(".//p:txBody", {"p": P})
    if tx is None:
        return
    bodyPr = tx.find("a:bodyPr", {"a": A})
    lIns = rIns = 0.1 * r.scale
    tIns = bIns = 0.05 * r.scale
    anchor = "t"
    if bodyPr is not None:
        anchor = bodyPr.get("anchor", "t")
        if bodyPr.get("lIns") is not None:
            lIns = r.px(bodyPr.get("lIns"))
        if bodyPr.get("rIns") is not None:
            rIns = r.px(bodyPr.get("rIns"))
        if bodyPr.get("tIns") is not None:
            tIns = r.px(bodyPr.get("tIns"))
        if bodyPr.get("bIns") is not None:
            bIns = r.px(bodyPr.get("bIns"))

    avail = w - lIns - rIns
    paras, total = [], 0.0
    for para in tx.findall("a:p", {"a": A}):
        runs = runs_of(para)
        if not any(v["text"].strip() for v in runs):
            continue
        p = para_props(para)
        # marL is stored in EMU. PowerPoint writes a real indent for bulleted lists, so a
        # round-tripped deck will have a large non-zero value here; treating it as pixels
        # collapses the wrap width and pushes every line off the slide.
        p["marL"] = p["marL"] / EMU * r.scale
        size = max(v["size"] for v in runs)
        ln = p["lnSpc"] or size * 1.2
        lines = wrap(r, runs, avail - p["marL"])
        paras.append({"lines": lines, "ln": ln, "props": p})
        total += len(lines) * ln * r.scale / 72.0 + p["after"] * r.scale / 72.0

    start = y + tIns
    if anchor == "ctr":
        start = y + (h - total) / 2.0
    elif anchor == "b":
        start = y + h - bIns - total

    cy = start
    for par in paras:
        p = par["props"]
        lh = par["ln"] * r.scale / 72.0
        for li, line in enumerate(par["lines"]):
            lw = sum(r.font(v["face"], v["bold"], v["size"], ch).getlength(ch) for ch, v in line)
            if p["align"] == "ctr":
                cx = x + lIns + p["marL"] + (avail - p["marL"] - lw) / 2.0
            elif p["align"] == "r":
                cx = x + w - rIns - lw
            else:
                cx = x + lIns + p["marL"]
            if p["bullet"] and li == 0:
                bcol = next((v["color"] for _, v in line), "#16222E")
                sz = max(2, int(3.2 * r.scale / 72.0 * 2))
                draw.rectangle([cx - p["marL"] * 0.72, cy + lh * 0.34,
                                cx - p["marL"] * 0.72 + sz, cy + lh * 0.34 + sz], fill=bcol)
            for ch, run in line:
                f = r.font(run["face"], run["bold"], run["size"], ch)
                draw.text((cx, cy), ch, font=f, fill=run["color"], anchor="la")
                cx += f.getlength(ch)
            cy += lh
        cy += p["after"] * r.scale / 72.0


def chevron_poly(x, y, w, h):
    s = h * 0.42
    return [(x, y), (x + w - s, y), (x + w, y + h / 2), (x + w - s, y + h),
            (x, y + h), (x + s, y + h / 2)]


def render_slide(z, names, name, r: Render):
    img = Image.new("RGB", (r.w, r.h), "#FFFFFF")
    draw = ImageDraw.Draw(img)
    root = ET.fromstring(z.read(name).decode("utf-8"))

    bg = root.find(".//p:bg//a:srgbClr", {"p": P, "a": A})
    if bg is not None and bg.get("val"):
        img.paste("#" + bg.get("val"), [0, 0, r.w, r.h])

    rels = {}
    rel_path = name.replace("slides/", "slides/_rels/") + ".rels"
    if rel_path in names:
        rr = ET.fromstring(z.read(rel_path).decode("utf-8"))
        for rel in rr:
            rels[rel.get("Id")] = rel.get("Target")

    tree = root.find(".//p:cSld/p:spTree", {"p": P})
    if tree is None:
        return img

    for node in list(tree):
        tag = node.tag.split("}")[1]

        if tag == "pic":
            xfrm = node.find(".//a:xfrm", {"a": A})
            blip = node.find(".//a:blip", {"a": A})
            if xfrm is None or blip is None:
                continue
            off, ext = xfrm.find("a:off", {"a": A}), xfrm.find("a:ext", {"a": A})
            x, y = r.px(off.get("x")), r.px(off.get("y"))
            w, h = r.px(ext.get("cx")), r.px(ext.get("cy"))
            target = rels.get(blip.get("{%s}embed" % R), "")
            media = os.path.normpath(os.path.join("ppt/slides", target)).replace("\\", "/")
            if media in names:
                pic = Image.open(BytesIO(z.read(media))).convert("RGBA")
                pic = pic.resize((max(1, int(w)), max(1, int(h))), Image.LANCZOS)
                img.paste(pic, (int(x), int(y)), pic)
            continue

        if tag == "graphicFrame":
            xfrm = node.find(".//p:xfrm", {"p": P})
            if xfrm is None:
                continue
            off, ext = xfrm.find("a:off", {"a": A}), xfrm.find("a:ext", {"a": A})
            draw.rectangle([r.px(off.get("x")), r.px(off.get("y")),
                            r.px(off.get("x")) + r.px(ext.get("cx")),
                            r.px(off.get("y")) + r.px(ext.get("cy"))],
                           outline="#C9D6E2", width=2)
            continue

        if tag != "sp":
            continue

        spPr = node.find(".//p:spPr", {"p": P})
        if spPr is None:
            continue
        xfrm = spPr.find("a:xfrm", {"a": A})
        if xfrm is None:
            continue
        off, ext = xfrm.find("a:off", {"a": A}), xfrm.find("a:ext", {"a": A})
        if off is None or ext is None:
            continue
        x, y = r.px(off.get("x")), r.px(off.get("y"))
        w, h = r.px(ext.get("cx")), r.px(ext.get("cy"))

        prst_el = spPr.find("a:prstGeom", {"a": A})
        prst = prst_el.get("prst") if prst_el is not None else "rect"
        nofill = spPr.find("a:noFill", {"a": A})
        fill = None if nofill is not None else solid(spPr.find("a:solidFill", {"a": A}))
        ln = spPr.find("a:ln", {"a": A})
        lc, lw = None, 0
        if ln is not None and ln.find("a:noFill", {"a": A}) is None:
            lw = float(ln.get("w", "9525")) / EMU * r.scale
            lc = solid(ln.find("a:solidFill", {"a": A}))

        if fill or lc:
            if prst == "roundRect":
                rad = 0.0
                gd = spPr.find('.//a:gd[@name="adj"]', {"a": A})
                if gd is not None and gd.get("fmla"):
                    try:
                        rad = float(gd.get("fmla").split()[-1]) / 100000.0 * min(w, h)
                    except Exception:
                        rad = 0.0
                draw.rounded_rectangle([x, y, x + w, y + h], radius=max(1, int(rad)),
                                       fill=fill, outline=lc,
                                       width=max(1, int(lw)) if lc else 0)
            elif prst == "ellipse":
                draw.ellipse([x, y, x + w, y + h], fill=fill, outline=lc,
                             width=max(1, int(lw)) if lc else 0)
            elif prst == "chevron":
                draw.polygon(chevron_poly(x, y, w, h), fill=fill, outline=lc)
            elif prst == "line":
                draw.line([x, y, x + w, y + h], fill=lc or "#000000", width=max(1, int(lw or 1)))
            else:
                draw.rectangle([x, y, x + w, y + h], fill=fill, outline=lc,
                               width=max(1, int(lw)) if lc else 0)
        draw_text(r, draw, node, x, y, w, h)
    return img


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--deck", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--dpi", type=int, default=130)
    ap.add_argument("--cjk-fallback", default="Heiti SC",
                    help="face used to draw Chinese when the declared one is missing")
    ap.add_argument("--contact-sheet", action="store_true",
                    help="also build one grid image of every slide")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    with zipfile.ZipFile(args.deck) as z:
        names = z.namelist()
        try:
            pres = ET.fromstring(z.read("ppt/presentation.xml"))
            sz = pres.find(".//p:sldSz", {"p": P})
            w_in, h_in = float(sz.get("cx")) / EMU, float(sz.get("cy")) / EMU
        except Exception:
            w_in, h_in = 13.333, 7.5
        r = Render(args.dpi, w_in, h_in, args.cjk_fallback)
        slides = sorted(
            (n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
            key=lambda n: int(re.findall(r"\d+", n)[-1]),
        )
        made = []
        for n in slides:
            idx = int(re.findall(r"\d+", n)[-1])
            path = os.path.join(args.out, f"slide-{idx:02d}.png")
            render_slide(z, names, n, r).save(path)
            made.append(path)

    print(f"rendered {len(made)} slide(s) to {args.out}")
    if SUBSTITUTED:
        print(f"WARN    these faces are not installed and were substituted: {sorted(SUBSTITUTED)}")
        print(f"        Chinese was drawn with {args.cjk_fallback}; the preview is approximate")

    if args.contact_sheet and made:
        cols = min(5, len(made))
        rows = (len(made) + cols - 1) // cols
        tw, th = 470, int(470 * h_in / w_in)
        sheet = Image.new("RGB", (cols * tw + (cols + 1) * 8, rows * th + (rows + 1) * 8), "#8a8a8a")
        for i, p in enumerate(made):
            im = Image.open(p).resize((tw, th), Image.LANCZOS)
            rr, cc = divmod(i, cols)
            sheet.paste(im, (8 + cc * (tw + 8), 8 + rr * (th + 8)))
        out = os.path.join(args.out, "_contact-sheet.png")
        sheet.save(out)
        print("contact sheet:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
