---
name: lky-search
description: >-
  Search and retrieve articles from public scholarly databases — PubMed, Europe PMC,
  Google Scholar, OpenAlex, Crossref, arXiv, Semantic Scholar — then deduplicate,
  rank, export (RIS/BibTeX/CSV), and archive results into the local knowledge base by
  topic. Use when the user asks to 检索文献、找文章、查论文、搜 PubMed、谷歌学术、
  学术搜索、批量下载文献、查某主题的最新研究、导出参考文献、生成引文、
  search papers, find literature, PubMed search, Google Scholar search, or
  build a literature list for a research topic.
metadata:
  compatibility: Python 3.9+ standard library only. No installation required.
---

# LKY Search

面向公共学术数据库的检索与抓取技能。引擎是一个零依赖的 Python 脚本，
配置一次（API 密钥、联系邮箱、归档目录），之后每次用一条命令完成检索、去重、导出与归档。

## 职责边界

本技能负责**发现与整理**：检索、元数据、摘要、去重、排序、引文、导出、按主题归档。

本技能**不负责**付费与机构全文下载。以下情况一律交给已安装的 `nature-downloader` skill：

- 中文文献（CNKI / 万方）
- 需要机构订阅的英文文献（Elsevier、Springer Nature、IEEE、Wiley 等）
- 补充材料（Supporting Information）

`lky_search.py oa` 只判定开放获取（OA）是否可得，并给出建议路线，不下载 PDF。

## 引擎位置

```
/Users/oldma/.codex/skills/lky-search/
├── scripts/lky_search.py      # 引擎（唯一入口）
├── config/credentials.env     # API 密钥与归档目录（权限 600）
└── references/                # 按需加载的深度说明
```

命令统一形如：

```bash
python3 /Users/oldma/.codex/skills/lky-search/scripts/lky_search.py <子命令> [参数]
```

## 标准流程

### 第 1 步：自检（每个会话只做一次）

```bash
python3 .../lky_search.py doctor
```

确认 NCBI 密钥有效、各源可达。若某个源不可用（例如 Google Scholar 被限流），
用其余源继续，不要把失败当成整体失败。

### 第 2 步：判断用户要哪类任务

| 用户意图 | 子命令 |
|----------|--------|
| 找某主题的文献、要清单 | `search` |
| 要某一篇的详细信息 | `fetch` |
| 判断某篇能不能免费拿到全文 | `oa` |
| 查期刊分区与影响因子 | `metrics` |
| 下载全文并按分区/影响因子命名 | `download` |
| 给已经下载好的 PDF 改名 | `rename` |
| 生成参考文献条目 | `cite` |
| 找和某篇相似的文章 | `related` |
| DOI / PMID / PMCID 互相转换 | `ids` |

### 第 3 步：检索

```bash
# 基础检索（默认跨 PubMed、Europe PMC、OpenAlex、Crossref、arXiv）
python3 .../lky_search.py search --query "covert consciousness neural decoding" --limit 20

# 限定年份 + 按被引排序（自动收窄到题名/摘要，避免擦边高被引论文混入）
python3 .../lky_search.py search --query "brain computer interface speech" --year-from 2023 --sort cited

# 归档到知识库：--topic 是检索方向，决定落在哪个主题文件夹
python3 .../lky_search.py search --query "brain computer interface consciousness" \
  --topic "Brain-Computer Interface" --year-from 2023 --limit 30 --save

# 需要搜中文库或更广覆盖面时，追加 Google Scholar（低频使用，见限制）
python3 .../lky_search.py search --query "..." --source "pubmed,europepmc,openalex,scholar"
```

检索词写法：PubMed 语法直接可用，例如
`(CRISPR[Title/Abstract]) AND (2020:2026[dp]) AND (review[pt])`。
细节见 [references/search-syntax.md](references/search-syntax.md)。

### 第 4 步：归档

`--save` 会按「检索方向」建主题文件夹，并在其中建立带日期的批次目录：

```
/Users/oldma/knowledge/
└── <主题>/
    └── 2026-09-21_<检索词缩写>/
        ├── 00_README_<主题>_检索结果.md   # 检索设定 + 结果表 + 取全文指引
        ├── results.csv / .ris / .bib / .json
        ├── manifest.json                  # 本批次台账（来源、OA 状态、下载状态）
        └── PDFs/                          # 留给后续下载的全文
```

同名主题会被复用，不会产生「BCI」与「Brain-Computer Interface」两个目录。
若要直接写进 Obsidian 库，加 `--root /Users/oldma/knowledge/artical`。
细节见 [references/output-layout.md](references/output-layout.md)。

### 第 5 步：取全文

下载目录**由用户指定**，文件名按分区与影响因子自动生成（见下一节）：

```bash
# 单篇或几篇：直接给标识符
python3 .../lky_search.py download --ids "10.1038/s41467-026-75065-x,PMID:40164740" \
  --out "/Users/oldma/Downloads/文献"

# 整批：直接吃检索批次的 manifest.json，下载到该批次的 PDFs/
python3 .../lky_search.py download --from-manifest "<归档目录>/manifest.json" \
  --out "<归档目录>/PDFs"

# 只想先看会生成什么文件名，不下载
python3 .../lky_search.py download --ids "<DOI>" --out "<目录>" --dry-run
```

运行结束时会在目标目录写 `_lky-downloads.json`，把结果分成四类：

| 结果 | 含义 | 下一步 |
|------|------|--------|
| 已下载 | 拿到开放获取 PDF | 完成 |
| 需机构订阅 | 确认没有开放获取版本 | 交给 `nature-downloader` 走机构授权 |
| 开放获取但被拦截 | 有免费版本，但出版社挡脚本（IOP、IEEE、PMC、Annual Reviews 等） | 在浏览器里打开另存到同一目录，再跑 `rename` |
| 失败 | 标识符无法解析等 | 检查标识符 |

已经下载好（或手工另存）的 PDF，用同一条规则批量改名：

```bash
python3 .../lky_search.py rename --dir "<目录>" --from-manifest "<归档目录>/manifest.json" --dry-run
```

中文文献与订阅内容仍走 `nature-downloader`，下载完再 `rename` 统一命名。

## 文件命名规则

默认格式（与用户约定的示例一致）：

```text
C{中科院大类分区}Q{JCR最好分区}-{影响因子} {文章标题}.pdf
```

示例：

```text
C1Q1-18.1 Time-staggered chemo-immunotherapy via engineered nanofiber resists postoperative dynamic immunosuppression in glioblastoma.pdf
```

规则细节：

- 中科院分区取**大类分区**（升级版），JCR 分区取该刊所有学科分类里最好的那个。
- 指标缺失的片段自动省略：只有 JCR 时就写成 `Q1-7 标题`；预印本等无指标时直接用标题。
- 标题里的 `/ : * ? " < > |` 等非法字符换成空格，整体按 UTF-8 字节截断以避免超长。
- 需要把年份也放进文件名时加 `--with-year`（形如 `C1Q1-18.1 (2025) 标题`）。
- 想换格式用 `--name-template`，可用占位符：`{cas} {jcr} {if} {title} {journal} {year} {doi}`。

分区与影响因子来自技能自带的本地指标库 `data/journals.db`（2.3 万条期刊，含中科院分区表与 JCR 2025）。
重建或更新：

```bash
~/.codex/bin/vpnctl p python3 .../scripts/build_journal_index.py --check "Nature Communications"
```

## 数据源与默认策略

默认五源并发：PubMed、Europe PMC、OpenAlex、Crossref、arXiv。
配置了 Semantic Scholar 密钥后，它会自动成为默认的第六个源（并行请求，不拖慢整体）。
Google Scholar 需显式加入 `--source`。

| 源 | 适合 | 注意 |
|----|------|------|
| PubMed | 医学、生命科学、临床 | 有密钥 10 次/秒，无密钥 3 次/秒 |
| Europe PMC | 上述补充、预印本、开放获取全文 | 免费无密钥 |
| OpenAlex | 跨学科、引用数、作者机构 | 免费；默认全文匹配，用 `--strict` 收窄 |
| Crossref | DOI 元数据、出版社记录 | 免费；部分文章无摘要 |
| arXiv | 预印本（物理、CS、数学） | 请求间隔 3 秒 |
| Semantic Scholar | 引用图谱、影响力、OA 链接 | 已配置密钥，配额 1 次/秒；未配置时走共享池，极易 429 |
| Google Scholar | 覆盖面最广的兜底 | 抓取模式，容易被限流，低频使用 |

Elsevier / Scopus / ScienceDirect 未配置（用户无 API 密钥与机构订阅），已跳过。

## 速率、缓存与合规

- 每个源有独立的限流与指数退避；单源失败只记录警告，不影响其他源。
- 响应本地缓存 24 小时（`~/.cache/lky-search`），重复检索不会重复打接口。
- Google Scholar 与 Semantic Scholar 属抓取/受限接口：查询间隔已设为 6 秒 / 1.2 秒，
  不要用它做大批量循环；被限流时改用浏览器方式，见
  [references/scholar-and-browser.md](references/scholar-and-browser.md)。
- 只检索公开元数据与开放获取内容；不绕过付费墙、不破解验证码。

## 凭据

密钥存放在 `config/credentials.env`（权限 600）：

```ini
NCBI_API_KEY=<在 https://www.ncbi.nlm.nih.gov/account/ 生成>
NCBI_EMAIL=<联系邮箱，NCBI 要求>
S2_API_KEY=<可选，https://www.semanticscholar.org/product/api#api-key-form>
SAVE_ROOT=/Users/oldma/knowledge
```

环境变量可覆盖文件中的同名项。**不要把任何账号密码写进该文件**；
需要登录态的站点（CNKI、出版社）由 `nature-downloader` 复用浏览器会话处理。

## 常见问题排查

| 现象 | 处理 |
|------|------|
| NCBI 返回 `API key status invalid` | 到 NCBI 账号页复制或重建密钥，更新 `NCBI_API_KEY` |
| 检索结果很少 | 去掉 `--strict`、放宽年份、改用 `--source all` 或追加 `scholar` |
| 结果跑题（尤其是按被引排序） | 加 `--strict` 把范围收窄到题名/摘要 |
| Semantic Scholar 偶发 429 | 说明前一秒内已有请求；稍等重试即可，密钥已在生效 |
| Google Scholar 被限流 | 等一段时间，或改用浏览器方式抓取 |
| 想导入 Zotero / EndNote | 用归档目录里的 `results.ris` |
| 文件名没有 `C..Q..` 前缀 | 该刊不在本地指标库（新刊、会议、预印本），用 `metrics` 查一下确认 |
| 开放获取却下不下来 | 出版社拦截脚本，看 `_lky-downloads.json` 的「开放获取但被拦截」分类，在浏览器里另存后 `rename` |

## 参考文档（按需读取）

- [references/sources.md](references/sources.md)：各源的接口能力、字段、限速与回退顺序
- [references/search-syntax.md](references/search-syntax.md)：PubMed / Europe PMC / OpenAlex 检索语法与常用式
- [references/output-layout.md](references/output-layout.md)：知识库归档结构与 `manifest.json` 字段
- [references/scholar-and-browser.md](references/scholar-and-browser.md)：Scholar 限流应对、中文库与付费文献的浏览器/机构路线
- [references/journal-metrics-and-naming.md](references/journal-metrics-and-naming.md)：分区指标来源、文件命名规则、下载路线与被拦截出版社清单
