# 数据源能力与回退顺序

引擎中各源的实现位于 `scripts/lky_search.py` 的 `search_*` 函数，全部使用官方公开 HTTP 接口，
不需要第三方库，也不做任何绕过验证码或付费墙的操作。

| 源 | 端点 | 认证 | 限速（引擎内置） | 摘要 | 引用数 | OA 标记 |
|----|------|------|------------------|------|--------|---------|
| PubMed | `eutils.ncbi.nlm.nih.gov` | `api_key` 可选 | 0.11 秒 / 0.34 秒 | 有 | 无 | 通过 PMCID 推断 |
| Europe PMC | `ebi.ac.uk/europepmc/webservices/rest` | 无 | 0.34 秒 | 有 | 有 | 有 |
| OpenAlex | `api.openalex.org` | `mailto` 礼貌池 | 0.11 秒 | 有（倒排索引重建） | 有 | 有 |
| Crossref | `api.crossref.org` | `mailto` 礼貌池 | 0.34 秒 | 部分（多数缺失） | 有 | 无 |
| arXiv | `export.arxiv.org/api/query` | 无 | 3 秒 | 有 | 无 | 全开放 |
| Semantic Scholar | `api.semanticscholar.org/graph/v1` | `x-api-key` 可选 | 1.2 秒 / 0.12 秒 | 有 | 有 | 有 |
| Google Scholar | `scholar.google.com/scholar` | 无（抓取） | 6 秒 | 片段 | 有 | 无 |

推荐复杂度递增的使用顺序：

1. **日常检索** — 默认五源（PubMed、Europe PMC、OpenAlex、Crossref、arXiv）。
2. **要引用排名或引用图谱** — 追加 `semanticscholar`（建议先配免费密钥）。
3. **覆盖面上不去** — 追加 `scholar`，注意会被限流。

## 各源已知特性

**PubMed**

- 只提供元数据，不提供被引次数。需要引用数时用 Europe PMC 或 OpenAlex 的合并结果。
- 一次 `efetch` 取多篇时偶发响应截断，引擎会自动拆成小批次重取。
- 密钥无效时接口会返回 `API key status invalid`，`doctor` 会直接报出来。

**Europe PMC**

- 同时收录 PubMed 记录（`source=MED`）和预印本（`source=PPR`），因此检索预印本不必单独接 bioRxiv API。
- `sort=CITED desc` 是在命中集内排序，可用；但当查询词没有限定字段时，
  「仅在全文擦边命中」的高被引文章会浮上来，因此引擎在按被引排序时自动收窄到 `TITLE_ABS`。

**OpenAlex**

- 默认 `search=` 是全库全文匹配，召回高但精度低；`title_and_abstract.search:` 精度高。
- 摘要以倒排索引（`abstract_inverted_index`）返回，引擎会按位置重建为正常文本。
- `cited_by_count:desc` 排序在命中集内进行，配合题名/摘要收窄后结果可用。

**Crossref**

- 摘要覆盖率低（出版社是否提交决定），所以单篇精取时引擎会用 PMID 回补 PubMed 摘要。
- `sort=is-referenced-by-count` 是**全库排序**，会返回与检索词无关的经典高被引论文；
  引擎改为先取相关度候选再本地排序，已规避。
- 用 `select=` 控制返回字段时，`language` 不是合法字段（会返回 400），引擎已移除。

**Semantic Scholar**

- 未配置密钥时约 1 次/秒，连续请求很容易返回 429。
- 免费密钥申请：<https://www.semanticscholar.org/product/api#api-key-form>

**Google Scholar**

- 抓取模式，无官方 API；连续请求会被跳转到人机验证页（HTTP 302）。
- 引擎把它排除在默认源之外，并且不做重试（重试只会加深封锁）。
- 被限流后的应对见 [scholar-and-browser.md](scholar-and-browser.md)。

## 未覆盖的源

| 源 | 状态 | 替代路线 |
|----|------|----------|
| Elsevier / Scopus / ScienceDirect | 无 API 密钥与机构订阅，接口返回 401 | 用 DOI 交给 `nature-downloader` 走机构授权 |
| Web of Science | 需机构订阅 | 同上 |
| CNKI / 万方 / 维普 | 无公开 API | 中文检索走浏览器方式，下载走 `nature-downloader` |
| bioRxiv / medRxiv 检索 | 官方接口不支持关键词检索 | 已由 Europe PMC 的预印本索引覆盖 |
