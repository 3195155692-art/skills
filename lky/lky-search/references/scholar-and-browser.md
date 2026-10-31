# Google Scholar 限流、中文库与付费全文

本页处理三类「接口搞不定」的情况：Scholar 被限流、中文文献、需要机构订阅的英文全文。

## Google Scholar 被限流

现象：请求被重定向到人机验证页，`doctor` 显示「触发人机验证」或「被限流」。

已实测：单次请求可以正常返回结果；但连续几次查询后，同一台机器会被要求验证。
引擎因此把 Scholar 排除在默认源之外，并做了两件事——查询间隔 6 秒、失败不重试。

处理顺序：

1. **优先换源**：多数医学/生命科学问题用 PubMed + Europe PMC + OpenAlex 已经足够，
   Scholar 主要是补会议论文与灰色文献。
2. **降频**：确实需要时，一次检索只查一轮，隔几分钟再查下一次；不要放进循环。
3. **走浏览器**：用 Codex 的浏览器打开 `https://scholar.google.com/scholar?q=<检索词>`，
   由页面直接呈现结果；这样用的是真实浏览器指纹，比脚本抓取稳定。
   需要翻页或批量取条目时，用浏览器自动化逐页读取，并保持人工节奏。
4. **不要做的**：不要用登录态脚本高频抓取，也不要尝试绕过验证码。

## 中文文献（CNKI / 万方 / 维普）

中文库没有公开检索 API，且访问依赖机构授权。因此中文文献走浏览器路线，检索与下载分工：

1. **检索**：用浏览器打开 CNKI 检索页，按用户给的主题检索，导出题录
   （CNKI 支持导出 RIS / EndNote / NoteExpress 格式）。把导出的 `.ris`/`.txt` 放进
   目标主题文件夹，作为中文部分的清单。
2. **下载**：把选中的中文文献交给 `nature-downloader` skill。它会复用用户已登录的浏览器
   会话走机构授权（CNKI 路线），导出的是 CAJ 还是 PDF 由数据库决定，需如实记录格式。
3. **归档**：把中文条目合并进同一批次的 `results.ris` 与 `manifest.json`，
   保持一个主题下中外文合一。

注意：中文文献不要先用英文库找 OA 副本再当成中文库结果；用户要的是 CNKI 版本时，以 CNKI 为准。

## 需要机构订阅的英文全文

`lky_search.py oa --doi <DOI>` 返回 `is_oa: false` 时，说明没有合法的开放获取版本。

处理流程：

1. 把 DOI 或题名交给 `nature-downloader` skill。
2. 该技能会先尝试出版社 API / 合法 OA 仓储，再按需走机构 Web Access（复用浏览器登录态）。
3. 若用户需要补充材料（SI），`nature-downloader` 会先确认一次，再决定是否下载。
4. 下载结果回填到本批次 `manifest.json` 的 `file` 字段，PDF 放进 `PDFs/`。

不要在付费墙前尝试任何绕过手段；拿不到就如实记录 `requiresInstitutionalAccess`。

## 代理

若所在网络访问 Google、Unpaywall、Europe PMC 受限，在 `config/credentials.env` 里设置：

```ini
HTTP_PROXY=http://127.0.0.1:7890
```

引擎的所有请求（含 Scholar）都会走该代理；留空表示直连。
