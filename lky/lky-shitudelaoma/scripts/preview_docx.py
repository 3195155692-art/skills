#!/usr/bin/env python3
"""docx 版式自检：转成 PDF，再把每页渲染成 PNG，用来肉眼确认排版。

注意：本机 LibreOffice 自带的 fontconfig 默认看不到系统中文字体，直接转换会把中文渲染成空白。
这里显式写一份 fontconfig 配置指向系统字体目录，转换结果才有中文。

用法:
    python3 preview_docx.py 文章.docx [--out /tmp/preview] [--dpi 110]
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pypdfium2 as pdfium

SOFFICE_CANDIDATES = [
    "/Users/oldma/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/override/soffice",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    "soffice",
]

FONTS_CONF = """<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <dir>/System/Library/Fonts</dir>
  <dir>/Library/Fonts</dir>
  <cachedir>{cache}</cachedir>
</fontconfig>
"""


def find_soffice():
    for candidate in SOFFICE_CANDIDATES:
        found = shutil.which(candidate) if os.sep not in candidate else (
            candidate if Path(candidate).exists() else None)
        if found:
            return found
    raise SystemExit("找不到 soffice，无法转 PDF")


def convert(docx, out_dir, cache_dir):
    conf = cache_dir / "fonts.conf"
    conf.write_text(FONTS_CONF.format(cache=cache_dir), encoding="utf-8")
    env = dict(os.environ, FONTCONFIG_FILE=str(conf))
    result = subprocess.run(
        [find_soffice(), "--headless", "--convert-to", "pdf", "--outdir",
         str(out_dir), str(docx)],
        env=env, capture_output=True, text=True,
    )
    pdf = out_dir / (Path(docx).stem + ".pdf")
    if not pdf.exists():
        print(result.stdout, result.stderr)
        raise SystemExit("PDF 转换失败")
    return pdf


def main(argv=None):
    ap = argparse.ArgumentParser(description="docx 版式预览")
    ap.add_argument("docx")
    ap.add_argument("--out", help="预览图输出目录，默认临时目录")
    ap.add_argument("--dpi", type=int, default=110)
    args = ap.parse_args(argv)

    docx = Path(args.docx).expanduser().resolve()
    out_dir = Path(args.out).expanduser().resolve() if args.out else Path(tempfile.mkdtemp(prefix="docx-preview-"))
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = out_dir / "fontconfig"
    cache_dir.mkdir(exist_ok=True)

    pdf = convert(docx, out_dir, cache_dir)
    doc = pdfium.PdfDocument(str(pdf))
    pages = []
    for i in range(len(doc)):
        target = out_dir / f"page{i + 1:02d}.png"
        doc[i].render(scale=args.dpi / 72).to_pil().save(target)
        pages.append(target)

    print(f"PDF: {pdf}")
    print(f"共 {len(pages)} 页，预览图：")
    for page in pages:
        print(f"  {page}")
    print("请逐页查看：中文字体是否正常、图片是否超出页边、快照与图注是否错位。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
