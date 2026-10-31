---
name: obsidian-reading
description: Build collection-level deep-reading notes for papers inside a local Obsidian vault. Use when the user asks to organize literature into an Obsidian folder of reading notes (精读笔记 / 文献精读合集), extend or upgrade an existing paper collection, produce a 中文精读报告 plus section-by-section 关键句与核心论点 extraction, rename or re-tag notes to vault conventions, or maintain a collection README/MOC. Produces Obsidian-native output with YAML frontmatter, title-based filenames, locally archived PDFs, and a download manifest. Do not use for single-paper generic Paper Cards, full-paper bilingual translation, formal peer review, or retrieval-only downloads.
metadata:
  version: "1.1.0"
---

# Obsidian Reading

Turn a set of papers into a **collection** of deep-reading notes that live in the user's Obsidian vault and follow that vault's conventions.

The deliverable is not a summary. Each note has two layers: a topic-driven Chinese reading report (what the paper means, where it sits, what it does not prove) and a faithful section-by-section extraction of the paper's own key sentences with one line of core argument per section. Every quoted sentence must be traceable to a local PDF or to an explicitly named public source.

Read the paper's own structure; do not reorder its argument into a shape you prefer.

## Vault conventions

These are fixed rules. Apply them to every note in a collection, including notes created earlier with a different convention.

### Frontmatter

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

- **Journal tag**: full English journal name with hyphens instead of spaces and punctuation (`New-England-Journal-of-Medicine`, `Nature-Neuroscience`, `Nature-Reviews-Neuroscience`).
- **Concept tags**: Chinese wording taken from the paper or the field's established translation (`认知运动分离`, `隐蔽意识`, `语义解码`).
- **Abbreviation tags**: give the abbreviation its own tag when the paper uses it as a term (`CMD`, `BCI`, `PDoC`).
- **`年份`**: publication year as a number.
- **`摘要`**: a **translation**, not a summary. Reproduce the whole abstract: one translated sentence for every source sentence, in the source's order, with the source's structure markers when it has them (`背景` / `方法` / `结果` / `结论`). Every number in the abstract appears in the translation. Never compress two sentences into one, drop a sentence, or move a sentence to a different section of the abstract.
- **`aliases`**: optional. Include only when the vault already uses it for that collection.

See [references/frontmatter-and-naming.md](references/frontmatter-and-naming.md) for the tag
vocabulary and the full abstract-translation rules. The translation rule is the one people
get wrong, so it is also checked mechanically — run `scripts/check_abstract.py` before
calling a note finished.

### Filenames

`<序号>_<论文完整标题>.md`, preserving the published capitalization and subtitle.

Sanitize characters Obsidian forbids in note names: replace `:` and `：` with ` - `, and strip `\ / * " < > | ?`. Never shorten the title to an abbreviation just to make the filename shorter.

### Vault hygiene

Never place tooling, caches, extracted text, or scripts inside the vault. If a helper must live near the project, use a dot-prefixed folder (Obsidian ignores those) or a directory outside the vault.

## Workflow

### 1. Locate the vault and the collection

Walk up from the project directory to find `.obsidian`; that directory is the vault root. Confirm the target collection folder with the user if it is ambiguous.

**Read existing notes before writing anything.** The user may have hand-edited them. Never overwrite a user's edits with a regenerated version; extend what is there.

### 2. Fix the paper list, then get full text

Use the `nature-downloader` skill for retrieval. It owns the access logic — open-access routing, publisher APIs, institutional routes, and the Supporting Information question. Ask the SI question once for the whole batch if that skill requires it.

Store PDFs in `<collection>/PDFs/` with the same stem as the note, and record provenance in `<collection>/manifest.json`. Details and required fields: [references/vault-and-archiving.md](references/vault-and-archiving.md).

When full text is unavailable, say so plainly and record the evidence you checked. A note built from an abstract only is acceptable **if** it is labeled as such.

### 3. Extract text and map the paper's structure

Run `scripts/pdf_intake.py` to pull text, hash the file, and write manifest entries. Then identify the paper's own section headings and keep their order, including the abstract.

### 4. Draft the two-layer note

Use [references/note-template.md](references/note-template.md) for the shape, and pick the matching body skeleton from [references/skeletons-by-type.md](references/skeletons-by-type.md) — empirical study, review, or technical/method paper. The second layer follows the paper's sections, not the skeleton.

The extraction rules in [references/extraction-discipline.md](references/extraction-discipline.md) are not optional; they are what makes the note trustworthy.

### 5. Verify the frontmatter abstract against the source

Save the paper's own abstract as plain text (one file per paper, outside the vault, named
after the note's numeric prefix) and run the comparison:

```bash
python3 scripts/check_abstract.py \
  --collection "<collection folder>" --abstract-dir "<folder of abstract texts>"
```

It flags a condensed summary, a dropped or merged sentence, and any number in the source
abstract that is missing from the translation. Fix the note rather than relaxing the check;
an off-by-one sentence count is reported as a warning, a missing number as an error.

### 6. Close the collection

Finish with a collection-level README/MOC that covers: reading order by layer, the field's main line of argument, the most reportable claims, the open question worth pursuing, a suggested talk title, and the full reference list. Then add cross-references inside individual notes so the collection reads as one argument rather than a file dump.

## Evidence rules

These are the rules that keep the notes honest. Full checklist in [references/extraction-discipline.md](references/extraction-discipline.md).

- Key sentences must be **verbatim** from the source, in the source language, with the source file named. Never paraphrase inside quotation marks.
- The frontmatter `摘要` is a **translation, not a summary**: one translated sentence per source sentence, in order, with every number carried across. Verify with `scripts/check_abstract.py`.
- If you only have an abstract, produce an abstract-level extraction and an explicit `待补清单`. Do not fabricate body quotes.
- Keep numbers exactly as published, with their source. Do not round, and do not drop confidence intervals or p-values that qualify a claim.
- Preserve counterexamples and boundary conditions, especially the ones that weaken the headline claim (a low positive rate in the control group, huge between-site spread, a subgroup that did not replicate).
- Separate what the authors claim from what the note infers. Mark inference explicitly.
- Flag internal inconsistencies in the paper rather than silently choosing one number.
- Flag version differences. An accepted manuscript, an in-press proof, and the version of record can differ in wording and pagination; say which one the note is based on.

## Reference routing

Load only what the current task needs.

| Read this | When |
| --- | --- |
| [references/note-template.md](references/note-template.md) | Always, before drafting a note |
| [references/skeletons-by-type.md](references/skeletons-by-type.md) | Choosing the body structure for a paper type |
| [references/frontmatter-and-naming.md](references/frontmatter-and-naming.md) | Writing frontmatter, naming files, translating abstracts, building the tag vocabulary |
| [references/extraction-discipline.md](references/extraction-discipline.md) | Any time you are quoting the paper or judging what it proves |
| [references/vault-and-archiving.md](references/vault-and-archiving.md) | Setting up a collection, archiving PDFs, writing the manifest, upgrading an older collection |

## Scripts

```bash
# Extract text, hash the PDF, and record manifest entries for a collection
python3 scripts/pdf_intake.py --collection "<collection folder>" [--pdf "PDFs/x.pdf"] [--text-dir <dir>]

# Check a collection against the conventions above
python3 scripts/check_notes.py --collection "<collection folder>"

# Check that every `摘要` is a full translation of that paper's abstract
python3 scripts/check_abstract.py --collection "<collection folder>" --abstract-dir "<dir>"
```

`pdf_intake.py` keeps extracted text outside the vault by default and never rewrites an existing manifest entry's source fields without `--force`. `check_notes.py` reports frontmatter gaps, filename violations, and notes missing the extraction layer; fix what it reports rather than suppressing it.

`check_abstract.py` compares the source abstract and the translation sentence by sentence
and statistic by statistic. It cannot judge prose quality — read the translation back
against the source once yourself — but it reliably catches the failures that matter:
a compressed summary, a missing sentence, a mistyped percentage.
