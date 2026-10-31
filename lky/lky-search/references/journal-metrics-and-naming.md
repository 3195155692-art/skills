# 分区指标、文件命名与全文下载路线

## 命名规则

```text
C{中科院大类分区}Q{JCR最好分区}-{影响因子} {文章标题}.pdf
C1Q1-18.1 Time-staggered chemo-immunotherapy via engineered nanofiber … .pdf
```

各片段来源：

| 片段 | 含义 | 来源字段 |
|------|------|----------|
| `C1` | 中科院分区表（升级版）**大类**分区 | `journals.cas_zone` |
| `Q1` | JCR 该刊所有学科里**最好**的分区 | `journals.jcr_quartile` |
| `18.1` | 影响因子（整数则不显示小数，如 `118`） | `journals.impact_factor` |

缺失时自动省略：只有 JCR → `Q1-7 标题`；都没有（预印本、会议、新刊）→ 只用标题。

可用 `--name-template` 自定义，占位符：`{cas} {jcr} {if} {title} {journal} {year} {doi}`。
例如想要年份在前：`--name-template "C{cas}Q{jcr}-{if} ({year}) {title}"`。

## 指标数据从哪来

技能自带一个本地 SQLite 指标库 `data/journals.db`（约 4.5 MB，2.3 万条期刊），
由 `scripts/build_journal_index.py` 从公开镜像仓库 [hitfyd/ShowJCR](https://github.com/hitfyd/ShowJCR)
的「中科院分区表升级版 2025」与「JCR 2025/2024」原始 CSV 构建。

说明与边界：

- 这是**第三方整理的镜像数据**，不是官方接口。中科院分区表与 JCR 原始版权分别归中科院文献情报中心与 Clarivate；
  本地库仅供个人检索使用，不随技能分发。
- 更新频率取决于上游仓库。每年分区/影响因子更新后重新跑一次 `build_journal_index.py` 即可。
- 查询顺序：ISSN → EISSN → 期刊名（归一化后匹配）。因此没有 ISSN 的记录也能命中。
- 会议论文、预印本、新刊通常查不到，此时文件名不加前缀，属正常情况。

```bash
# 重建（会自动下载原始 CSV 到 data/raw/）
~/.codex/bin/vpnctl p python3 scripts/build_journal_index.py --check "Nature Communications"

# 只查一条
python3 scripts/lky_search.py metrics --journal "NeuroImage"
python3 scripts/lky_search.py metrics --id 10.1038/s41467-026-75065-x
```

## 下载路线（按顺序尝试）

1. **出版社 CDN 规律**：MDPI 这类落地页被 WAF 拦掉的出版社，其 CDN（`mdpi-res.com`）可直接访问，
   由 DOI 与卷号、篇号推导出地址。
2. **Unpaywall / OpenAlex 的 PDF 直链**：大多数金色开放获取期刊（Nature Communications、Frontiers、
   PLOS、BMC 等）走这条即可。
3. **PMC / Europe PMC**：对开放获取的 PMC 文章再试一次。
4. **落地页解析**：从文章页读 `citation_pdf_url`（出版社通用的标准 meta 标签）再试。
5. **浏览器兜底**（`--browser-fallback`）：用无头 Chrome 抓取。实测对 Cloudflare 人机校验无效，
   属于 best-effort，默认关闭。

## 已知拦脚本的出版社（实测）

| 出版社 / 平台 | 现象 | 处理 |
|---------------|------|------|
| MDPI 主站 | 脚本与无头浏览器都返回 `Access Denied` | 已用 `mdpi-res.com` CDN 绕过，正常下载 |
| Europe PMC render、PMC `/pdf/` | 403 或 Cloudflare「请稍候…」 | 归类为「开放获取但被拦截」，浏览器另存 |
| IOP、IEEE、Annual Reviews | 直链返回 HTML 而不是 PDF | 同上 |
| Elsevier / Springer 订阅内容 | 无开放获取版本 | 交给 `nature-downloader` 走机构授权 |

## 与 nature-downloader 的分工

- 中文文献（CNKI）、订阅内容、补充材料：`nature-downloader`。
- 它下载完成的 PDF 放进目录后，用本技能的 `rename` 按同一规则统一命名，
  这样手工下载与自动下载的文件名保持一致。
