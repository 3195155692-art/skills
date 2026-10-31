# Note template

A note has exactly two layers, separated by a horizontal rule. The first layer is written by you (topic-driven, Chinese). The second layer is extracted from the paper (section-driven, source language).

```markdown
---
tags:
  - <领域标签，中文>
  - <期刊标签，英文全称连字符>
  - <概念标签，中文>
  - <缩写>
年份: <四位数字>
摘要: <该论文 abstract 的完整中文翻译——逐句对应，不压缩、不合并、不调换小节>
---
# 精读报告 <序号>：<论文完整标题>

## 1. 文献信息
...

## 2. 一句话结论
...

...   （see skeletons-by-type.md for the middle sections）

## N. 参考来源

<作者>. *<期刊>.* <年>;<卷期>:<页码>. DOI: <doi>.

---

# 附：关键句与核心论点（逐节原文提取）

> 提取方式：按论文原有小节顺序，逐节给出**原文关键句**（保留英文原句，便于回查与直接引用）+ **核心论点**（中文一句话）。
> 原文文件：`PDFs/<同名>.pdf`（<版本说明>）。

## A1. <论文小节名>｜<这一节在做什么>

1. "<verbatim sentence from the paper>"
   → <中文说明，一句话，讲这句在说什么、为什么要记它>。
2. "<verbatim sentence>"
   → <中文说明>。

> **核心论点**：<用一句话概括这一节的论点，不复述上面的关键句>。

## A2. ...
```

## Layer 1 conventions

- Numbered `## N. 标题`, one topic per section. Numbering is per-note and starts at 1.
- **Section 2 is always 一句话结论** — one paragraph, and it must state the paper's actual finding, not its topic.
- **The last section is always 参考来源** with the full citation and DOI.
- Keep the paper's own vocabulary in English inside parentheses on first use, e.g. `认知-运动分离（cognitive motor dissociation, CMD）`.
- Use fenced blocks or arrows for pipelines and evidence ladders; they carry meaning that prose loses.
- Cite numbers inline in the same section where the claim is made.

## Layer 2 conventions

- One `## A<n>.` heading per paper section, in the paper's order. Name the heading from the paper's own heading, then add `｜` and a short Chinese gloss of what that section does.
- Number the items inside each section. Each item is a quoted sentence followed on the next line by `→` and a one-sentence Chinese note.
- End each section with `> **核心论点**：...`. One sentence. It should state the *argument*, not repeat the quote.
- Quote only sentences that carry weight: the definition sentence, the headline number, the acknowledged limitation, the sentence that contradicts a common assumption.
- Keep hedging in the quote. If the authors wrote "may", do not quote it as "does".
- When a section contains a table that carries the argument, rebuild the table in the note rather than quoting cells in prose.
- Use `⚠️` callouts for version warnings, internal inconsistencies, and numbers that need checking against the final version.

## Condensed worked example

This is `01_Cognitive Motor Dissociation in Disorders of Consciousness.md` trimmed down to show the shape. It is the reference standard; match this density and texture.

```markdown
---
tags:
  - 脑机接口
  - New-England-Journal-of-Medicine
  - 认知运动分离
  - CMD
年份: 2024
摘要: 背景 对指令无反应的脑损伤患者可能仍能执行某些认知任务，这些任务可通过功能性磁共振成像（fMRI）和脑电图（EEG）检测到。这种现象被称为认知-运动分离，尚未在意识障碍患者的大型队列中得到系统研究。方法 ……（此处逐句续写，直到摘要最后一句；不得压缩、合并或调换小节）…… 结论 对指令无可观察反应的参与者中，约每四人有一人可在 fMRI 或 EEG 上完成认知任务；而对指令有可观察反应的参与者中，这一比例约为每三人有一人。（由 James S. McDonnell 基金会等资助。）
---
# 精读报告 01：Cognitive Motor Dissociation in Disorders of Consciousness

## 1. 文献信息

- **题目**：Cognitive Motor Dissociation in Disorders of Consciousness
- **作者**：Yelena G. Bodien, Judith Allanson, Paolo Cardone, et al.
- **期刊**：*New England Journal of Medicine*
- **年份/卷期/页码**：2024; 391(7): 598–608
- **DOI**：10.1056/NEJMoa2400645
- **研究类型**：多中心观察性研究 / 临床神经科学研究
- **核心关键词**：cognitive motor dissociation, disorders of consciousness, EEG, fMRI, covert consciousness

## 2. 一句话结论

这项多中心研究最重要的发现是：**在临床上对指令没有可观察行为反应的意识障碍患者中，约 25% 仍可通过 EEG 和/或任务态 fMRI 检测到与“理解指令并执行意图”一致的脑活动，即 cognitive motor dissociation（CMD）**。这直接说明“没有动作反应”不能等同于“没有认知/意识”。

## 3. 为什么这篇文章重要

（……传统评估依赖行为；问题在于……）

> **认知能力仍然存在，但输出通道已经损坏。**

CMD 的核心就是：

> **cognition preserved / motor output unavailable**

定义：CRS-R 无命令跟随和可理解言语，即听觉子量表 <3、视觉 <5、口运动/言语 <3、交流 <1，同时至少一个任务态 fMRI 或 EEG 阳性。任务包括运动想象、视觉/听觉辨别等，要求持续数分钟。健康对照中 70%—100% 可出现阳性，说明方法有验证基础。

---

# 附：关键句与核心论点（逐节原文提取）

> 提取方式：按论文原有小节顺序，逐节给出**原文关键句**（保留英文原句，便于回查与直接引用）+ **核心论点**（中文一句话）。
> 原文文件：`PDFs/01_Cognitive Motor Dissociation in Disorders of Consciousness.pdf`（Kent Academic Repository 收录的 **Author Accepted Manuscript**，共 25 页）。
> ⚠️ 版本提示：本地 PDF 为作者定稿（AAM），与 NEJM 正式排版版（391(7):598–608）在措辞与页码上可能略有差异；正式引用页码时请核对出版社终版。

## A1. Abstract / Background｜问题起点

1. "Patients with brain injury who are unresponsive to commands may perform cognitive tasks that are detected on functional magnetic resonance imaging (fMRI) and electroencephalography (EEG)."
   → 对指令无行为反应的患者，仍可能在 fMRI/EEG 上完成认知任务。
2. "This phenomenon, known as cognitive motor dissociation, has not been systematically studied in a large cohort of persons with disorders of consciousness."
   → 现象早已存在，但缺的是**大样本系统证据**——这就是本文要补的空白。

> **核心论点**：CMD 不是新现象，而是长期缺乏大规模、多中心的系统确认。

## A4. Abstract / Conclusions｜作者自述结论

1. "Approximately one in four participants without an observable response to commands performed a cognitive task on fMRI or EEG as compared with one in three participants with an observable response to commands."
   → 一句话结论：1/4 vs 1/3。
2. "(Funded by the James S. McDonnell Foundation and others.)"
   → 非商业资助，由基金会支持。

> **核心论点**：CMD 的检出率已接近“有反应患者”的检出率，提示无反应群体中隐藏着大量有认知能力的人。
```

Note what the example does that a generic summary does not: it keeps the control-group number (1/3) next to the headline number (1/4), because the pair is what makes the claim debatable.
