# Frontmatter, tags, filenames, abstracts

## Frontmatter contract

```yaml
---
tags:
  - <领域标签，中文>
  - <期刊标签，英文全称连字符>
  - <概念标签，中文>
  - <缩写>
年份: <数字>
摘要: <摘要的完整中文翻译>
---
```

Order the tags **领域 → 期刊 → 概念 → 缩写**. The order is what makes Dataview queries and the tag pane readable, so keep it stable even when a note has only three tags.

### 领域标签

Chinese, drawn from a small stable set for the collection. Do not invent a new domain tag per paper; if a paper needs two domains, use two tags.

```text
脑机接口 / 意识研究 / 神经解码 / 神经调控 / 临床神经科学
```

### 期刊标签

Full English journal name, spaces and punctuation replaced by hyphens. Keep the journal's own capitalization. Do not use the ISO abbreviation.

| Journal as published | Tag |
| --- | --- |
| New England Journal of Medicine | `New-England-Journal-of-Medicine` |
| Nature Neuroscience | `Nature-Neuroscience` |
| Nature Reviews Neuroscience | `Nature-Reviews-Neuroscience` |
| Nature | `Nature` |
| Neurology | `Neurology` |
| Journal of Clinical Medicine | `Journal-of-Clinical-Medicine` |
| Communications Medicine | `Communications-Medicine` |

Drop a leading article (`The Lancet Neurology` → `Lancet-Neurology`). If a journal has an ampersand or colon, drop it rather than transliterating it.

### 概念标签

Chinese, using the paper's own key terms as rendered in the field's established Chinese usage. Two to four per note is usually right.

```text
认知运动分离 / 隐蔽意识 / 语义解码 / 语音脑机接口 / 闭环刺激 / 意识障碍
```

### 缩写标签

Give the abbreviation its own tag when the paper uses it as a term rather than as a passing acronym. Prefer the ones a reader would search for.

```text
CMD / BCI / DoC / PDoC / LIS / MCS / UWS
```

Do not tag generic instrumentation (`EEG`, `fMRI`) unless the paper is *about* that modality.

### 年份

Number, unquoted, matching the publication year of the version cited.

### 摘要

A **complete** Chinese translation of the paper's abstract. Not a summary, not a paraphrase,
not the first two sentences. A reader who does not read English must be able to reconstruct
the entire abstract from this field alone.

- Preserve the source abstract's structure markers when it has them: `背景 … 方法 … 结果 … 结论：…`.
- **One translated sentence per source sentence.** Do not merge two short source sentences into one, do not split one into two, and do not move a sentence into a different part of the abstract. If the source has a short standalone sentence such as `Consciousness is private.`, the translation has a short standalone sentence too.
- **Keep every number exactly as published.** Every percentage, sample size, decimal and p-value in the source abstract appears in the translation. This is where summaries fail silently: `65%` becoming `66%`, or `25%` becoming `26%`, changes the paper's claim.
- Keep abbreviations in parentheses at first use: `功能性磁共振成像（fMRI）`.
- If the paper has a "plain language summary" in addition to the abstract, translate the abstract; do not merge the two.
- If only an abstract is available (no full text), say so in the note body, but the frontmatter abstract is still the full translation.
- Translate the abstract belonging to the version cited. When a local copy is an accepted manuscript and its abstract differs from the published one, translate the published abstract and let the note body carry the version warning — do not silently mix the two.

Because the notes we write are themselves examined long after writing, the abstract is worth
one mechanical pass in addition to a careful read. Save the source abstract as plain text and
run:

```bash
python3 scripts/check_abstract.py --note "<note.md>" --abstract "<abstract.txt>"
```

It reports the source and translation sentence counts, and lists any number present in the
source abstract but absent from the translation. Both are symptoms of the same failure: the
field was written from the paper's meaning rather than from its abstract.

### aliases

Optional. Include only when the vault already uses `aliases` for that collection. When present, list Chinese and English short names people would search for.

## Filenames

```text
<序号>_<论文完整标题>.md
```

- Keep the published capitalization and the subtitle.
- **Sanitize for Obsidian.** Obsidian forbids `\ / * " < > | ?` and treats `:` awkwardly. Replace `:` and `：` with ` - `; strip the rest.
- Zero-pad the sequence number to two digits so the folder sorts correctly (`01`, `02`, … `10`).
- Keep the PDF stem identical to the note stem, so `PDFs/<stem>.pdf` always resolves.

Worked examples:

| Paper title | Filename |
| --- | --- |
| Cognitive Motor Dissociation in Disorders of Consciousness | `01_Cognitive Motor Dissociation in Disorders of Consciousness.md` |
| Reconstructing Covert Consciousness: Neural Decoding as a Novel Consciousness Assessment | `02_Reconstructing Covert Consciousness - Neural Decoding as a Novel Consciousness Assessment.md` |
| An instantaneous voice-synthesis neuroprosthesis | `05_An instantaneous voice-synthesis neuroprosthesis.md` |

Record the original title in `## 1. 文献信息` regardless of how the filename was sanitized.

## Renaming an existing collection

When applying the naming rule to notes that already exist:

1. Rename the note **and** the matching PDF together, so the stem rule still holds.
2. Obsidian normally rewrites `[[wikilinks]]` on rename. After renaming a batch, grep the collection (and the vault) for the old stems to catch links Obsidian did not touch.
3. Update the collection README/MOC table in the same pass — a stale filename in the index is worse than the old filename.
4. If the note has been hand-edited, never regenerate it. Rename, add the frontmatter, and leave the prose alone.

## Tag vocabulary hygiene

Keep one vocabulary table per collection — either in the README or in this file's section for that collection — and extend it before adding a new tag. Drift happens when the same journal or concept gets two spellings across notes.

If an older note in the same collection uses a different convention (for example a journal quartile like `Q1` in the tag list, or a misspelled journal tag), normalize it when you are already editing that note. Do not launch a vault-wide rewrite unless the user asks for one.
