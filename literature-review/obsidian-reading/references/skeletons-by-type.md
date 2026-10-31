# Body skeletons by paper type

Layer 1 is topic-driven, and the topics depend on what kind of paper it is. Do not force a technical paper into a clinical skeleton.

## Always present, in this order

1. `## 1. 文献信息` — title, authors (`et al.` after three), journal in italics, year/volume/pages, DOI, type, keywords.
2. `## 2. 一句话结论` — the paper's actual finding in one paragraph, with the headline number.
3. …type-specific middle sections…
4. A closing `## N. 参考来源` with the full citation.

Two sections recur in almost every note and are worth adding whenever the collection is read as a whole:

- **与前后文献的关系** — place the note on the collection's argument chain (what it answers, what it hands off to the next paper).
- **汇报建议 / 一句话总结** — the one sentence a presenter should say, plus where in a talk this paper belongs.

## Empirical or clinical study

Use for cohort studies, trials, and diagnostic studies (e.g. Bodien 2024, du Bois 2026).

```text
1. 文献信息
2. 一句话结论
3. 为什么这篇文章重要          ← the clinical or scientific problem it addresses
4. 研究设计                    ← population, sites, period, blinding, thresholds, analysis
5. 主要结果                    ← headline numbers first, then subgroups and correlates
6. <measurement comparison>    ← e.g. "EEG 与 fMRI 各自解决什么问题"
7. 这是不是证明…？             ← the claim-boundary section; what the design cannot show
8. 与 <your field> 的直接关系   ← translate the clinical result into the reader's problem
9. 文章的主要优势
10. 局限
11. 对研究的启示                ← concrete design implications
12. 汇报时建议强调
N. 参考来源
```

The **claim-boundary section** (7 above) is the one readers copy from. In Bodien 2024 it separates "CMD detected" from "consciousness proven" and draws the evidence ladder. Never skip it, and never let it become a hedge paragraph — give it the ladder or the taxonomy.

## Review or perspective

Use for narrative reviews and position papers (e.g. Fischer 2025, Kronemer 2025, Kordas 2026).

```text
1. 文献信息
2. 核心观点 / 文章定位          ← what the paper argues, not what it surveys
3. 传统方法的问题               ← the target of the critique
4. 文章提出的新框架 / 思路
5. 为什么这对本领域特别重要
6. 潜在优势
7. 与 BCI / 本领域的关系
8. 研究框架 / 技术路线
9. 最大的科学难题
10. 对实验设计的启示
11. 真正的创新点                ← "it did not propose a new classifier, it redefined the question"
12. 与相关文献的关系
13. 局限
14. 汇报结论
N. 参考来源
```

For reviews, the extraction layer matters more than usual: the value is knowing exactly which sentences the authors commit to. Quote the position sentences, and quote the sentences where they admit a limit (e.g. "there is unlikely to be any specific fidelity threshold…").

If the review is gated and only the abstract is available, do not write the full skeleton. Write 文献信息 + 核心观点 from the abstract, an abstract-level extraction, and a `待补清单` naming the sections to fill later.

## Technical, method, or neuroprosthesis paper

Use for decoder papers, systems papers, and demonstrations (e.g. Tang 2023, Wairagkar 2025, Littlejohn 2025).

```text
1. 文献信息
2. 核心问题                    ← the specific engineering or scientific obstacle
3. 受试者与信号 / 数据集        ← N, implant or recording, coverage, sampling
4. 技术路线                    ← as a pipeline diagram, not prose
5. 为什么这个方向重要
6. 关键技术价值                ← what becomes possible that was not before
7. 与 <closest comparable work> 的区别   ← explicit comparison table
8. 与 consciousness / 本领域的关系
9. 一个重要的科研问题           ← the boundary the paper does not cross
10. 局限
11. 汇报时建议用一句话总结
N. 参考来源
```

Two rules for this type:

- Give the **pipeline as a fenced text diagram**, and name the data structure at each stage.
- Always include the **explicit comparison table** against the closest paper in the collection. Technical papers are read in pairs; the comparison is the contribution.

## Choosing when a paper spans types

Pick the skeleton that matches the paper's *contribution*, not its venue. A clinical journal can publish a review (use the review skeleton); a technical paper can carry a large patient cohort (still use the technical skeleton, but expand 受试者与信号).
