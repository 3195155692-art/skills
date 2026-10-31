# 检索语法与常用检索式

同一个 `--query` 会分发给所有数据源。PubMed 语法最完整，引擎在需要时会把年份范围
改写成各源自己的语法；其余源按各自支持的写法解析。

## PubMed 字段标签（可直接写在 --query 里）

| 标签 | 含义 | 示例 |
|------|------|------|
| `[tiab]` | 题名与摘要 | `covert consciousness[tiab]` |
| `[ti]` | 仅题名 | `brain-computer interface[ti]` |
| `[MeSH]` / `[mh]` | 主题词 | `Consciousness Disorders[mh]` |
| `[au]` | 作者 | `Schiff ND[au]` |
| `[ta]` | 期刊缩写 | `Neurology[ta]` |
| `[pt]` | 出版类型 | `review[pt]`、`clinical trial[pt]` |
| `[dp]` | 出版日期 | `2020:2026[dp]` |
| `[tw]` | 全文任意位置 | `neuroprosthesis[tw]` |

布尔运算：`AND` / `OR` / `NOT`，圆括号分组。字段标签只对 PubMed 生效，
其他源会把它当成普通词处理，因此复杂语法建议配合 `--source pubmed` 单源使用。

## 典型检索式

```text
# 主题 + 时间段 + 只看综述
(covert consciousness[tiab] OR cognitive motor dissociation[tiab])
  AND (2020:2026[dp]) AND (review[pt])

# 某一篇论文的后续引用工作（作者 + 主题 + 年份）
(Schiff ND[au]) AND (consciousness[tiab]) AND (2022:2026[dp])

# 方法 + 应用场景
("neural decoding"[tiab]) AND ("speech"[tiab]) AND (2022:2026[dp])
```

## Europe PMC 字段（需要精确控制时使用）

```text
TITLE_ABS:"covert consciousness"
AUTH:"Schiff"  AND  PUB_YEAR:[2020 TO 2026]
SRC:PPR                 # 只要预印本（MED=PubMed 记录）
OPEN_ACCESS:Y           # 只要开放获取
DOI:"10.1212/WNL.0000000000210208"
```

引擎在 `--sort cited` 或 `--strict` 时，会把纯关键词查询自动包成 `TITLE_ABS:"..."`。
若查询里已经含引号、冒号或括号，引擎保持原样，不做改写。

## OpenAlex

默认使用全文匹配；`--strict` 或 `--sort cited` 时切换到题名/摘要匹配。
年份由引擎翻译成 `from_publication_date` / `to_publication_date` 过滤器。

## 提高检索质量的经验规则

1. **先宽后窄**：先用 3–5 个关键词跑默认五源，看清领域用词，再用 PubMed 字段标签精修。
2. **同义词要显式写出**：不同社区用词差异大（covert consciousness / cognitive motor dissociation /
   command following），检索式里用 `OR` 连起来，否则会漏。
3. **不要一上来就 `--strict`**：先用默认召回，发现跑题再收窄。
4. **按被引排序配合 `--strict`**：该模式下引擎会自动收窄，如果查询本身含复杂语法则不会自动改写，
   此时结果可能跑题，需要手动加 `--strict` 或换用更具体的词。
5. **中文主题用英文检索**：五大源对中文题名覆盖很差；中文文献直接走 CNKI 路线。
6. **记录检索式**：归档目录的 `00_README_*.md` 会写下检索式与设定，便于日后复现或更新。

## 严格模式下的本地相关性闸门

`--strict` 与 `--sort cited` 除了改写各源的查询范围，还会启用一道**本地闸门**：
检索词里的实义词（去掉 of / the / study 这类停用词）至少有 60% 要出现在该条的
题名或摘要里，否则丢弃。原因是各库匹配策略不同——Crossref 是 OR 式部分匹配、
arXiv 的 `all:` 会命中全文、OpenAlex 默认匹配全文——不设闸门时
「按被引排序」会把仅在全文里擦边提到关键词的经典高被引论文顶到最前面。

闸门对没有题名/摘要可比对的记录不做判断（避免误杀）。过滤条数会在命令结束时提示。
