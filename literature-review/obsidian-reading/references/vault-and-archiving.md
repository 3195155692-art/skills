# Vault layout, PDF archiving, manifest

## Finding the vault

Walk up from the project directory until a `.obsidian` directory appears; that directory is the vault root. Notes must live inside it so Obsidian indexes them. Tooling must not.

```bash
vault_root="$(dir="$PWD"; while [ "$dir" != "/" ]; do [ -d "$dir/.obsidian" ] && echo "$dir" && break; dir="$(dirname "$dir")"; done)"
```

## Collection layout

```text
<collection folder>/
  README_<合集名>.md          # MOC: reading order, main line, key claims, open question
  01_<Title>.md
  02_<Title>.md
  ...
  PDFs/
    01_<Title>.pdf            # stem identical to the note
    ...
  manifest.json               # provenance for every PDF
```

Keep the PDF stem identical to the note stem. That single rule makes `PDFs/<stem>.pdf` resolvable from every note without a lookup table.

## Getting the files

Retrieval belongs to the `nature-downloader` skill. Hand it the whole list at once, and let it ask the Supporting Information question once for the batch. Do not re-implement download routing here.

What this skill owns:

- choosing the destination (`PDFs/` inside the collection),
- naming the file to match the note stem,
- recording provenance,
- and keeping extracted text out of the vault.

Never treat a saved HTML page, a login page, or a CAJ file as a PDF. If only HTML full text is available, say so and store it under `FullText/`, not `PDFs/`.

## Extracted text

Keep extracted text in a cache **outside** the vault (for example `/tmp/<collection>_text/`), or in a dot-folder that Obsidian ignores. Extracted text inside the vault pollutes search and the graph view.

## manifest.json

One manifest per collection. Every PDF gets one entry. Omit fields you genuinely do not know rather than guessing.

```json
{
  "project": "<collection name>",
  "generatedAt": "<ISO-8601 with timezone>",
  "tool": "<how the files were obtained>",
  "siPolicy": "main text only (--no-si) | with supporting information (--si)",
  "outputLayout": { "pdfs": "PDFs/", "notes": "*.md" },
  "summary": { "total": 8, "downloaded": 6, "pending_institutional_access": 2 },
  "results": [
    {
      "note": "01_<Title>.md",
      "file": "PDFs/01_<Title>.pdf",
      "title": "<published title>",
      "authors": "<first three et al.>",
      "journal": "<journal>",
      "year": 2024,
      "vol": "391(7):598-608",
      "doi": "10.1056/NEJMoa2400645",
      "language": "en",
      "publisher": "<publisher>",
      "status": "open_access_downloaded",
      "accessMode": "open_access | subscription | publisher_api",
      "version": "Author Accepted Manuscript (AAM) | Version of record | In-press | Preprint",
      "source": "<exact URL the file came from>",
      "sourceHost": "<host>",
      "format": "pdf",
      "mime": "application/pdf",
      "bytes": 359937,
      "sha256": "<hash>",
      "si_requested": false,
      "si_found": null,
      "altSources": ["<other legitimate copies, with a note on what they are>"]
    }
  ]
}
```

For a paper you could not obtain, keep a full entry with `"file": null` and an `evidence` array listing what you checked, so a later attempt does not repeat the search:

```json
{
  "note": "03_<Title>.md",
  "file": null,
  "status": "no_authorized_pdf_found",
  "accessMode": "subscription",
  "evidence": [
    "Unpaywall is_oa=false",
    "OpenAlex oa_status=closed, any_repository_has_fulltext=false",
    "Europe PMC inEPMC=N, no PMCID",
    "Europe PMC preprint index (SRC:PPR): no matching record"
  ],
  "requiresInstitutionalAccess": true
}
```

Useful `status` values: `open_access_downloaded`, `downloaded`, `downloaded_with_si`, `full_text_html_available`, `native_fulltext_downloaded`, `no_authorized_pdf_found`, `oa_not_found`, `credentials_missing`, `si_confirmation_required`, `failed_after_retry`.

Always re-verify the hash after copying or renaming a PDF, so the manifest cannot silently drift from the bytes on disk.

## Collection README (MOC)

The README is what makes a folder a collection. Keep these sections:

1. **合集说明** — scope, time window, themes covered.
2. **推荐阅读顺序** — grouped into layers (clinical problem → new paradigm → technical basis → clinical translation), each with the question that note answers.
3. **整个领域的主线** — one fenced arrow diagram showing how the papers chain together.
4. **最值得汇报的核心观点** — the three to five claims, each with its number.
5. **一个值得深入研究的问题** — the open question, in English and Chinese.
6. **建议的汇报标题** — one line, English and Chinese.
7. **文献清单** — full citations, numbered to match the notes.
8. **本地原文与获取状态** — a table of note → PDF present → version → source → status.
9. **每篇笔记的结构** and **待办** — what each note contains, and which ones are pending full text.
10. A closing caveat separating what the notes claim from what the papers prove.

Update the README in the same pass as any rename or addition. An index that points at old filenames is worse than no index.

## Upgrading an older collection to these conventions

When a collection was built before these rules:

1. Read every note first. Assume the user edited them; never regenerate.
2. Rename notes to `<序号>_<完整标题>.md`, sanitizing Obsidian-illegal characters (`:` becomes ` - `).
3. Rename the matching PDFs to the new stems.
4. Add the frontmatter block to each note. Leave the body untouched.
5. Align the `# 精读报告 <序号>：<标题>` H1 with the filename.
6. Sweep the vault for links to the old stems.
7. Update the README table and the manifest `note` / `file` fields.

Re-run `scripts/check_notes.py` afterwards; it should come back clean.
