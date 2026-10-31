# 配图规范（matplotlib）

## 环境

运行时自带的 Python 里有 python-docx、Pillow、numpy、pandas，但**没有 matplotlib**。
绘图用一个能看见系统包的专用虚拟环境：

```bash
RUNTIME=/Users/oldma/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3
VENV=/Users/oldma/.cache/lky-shitudelaoma/venv
~/.codex/bin/vpnctl p "$RUNTIME" -m venv --system-site-packages "$VENV"
~/.codex/bin/vpnctl p "$VENV/bin/python3" -m pip install --quiet matplotlib
"$VENV/bin/python3" -c "import matplotlib, docx; print(matplotlib.__version__)"
```

之后所有绘图脚本都用 `$VENV/bin/python3` 运行。虚拟环境已经存在就不要重复创建或重装。

## 中文字体

本机没有微软雅黑，可用中文字体是 `Hiragino Sans GB` 与 `STHeiti`。
用 `scripts/figures_common.py` 的 `use_chinese_font()` 自动查找注册，
不要在脚本里写死字体路径：

```python
import sys
sys.path.insert(0, "/Users/oldma/.codex/skills/lky-shitudelaoma/scripts")
from figures_common import use_chinese_font, save_figure, check_text_overlap

use_chinese_font()
```

## 出图要求

- 画布 8x5 到 10x6 英寸；标题 >= 16pt，坐标轴标签与主要标注 >= 12pt，最小标注 >= 10pt。
- 300dpi 保存 PNG；插入文章前压到 1200px 宽（`save_figure` 一并处理）。
- 文字不贴边、不重叠。出图后调用 `check_text_overlap(fig)`，有重叠就调版式重画，不要带着重叠交付。
- 图中文字也用黑色；配色只用于数据本身（线、点、填充），不用于文字。
- 坐标轴、图例、单位齐全；模拟数据要在图注里写明。

## 表格图片化

方法对比表、论文快照类表格一律画成 PNG。不要用 `ax.table` 的默认小字号：
手动设列宽行高，单元格文字 11–12pt，表头加粗，长文本自动换行，表格占满画布宽度，
导出后再压到 1200px。

## 常见坑

| 现象 | 原因 | 处理 |
|---|---|---|
| 中文显示成方框 | 字体未注册或名称写错 | 用 `use_chinese_font()`，并用它返回的字体名设置 rcParams |
| 文字重叠 | 版式太挤 | 先加画布、缩短标签、旋转刻度，再考虑减字号 |
| 负号变方框 | `axes.unicode_minus` 未关 | `use_chinese_font()` 已处理 |
| 图中出现 `<=` 之外的符号被吞 | 用了非 ASCII 符号 | 统一用 `<=` `>=` `alpha` |
| 图太糊 | 分辨率不够或事后放大 | 300dpi 直接出图，不要放大已有位图 |
| 图太大导不进公众号 | 未压缩 | `save_figure` 的 `max_width=1200` |
