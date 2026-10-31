#!/usr/bin/env python3
"""从论文 PDF 里取原图（pypdfium2 实现，替代旧脚本用的 PyMuPDF）。

四个子命令:
    list      列出每页尺寸与嵌入图片（坐标用点，原点在页面左下角）
    extract   抽取嵌入图片为 PNG（按尺寸过滤掉图标/装饰图）
    crop      渲染整页后按坐标裁剪（矢量主图走这条路）
    compress  把已有 PNG 压到指定宽度

例子:
    python3 extract_pdf_figures.py list  paper.pdf --pages 1-6
    python3 extract_pdf_figures.py extract paper.pdf --out fig/ --prefix ed_fig --min-pt 120
    python3 extract_pdf_figures.py crop paper.pdf --page 2 --box 0.08,0.45,0.95,0.95 \
        --unit frac --out fig/km_fig1.png
    python3 extract_pdf_figures.py compress fig/*.png --max-width 1200
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image


def parse_pages(spec, total):
    if not spec:
        return list(range(total))
    pages = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            pages.extend(range(int(start) - 1, int(end)))
        elif part:
            pages.append(int(part) - 1)
    return [p for p in pages if 0 <= p < total]


def to_rgb(img):
    if img.mode in ("CMYK", "LA", "P", "L"):
        return img.convert("RGB")
    if img.mode == "RGBA":
        return img
    return img.convert("RGB")


def save_png(img, path, max_width=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    img = to_rgb(img)
    if max_width and img.width > max_width:
        height = round(img.height * max_width / img.width)
        img = img.resize((max_width, height), Image.LANCZOS)
    img.save(path, "PNG", optimize=True)
    return path, img.size


def cmd_list(args):
    pdf = pdfium.PdfDocument(args.pdf)
    print(f"文件: {args.pdf}")
    print(f"页数: {len(pdf)}")
    for index in parse_pages(args.pages, len(pdf)):
        page = pdf[index]
        width, height = page.get_size()
        print(f"\n第 {index + 1} 页  页面尺寸 {width:.1f} x {height:.1f} pt"
              f"  （可裁剪范围 x: 0-{width:.1f}, y: 0-{height:.1f}，y 从页面底部起算）")
        images = [obj for obj in page.get_objects() if isinstance(obj, pdfium.PdfImage)]
        if not images:
            print("  无嵌入图片 —— 主图是矢量绘制，用 crop 子命令渲染裁剪")
            continue
        entries = []
        for i, obj in enumerate(images):
            left, bottom, right, top = obj.get_bounds()
            px_w, px_h = obj.get_px_size()
            entries.append((i, left, bottom, right, top, px_w, px_h, obj.get_filters()))
        usable = [e for e in entries if (e[3] - e[1]) >= args.min_pt]
        small = len(entries) - len(usable)
        usable.sort(key=lambda e: (e[3] - e[1]) * (e[4] - e[2]), reverse=True)
        for i, left, bottom, right, top, px_w, px_h, filters in usable[:args.top]:
            print(f"  [{i}] 位置 ({left:.1f},{bottom:.1f})-({right:.1f},{top:.1f}) pt"
                  f"  宽 {right - left:.1f} pt  原始 {px_w}x{px_h} px  滤镜 {'/'.join(filters)}")
        if len(usable) > args.top:
            print(f"  ... 另有 {len(usable) - args.top} 张同类图片（用 --top 调大显示数量）")
        if small:
            print(f"  （另有 {small} 张宽度小于 {args.min_pt:.0f} pt 的小图，通常是图标或装饰，已折叠）")
    return 0


def cmd_extract(args):
    pdf = pdfium.PdfDocument(args.pdf)
    out_dir = Path(args.out or ".").expanduser().resolve()
    saved = []
    for index in parse_pages(args.pages, len(pdf)):
        page = pdf[index]
        images = [obj for obj in page.get_objects() if isinstance(obj, pdfium.PdfImage)]
        for i, obj in enumerate(images):
            left, bottom, right, top = obj.get_bounds()
            px_w, px_h = obj.get_px_size()
            if (right - left) < args.min_pt or px_w < args.min_px:
                continue
            img = obj.get_bitmap(render=True, scale_to_original=True).to_pil()
            name = f"{args.prefix}{index + 1:02d}_{i + 1:02d}.png"
            path, size = save_png(img, out_dir / name, max_width=args.max_width)
            saved.append((name, size[0], size[1], path.stat().st_size / 1024))
    if not saved:
        print("[warn] 没有符合尺寸阈值的嵌入图片；主图可能是矢量绘制，改用 crop 子命令")
        return 1
    print(f"抽出 {len(saved)} 张图片到 {out_dir}")
    for name, w, h, kb in saved:
        print(f"  {name}  {w}x{h} px  {kb:.0f} KB")
    return 0


def cmd_crop(args):
    pdf = pdfium.PdfDocument(args.pdf)
    index = args.page - 1
    page = pdf[index]
    page_w, page_h = page.get_size()
    values = [float(v) for v in args.box.split(",")]
    if len(values) != 4:
        raise SystemExit("--box 需要 4 个数字：left,bottom,right,top")
    left, bottom, right, top = values
    if args.unit == "frac":
        left, right = left * page_w, right * page_w
        bottom, top = bottom * page_h, top * page_h

    scale = args.dpi / 72.0
    bitmap = page.render(scale=scale)
    img = bitmap.to_pil()
    box = (round(left * scale), round((page_h - top) * scale),
           round(right * scale), round((page_h - bottom) * scale))
    box = (max(box[0], 0), max(box[1], 0),
           min(box[2], img.width), min(box[3], img.height))
    if box[2] - box[0] < 10 or box[3] - box[1] < 10:
        raise SystemExit(f"裁剪区域太小: {box}")
    cropped = img.crop(box)
    path, size = save_png(cropped, args.out, max_width=args.max_width)
    print(f"已裁剪第 {args.page} 页 {box} -> {path}  {size[0]}x{size[1]} px"
          f"  {path.stat().st_size / 1024:.0f} KB")
    return 0


def cmd_compress(args):
    for raw in args.paths:
        path = Path(raw).expanduser()
        if not path.exists():
            print(f"[skip] 找不到 {path}")
            continue
        img = Image.open(path)
        before = path.stat().st_size / 1024
        img = to_rgb(img)
        if img.width > args.max_width:
            height = round(img.height * args.max_width / img.width)
            img = img.resize((args.max_width, height), Image.LANCZOS)
        img.save(path, "PNG", optimize=True)
        print(f"{path.name}  {before:.0f} KB -> {path.stat().st_size / 1024:.0f} KB"
              f"  ({img.width}x{img.height})")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="论文 PDF 原图提取")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list", help="列出页面尺寸与嵌入图片")
    p.add_argument("pdf")
    p.add_argument("--pages", help="页码范围，如 1-6 或 1,3,5")
    p.add_argument("--min-pt", type=float, default=100, help="小于该宽度的图折叠不显示")
    p.add_argument("--top", type=int, default=12, help="每页最多显示多少张图")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("extract", help="抽取嵌入图片")
    p.add_argument("pdf")
    p.add_argument("--out", default=".")
    p.add_argument("--prefix", default="fig")
    p.add_argument("--pages")
    p.add_argument("--min-pt", type=float, default=100, help="最小显示宽度（点）")
    p.add_argument("--min-px", type=int, default=200, help="最小原始像素宽度")
    p.add_argument("--max-width", type=int, default=1200)
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("crop", help="渲染整页后按坐标裁剪矢量主图")
    p.add_argument("pdf")
    p.add_argument("--page", type=int, required=True, help="页码，从 1 开始")
    p.add_argument("--box", required=True, help="left,bottom,right,top")
    p.add_argument("--unit", choices=["pt", "frac"], default="pt")
    p.add_argument("--dpi", type=int, default=300)
    p.add_argument("--out", required=True)
    p.add_argument("--max-width", type=int, default=1200)
    p.set_defaults(func=cmd_crop)

    p = sub.add_parser("compress", help="压缩已有 PNG")
    p.add_argument("paths", nargs="+")
    p.add_argument("--max-width", type=int, default=1200)
    p.set_defaults(func=cmd_compress)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
