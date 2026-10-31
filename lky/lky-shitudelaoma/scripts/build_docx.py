#!/usr/bin/env python3
"""把内容 JSON 渲染成符合公众号两个系列版式规范的 docx。

用法:
    runtime_python build_docx.py content.json [--output out.docx] [--fig-dir DIR]

版式参数与 references/docx-format.md 一一对应，改版式请同时改两处。
学生信在 JSON 顶层写 "series": "学生信" 以套用模拟图声明文字。
"""
from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

CJK_FONT = "Microsoft YaHei"
CODE_FONT = "Consolas"
CODE_STYLE = "Code Block"
BLACK = RGBColor(0x00, 0x00, 0x00)
# 全篇纯黑：标题也只靠字号与加粗区分，不用任何彩色。
INK_TITLE = BLACK
INK_H1 = BLACK
INK_H2 = BLACK

BODY_PT = 12          # 正文 16px（Word pt × 96/72 = px）
CAPTION_PT = 10.5     # 图注 14px
CODE_PT = 10.5        # 附录代码，等宽字体
REFERENCE_PT = 9      # 参考文献 12px
TITLE_PT = 22
SUBTITLE_PT = 14
IMAGE_WIDTH_IN = 5.2
LINE_SPACING = 1.5

DISCLAIMER_DEFAULT = "（声明：本文图片均来源于论文原文，仅供学术交流，不构成商业用途）"
SERIES_DISCLAIMER = {
    "学生信": "（声明：本文图片均为模拟生成，不代表真实数据）",
}

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"


def _cjk(run):
    """统一 run 的中西文字体。"""
    run.font.name = CJK_FONT
    run._element.rPr.rFonts.set(qn("w:eastAsia"), CJK_FONT)


def _style(doc, name, *, size, bold, color, before, after):
    st = doc.styles[name]
    st.font.name = CJK_FONT
    st.font.size = Pt(size)
    st.font.bold = bold
    st.font.color.rgb = color
    st.element.rPr.rFonts.set(qn("w:eastAsia"), CJK_FONT)
    pf = st.paragraph_format
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    return st


def _strip_border(style):
    """内置 Title 样式自带下边框，公众号排版不需要，去掉。"""
    ppr = style.element.get_or_add_pPr()
    for bdr in ppr.findall(qn("w:pBdr")):
        ppr.remove(bdr)


def _setup_styles(doc):
    normal = doc.styles["Normal"]
    normal.font.name = CJK_FONT
    normal.font.size = Pt(BODY_PT)
    normal.font.color.rgb = BLACK
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), CJK_FONT)
    pf = normal.paragraph_format
    pf.line_spacing = LINE_SPACING
    pf.space_after = Pt(8)
    pf.space_before = Pt(0)

    title = _style(doc, "Title", size=TITLE_PT, bold=True, color=INK_TITLE, before=0, after=4)
    _strip_border(title)
    _style(doc, "Heading 1", size=17, bold=True, color=INK_H1, before=28, after=14)
    _style(doc, "Heading 2", size=14, bold=True, color=INK_H2, before=20, after=10)
    _style(doc, "Heading 3", size=12.5, bold=True, color=INK_H2, before=14, after=8)

    code = doc.styles.add_style(CODE_STYLE, WD_STYLE_TYPE.PARAGRAPH)
    code.base_style = doc.styles["Normal"]
    code.font.name = CODE_FONT
    code.font.size = Pt(CODE_PT)
    code.font.color.rgb = BLACK
    code.element.rPr.rFonts.set(qn("w:eastAsia"), CJK_FONT)
    cpf = code.paragraph_format
    cpf.line_spacing = 1.15
    cpf.space_before = Pt(0)
    cpf.space_after = Pt(0)


def add_para(doc, text, *, size=BODY_PT, bold=False, color=BLACK, align=None,
             space_after=None, space_before=None):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.bold = bold
    run.font.size = Pt(size)
    run.font.color.rgb = color
    _cjk(run)
    pf = p.paragraph_format
    if align is not None:
        p.alignment = align
    if space_after is not None:
        pf.space_after = Pt(space_after)
    if space_before is not None:
        pf.space_before = Pt(space_before)
    return p


def add_blank_line(doc):
    """图注之后的空行，用来把图注和下面的正文隔开。"""
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)
    pf.line_spacing = 1.0
    return p


def add_point(doc, name, text):
    """并列项：· **名称**：说明（微信导入安全写法）"""
    p = doc.add_paragraph()
    head = p.add_run("· ")
    head.font.size = Pt(BODY_PT)
    head.font.color.rgb = BLACK
    _cjk(head)
    label = p.add_run(f"{name}：")
    label.bold = True
    label.font.size = Pt(BODY_PT)
    label.font.color.rgb = BLACK
    _cjk(label)
    body = p.add_run(text)
    body.font.size = Pt(BODY_PT)
    body.font.color.rgb = BLACK
    _cjk(body)
    p.paragraph_format.space_after = Pt(6)
    return p


def add_snapshot(doc, label, value):
    p = doc.add_paragraph()
    lead = p.add_run(f"{label}：")
    lead.bold = True
    lead.font.size = Pt(BODY_PT)
    lead.font.color.rgb = BLACK
    _cjk(lead)
    val = p.add_run(str(value))
    val.font.size = Pt(BODY_PT)
    val.font.color.rgb = BLACK
    _cjk(val)
    pf = p.paragraph_format
    pf.space_after = Pt(2)
    pf.space_before = Pt(2)
    return p


def add_image(doc, path, caption, disclaimer=False, disclaimer_text=DISCLAIMER_DEFAULT,
              width_in=IMAGE_WIDTH_IN):
    if not Path(path).exists():
        raise FileNotFoundError(f"图片不存在: {path}")
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(4)
    p.add_run().add_picture(str(path), width=Inches(width_in))

    add_para(doc, caption, size=CAPTION_PT, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=2)
    if disclaimer:
        add_para(doc, disclaimer_text, size=CAPTION_PT,
                 align=WD_ALIGN_PARAGRAPH.CENTER, space_after=2)
    add_blank_line(doc)


def add_qa(doc, question, answer):
    """常见问题：[问题] 标题 + [回答] 正文，各占一段。"""
    for label, text, after in (("[问题] ", question, 6), ("[回答] ", answer, 12)):
        p = doc.add_paragraph()
        head = p.add_run(label)
        head.bold = True
        head.font.size = Pt(BODY_PT)
        head.font.color.rgb = BLACK
        _cjk(head)
        body = p.add_run(text)
        body.font.size = Pt(BODY_PT)
        body.font.color.rgb = BLACK
        _cjk(body)
        p.paragraph_format.space_after = Pt(after)


def add_code(doc, text):
    """附录代码：逐行成段，等宽字体，保留原始缩进。"""
    lines = str(text).replace("\r\n", "\n").split("\n")
    while lines and not lines[-1].strip():
        lines.pop()
    for line in lines:
        p = doc.add_paragraph(style=CODE_STYLE)
        run = p.add_run(line)
        run.font.name = CODE_FONT
        run.font.size = Pt(CODE_PT)
        run.font.color.rgb = BLACK
        run._element.rPr.rFonts.set(qn("w:eastAsia"), CJK_FONT)
    doc.add_paragraph()


def render(data, out_path):
    doc = Document()
    _setup_styles(doc)
    fig_dir = Path(data.get("fig_dir") or out_path.parent)

    doc.add_paragraph(data["title"], style="Title").alignment = WD_ALIGN_PARAGRAPH.CENTER
    if data.get("subtitle"):
        add_para(doc, data["subtitle"], size=SUBTITLE_PT,
                 align=WD_ALIGN_PARAGRAPH.CENTER, space_after=14)

    if data.get("snapshot"):
        add_para(doc, "论文快照", bold=True, size=14, color=INK_H2, space_after=6)
        for pair in data["snapshot"]:
            add_snapshot(doc, pair[0], pair[1])
        doc.add_paragraph()

    if data.get("toc"):
        doc.add_heading("小目录", level=1)
        for line in data["toc"]:
            add_para(doc, line, space_after=2)
        doc.add_paragraph()

    # 开篇（学生信）：小目录之后的钩子段落，放在正文各章之前。
    if data.get("intro"):
        for text in data["intro"]:
            add_para(doc, text)
        doc.add_paragraph()

    first_image_seen = False
    default_disclaimer = (data.get("disclaimer_text")
                          or SERIES_DISCLAIMER.get(data.get("series"), DISCLAIMER_DEFAULT))
    for section in data.get("sections", []):
        doc.add_heading(section["heading"], level=int(section.get("level", 1)))
        for block in section.get("blocks", []):
            kind = block.get("type", "para")
            if kind == "para":
                add_para(doc, block["text"])
            elif kind == "sub":
                doc.add_heading(block["text"], level=int(block.get("level", 2)))
            elif kind == "point":
                for item in block["items"]:
                    add_point(doc, item[0], item[1])
            elif kind == "image":
                img_path = Path(block["file"])
                if not img_path.is_absolute():
                    img_path = fig_dir / img_path
                want_disclaimer = bool(block.get("disclaimer")) or not first_image_seen
                add_image(doc, img_path, block["caption"], disclaimer=want_disclaimer,
                          disclaimer_text=(block.get("disclaimer_text")
                                           or default_disclaimer),
                          width_in=float(block.get("width_in", IMAGE_WIDTH_IN)))
                first_image_seen = True
            elif kind == "qa":
                for item in block["items"]:
                    add_qa(doc, item[0], item[1])
            elif kind == "code":
                add_code(doc, block["text"])
            else:
                raise ValueError(f"未知 block 类型: {kind}")

    if data.get("references"):
        doc.add_heading("参考文献", level=1)
        for ref in data["references"]:
            add_para(doc, ref, size=REFERENCE_PT, space_after=4)

    if data.get("footnote"):
        for index, line in enumerate(data["footnote"]):
            add_para(doc, line, align=WD_ALIGN_PARAGRAPH.CENTER,
                     space_before=20 if index == 0 else 0, space_after=4)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))
    return doc


def report(doc, out_path):
    body = doc.element.body
    images = body.findall(f".//{{{WP_NS}}}inline") + body.findall(f".//{{{WP_NS}}}anchor")
    text = "\n".join(p.text for p in doc.paragraphs)
    size_mb = out_path.stat().st_size / 1024 / 1024
    print(f"[OK] 已生成 {out_path}")
    print(f"     段落数 {len(doc.paragraphs)}，内嵌图片 {len(images)}，文件 {size_mb:.2f} MB")
    problems = []
    for i, p in enumerate(doc.paragraphs, 1):
        stripped = p.text.lstrip()
        if stripped.startswith(("- ", "* ", "·")) and p.text.startswith(("- ", "* ")):
            problems.append(f"第{i}段出现列表语法: {p.text[:40]}")
        if "](" in p.text and "![" not in p.text:
            problems.append(f"第{i}段可能含超链接: {p.text[:40]}")
    if "声明：" not in text:
        problems.append("全文没有找到图片来源声明行")
    if not problems:
        print("     结构自检: 无列表语法、无超链接、声明行在位")
    else:
        print("     结构自检发现问题:")
        for item in problems:
            print(f"       - {item}")
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description="内容 JSON -> 公众号 docx")
    ap.add_argument("content", help="内容 JSON 路径")
    ap.add_argument("--output", help="输出 docx 路径（默认取 JSON 的 output 字段）")
    ap.add_argument("--fig-dir", help="图片目录（默认取 JSON 的 fig_dir 字段）")
    args = ap.parse_args(argv)

    content_path = Path(args.content).expanduser().resolve()
    data = json.loads(content_path.read_text(encoding="utf-8"))
    if args.fig_dir:
        data["fig_dir"] = args.fig_dir
    if not data.get("fig_dir"):
        data["fig_dir"] = str(content_path.parent)

    out = args.output or data.get("output")
    if not out:
        raise SystemExit("没有指定输出路径：请在 JSON 里写 output，或用 --output")
    out_path = Path(out).expanduser().resolve()

    doc = render(data, out_path)
    problems = report(doc, out_path)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
