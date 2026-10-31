# 知识库归档结构与台账字段

归档沿用 `~/knowledge/artical` 里已有的「文献合集」习惯：一个主题一个文件夹，
批次目录里放说明、数据文件和 `PDFs/` 子目录。

## 目录结构

```text
/Users/oldma/knowledge/                  # SAVE_ROOT，可用 --root 覆盖
└── <检索方向>/
    └── 2026-09-21_<检索词缩写>/
        ├── 00_README_<检索方向>_检索结果.md
        ├── results.md         # 结果表（Markdown）
        ├── results.csv        # Excel / Numbers
        ├── results.ris        # Zotero / EndNote / NoteExpress
        ├── results.bib        # LaTeX / Obsidian
        ├── results.json       # 含摘要的结构化数据
        ├── manifest.json      # 台账
        └── PDFs/              # 下载的全文
```

主题文件夹名与用户给 `--topic` 的写法一致；若根目录下已有同名主题
（比较时忽略大小写、空格与标点），直接复用，不会重复建目录。

批次目录以当天日期开头；同一天同一主题重复检索会自动加 `_2`、`_3` 后缀，不会覆盖。

## manifest.json 字段

| 字段 | 含义 |
|------|------|
| `project` | 相对根目录的路径，便于跨设备引用 |
| `generatedAt` | 生成时间（含时区） |
| `tool` | 引擎版本，便于回溯是哪一版产生的 |
| `kind` | `search` / `fetch` / `related` |
| `query` / `sources` / `sort` / `filters` | 本次检索的完整设定，用于复现 |
| `summary` | 总数、有 DOI 数、有开放获取版本数 |
| `errors` | 本次各源的失败记录（含被限流的源） |
| `results[]` | 每条记录：题名、作者、期刊、年份、DOI/PMID/PMCID/arXiv、被引、`openAccess`、`sources`、`url` |
| `results[].file` | 下载完成后回填的 PDF 文件名 |
| `results[].note` | 精读笔记文件名（由后续写作流程回填） |

## 与精读流程衔接

需要把清单升级成精读合集时，按既有习惯命名，使笔记、PDF、台账三者对齐：

```text
01_<Title>.md          # 精读笔记
PDFs/01_<Title>.pdf    # 对应全文
```

编号与 `manifest.json` 中 `results[].index` 一致；回填方式：

```json
{ "index": 3, "file": "03_Covert consciousness.pdf", "note": "03_Covert consciousness.md" }
```

`00_README_*.md` 已包含检索设定、结果表与取全文指引，可直接作为合集首页使用。

## 覆盖默认根目录

```bash
# 直接写进 Obsidian 库
python3 .../lky_search.py search --query "..." --topic "<方向>" --save \
  --root /Users/oldma/knowledge/artical

# 写到别处（例如某个项目目录）
python3 .../lky_search.py search --query "..." --topic "<方向>" --save --root /path/to/project/lit
```

`SAVE_ROOT` 写在 `config/credentials.env` 里，改一次就长期生效；`--root` 只影响当次。
