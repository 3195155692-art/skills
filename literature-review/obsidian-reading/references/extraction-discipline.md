# Extraction and honesty discipline

This file is the reason the notes are worth more than a summary. The extraction layer is a small, auditable dataset: someone should be able to check any line against the PDF in under a minute.

## What is worth extracting

A sentence earns a place in the extraction layer if it does at least one of these:

- **defines** the phenomenon or the operational criterion;
- **carries the headline number**, or the number that qualifies it;
- **states the mechanism** the authors invoke;
- **admits a limit** — sensitivity, generalization, cohort, cost, ethics;
- **contradicts an assumption** a reader would otherwise hold;
- **hands off** to the next paper (an explicit call for future work).

Sentences that merely restate background, or that describe a figure, do not qualify. Three to five per section is usually right; more than eight means you are transcribing.

## Quoting rules

- **Verbatim only.** Copy the sentence exactly, including hedges. If the authors wrote "may not generalize", the quote keeps "may".
- Fix only whitespace and hyphenation artifacts introduced by PDF extraction (a line break inside a word, `re ﬂect` → `reflect`). Never "fix" the authors' grammar or word choice silently; if the source is genuinely awkward, quote it as it is.
- One sentence per item, or one short contiguous span. Do not stitch together distant sentences inside one pair of quotation marks.
- Never put a paraphrase inside quotation marks. If you want to compress, use the `→` line for that.
- Record the local file the quotes come from, in the layer-2 header: `原文文件：PDFs/<stem>.pdf`（<版本>，<页数>）.

## The arrow annotation

One sentence, in Chinese, on the line after the quote, introduced by `→`. It says what the quote is doing and why it was kept — not a translation of it.

Good: `→ **对照组也只有 38% 阳性**——这一点常被忽略，它说明范式本身假阴性率很高。`

Weak: `→ 这说明有 38% 的人有反应。` (that is a translation, not an annotation)

Use bold sparingly, for the two or three words that carry the weight. Keep the annotation's epistemic strength at or below the quote's: a quote with "suggests" gets an annotation with 提示/可能, not 证明.

## The core-argument line

One sentence per section, formatted `> **核心论点**：…`, stating the argument that section makes. It must not restate any quoted sentence — if it does, the section has no synthesis and you should reread it.

This is the line a reader skims. Write it as a claim with a direction:

`> **核心论点**：CRS-R、fMRI、EEG 在测量同一个人时几乎不收敛——它们不是同一把尺子的三种刻度，而是三条互补通道。`

## Numbers

- Copy numbers exactly: `kappa 0.09–0.15`, not "约 0.1"; `p = 0.007`, not "显著".
- Keep the qualifying statistic with the number: confidence intervals, interquartile ranges, group sizes.
- Keep the **comparison** number, not just the headline. `25%` is the finding; `38% in the control group` is what makes it interpretable.
- Keep the **spread** when a paper reports one: a between-site range of `2%–45%` is more informative than any single site's value.
- If two numbers in the paper disagree, record both and flag them, for example: `⚠️ **数字不一致提示（需在终版核对）**：融合模型的平衡准确率在本文中出现三个数值……`

The same rule governs the frontmatter `摘要`, and it is the field most likely to drift,
because it is written once and read by nobody until months later. Two rules keep it honest:

- **one translated sentence per source sentence**, in the source's order and under the source's structure markers;
- **every number in the abstract appears in the translation**, including the ones that weaken the headline claim.

A condensed abstract is not a smaller version of the truth; it is a different document. If
the source abstract says `Data from fMRI only or EEG only were available for 65% of the
participants`, the translation carries `65%` — not `66%`, and not a sentence about modality
coverage placed under `方法` because that is where it feels like it belongs.

Run the mechanical check before finishing a collection:

```bash
python3 scripts/check_abstract.py --collection <collection> --abstract-dir <abstract texts>
```

It compares sentence counts and statistic coverage between each paper's abstract and the
note's `摘要`. It cannot judge the Chinese; read the translation back against the source once
yourself.

## Boundary conditions and counterevidence

The sections most often lost are the ones that weaken the paper. Keep them, and keep them adjacent to the claim they qualify:

- the control or benchmark group's weaker performance;
- the subgroup that did **not** replicate;
- the participants excluded, and why that creates survivorship bias;
- the confound the authors could not rule out;
- the population the result does not cover.

An extraction section that only contains positive findings is a red flag; go back to the Discussion and Limitations.

## Authors versus the note

- Attribute claims: `作者自述结论`, `作者明确指出`, `作者承认`.
- Mark your own inference: `本笔记推论`, `值得注意的推论是`.
- Never write `该研究证明了意识` when the paper says it detected command-following. Keep the paper's own verb.

### Domain guardrail for consciousness work

Keep these three apart in every note, in the prose and in the extraction:

```text
神经信息可解码      → brain activity carries decodable information
隐蔽认知 / CMD      → covert task performance without behaviour
主观意识本身        → subjective experience, not directly observable
```

An evidence ladder is a useful device for this, and it belongs in layer 1:

```text
无行为反应 → 脑活动存在 → 任务相关脑活动 → 能够隐蔽执行指令 → CMD
          → 能够解码具体认知内容 → 潜在 conscious content
```

State which rung the paper actually occupies.

## Tables and figures that carry the argument

When a table is the argument (a modality comparison, a limitations-to-solutions map, a condition matrix), rebuild it as a Markdown table in the note. Quote the cell wording rather than paraphrasing, and title it so a reader knows what it maps.

Do not transcribe tables that are just data dumps; cite the figure number instead.

## Version provenance

Always record which version the extraction is based on, in the layer-2 header, and warn when it matters:

- **Version of record** — safe to cite by page number.
- **Author accepted manuscript (AAM)** — wording and pagination may differ from the published version.
- **In-press / unedited proof** — expect copy-editing changes; line numbers may be interleaved in the extracted text.
- **Preprint** — mark it as such, and never let it stand in for the published version without saying so.

## When only the abstract is available

Do not write a full skeleton and do not invent body quotes. Instead:

1. State the access situation plainly at the top of the extraction layer, with the evidence you checked, for example: `⚠️ **当前状态：全文未获取**。…经 Unpaywall / OpenAlex / Europe PMC / 预印本检索确认**无合法开放版本**…`
2. Extract the abstract sentence by sentence, each with an arrow annotation and a core-argument line.
3. Add a `待补清单` — a checkbox list of the sections to extract once full text arrives.
4. Keep the layer-1 report short, and mark it as abstract-based.

This keeps the note honest and makes the later upgrade a fill-in job rather than a rewrite.

## Checklist before you call a note done

- [ ] Every quoted sentence exists verbatim in the named local file or named source.
- [ ] Every section in the extraction layer matches a real section of the paper, in order.
- [ ] Every section ends with a core-argument line that does not repeat a quote.
- [ ] Headline numbers appear with their comparison numbers.
- [ ] At least one limitation or counterexample per paper is preserved.
- [ ] The version is stated, and any version risk is flagged.
- [ ] Author claims and note inferences are distinguishable on a skim.
- [ ] No claim about consciousness exceeds the paper's own verb.
