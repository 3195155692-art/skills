#!/usr/bin/env python3
"""交付前自检：格式红线、图片、必备字段、Q&A、声明行。

用法:
    python3 check_article.py <文章.md|文章.docx|期数目录> [--series 学生信|文献精读]

硬性问题（列表语法、超链接、表格语法、emoji）会返回非零退出码；符号与提示性问题只报告。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from docx.enum.text import WD_ALIGN_PARAGRAPH

WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"

CAPTION_PT = 10.5  # 图注 14px；正文 16px = 12pt
REFERENCE_PT = 9   # 参考文献 12px

BAD_CHAR_RANGES = [
    (0x1F000, 0x1FAFF, "emoji"),
    (0x2600, 0x27BF, "杂项符号"),
    (0x2B00, 0x2BFF, "箭头符号"),
    (0x2190, 0x21FF, "箭头"),
    (0x2200, 0x22FF, "数学符号"),
    (0x0370, 0x03FF, "希腊字母"),
    (0xFE0F, 0xFE0F, "变体选择符"),
]

BULLET_RE = re.compile(r"^\s*[-*+]\s+")
ORDERED_RE = re.compile(r"^\s*\d+\.\s+")
LINK_RE = re.compile(r"\[[^\]\n]+\]\((?!\s*#)[^)\n]+\)")
TABLE_RE = re.compile(r"^\s*\|.*\|\s*$")
DASH_RE = re.compile(r"—{2,}")
REFERENCE_LINE = re.compile(r"^\s*\[\d+\]")
NEGATIVE_PATTERNS = [
    (re.compile(r"不是[^。；！？]{0,40}而是"), "先否定后肯定「不是…而是…」"),
    (re.compile(r"没有[^。；！？]{0,40}只有"), "先否定后肯定「没有…只有…」"),
    (re.compile(r"不像[^。；！？]{0,40}更像"), "先否定后肯定「不像…更像…」"),
]

REFERENCE_FIELDS = ["标题", "期刊", "DOI", "分区", "影响因子", "主要作者"]
FINDING_ALIASES = ["文章摘要", "摘要"]
SNAPSHOT_REMOVED = ["研究背景", "数据来源", "研究方法"]
INNOVATION_ALIASES = ["创新点与不足", "创新点"]
CHAPTER_KEYS = ["这篇文章要解决什么问题", "研究设计与方法论", "结果解读",
                "与以往研究的不同", "不足与局限"]


def strip_markup(line):
    line = re.sub(r"^#+\s*", "", line)
    line = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", line)
    line = re.sub(r"\*\*", "", line)
    return line


def check_text_lines(lines):
    hard, soft = [], []
    body_links = []
    for no, raw in enumerate(lines, 1):
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        if BULLET_RE.match(line):
            hard.append(f"第 {no} 行 列表语法: {line.strip()[:40]}")
        elif ORDERED_RE.match(line):
            soft.append(f"第 {no} 行 有序列表前缀（建议改成 一、或（1））: {line.strip()[:30]}")
        if TABLE_RE.match(line):
            hard.append(f"第 {no} 行 Markdown 表格: {line.strip()[:40]}")
        is_reference = bool(REFERENCE_LINE.match(line))
        if not is_reference and DASH_RE.search(line):
            hard.append(f"第 {no} 行 破折号（——）: {line.strip()[:40]}")
        if not is_reference:
            for pattern, label in NEGATIVE_PATTERNS:
                if pattern.search(line):
                    hard.append(f"第 {no} 行 {label}: {line.strip()[:40]}")
        for match in LINK_RE.finditer(line):
            if line.strip().startswith("!") and match.start() == 0:
                continue
            if "![" in line[:match.start() + 1]:
                continue
            body_links.append(f"第 {no} 行 超链接: {match.group(0)[:50]}")
        for ch in line:
            code = ord(ch)
            for low, high, label in BAD_CHAR_RANGES:
                if low <= code <= high:
                    soft.append(f"第 {no} 行 {label}: {ch!r} ({line.strip()[:30]})")
                    break
    return hard + body_links, soft


def check_captions(doc):
    """图注紧跟图片、14px(10.5pt)、居中，且图注之后要有空行。"""
    issues = []
    paragraphs = doc.paragraphs
    for index, para in enumerate(paragraphs):
        has_image = (para._p.findall(f".//{{{WP_NS}}}inline")
                     or para._p.findall(f".//{{{WP_NS}}}anchor"))
        if not has_image:
            continue
        if index + 1 >= len(paragraphs):
            issues.append(f"图片之后没有图注（第 {index + 1} 段）")
            continue
        caption = paragraphs[index + 1]
        text = caption.text.strip()
        if not text:
            issues.append(f"图片之后没有图注（第 {index + 2} 段）")
            continue
        sizes = [run.font.size.pt for run in caption.runs if run.font.size]
        if not sizes or any(abs(size - CAPTION_PT) > 0.01 for size in sizes):
            issues.append(f"图注字号应为 10.5pt（14px）: {text[:24]}")
        if caption.alignment != WD_ALIGN_PARAGRAPH.CENTER:
            issues.append(f"图注未居中: {text[:24]}")
        after = index + 2
        if after < len(paragraphs) and paragraphs[after].text.strip().startswith("（声明："):
            after += 1
        if after >= len(paragraphs) or paragraphs[after].text.strip():
            issues.append(f"图注之后缺空行: {text[:24]}")
    return issues


def check_first_chapter(doc, start_heading="一、这篇文章要解决什么问题",
                        end_heading="二、研究设计与方法论"):
    """第一章只写 1-2 段，不铺开成背景综述。"""
    paragraphs = doc.paragraphs
    start = end = None
    for index, para in enumerate(paragraphs):
        text = para.text.strip()
        is_heading = para.style.name.startswith("Heading")
        if start is None and text == start_heading and is_heading:
            start = index
        elif start is not None and text == end_heading and is_heading:
            end = index
            break
    if start is None or end is None:
        return []  # 章节缺失由章节检查单独报告
    body = [para for para in paragraphs[start + 1:end] if para.text.strip()]
    if not 1 <= len(body) <= 2:
        return [f"第一章有 {len(body)} 段，应控制在 1-2 段"]
    return []


def series_default(path, explicit):
    if explicit:
        return explicit
    name = str(path)
    if "学生信" in name:
        return "学生信"
    if "文献精读" in name or "读文献" in name:
        return "文献精读"
    return None


def report(title, items, level="问题", ok_msg=None):
    if items:
        print(f"  [{level}] {title}: {len(items)} 条")
        for item in items[:15]:
            print(f"        {item}")
    else:
        print(f"  [OK] {ok_msg or title}")


def check_markdown(path, series):
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    hard, soft = check_text_lines(lines)

    images = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text)
    fig_files = sorted(p.name for p in path.parent.glob("*.png"))

    print(f"\n== {path.name}（{series or '未指定系列'}）==")
    print(f"  非空行 {sum(1 for l in lines if l.strip())}，图片引用 {len(images)}，目录内 PNG {len(fig_files)}")
    report("列表 / 表格 / 超链接", hard)
    report("特殊符号", soft, level="提示")

    missing = [img for img in images if not (path.parent / img.split()[0]).exists()]
    report("图片引用指向的文件缺失", missing, ok_msg="图片引用指向的文件都在")
    if len(images) < 6 and series != "文献精读":
        print(f"  [问题] 配图不足 6 张：当前 {len(images)}")
    if "声明：" not in text:
        hard.append("缺少图片声明行")
        print("  [问题] 缺少图片声明行")
    else:
        print("  [OK] 图片声明行在位")

    refs = [l for l in lines if re.match(r"^\[\d+\]", l.strip())]
    print(f"  参考文献 {len(refs)} 条")

    if series == "学生信":
        qa = len(re.findall(r"^\[问题\]", text, flags=re.M))
        status = "OK" if qa >= 10 else "问题"
        print(f"  [{status}] Q&A {qa} 条（要求 >= 10）")
        if qa < 10:
            hard.append("Q&A 少于 10 条")
        for key in ("常见问题", "参考文献"):
            if key not in text:
                hard.append(f"缺少必要章节：{key}")
    return hard


def check_docx(path, series):
    from docx import Document

    doc = Document(str(path))
    body = doc.element.body
    images = body.findall(f".//{{{WP_NS}}}inline") + body.findall(f".//{{{WP_NS}}}anchor")
    # 附录代码是等宽段落，里面出现破折号、列表前缀之类不算违规，检查时跳过。
    lines = [p.text for p in doc.paragraphs if not p.style.name.startswith("Code")]
    text = "\n".join(lines)
    hard, soft = check_text_lines(lines)

    fig_files = sorted(p.name for p in path.parent.glob("*.png"))
    print(f"\n== {path.name}（{series or '未指定系列'}）==")
    print(f"  段落 {len(doc.paragraphs)}，内嵌图片 {len(images)}，目录内 PNG {len(fig_files)}")
    report("列表 / 表格 / 超链接", hard)
    report("特殊符号", soft, level="提示")

    caption_issues = check_captions(doc)
    report("图注（14px/10.5pt、居中、图注后空行）", caption_issues)
    hard.extend(caption_issues)

    reference_issues = []
    for para in doc.paragraphs:
        ref_text = para.text.strip()
        if not REFERENCE_LINE.match(ref_text):
            continue
        sizes = [run.font.size.pt for run in para.runs if run.font.size]
        if not sizes or any(abs(size - REFERENCE_PT) > 0.01 for size in sizes):
            reference_issues.append(f"参考文献字号应为 9pt（12px）: {ref_text[:28]}")
    report("参考文献字号（9pt / 网页 12px）", reference_issues, ok_msg="参考文献字号 9pt")
    hard.extend(reference_issues)

    if "声明：" not in text:
        hard.append("缺少图片来源声明")
        print("  [问题] 缺少图片来源声明")
    else:
        print("  [OK] 图片来源声明在位")
    if fig_files and len(images) < len(fig_files):
        note = f"内嵌图片 {len(images)} 少于目录内 PNG {len(fig_files)}（可能有无用图未清理）"
        print(f"  [提示] {note}")

    if series == "文献精读":
        snapshot = []
        in_snapshot = False
        for line in lines:
            stripped = line.strip()
            if stripped == "论文快照":
                in_snapshot = True
                continue
            if in_snapshot and stripped.startswith("小目录"):
                break
            if in_snapshot and stripped:
                snapshot.append(stripped)

        missing = [f for f in REFERENCE_FIELDS
                   if not any(line.startswith(f"{f}：") for line in snapshot)]
        report("论文快照字段缺失", missing, ok_msg="8 个必备字段齐全")
        removed = [f for f in SNAPSHOT_REMOVED
                   if any(line.startswith(f"{f}：") for line in snapshot)]
        report("快照里已取消的字段", removed,
               ok_msg="快照已去掉研究背景、数据来源与研究方法")
        hard.extend(removed)
        bracketed = [f"{field} 带了括号注释" for field in ("分区", "影响因子")
                     if any(line.startswith(f"{field}：") and ("（" in line or "(" in line)
                            for line in snapshot)]
        report("分区与影响因子只给数值", bracketed, ok_msg="分区与影响因子只给数值")
        hard.extend(bracketed)
        if not any(any(line.startswith(f"{a}：") for line in snapshot)
                   for a in FINDING_ALIASES):
            hard.append("缺少「文章摘要」字段")
            print("  [问题] 快照缺少「文章摘要」（原文 Abstract 的中文直译）")
        if not any(any(line.startswith(f"{a}：") for line in snapshot)
                   for a in INNOVATION_ALIASES):
            hard.append("缺少「创新点与不足」字段")
            print("  [问题] 快照缺少「创新点与不足」")
        chapter_one = check_first_chapter(doc)
        report("第一章篇幅（1-2 段）", chapter_one, ok_msg="第一章 1-2 段")
        hard.extend(chapter_one)
        missing_chapters = [c for c in CHAPTER_KEYS if c not in text]
        report("章节缺失", missing_chapters, ok_msg="五个章节齐全")
        if "老马说说" in text:
            hard.append("出现已废弃的「老马说说」章节")
            print("  [问题] 出现已废弃的「老马说说」章节")

    if series == "学生信":
        qa = sum(1 for line in lines if line.strip().startswith("[问题]"))
        status = "OK" if qa >= 10 else "问题"
        print(f"  [{status}] Q&A {qa} 条（要求 >= 10）")
        if qa < 10:
            hard.append("Q&A 少于 10 条")
        missing_sections = [key for key in ("常见问题", "参考文献") if key not in text]
        report("必要章节缺失", missing_sections, ok_msg="常见问题与参考文献章节齐全")
        hard.extend(missing_sections)
        if len(images) < 6:
            hard.append(f"配图不足 6 张：当前 {len(images)}")
            print(f"  [问题] 配图不足 6 张：当前 {len(images)}")
        else:
            print(f"  [OK] 配图 {len(images)} 张（要求 >= 6）")
    return hard


def main(argv=None):
    ap = argparse.ArgumentParser(description="公众号文章交付前自检")
    ap.add_argument("path", help="文章文件或期数目录")
    ap.add_argument("--series", choices=["学生信", "文献精读"], help="不填则按路径推断")
    args = ap.parse_args(argv)

    target = Path(args.path).expanduser()
    if target.is_dir():
        candidates = sorted(list(target.glob("*.md")) + list(target.glob("*.docx")))
        if not candidates:
            raise SystemExit(f"{target} 里没有 md/docx")
        target = candidates[0]
    series = series_default(target, args.series)

    hard = check_markdown(target, series) if target.suffix == ".md" else check_docx(target, series)
    print()
    if hard:
        print(f"结论：发现 {len(hard)} 个必须修的问题")
        return 1
    print("结论：确定性检查全部通过（方法论深度、论证质量需人工再过一遍）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
