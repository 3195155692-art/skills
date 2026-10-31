#!/usr/bin/env python3
"""matplotlib 中文出图公共模块：字体注册、保存压缩、文字重叠自检。

用法:
    import sys; sys.path.insert(0, "<skill>/scripts")
    from figures_common import use_chinese_font, save_figure, check_text_overlap
    use_chinese_font()
"""
from __future__ import annotations

from pathlib import Path

CJK_CANDIDATES = [
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
]


def find_cjk_font():
    for path in CJK_CANDIDATES:
        if Path(path).exists():
            return path
    return None


def use_chinese_font():
    """注册并启用可用中文字体，返回字体名。找不到就保持默认并给出警告。"""
    import logging

    import matplotlib
    from matplotlib import font_manager, rcParams

    matplotlib.use("Agg")
    # Hiragino 的 .ttc 只有 W3/W6 两个权重，matplotlib 会刷 "font weight normal" 噪音，
    # 不影响渲染，这里静音。
    logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
    path = find_cjk_font()
    if path:
        font_manager.fontManager.addfont(path)
        name = font_manager.FontProperties(fname=path).get_name()
    else:
        name = "DejaVu Sans"
        print("[warn] 未找到可用中文字体，图中中文可能显示为方框")

    rcParams["font.sans-serif"] = [name, "Hiragino Sans GB", "Heiti TC", "Heiti SC",
                                   "Songti SC", "STSong", "DejaVu Sans"]
    rcParams["font.family"] = "sans-serif"
    rcParams["axes.unicode_minus"] = False
    rcParams["mathtext.fontset"] = "stixsans"
    rcParams["savefig.dpi"] = 300
    rcParams["figure.dpi"] = 150
    return name


def save_figure(fig, path, dpi=300, max_width=1200):
    """300dpi 存 PNG，并按需缩到 max_width 像素宽。返回最终文件大小（KB）。"""
    from PIL import Image

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=dpi, bbox_inches="tight", facecolor="white")

    img = Image.open(path)
    if max_width and img.width > max_width:
        height = round(img.height * max_width / img.width)
        img = img.resize((max_width, height), Image.LANCZOS)
        img.save(path, "PNG", optimize=True)
    return path.stat().st_size / 1024


def check_text_overlap(fig, tolerance=1.0, verbose=True):
    """返回相互重叠的文字包围盒配对列表；空列表表示干净。"""
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()

    boxes = []
    for ax in fig.axes:
        items = list(ax.texts) + ax.get_xticklabels() + ax.get_yticklabels()
        if ax.get_title():
            items.append(ax.title)
        if ax.get_xlabel():
            items.append(ax.xaxis.label)
        if ax.get_ylabel():
            items.append(ax.yaxis.label)
        legend = ax.get_legend()
        if legend is not None:
            items += legend.get_texts()
        for item in items:
            try:
                text = item.get_text()
            except AttributeError:
                continue
            if not text or not text.strip():
                continue
            box = item.get_window_extent(renderer=renderer)
            boxes.append((text.strip()[:24], box))

    overlaps = []
    for i in range(len(boxes)):
        label_a, box_a = boxes[i]
        for j in range(i + 1, len(boxes)):
            label_b, box_b = boxes[j]
            if box_a.overlaps(box_b):
                inter = box_a.intersection(box_a, box_b)
                if inter is None:
                    continue
                area = inter.width * inter.height
                if area > tolerance:
                    overlaps.append((label_a, label_b, round(area, 1)))

    if verbose:
        if overlaps:
            print(f"[warn] 发现 {len(overlaps)} 处文字重叠：")
            for a, b, area in overlaps[:10]:
                print(f"       '{a}' <-> '{b}' (重叠面积 {area})")
        else:
            print("[ok] 文字无重叠")
    return overlaps
