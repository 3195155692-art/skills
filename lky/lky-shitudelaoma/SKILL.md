---
name: lky-shitudelaoma
description: 撰写「跟着老马学生信」与「老马文献精读」两个公众号系列文章，两系列都输出 Word（.docx）：学生信按方法/概念主题成文，文献精读按论文 PDF 提取原文图、深挖研究设计与方法论。用户给出生信方法/概念主题，或给出论文 PDF/DOI/标题要求精读成文时使用。
---

# 识途老马公众号写作

两个系列都输出 Word（.docx），先分流再动笔：素材来源与章节骨架不同，版式与生成方式共用一套。

**规范正本**：项目根目录 `/Users/oldma/Desktop/article/公众号` 下的 `CLAUDE.md`。
每次动笔前先读它；本 skill 固化的是可复用的操作细节与原环境踩坑点，两者冲突时以 `CLAUDE.md` 为准。

## 分流

| 用户给的 | 系列 | 成品 | 详细规范 |
|---|---|---|---|
| 生信方法 / 概念 / 工具 / 数据库主题 | 跟着老马学生信 | `跟着老马学生信（N）：主题.docx` | [references/xueshengxin.md](references/xueshengxin.md) |
| 一篇论文的 PDF / DOI / 标题 | 老马文献精读 | `老马文献精读（N）：主题.docx` | [references/wenxian-jingdu.md](references/wenxian-jingdu.md) |
| 其他主题（AI 工具、方法论综述等） | 借学生信的骨架当独立系列 | 输出形式与用户确认 | [references/xueshengxin.md](references/xueshengxin.md) |

## 硬约束（两系列通用）

这些是微信导入时真踩过的坑，逐条照做：

1. 正文不出现 Markdown 超链接；参考文献用纯文本，不加 DOI 链接。
2. 不出现 `- ` / `* ` / `+ ` 列表语法。并列项写成 `· **名称**：说明` 的独立段落；小目录写成 `一、章节名` 普通段落；
   `1. ` 起头的行同样不要用，小标题走二级/三级标题（markdown 里 `### 2.1 标题`，docx 里 `sub` block），
   正文内并列写 `（1）`。
3. 不使用 emoji 与特殊字符（`<=` `>=` `->` `alpha` `beta` 替代 `≤` `≥` `→` `α` `β`），也不使用 `⚠ ✓ ❓ ✅` 一类符号。
4. 不使用 Markdown 表格语法；表格一律用 matplotlib 画成 PNG 再插入。
5. 正文与图注统一黑色。正文按 16px（docx 里 12pt），图注按 **14px（docx 里 10.5pt）、居中，图注之后空一行**；只有标题层级可以不同。
6. 配图里也不允许文字重叠或贴边 —— 出图后必须检查（见 [references/figures.md](references/figures.md)）。

## 环境

- **Python**：`/Users/oldma/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3`
  已含 python-docx、Pillow、numpy、pandas、pypdfium2、pdfplumber。
- **matplotlib 不包含在上面这个解释器里**。绘图统一用专用虚拟环境
  `/Users/oldma/.cache/lky-shitudelaoma/venv/bin/python3`；缺失时按 [references/figures.md](references/figures.md) 的「环境」一节一次性创建。
- **PyMuPDF（fitz）本机没有**，PDF 处理一律用 `scripts/extract_pdf_figures.py`（基于 pypdfium2）。
- **联网命令**一律用 `~/.codex/bin/vpnctl p` 包裹（装包、检索、下载）。
- **版式自检**：用 `scripts/preview_docx.py` 把 docx 转 PDF 再渲染成逐页 PNG。
  不要直接调 soffice —— 本机它的 fontconfig 看不到系统中文字体，裸转换会把中文渲染成空白。

## 流程

0. 读 `CLAUDE.md`，确认本轮适用的撰写标准。
1. **定期数**：看系列文件夹里已有的最大期数，新一期 = 最大 + 1。
2. **素材**：
   - 学生信：先做主题调研，重点搜集常见坑与 FAQ（Q&A 章节要 >= 10 条）。
   - 文献精读：读通论文全文；「与以往研究的不同」一章用 `lky-search` 检索既往研究，不要凭记忆下对比结论。
3. **配图**：
   - 学生信：matplotlib 生成 >= 6 张模拟图，第一张图注下方加「本文图片均为模拟生成」声明。
   - 文献精读：从论文 PDF 提取原文图，不改绘不模拟，第一张图注下方加「图片来源于论文原文」声明。
4. **成文**：
   - 两个系列都先写 JSON 内容文件，再用 `scripts/build_docx.py` 生成 docx（不要手搓 docx 脚本）。
     学生信的 `qa`（常见问题）与 `code`（附录代码）是脚本内置的 block 类型，见
     [references/docx-format.md](references/docx-format.md)。
5. **成稿后润色**：调用 `$lky-polish` 完成两轮修订。先去除 AI 腔并调整中文表达，
   再检查段落逻辑、主张与证据强度、引用位置和不可变数值。润色产物必须包含
   【润色后】【修改说明】【需作者确认】三部分。
6. **归档**到 `系列/第N期 主题/`；顺带更新 `CLAUDE.md` 与 `README.md` 的已发布列表。
7. **自检**：
   - `scripts/check_article.py` 做确定性检查，修到全绿再交付。
   - 两系列都跑 `scripts/preview_docx.py`，逐页看版式（中文字体、图片宽度、章节与图注位置）。
8. **清理**：删掉临时文件；绘图脚本留在期数目录里以便复现。

## 交付前自检

```bash
PY=/Users/oldma/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3
$PY ~/.codex/skills/lky-shitudelaoma/scripts/check_article.py <文章或期数目录> --series 学生信|文献精读
```

脚本会报告：列表/超链接/表格语法/特殊字符/破折号/先否定后肯定结构是否清零、
第一张图下的声明是否在位、
文献精读 8 个必备字段是否齐全、学生信 Q&A 是否 >= 10 且配图 >= 6 张、
docx 是否可打开且内嵌图片数与目录内 PNG 数一致。
脚本只做确定性检查，判不了「方法论讲得够不够深」，那部分靠人读一遍。

## 交付话术

汇总里给出：成品路径、图片清单（编号 + 说明）、正文字数、自检结果表，
以及润色环节的【修改说明】与【需作者确认】。
不要写工具调用流水账，也不要报 token 花费，除非用户问了。
