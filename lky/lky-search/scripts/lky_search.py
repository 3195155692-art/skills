#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LKY Search — 公共学术数据库检索与抓取引擎（零第三方依赖，Python 3.9+ 标准库）。

职责边界：
  本引擎负责「发现与整理」——多源检索、元数据、摘要、去重、排序、引文、导出、按主题落盘。
  「机构/付费全文下载」（CNKI、出版社 Web Access、补充材料）交给 nature-downloader skill；
  本引擎只判定开放获取（OA）可得性并给出取全文路线。

子命令
  doctor    自检：配置、NCBI 密钥有效性、各数据源连通性
  search    多源检索 → 去重 → 排序 → 表格 / 导出 / 归档
  fetch     按 PMID / DOI / arXiv ID 精取单篇元数据与摘要
  ids       DOI ↔ PMID ↔ PMCID ↔ arXiv ID 互转
  cite      生成 APA / Vancouver / BibTeX / RIS 引文
  related   相关文章
  oa        判定开放获取可得性，给出取全文路线
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import gzip
import hashlib
import html
import http.client
import io
import json
import os
import re
import shutil
import socket
import ssl
import sys
import sqlite3
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime

VERSION = "1.0.0"

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(SKILL_DIR, "config", "credentials.env")
CACHE_DIR = os.path.expanduser("~/.cache/lky-search")

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
IDCONV = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
EUROPEPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"
OPENALEX = "https://api.openalex.org"
CROSSREF = "https://api.crossref.org"
ARXIV = "https://export.arxiv.org/api/query"
S2 = "https://api.semanticscholar.org/graph/v1"
UNPAYWALL = "https://api.unpaywall.org/v2"
SCHOLAR = "https://scholar.google.com/scholar"

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

ALL_SOURCES = ["pubmed", "europepmc", "openalex", "crossref", "arxiv", "semanticscholar", "scholar"]
DEFAULT_SOURCES = ["pubmed", "europepmc", "openalex", "crossref", "arxiv"]

SOURCE_LABELS = {
    "pubmed": "PubMed", "europepmc": "Europe PMC", "openalex": "OpenAlex",
    "crossref": "Crossref", "arxiv": "arXiv", "semanticscholar": "Semantic Scholar",
    "scholar": "Google Scholar",
}

DEFAULT_CONFIG = {
    "NCBI_API_KEY": "",
    "NCBI_EMAIL": "",
    "NCBI_TOOL": "lky-search",
    "S2_API_KEY": "",
    "OPENALEX_MAILTO": "",
    "CROSSREF_MAILTO": "",
    "SAVE_ROOT": "/Users/oldma/knowledge",
    "HTTP_PROXY": "",
}


# --------------------------------------------------------------------------
# 配置
# --------------------------------------------------------------------------

def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key:
                    cfg[key] = value
    for key in list(cfg.keys()):
        if os.environ.get(key):
            cfg[key] = os.environ[key]
    if not cfg["NCBI_EMAIL"]:
        cfg["NCBI_EMAIL"] = cfg["OPENALEX_MAILTO"] or cfg["CROSSREF_MAILTO"]
    if not cfg["OPENALEX_MAILTO"]:
        cfg["OPENALEX_MAILTO"] = cfg["NCBI_EMAIL"]
    if not cfg["CROSSREF_MAILTO"]:
        cfg["CROSSREF_MAILTO"] = cfg["NCBI_EMAIL"]
    return cfg


def source_intervals(cfg: dict) -> dict:
    """各数据源最小请求间隔（秒），遵守站点礼貌速率。"""
    have_ncbi = bool(cfg.get("NCBI_API_KEY"))
    return {
        "pubmed": 0.11 if have_ncbi else 0.34,
        "ncbi_idconv": 0.11 if have_ncbi else 0.34,
        "europepmc": 0.34,
        "openalex": 0.11,
        "crossref": 0.34,
        "arxiv": 3.0,
        # Semantic Scholar 的入门配额是 1 次/秒（含密钥），未认证走共享池更容易 429。
        "semanticscholar": 1.1 if cfg.get("S2_API_KEY") else 1.6,
        "scholar": 6.0,
        "unpaywall": 0.34,
    }


# --------------------------------------------------------------------------
# 文本工具
# --------------------------------------------------------------------------

NAMED_ENTITIES = {
    "bgr": "β", "ggr": "γ", "agr": "α", "dgr": "δ", "egr": "ε", "mgr": "μ",
    "kgr": "κ", "lgr": "λ", "sgr": "σ", "tgr": "τ", "pgr": "π", "zgr": "ζ",
    "nbsp": " ", "ndash": "–", "mdash": "—", "minus": "−", "deg": "°",
    "plusmn": "±", "times": "×", "le": "≤", "ge": "≥", "ne": "≠", "asymp": "≈",
    "approx": "≈", "prime": "′", "Prime": "″", "hellip": "…", "ldquo": "“",
    "rdquo": "”", "lsquo": "‘", "rsquo": "’", "sup2": "²", "sup3": "³", "sup1": "¹",
    "copy": "©", "reg": "®", "trade": "™",
}


def strip_tags(markup: str) -> str:
    """把 JATS / HTML 片段转成纯文本。"""
    if not markup:
        return ""
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", markup)
    text = re.sub(r"(?i)</(p|div|sec|abstract|title|td|tr|li|h\d)>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", " ", text)
    text = re.sub(r"(?i)<(sub|sup)>", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace("\u00ad", "")
    return re.sub(r"\s+", " ", text).strip()


def safe_xml(payload: bytes) -> ET.Element:
    """解析 NCBI XML：剔除 DOCTYPE，替换未定义实体。"""
    text = payload.decode("utf-8", "ignore")
    text = re.sub(r"(?is)<!DOCTYPE[^>]*>", "", text)

    def _replace(match):
        name = match.group(1)
        if name in ("amp", "lt", "gt", "quot", "apos"):
            return match.group(0)
        return NAMED_ENTITIES.get(name, " ")

    text = re.sub(r"&([A-Za-z][A-Za-z0-9]*);", _replace, text)
    return ET.fromstring(text)


def norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", html.unescape(title or "").lower())


def norm_doi(doi: str) -> str:
    if not doi:
        return ""
    doi = re.sub(r"^(https?://)?(dx\.)?doi\.org/", "", doi.strip(), flags=re.I)
    doi = re.sub(r"^doi:\s*", "", doi, flags=re.I)
    return doi.strip().rstrip(".").lower()


def slugify(text: str, limit: int = 60) -> str:
    slug = re.sub(r"[^\w\u4e00-\u9fff]+", "_", (text or "").strip(), flags=re.UNICODE)
    slug = re.sub(r"_+", "_", slug).strip("_")
    return (slug[:limit] or "search").strip("_")


def first_author_family(record: dict) -> str:
    authors = record.get("authors") or []
    if not authors:
        return "anon"
    name = authors[0]
    if "," in name:
        candidate = name.split(",")[0]
    else:
        parts = name.split()
        candidate = parts[-1] if parts else name
    return re.sub(r"[^A-Za-z\u4e00-\u9fff]", "", candidate) or "anon"


def year_of(record: dict):
    if record.get("year"):
        try:
            return int(str(record["year"])[:4])
        except ValueError:
            pass
    match = re.search(r"(19|20)\d{2}", str(record.get("date") or ""))
    return int(match.group(0)) if match else None


def truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def guess_year(text: str):
    match = re.search(r"(19|20)\d{2}", text or "")
    return int(match.group(0)) if match else None


def xml_complete(payload: bytes) -> bool:
    """XML 响应完整性校验。

    NCBI 在高并发下会静默截断响应（返回 200、连接正常关闭、内容是半截 XML），
    既不报错也看不出异常；这里用「必须以闭合标签收尾」作为判据，避免把半截数据当成结果。
    """
    if not payload:
        return False
    return payload.rstrip().endswith(b">")


def pubmed_set_complete(payload: bytes) -> bool:
    """PubMed efetch 必须是完整的 PubmedArticleSet，半截记录无法解析。"""
    return bool(payload) and payload.rstrip().endswith(b"</PubmedArticleSet>")


def json_complete(payload: bytes) -> bool:
    """JSON 响应完整性校验：能整体解析才算完整。"""
    if not payload:
        return False
    try:
        json.loads(payload.decode("utf-8", "ignore"))
        return True
    except ValueError:
        return False


# --------------------------------------------------------------------------
# HTTP：缓存 + 限流 + 指数退避重试
# --------------------------------------------------------------------------

class Http:
    # 各源的失败重试策略：(重试次数, 退避基数秒)。语义学者的入门配额是全局共享的
    # 1 次/秒，高峰期即使有密钥也会随机 429，因此给它更多次、更长的退避。
    RETRY_POLICY = {"semanticscholar": (4, 2.0), "scholar": (1, 0.0)}

    def __init__(self, cfg: dict, use_cache: bool = True, cache_ttl: int = 86400, verbose: bool = False):
        self.cfg = cfg
        self.intervals = source_intervals(cfg)
        self.use_cache = use_cache
        self.cache_ttl = cache_ttl
        self.verbose = verbose
        self.errors = []
        self._locks, self._last = {}, {}
        self._guard = threading.Lock()
        handlers = []
        proxy = cfg.get("HTTP_PROXY") or ""
        if proxy:
            handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        self.opener = urllib.request.build_opener(*handlers)

    def _cache_path(self, url: str) -> str:
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
        return os.path.join(CACHE_DIR, digest[:2], digest + ".cache")

    def _cache_read(self, url: str, validate=None):
        path = self._cache_path(url)
        try:
            if time.time() - os.path.getmtime(path) > self.cache_ttl:
                return None
            with open(path, "rb") as fh:
                payload = fh.read()
        except OSError:
            return None
        if validate and not validate(payload):
            return None  # 早期版本可能缓存过被截断的响应，这里直接忽略
        return payload

    def _cache_write(self, url: str, payload: bytes) -> None:
        path = self._cache_path(url)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            handle, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
            with os.fdopen(handle, "wb") as fh:
                fh.write(payload)
            os.replace(tmp, path)
        except OSError:
            pass

    def _throttle(self, source: str) -> None:
        with self._guard:
            lock = self._locks.setdefault(source, threading.Lock())
        with lock:
            wait = self.intervals.get(source, 0.5) - (time.time() - self._last.get(source, 0.0))
            if wait > 0:
                time.sleep(wait)
            self._last[source] = time.time()

    def record_error(self, source: str, message: str) -> None:
        self.errors.append({"source": source, "error": message})
        if self.verbose:
            sys.stderr.write("[warn] %s: %s\n" % (source, message))

    def get(self, url, params=None, source="generic", headers=None, timeout=30, use_cache=None,
            retries=3, validate=None):
        if params:
            clean = {k: v for k, v in params.items() if v not in (None, "")}
            url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(clean)
        # Scholar 的限流是「硬拒绝」，重试只会加深封锁，因此不重试。
        planned_retries, backoff = self.RETRY_POLICY.get(source, (retries, 1.5))
        retries = planned_retries
        cache_on = self.use_cache if use_cache is None else use_cache
        if cache_on:
            cached = self._cache_read(url, validate)
            if cached is not None:
                return cached
        contact = self.cfg.get("NCBI_EMAIL") or "anonymous"
        # 出版社与 PMC/Europe PMC 的渲染端点会拒绝非浏览器客户端，下载 PDF 时统一用浏览器 UA。
        browser_like = source in ("scholar", "pdf")
        base_headers = {
            "User-Agent": BROWSER_UA if browser_like else "lky-search/%s (mailto:%s)" % (VERSION, contact),
            "Accept": "application/json, application/xml, text/html;q=0.9, */*;q=0.8",
        }
        if browser_like:
            base_headers["Accept-Language"] = "en-US,en;q=0.9"
        if source == "scholar":
            base_headers["Accept-Encoding"] = "gzip"
        if headers:
            base_headers.update(headers)

        last_error, payload = "unknown", None
        for attempt in range(retries):
            self._throttle(source)
            payload = None
            try:
                with self.opener.open(urllib.request.Request(url, headers=base_headers), timeout=timeout) as response:
                    payload = response.read()
                    if (response.headers.get("Content-Encoding") or "").lower() == "gzip":
                        payload = gzip.decompress(payload)
            except urllib.error.HTTPError as exc:
                last_error = "HTTP %s" % exc.code
                if exc.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                    time.sleep(1.5 * (2 ** attempt))
                    continue
                break
            except http.client.IncompleteRead as exc:
                payload = getattr(exc, "partial", b"") or b""
                last_error = "连接中断（已收到 %d 字节）" % len(payload)
            except (urllib.error.URLError, ssl.SSLError, TimeoutError, OSError, ValueError) as exc:
                last_error = str(getattr(exc, "reason", exc))
            if payload is not None:
                if validate is None or validate(payload):
                    if cache_on and len(payload) > 200:
                        self._cache_write(url, payload)
                    return payload
                last_error = "响应不完整（%d 字节，疑似被截断）" % len(payload)
            if attempt < retries - 1:
                time.sleep(backoff * (2 ** attempt))
                continue
            break
        self.record_error(source, "%s (%s)" % (last_error, truncate(url, 90)))
        return payload if payload else b""

    def get_json(self, url, params=None, **kwargs):
        kwargs.setdefault("validate", json_complete)
        payload = self.get(url, params, **kwargs)
        if not payload:
            return None
        try:
            return json.loads(payload.decode("utf-8", "ignore"))
        except ValueError:
            return None


# --------------------------------------------------------------------------
# 数据源适配器
# --------------------------------------------------------------------------

def blank_record(source: str) -> dict:
    return {
        "source": source, "sources": [source], "title": "", "authors": [], "journal": "",
        "year": None, "date": "", "abstract": "", "doi": "", "pmid": "", "pmcid": "",
        "arxiv": "", "citations": None, "url": "", "type": "article", "volume": "",
        "issue": "", "pages": "", "publisher": "", "language": "", "oa": None,
        "issn": "", "eissn": "",
    }


def pubmed_params(cfg: dict) -> dict:
    return {"api_key": cfg.get("NCBI_API_KEY") or None,
            "tool": cfg.get("NCBI_TOOL") or None,
            "email": cfg.get("NCBI_EMAIL") or None}


def _parse_pubmed_article(node) -> dict:
    record = blank_record("pubmed")
    citation = node.find("MedlineCitation")
    if citation is None:
        return record
    pmid = (citation.findtext("PMID") or "").strip()
    record["pmid"] = pmid
    article = citation.find("Article")
    if article is None:
        return record
    title_node = article.find("ArticleTitle")
    record["title"] = strip_tags("".join(title_node.itertext())) if title_node is not None else ""

    bits = []
    abstract = article.find("Abstract")
    if abstract is not None:
        for chunk in abstract.findall("AbstractText"):
            label = chunk.get("Label") or ""
            body = strip_tags("".join(chunk.itertext()))
            if body:
                bits.append(("%s: %s" % (label, body)) if label else body)
    record["abstract"] = " ".join(bits)

    authors = []
    author_list = article.find("AuthorList")
    if author_list is not None:
        for author in author_list.findall("Author"):
            collective = author.findtext("CollectiveName")
            if collective:
                authors.append(collective.strip())
                continue
            family = (author.findtext("LastName") or "").strip()
            given = (author.findtext("ForeName") or author.findtext("Initials") or "").strip()
            if family:
                authors.append(("%s %s" % (given, family)).strip())
    record["authors"] = authors

    journal = article.find("Journal")
    if journal is not None:
        record["journal"] = (journal.findtext("ISOAbbreviation") or journal.findtext("Title") or "").strip()
        for issn_node in journal.findall("ISSN"):
            value = (issn_node.text or "").strip()
            if (issn_node.get("IssnType") or "").lower() == "electronic":
                record["eissn"] = record["eissn"] or value
            else:
                record["issn"] = record["issn"] or value
        issue = journal.find("JournalIssue")
        if issue is not None:
            record["volume"] = (issue.findtext("Volume") or "").strip()
            record["issue"] = (issue.findtext("Issue") or "").strip()
            pubdate = issue.find("PubDate")
            if pubdate is not None:
                year = (pubdate.findtext("Year") or "").strip()
                medline = (pubdate.findtext("MedlineDate") or "").strip()
                if year.isdigit():
                    record["year"] = int(year)
                    record["date"] = "-".join(p for p in (year, (pubdate.findtext("Month") or "").strip(),
                                                           (pubdate.findtext("Day") or "").strip()) if p)
                elif medline:
                    record["year"] = guess_year(medline)
                    record["date"] = medline
    pages = article.find("Pagination")
    if pages is not None:
        record["pages"] = (pages.findtext("MedlinePgn") or "").strip()

    id_list = node.find("PubmedData/ArticleIdList")
    if id_list is not None:
        for item in id_list.findall("ArticleId"):
            id_type = (item.get("IdType") or "").lower()
            value = (item.text or "").strip()
            if id_type == "doi":
                record["doi"] = norm_doi(value)
            elif id_type == "pmc":
                record["pmcid"] = value
    record["url"] = "https://pubmed.ncbi.nlm.nih.gov/%s/" % pmid if pmid else ""
    record["language"] = ", ".join(lang.text for lang in citation.findall("Language") if lang.text)
    return record


def search_pubmed(http, cfg, query, limit, sort="relevance", year_from=None, year_to=None, strict=False) -> list:
    term = query
    if year_from or year_to:
        term = "(%s) AND (%s:%s[dp])" % (query, year_from or 1800, year_to or datetime.now().year)
    params = {"db": "pubmed", "term": term, "retmax": max(limit, 1), "retmode": "json",
              "sort": {"date": "pub_date"}.get(sort, "relevance")}
    params.update(pubmed_params(cfg))
    data = http.get_json("%s/esearch.fcgi" % EUTILS, params, source="pubmed")
    ids = ((data or {}).get("esearchresult") or {}).get("idlist") or []
    if not ids:
        return []
    return fetch_pubmed_ids(http, cfg, ids)


def fetch_pubmed_ids(http, cfg, ids) -> list:
    ids = [str(i) for i in ids]
    if len(ids) > 1:
        # PubMed 大批量 efetch 偶发响应截断；失败时按半拆分重取，保证单篇失败不拖垮整批。
        payload = _pubmed_efetch(http, cfg, ids)
        records = _parse_pubmed_payload(http, payload)
        if records:
            return records
        mid = len(ids) // 2
        http.record_error("pubmed", "批量取回失败，改用小批次重试（%d 条）" % len(ids))
        return fetch_pubmed_ids(http, cfg, ids[:mid]) + fetch_pubmed_ids(http, cfg, ids[mid:])
    payload = _pubmed_efetch(http, cfg, ids)
    return _parse_pubmed_payload(http, payload)


def _pubmed_efetch(http, cfg, ids) -> bytes:
    params = {"db": "pubmed", "id": ",".join(str(i) for i in ids), "retmode": "xml"}
    params.update(pubmed_params(cfg))
    return http.get("%s/efetch.fcgi" % EUTILS, params, source="pubmed", validate=pubmed_set_complete)


def _parse_pubmed_payload(http, payload) -> list:
    if not payload:
        return []
    try:
        root = safe_xml(payload)
    except ET.ParseError as exc:
        http.record_error("pubmed", "XML 解析失败：%s" % exc)
        return []
    return [r for r in (_parse_pubmed_article(n) for n in root.findall(".//PubmedArticle")) if r.get("title")]


def search_europepmc(http, cfg, query, limit, sort="relevance", year_from=None, year_to=None, strict=False) -> list:
    terms = query
    # 按被引排序会把「仅在全文里擦边命中」的高被引论文顶上来，因此该模式下自动收窄到题名/摘要。
    if (strict or sort == "cited") and not re.search(r'[:"\(\)]|\bAND\b|\bOR\b', query):
        terms = 'TITLE_ABS:"%s"' % query.strip()
    if year_from or year_to:
        terms = "(%s) AND (PUB_YEAR:[%s TO %s])" % (terms, year_from or 1800, year_to or datetime.now().year)
    data = http.get_json("%s/search" % EUROPEPMC, {
        "query": terms, "format": "json", "resultType": "core", "pageSize": max(limit, 1),
        "sort": {"cited": "CITED desc", "date": "P_PDATE_D desc"}.get(sort, None),
    }, source="europepmc")
    out = []
    for item in ((data or {}).get("resultList") or {}).get("result") or []:
        record = blank_record("europepmc")
        record["title"] = strip_tags(item.get("title") or "")
        if not record["title"]:
            continue
        record["abstract"] = strip_tags(item.get("abstractText") or "")
        record["journal"] = (item.get("journalTitle")
                             or ((item.get("journalInfo") or {}).get("journal") or {}).get("title") or "")
        issn_info = ((item.get("journalInfo") or {}).get("journal") or {})
        record["issn"] = issn_info.get("issn") or item.get("issn") or ""
        year = str(item.get("pubYear") or "")
        record["year"] = int(year) if year.isdigit() else None
        record["date"] = item.get("firstPublicationDate") or ""
        record["doi"] = norm_doi(item.get("doi") or "")
        record["pmid"] = item.get("pmid") or ""
        record["pmcid"] = item.get("pmcid") or ""
        record["citations"] = item.get("citedByCount")
        record["volume"] = item.get("journalVolume") or ""
        record["issue"] = item.get("issue") or ""
        record["pages"] = item.get("pageInfo") or ""
        record["language"] = item.get("language") or ""
        record["publisher"] = item.get("publisher") or ""
        record["oa"] = item.get("isOpenAccess") == "Y"
        record["type"] = "preprint" if item.get("source") == "PPR" else "article"
        record["authors"] = [a.strip().rstrip(".") for a in (item.get("authorString") or "").split(",") if a.strip()]
        record["url"] = "https://europepmc.org/article/%s/%s" % (item.get("source") or "MED", item.get("id"))
        out.append(record)
    return out


def _openalex_abstract(inverted) -> str:
    if not inverted:
        return ""
    pairs = []
    for word, slots in inverted.items():
        for slot in slots:
            pairs.append((slot, word))
    pairs.sort()
    return " ".join(word for _, word in pairs)


def search_openalex(http, cfg, query, limit, sort="relevance", year_from=None, year_to=None, strict=False) -> list:
    filters = []
    params = {"search": query}
    if strict or sort == "cited":
        # OpenAlex 默认是全库全文匹配，收窄到题名/摘要可显著提高精度。
        del params["search"]
        filters.append("title_and_abstract.search:%s" % query)
    if year_from:
        filters.append("from_publication_date:%s-01-01" % year_from)
    if year_to:
        filters.append("to_publication_date:%s-12-31" % year_to)
    params.update({
        "per-page": max(limit, 1),
        "sort": {"cited": "cited_by_count:desc", "date": "publication_date:desc"}.get(sort, "relevance_score:desc"),
        "filter": ",".join(filters) or None,
        "mailto": cfg.get("OPENALEX_MAILTO") or None,
    })
    data = http.get_json("%s/works" % OPENALEX, params, source="openalex")
    out = []
    for item in (data or {}).get("results", []):
        record = blank_record("openalex")
        record["title"] = strip_tags(item.get("title") or item.get("display_name") or "")
        if not record["title"]:
            continue
        record["abstract"] = _openalex_abstract(item.get("abstract_inverted_index"))
        record["year"] = item.get("publication_year")
        record["date"] = item.get("publication_date") or ""
        record["citations"] = item.get("cited_by_count")
        record["doi"] = norm_doi(item.get("doi") or "")
        ids = item.get("ids") or {}
        record["pmid"] = (ids.get("pmid") or "").rsplit("/", 1)[-1]
        record["pmcid"] = (ids.get("pmcid") or "").rsplit("/", 1)[-1]
        source = (item.get("primary_location") or {}).get("source") or {}
        record["journal"] = source.get("display_name") or ""
        record["issn"] = source.get("issn_l") or ""
        extra_issns = source.get("issn") or []
        if not record["issn"] and extra_issns:
            record["issn"] = extra_issns[0]
        if len(extra_issns) > 1:
            record["eissn"] = extra_issns[1]
        record["publisher"] = source.get("host_organization_name") or ""
        record["authors"] = [(a.get("author") or {}).get("display_name", "")
                             for a in (item.get("authorships") or []) if (a.get("author") or {}).get("display_name")]
        record["url"] = (item.get("primary_location") or {}).get("landing_page_url") or item.get("id") or ""
        biblio = item.get("biblio") or {}
        record["volume"] = biblio.get("volume") or ""
        record["issue"] = biblio.get("issue") or ""
        first, last = biblio.get("first_page") or "", biblio.get("last_page") or ""
        record["pages"] = ("%s-%s" % (first, last)).strip("-") if first else ""
        record["oa"] = bool((item.get("open_access") or {}).get("is_oa"))
        record["type"] = "preprint" if item.get("type") == "preprint" else "article"
        record["language"] = item.get("language") or ""
        out.append(record)
    return out


CROSSREF_SELECT = ("DOI,title,author,container-title,issued,abstract,is-referenced-by-count,"
                   "volume,issue,page,type,URL,publisher,ISSN")


def _crossref_item(item: dict, source: str = "crossref") -> dict:
    record = blank_record(source)
    titles = item.get("title") or []
    record["title"] = strip_tags(titles[0]) if titles else ""
    record["abstract"] = strip_tags(item.get("abstract") or "")
    containers = item.get("container-title") or []
    record["journal"] = containers[0] if containers else ""
    issns = item.get("ISSN") or []
    if issns:
        record["issn"] = issns[0]
        if len(issns) > 1:
            record["eissn"] = issns[1]
    record["publisher"] = item.get("publisher") or ""
    record["doi"] = norm_doi(item.get("DOI") or "")
    record["citations"] = item.get("is-referenced-by-count")
    record["volume"] = item.get("volume") or ""
    record["issue"] = item.get("issue") or ""
    record["pages"] = item.get("page") or ""
    record["language"] = item.get("language") or ""
    record["url"] = item.get("URL") or ""
    record["type"] = "preprint" if item.get("type") == "posted-content" else "article"
    parts = ((item.get("issued") or {}).get("date-parts") or [[None]])[0]
    if parts and parts[0]:
        record["year"] = int(parts[0])
        record["date"] = "-".join(str(p) for p in parts if p)
    record["authors"] = [
        ("%s %s" % ((a.get("given") or "").strip(), (a.get("family") or "").strip())).strip()
        or (a.get("name") or "")
        for a in (item.get("author") or [])
    ]
    return record


def search_crossref(http, cfg, query, limit, sort="relevance", year_from=None, year_to=None, strict=False) -> list:
    filters = []
    if year_from:
        filters.append("from-pub-date:%s-01-01" % year_from)
    if year_to:
        filters.append("until-pub-date:%s-12-31" % year_to)
    # Crossref 的 is-referenced-by-count 排序是「全库排序」，会返回与检索词无关的高被引论文。
    # 因此按被引排序时先取相关度候选，再在本地按被引排序。
    request_sort = "relevance" if sort == "cited" else {"date": "published"}.get(sort, "relevance")
    rows = max(limit, 1) * 4 if sort == "cited" else max(limit, 1)
    data = http.get_json("%s/works" % CROSSREF, {
        "query": query, "rows": rows, "sort": request_sort,
        "order": "desc" if sort == "date" else None,
        "filter": ",".join(filters) or None,
        "mailto": cfg.get("CROSSREF_MAILTO") or None,
        "select": CROSSREF_SELECT,
    }, source="crossref")
    items = ((data or {}).get("message") or {}).get("items") or []
    records = [r for r in (_crossref_item(i) for i in items) if r["title"]]
    if sort == "cited":
        records.sort(key=lambda r: r.get("citations") or 0, reverse=True)
    return records[: max(limit, 1)] if sort == "cited" else records


def crossref_by_doi(http, cfg, doi) -> dict:
    data = http.get_json("%s/works/%s" % (CROSSREF, urllib.parse.quote(norm_doi(doi), safe="")),
                         {"mailto": cfg.get("CROSSREF_MAILTO") or None}, source="crossref")
    item = (data or {}).get("message")
    return _crossref_item(item) if item else {}


ARXIV_NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


def _arxiv_record(entry) -> dict:
    record = blank_record("arxiv")
    record["title"] = strip_tags(entry.findtext("a:title", "", ARXIV_NS))
    record["abstract"] = strip_tags(entry.findtext("a:summary", "", ARXIV_NS))
    published = entry.findtext("a:published", "", ARXIV_NS)
    record["date"] = published[:10]
    record["year"] = int(published[:4]) if published[:4].isdigit() else None
    raw_id = entry.findtext("a:id", "", ARXIV_NS)
    match = re.search(r"abs/(.+?)(v\d+)?$", raw_id)
    record["arxiv"] = match.group(1) if match else raw_id
    record["doi"] = norm_doi(entry.findtext("arxiv:doi", "", ARXIV_NS))
    record["journal"] = strip_tags(entry.findtext("arxiv:journal_ref", "", ARXIV_NS))
    record["authors"] = [a.findtext("a:name", "", ARXIV_NS) for a in entry.findall("a:author", ARXIV_NS)]
    record["url"] = raw_id
    record["type"] = "preprint"
    primary = entry.find("arxiv:primary_category", ARXIV_NS)
    if primary is not None:
        record["publisher"] = primary.get("term", "")
    return record


def search_arxiv(http, cfg, query, limit, sort="relevance", year_from=None, year_to=None, strict=False) -> list:
    terms = '"%s"' % query.strip() if (" " in query.strip() and not re.search(r'[:"\[]', query)) else query
    if strict or sort == "cited":
        # arXiv 的 all: 会匹配全文，容易召回无关论文；收窄到题名与摘要。
        search_query = '(ti:%s OR abs:%s)' % (terms, terms)
    else:
        search_query = "all:%s" % terms
    payload = http.get(ARXIV, {
        "search_query": search_query, "start": 0, "max_results": max(limit, 1),
        "sortBy": {"date": "submittedDate"}.get(sort, "relevance"), "sortOrder": "descending",
    }, source="arxiv", validate=xml_complete)
    if not payload:
        return []
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        http.record_error("arxiv", "XML 解析失败：%s" % exc)
        return []
    out = []
    for entry in root.findall("a:entry", ARXIV_NS):
        record = _arxiv_record(entry)
        if year_from and (record["year"] or 0) < int(year_from):
            continue
        if year_to and (record["year"] or 9999) > int(year_to):
            continue
        if record["title"]:
            out.append(record)
    return out


def arxiv_by_id(http, cfg, arxiv_id) -> dict:
    payload = http.get(ARXIV, {"id_list": arxiv_id}, source="arxiv", validate=xml_complete)
    if not payload:
        return {}
    try:
        entry = ET.fromstring(payload).find("a:entry", ARXIV_NS)
    except ET.ParseError:
        return {}
    if entry is None:
        return {}
    record = _arxiv_record(entry)
    record["arxiv"] = arxiv_id
    return record


def search_semanticscholar(http, cfg, query, limit, sort="relevance", year_from=None, year_to=None, strict=False) -> list:
    params = {"query": query, "limit": max(limit, 1),
              "fields": "title,abstract,year,publicationDate,venue,externalIds,authors,"
                        "citationCount,openAccessPdf,url,publicationTypes"}
    if year_from or year_to:
        params["year"] = "%s-%s" % (year_from or "", year_to or "")
    headers = {"x-api-key": cfg["S2_API_KEY"]} if cfg.get("S2_API_KEY") else None
    data = http.get_json("%s/paper/search" % S2, params, source="semanticscholar", headers=headers)
    out = []
    for item in (data or {}).get("data") or []:
        record = blank_record("semanticscholar")
        record["title"] = strip_tags(item.get("title") or "")
        if not record["title"]:
            continue
        record["abstract"] = strip_tags(item.get("abstract") or "")
        record["year"] = item.get("year")
        record["date"] = item.get("publicationDate") or ""
        record["journal"] = item.get("venue") or ""
        record["citations"] = item.get("citationCount")
        ids = item.get("externalIds") or {}
        record["doi"] = norm_doi(ids.get("DOI") or "")
        record["pmid"] = ids.get("PubMed") or ""
        record["arxiv"] = ids.get("ArXiv") or ""
        record["authors"] = [a.get("name", "") for a in (item.get("authors") or [])]
        record["url"] = item.get("url") or ""
        record["oa"] = bool(item.get("openAccessPdf"))
        record["type"] = "review" if "Review" in (item.get("publicationTypes") or []) else "article"
        out.append(record)
    return out


def _parse_scholar(page: str) -> list:
    out = []
    blocks = re.findall(r'<div class="gs_ri">(.*?)(?=<div class="gs_ri">|\Z)', page, re.S)
    for block in blocks:
        title_match = re.search(r'<h3 class="gs_rt"[^>]*>(.*?)</h3>', block, re.S)
        if not title_match:
            continue
        raw_title = title_match.group(1)
        record = blank_record("scholar")
        link_match = re.search(r'href="([^"]+)"', raw_title)
        record["url"] = html.unescape(link_match.group(1)) if link_match else ""
        record["title"] = strip_tags(re.sub(r'<span class="gs_ctu".*?</span>', " ", raw_title, flags=re.S))
        meta_match = re.search(r'<div class="gs_a">(.*?)</div>', block, re.S)
        if meta_match:
            meta = strip_tags(meta_match.group(1))
            parts = [p.strip() for p in meta.split("-")]
            record["authors"] = [a.strip() for a in parts[0].split(",") if a.strip()]
            if len(parts) > 1:
                record["journal"] = parts[1].strip()
            record["year"] = guess_year(meta)
            record["_meta"] = meta
        snippet = re.search(r'<div class="gs_rs">(.*?)</div>', block, re.S)
        record["abstract"] = strip_tags(snippet.group(1)) if snippet else ""
        cited = re.search(r"Cited by (\d+)", block)
        if cited:
            record["citations"] = int(cited.group(1))
        if record["title"]:
            out.append(record)
    return out


def search_scholar(http, cfg, query, limit, sort="relevance", year_from=None, year_to=None, strict=False) -> list:
    params = {"q": query, "hl": "en", "num": 20}
    if year_from:
        params["as_ylo"] = year_from
    if year_to:
        params["as_yhi"] = year_to
    if sort == "date":
        params["scisbd"] = 1
    collected, start = [], 0
    while len(collected) < limit and start <= 40:
        params["start"] = start
        payload = http.get(SCHOLAR, params, source="scholar", use_cache=(start == 0))
        if not payload:
            break
        page = payload.decode("utf-8", "ignore")
        if re.search(r"not a robot|unusual traffic|/sorry/", page, re.I):
            http.record_error("scholar", "触发人机验证：请改用浏览器方式（见 references/scholar-and-browser.md）")
            break
        batch = _parse_scholar(page)
        if not batch:
            break
        collected.extend(batch)
        if len(batch) < 10:
            break
        start += 10
    for record in collected:
        record.pop("_meta", None)
    return collected[:limit]


SOURCE_FUNCS = {
    "pubmed": search_pubmed,
    "europepmc": search_europepmc,
    "openalex": search_openalex,
    "crossref": search_crossref,
    "arxiv": search_arxiv,
    "semanticscholar": search_semanticscholar,
    "scholar": search_scholar,
}


# --------------------------------------------------------------------------
# 去重与排序
# --------------------------------------------------------------------------

STOPWORDS = {"the", "and", "for", "with", "from", "into", "that", "this", "are", "was",
             "were", "been", "using", "based", "between", "among", "during", "study",
             "review", "analysis", "approach", "method", "methods", "effect", "effects"}


def query_tokens(query: str) -> list:
    """取出检索词里的实义词，用于本地相关性闸门。"""
    words = re.findall(r"[A-Za-z][A-Za-z\-]{3,}", (query or "").lower())
    return [w for w in words if w not in STOPWORDS and w not in ("tiab", "title", "abstract")]


def passes_query(record: dict, tokens: list, threshold: float = 0.6) -> bool:
    """本地相关性闸门。

    各库的匹配策略不同（Crossref 是 OR 式部分匹配、arXiv 的 all: 命中全文、
    OpenAlex 默认匹配全文），严格模式下用一个统一的题名/摘要闸门过滤擦边结果。
    """
    if not tokens:
        return True
    haystack = " ".join([record.get("title") or "", record.get("abstract") or ""]).lower()
    if not haystack.strip():
        return True  # 没有题名摘要可比对时不做判断，避免误杀
    hits = sum(1 for token in tokens if token in haystack)
    need = max(1, int(len(tokens) * threshold + 0.999))
    return hits >= need


def merge_records(records: list) -> list:
    """DOI → PMID → 标题 三级归并，并做标题级二次合并。"""
    buckets, order = {}, []
    for record in records:
        doi = norm_doi(record.get("doi"))
        if doi:
            key = ("doi", doi)
        elif record.get("pmid"):
            key = ("pmid", record["pmid"])
        else:
            key = ("title", norm_title(record.get("title")))
        if key not in buckets:
            buckets[key] = dict(record)
            order.append(key)
            continue
        kept = buckets[key]
        for source in record.get("sources", []):
            if source not in kept["sources"]:
                kept["sources"].append(source)
        for field in ("doi", "pmid", "pmcid", "arxiv", "journal", "date", "volume",
                      "issue", "pages", "publisher", "language", "url", "type"):
            if not kept.get(field) and record.get(field):
                kept[field] = record[field]
        if len(record.get("abstract") or "") > len(kept.get("abstract") or ""):
            kept["abstract"] = record["abstract"]
        if len(record.get("authors") or []) > len(kept.get("authors") or []):
            kept["authors"] = record["authors"]
        if kept.get("year") is None and record.get("year"):
            kept["year"] = record["year"]
        counts = [c for c in (kept.get("citations"), record.get("citations")) if isinstance(c, int)]
        if counts:
            kept["citations"] = max(counts)
        if record.get("oa"):
            kept["oa"] = True

    final, by_title = [], {}
    for record in (buckets[k] for k in order):
        key = norm_title(record.get("title"))
        if key and key in by_title:
            target = by_title[key]
            for source in record.get("sources", []):
                if source not in target["sources"]:
                    target["sources"].append(source)
            counts = [c for c in (target.get("citations"), record.get("citations")) if isinstance(c, int)]
            if counts:
                target["citations"] = max(counts)
            if not target.get("doi") and record.get("doi"):
                target["doi"] = record["doi"]
            if len(record.get("abstract") or "") > len(target.get("abstract") or ""):
                target["abstract"] = record["abstract"]
            continue
        by_title[key] = record
        final.append(record)
    return final


def rank_records(records: list, mode: str = "relevance") -> list:
    if mode == "cited":
        return sorted(records, key=lambda r: (-(r.get("citations") or 0), -(year_of(r) or 0)))
    if mode == "date":
        return sorted(records, key=lambda r: (r.get("date") or "", year_of(r) or 0), reverse=True)
    buckets = {}
    for record in records:
        buckets.setdefault(record.get("source", "?"), []).append(record)
    ranked = []
    while any(buckets.values()):
        for source in list(buckets.keys()):
            if buckets[source]:
                ranked.append(buckets[source].pop(0))
    return ranked


# --------------------------------------------------------------------------
# 导出
# --------------------------------------------------------------------------

RIS_TYPE = {"article": "JOUR", "review": "JOUR", "preprint": "UNPB", "conference": "CPAPER", "book": "BOOK"}
BIB_TYPE = {"article": "article", "review": "article", "preprint": "misc", "conference": "inproceedings", "book": "book"}


def to_ris(records: list) -> str:
    chunks = []
    for record in records:
        lines = ["TY  - %s" % RIS_TYPE.get(record.get("type", "article"), "JOUR")]
        lines += ["AU  - %s" % a for a in record.get("authors") or []]
        lines.append("TI  - %s" % record.get("title", ""))
        if record.get("journal"):
            lines.append("JO  - %s" % record["journal"])
        if record.get("abstract"):
            lines.append("AB  - %s" % record["abstract"])
        lines.append("PY  - %s" % (record.get("year") or record.get("date") or ""))
        if record.get("date"):
            lines.append("DA  - %s" % record["date"])
        if record.get("volume"):
            lines.append("VL  - %s" % record["volume"])
        if record.get("issue"):
            lines.append("IS  - %s" % record["issue"])
        pages = record.get("pages") or ""
        if pages:
            if "-" in pages:
                start, _, end = pages.partition("-")
                lines += ["SP  - %s" % start.strip(), "EP  - %s" % end.strip()]
            else:
                lines.append("SP  - %s" % pages)
        if record.get("doi"):
            lines.append("DO  - %s" % record["doi"])
        if record.get("pmid"):
            lines.append("AN  - %s" % record["pmid"])
        if record.get("url"):
            lines.append("UR  - %s" % record["url"])
        if record.get("publisher"):
            lines.append("PB  - %s" % record["publisher"])
        if record.get("language"):
            lines.append("LA  - %s" % record["language"])
        lines.append("ER  - ")
        chunks.append("\n".join(lines))
    return "\n\n".join(chunks) + "\n"


def to_bibtex(records: list) -> str:
    used, chunks = {}, []
    for record in records:
        family = first_author_family(record)
        year = record.get("year") or "nd"
        word = ""
        for token in re.split(r"\W+", record.get("title", "")):
            if len(token) > 3:
                word = token.lower()
                break
        base = "%s%s%s" % (family, year, word)
        count = used.get(base, 0) + 1
        used[base] = count
        key = base if count == 1 else "%s%s" % (base, chr(96 + count))
        fields = [
            ("title", record.get("title", "")),
            ("author", " and ".join(record.get("authors") or [])),
            ("journal", record.get("journal", "")),
            ("year", str(record.get("year") or "")),
            ("volume", record.get("volume", "")),
            ("number", record.get("issue", "")),
            ("pages", record.get("pages", "")),
            ("doi", record.get("doi", "")),
            ("url", record.get("url", "")),
            ("abstract", truncate(record.get("abstract", ""), 600)),
        ]
        body = ",\n".join("  %s = {%s}" % (name, str(value).replace("{", "(").replace("}", ")"))
                          for name, value in fields if value)
        chunks.append("@%s{%s,\n%s\n}" % (BIB_TYPE.get(record.get("type", "article"), "article"), key, body))
    return "\n\n".join(chunks) + "\n"


def to_csv(records: list) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["#", "Title", "Authors", "Journal", "Year", "Citations", "DOI",
                     "PMID", "PMCID", "OA", "Type", "Sources", "URL"])
    for index, record in enumerate(records, 1):
        writer.writerow([
            index, record.get("title", ""), "; ".join(record.get("authors") or []),
            record.get("journal", ""), record.get("year") or "",
            record.get("citations") if record.get("citations") is not None else "",
            record.get("doi", ""), record.get("pmid", ""), record.get("pmcid", ""),
            "Y" if record.get("oa") else ("N" if record.get("oa") is False else ""),
            record.get("type", ""), "+".join(record.get("sources") or []), record.get("url", ""),
        ])
    return buffer.getvalue()


def to_markdown_table(records: list, start_index: int = 1) -> str:
    lines = ["| # | 题目 | 作者 | 期刊 | 年份 | 被引 | DOI | 来源 |",
             "|---|------|------|------|------|------|-----|------|"]
    for index, record in enumerate(records, start_index):
        authors = record.get("authors") or []
        author_text = ", ".join(authors[:3]) + (" et al." if len(authors) > 3 else "")
        doi = record.get("doi", "")
        cell = "[%s](https://doi.org/%s)" % (doi, doi) if doi else "-"
        cites = record.get("citations")
        lines.append("| %d | %s | %s | %s | %s | %s | %s | %s |" % (
            index,
            truncate(record.get("title", "").replace("|", "\\|"), 120),
            truncate(author_text.replace("|", "\\|"), 60),
            truncate(record.get("journal", "").replace("|", "\\|"), 40),
            record.get("year") or "-",
            cites if cites is not None else "-",
            cell,
            "+".join(record.get("sources") or []),
        ))
    return "\n".join(lines)


def render_records(records: list, fmt: str) -> str:
    fmt = (fmt or "md").lower()
    if fmt in ("md", "table", "markdown"):
        return to_markdown_table(records)
    if fmt == "csv":
        return to_csv(records)
    if fmt == "ris":
        return to_ris(records)
    if fmt in ("bib", "bibtex"):
        return to_bibtex(records)
    if fmt == "json":
        return json.dumps(records, ensure_ascii=False, indent=2)
    raise SystemExit("未知输出格式：%s（可用：md/csv/ris/bib/json）" % fmt)


# --------------------------------------------------------------------------
# 期刊指标（中科院分区 / JCR 分区 / 影响因子）与文件命名
# --------------------------------------------------------------------------

JOURNAL_DB = os.path.join(SKILL_DIR, "data", "journals.db")


def journal_name_key(name: str) -> str:
    """与 build_journal_index.py 保持一致的期刊名归一化。"""
    text = (name or "").upper().replace("&", " AND ")
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"[^A-Z0-9\u4e00-\u9fff]+", " ", text)
    text = re.sub(r"\b(THE|JOURNAL|INT J|INTL)\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def journal_metrics(issn: str = "", eissn: str = "", name: str = "") -> dict:
    """查询中科院分区、JCR 分区与影响因子。

    优先用 ISSN/EISSN 精确匹配，再退回期刊名。数据来自本地 data/journals.db
    （由 build_journal_index.py 从公开镜像数据构建）。
    """
    if not os.path.exists(JOURNAL_DB):
        return {}
    conn = sqlite3.connect(JOURNAL_DB)
    conn.row_factory = sqlite3.Row
    row = None
    try:
        for field, value in (("issn", issn), ("eissn", eissn)):
            value = (value or "").strip()
            if not value:
                continue
            row = conn.execute("SELECT * FROM journals WHERE %s=? LIMIT 1" % field, (value,)).fetchone()
            if row:
                break
        if row is None and name:
            key = journal_name_key(name)
            row = conn.execute("SELECT * FROM journals WHERE name_key=? LIMIT 1", (key,)).fetchone()
            if row is None and len(key) > 8:
                row = conn.execute("SELECT * FROM journals WHERE name_key LIKE ? LIMIT 1",
                                   (key[: max(8, len(key) // 2)] + "%",)).fetchone()
    finally:
        conn.close()
    if row is None:
        return {}
    return {
        "journal_full": row["name"],
        "cas_zone": row["cas_zone"],
        "cas_top": bool(row["cas_top"]),
        "cas_category": row["cas_category"] or "",
        "jcr_quartile": row["jcr_quartile"],
        "impact_factor": row["impact_factor"],
        "jcr_year": row["jcr_year"] or "",
        "cas_year": row["cas_year"] or "",
        "wos": row["wos"] or "",
    }


def format_if(value) -> str:
    if value is None:
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    return str(int(round(number))) if abs(number - round(number)) < 0.05 else "%.1f" % number


INVALID_FILENAME = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def safe_filename(text: str, limit: int = 180) -> str:
    """清掉文件系统非法字符，并按字节长度截断（中文按 UTF-8 计 3 字节）。"""
    text = INVALID_FILENAME.sub(" ", text or "")
    text = re.sub(r"\s+", " ", text).strip().strip(".")
    if not text:
        return "untitled"
    data = text.encode("utf-8")
    if len(data) <= limit:
        return text
    cut = data[:limit].decode("utf-8", "ignore").rstrip()
    return cut or "untitled"


def build_pdf_name(record: dict, metrics: dict, template: str = "", with_year: bool = False) -> str:
    """按「中科院分区+JCR分区-影响因子 标题」生成文件名（不含扩展名）。

    默认效果：C1Q1-18.1 Time-staggered chemo-immunotherapy via engineered nanofiber …
    指标缺失时相应片段自动省略，不会留下空占位。
    """
    cas = metrics.get("cas_zone")
    jcr = metrics.get("jcr_quartile")
    impact = format_if(metrics.get("impact_factor"))
    title = safe_filename(record.get("title") or "", limit=170)
    if with_year and record.get("year"):
        title = "(%s) %s" % (record["year"], title)
    if template:
        return safe_filename(template.format(
            cas=cas or "", jcr=jcr or "", **{"if": impact},
            title=record.get("title") or "", journal=record.get("journal") or "",
            year=record.get("year") or "", doi=record.get("doi") or "",
        ))
    prefix = ""
    if cas:
        prefix += "C%d" % cas
    if jcr:
        prefix += "Q%d" % jcr
    if prefix and impact:
        prefix += "-" + impact
    return safe_filename(("%s %s" % (prefix, title)).strip() if prefix else title)


# --------------------------------------------------------------------------
# 落盘：按主题归档到知识库
# --------------------------------------------------------------------------

def resolve_topic_dir(root: str, topic: str) -> str:
    """在根目录下复用（或创建）主题文件夹，避免出现「BCI」与「Brain-Computer Interface」这类重复目录。"""
    os.makedirs(root, exist_ok=True)
    wanted = re.sub(r"\s+", " ", (topic or "").strip()) or "未分类"
    key = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", wanted.lower())
    try:
        for entry in sorted(os.listdir(root)):
            path = os.path.join(root, entry)
            if not os.path.isdir(path) or entry.startswith("."):
                continue
            if re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", entry.lower()) == key:
                return path
    except OSError:
        pass
    safe = re.sub(r"[/:\\]", "-", wanted).strip(". ") or "未分类"
    path = os.path.join(root, safe)
    os.makedirs(path, exist_ok=True)
    return path


def build_readme(records: list, args, kind: str) -> str:
    oa_count = sum(1 for r in records if r.get("oa"))
    with_doi = sum(1 for r in records if r.get("doi"))
    lines = [
        "# %s：检索结果" % (args.topic or args.query or "文献"),
        "",
        "## 一、检索设定",
        "",
        "- 检索词：`%s`" % (args.query or "-"),
        "- 数据源：%s" % ("、".join(SOURCE_LABELS.get(s, s) for s in (args.sources or [])) or "（单篇精取）"),
        "- 排序：%s" % args.sort,
        "- 年份范围：%s" % ("%s – %s" % (args.year_from or "不限", args.year_to or "不限")),
        "- 执行时间：%s" % datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z"),
        "- 命中：%d 篇（含 DOI %d 篇；有开放获取版本 %d 篇）" % (len(records), with_doi, oa_count),
        "",
        "## 二、结果清单",
        "",
        to_markdown_table(records),
        "",
        "## 三、下一步：取全文",
        "",
        "1. 看 `manifest.json` 的 `oa` 字段：`true` 表示存在开放获取版本，可直接下载。",
        "2. 中文文献、以及只有订阅才能获取的英文文献，改用 `nature-downloader` skill 走机构授权（会复用你已登录的浏览器）。",
        "3. 下载好的 PDF 放进本目录的 `PDFs/`，并把文件名回填到 `manifest.json` 的 `file` 字段。",
        "",
        "## 四、随附数据文件",
        "",
        "| 文件 | 用途 |",
        "|------|------|",
        "| `results.csv` | Excel / Numbers 打开，人工筛选、标星 |",
        "| `results.ris` | 导入 Zotero / EndNote / NoteExpress |",
        "| `results.bib` | 供 LaTeX / Obsidian 引用 |",
        "| `results.json` | 含摘要的结构化数据，供后续程序化处理 |",
        "| `manifest.json` | 本批次台账（来源、OA 状态、下载状态） |",
        "",
    ]
    return "\n".join(lines)


def save_bundle(records: list, args, http, cfg: dict, kind: str = "search") -> dict:
    root = args.root or cfg.get("SAVE_ROOT") or DEFAULT_CONFIG["SAVE_ROOT"]
    topic_dir = resolve_topic_dir(root, args.topic)
    stamp = datetime.now().strftime("%Y-%m-%d")
    slug = slugify(args.topic or args.query or "search")
    folder = os.path.join(topic_dir, "%s_%s" % (stamp, slug))
    suffix = 2
    while os.path.exists(folder):
        folder = os.path.join(topic_dir, "%s_%s_%d" % (stamp, slug, suffix))
        suffix += 1
    os.makedirs(folder, exist_ok=True)

    files = {
        "results.csv": to_csv(records),
        "results.ris": to_ris(records),
        "results.bib": to_bibtex(records),
        "results.json": json.dumps(records, ensure_ascii=False, indent=2),
        "results.md": "# %s\n\n%s\n" % (args.topic or args.query, to_markdown_table(records)),
        "00_README_%s_检索结果.md" % slug: build_readme(records, args, kind),
    }
    written = {}
    for name, content in files.items():
        path = os.path.join(folder, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        written[name] = path

    manifest = {
        "project": os.path.relpath(folder, root),
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "tool": "lky-search v%s" % VERSION,
        "kind": kind,
        "query": getattr(args, "query", None),
        "sources": args.sources,
        "sort": args.sort,
        "filters": {"year_from": getattr(args, "year_from", None), "year_to": getattr(args, "year_to", None)},
        "outputLayout": {"notes": "*.md", "pdfs": "PDFs/", "data": "results.{csv,ris,bib,json}"},
        "fullTextPolicy": "本技能只判定 OA；付费与 CNKI 全文由 nature-downloader 获取",
        "summary": {"total": len(records),
                    "with_doi": sum(1 for r in records if r.get("doi")),
                    "open_access": sum(1 for r in records if r.get("oa"))},
        "errors": http.errors,
        "results": [{
            "index": index,
            "title": record.get("title", ""),
            "authors": "; ".join(record.get("authors") or []),
            "journal": record.get("journal", ""),
            "year": record.get("year"),
            "doi": record.get("doi", ""),
            "pmid": record.get("pmid", ""),
            "pmcid": record.get("pmcid", ""),
            "arxiv": record.get("arxiv", ""),
            "citations": record.get("citations"),
            "openAccess": record.get("oa"),
            "sources": record.get("sources"),
            "url": record.get("url", ""),
            "file": None,
            "note": None,
        } for index, record in enumerate(records, 1)],
    }
    manifest_path = os.path.join(folder, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    written["manifest.json"] = manifest_path
    os.makedirs(os.path.join(folder, "PDFs"), exist_ok=True)
    return {"folder": folder, "files": written, "count": len(records)}


# --------------------------------------------------------------------------
# 单篇精取 / ID 转换 / 引文
# --------------------------------------------------------------------------

def convert_ids(http, cfg, identifiers: str) -> dict:
    params = {"ids": identifiers, "format": "json",
              "tool": cfg.get("NCBI_TOOL") or "lky-search",
              "email": cfg.get("NCBI_EMAIL") or None,
              "api_key": cfg.get("NCBI_API_KEY") or None}
    data = http.get_json(IDCONV, params, source="ncbi_idconv")
    records = (data or {}).get("records") or []
    if not records:
        return {}
    item = records[0]
    return {"requested": item.get("requested-id", ""), "status": item.get("status", "ok"),
            "pmid": item.get("pmid", ""), "pmcid": item.get("pmcid", ""),
            "doi": norm_doi(item.get("doi", ""))}


def resolve_ids(http, cfg, identifier: str) -> dict:
    """优先用 NCBI 转换；失败时用 Europe PMC 兜底（很多 DOI 还没进 PMC，NCBI 会返回 error）。"""
    ident = (identifier or "").strip()
    ids = convert_ids(http, cfg, ident)
    if ids.get("pmid") or ids.get("pmcid"):
        return ids
    query = 'DOI:"%s"' % norm_doi(ident) if re.search(r"10\.\d{4,9}/", ident) else ident
    data = http.get_json("%s/search" % EUROPEPMC,
                         {"query": query, "format": "json", "resultType": "lite", "pageSize": 1},
                         source="europepmc")
    hits = ((data or {}).get("resultList") or {}).get("result") or []
    if not hits:
        return ids or {"requested": ident, "status": "not_found", "pmid": "", "pmcid": "", "doi": ""}
    hit = hits[0]
    return {"requested": ident, "status": "resolved-via-europepmc",
            "pmid": hit.get("pmid") or "", "pmcid": hit.get("pmcid") or "",
            "doi": norm_doi(hit.get("doi") or ident)}


def oa_lookup(http, cfg, doi: str) -> dict:
    result = {"doi": norm_doi(doi), "is_oa": None, "best_url": None, "evidence": []}
    if not result["doi"]:
        return result
    email = cfg.get("NCBI_EMAIL") or cfg.get("OPENALEX_MAILTO")
    if email:
        data = http.get_json("%s/%s" % (UNPAYWALL, urllib.parse.quote(result["doi"], safe="")),
                             {"email": email}, source="unpaywall")
        if data and not data.get("error"):
            result["is_oa"] = bool(data.get("is_oa"))
            result["oa_status"] = data.get("oa_status")
            best = data.get("best_oa_location") or {}
            result["pdf_url"] = best.get("url_for_pdf") or ""
            result["best_url"] = best.get("url_for_pdf") or best.get("url")
            result["evidence"].append("Unpaywall is_oa=%s status=%s" % (data.get("is_oa"), data.get("oa_status")))
    if not result.get("pdf_url"):
        # Unpaywall 有时只给落地页（尤其是 MDPI 这类），从 OA 位置列表里再找一次 PDF 直链
        for location in (data or {}).get("oa_locations") or []:
            if location.get("url_for_pdf"):
                result["pdf_url"] = location["url_for_pdf"]
                break
    if result["is_oa"] is None or not result["best_url"]:
        data = http.get_json("%s/works/doi:%s" % (OPENALEX, urllib.parse.quote(result["doi"], safe="")),
                             {"mailto": cfg.get("OPENALEX_MAILTO") or None}, source="openalex")
        if data:
            oa = data.get("open_access") or {}
            if result["is_oa"] is None:
                result["is_oa"] = bool(oa.get("is_oa"))
            best = data.get("best_oa_location") or {}
            if not result.get("pdf_url") and best.get("pdf_url"):
                result["pdf_url"] = best["pdf_url"]
            result["best_url"] = result["best_url"] or best.get("pdf_url") or best.get("landing_page_url")
            result["evidence"].append("OpenAlex oa_status=%s" % oa.get("oa_status"))
    epmc = http.get_json("%s/search" % EUROPEPMC,
                         {"query": 'DOI:"%s"' % result["doi"], "format": "json",
                          "resultType": "lite", "pageSize": 1}, source="europepmc")
    hits = ((epmc or {}).get("resultList") or {}).get("result") or []
    if hits:
        hit = hits[0]
        result["pmid"] = hit.get("pmid") or ""
        result["pmcid"] = hit.get("pmcid") or ""
        result["evidence"].append("Europe PMC inEPMC=%s PMCID=%s" % (hit.get("inEPMC"), hit.get("pmcid") or "-"))
        if result["is_oa"] is None:
            result["is_oa"] = hit.get("isOpenAccess") == "Y"
    if not result["best_url"] and result.get("pmcid"):
        result["best_url"] = "https://www.ncbi.nlm.nih.gov/pmc/articles/%s/pdf/" % result["pmcid"]
    return result


def fetch_publication(http, cfg, identifier: str) -> dict:
    ident = (identifier or "").strip()
    lower = ident.lower()
    # arXiv 的 DOI 形式（10.48550/arXiv.xxxx.xxxxx）直接转到 arXiv 接口
    arxiv_doi = re.match(r"^10\.48550/arxiv\.(.+)$", lower)
    if arxiv_doi:
        record = arxiv_by_id(http, cfg, arxiv_doi.group(1))
        if record:
            record["doi"] = norm_doi(ident)
            return enrich(record, http, cfg)
    if re.fullmatch(r"\d{6,9}", ident):
        records = fetch_pubmed_ids(http, cfg, [ident])
        if records:
            return enrich(records[0], http, cfg)
    if re.search(r"10\.\d{4,9}/\S+", lower):
        record = crossref_by_doi(http, cfg, ident)
        if record:
            return enrich(record, http, cfg)
    if re.match(r"^(arxiv:)?\d{4}\.\d{4,5}(v\d+)?$", lower):
        record = arxiv_by_id(http, cfg, lower.replace("arxiv:", ""))
        if record:
            return enrich(record, http, cfg)
    pmcid = re.fullmatch(r"(pmc)?(\d{6,9})", lower)
    if pmcid and lower.startswith("pmc"):
        ids = convert_ids(http, cfg, ident)
        if ids.get("pmid"):
            records = fetch_pubmed_ids(http, cfg, [ids["pmid"]])
            if records:
                return enrich(records[0], http, cfg)
    # 兜底：Europe PMC 全文检索
    data = http.get_json("%s/search" % EUROPEPMC,
                         {"query": ident, "format": "json", "resultType": "core", "pageSize": 1},
                         source="europepmc")
    hits = ((data or {}).get("resultList") or {}).get("result") or []
    if hits:
        return enrich(search_europepmc(http, cfg, ident, 1)[0], http, cfg)
    return {}


def enrich(record: dict, http, cfg) -> dict:
    """补齐 DOI/PMID/PMCID 与 OA 状态，让单篇记录信息尽量完整。"""
    if not record:
        return record
    if record.get("doi") and not (record.get("pmid") and record.get("pmcid")):
        ids = resolve_ids(http, cfg, record["doi"])
        record["pmid"] = record.get("pmid") or ids.get("pmid", "")
        record["pmcid"] = record.get("pmcid") or ids.get("pmcid", "")
    if not record.get("abstract") and record.get("pmid"):
        extra = fetch_pubmed_ids(http, cfg, [record["pmid"]])
        if extra:
            record["abstract"] = extra[0].get("abstract", "")
            record["journal"] = record.get("journal") or extra[0].get("journal", "")
            record["authors"] = record.get("authors") or extra[0].get("authors", [])
    if record.get("doi") and record.get("oa") is None:
        info = oa_lookup(http, cfg, record["doi"])
        record["oa"] = info.get("is_oa")
        record["oa_url"] = info.get("best_url")
        record["oa_evidence"] = info.get("evidence")
    return record


def related_articles(http, cfg, pmid: str, limit: int = 10) -> list:
    params = {"dbfrom": "pubmed", "db": "pubmed", "id": pmid, "retmode": "json", "cmd": "neighbor"}
    params.update(pubmed_params(cfg))
    data = http.get_json("%s/elink.fcgi" % EUTILS, params, source="pubmed")
    ids = []
    for linkset in (data or {}).get("linksets", []):
        for block in linkset.get("linksetdbs", []):
            if block.get("linkname") == "pubmed_pubmed":
                ids.extend(block.get("links", []))
    ids = [i for i in ids if str(i) != str(pmid)][:limit]
    return fetch_pubmed_ids(http, cfg, ids) if ids else []


def format_citation(record: dict, style: str) -> str:
    authors = record.get("authors") or []
    year = record.get("year") or "n.d."
    title = (record.get("title") or "").rstrip(".")
    journal = record.get("journal", "")
    volume, issue, pages = record.get("volume", ""), record.get("issue", ""), record.get("pages", "")
    doi = record.get("doi", "")
    style = (style or "apa").lower()
    if style in ("bibtex", "bib"):
        return to_bibtex([record]).strip()
    if style == "ris":
        return to_ris([record]).strip()
    if style in ("vancouver", "vancouver-superscript"):
        names = ", ".join(authors[:6]) + (", et al" if len(authors) > 6 else "")
        return "".join([
            "%s. " % names if names else "",
            "%s. " % title,
            "%s. " % journal if journal else "",
            "%s" % year,
            ";%s" % volume if volume else "",
            "(%s)" % issue if issue else "",
            ":%s" % pages if pages else "",
            ". doi:%s" % doi if doi else ".",
        ])
    if not authors:
        names = "(无作者信息)"
    elif len(authors) == 1:
        names = authors[0]
    elif len(authors) <= 20:
        names = ", ".join(authors[:-1]) + ", & " + authors[-1]
    else:
        names = ", ".join(authors[:19]) + ", ... " + authors[-1]
    parts = ["%s (%s). %s." % (names, year, title)]
    if journal:
        parts.append(" *%s*" % journal + (", *%s*" % volume if volume else "")
                     + ("(%s)" % issue if issue else "") + (", %s" % pages if pages else "") + ".")
    if doi:
        parts.append(" https://doi.org/%s" % doi)
    return "".join(parts).strip()


# --------------------------------------------------------------------------
# 命令实现
# --------------------------------------------------------------------------

def cmd_doctor(args, cfg: dict) -> int:
    print("lky-search v%s 自检" % VERSION)
    print("-" * 56)
    key = cfg.get("NCBI_API_KEY") or ""
    print("配置文件      : %s%s" % (CONFIG_PATH, "" if os.path.exists(CONFIG_PATH) else "（缺失）"))
    print("NCBI 密钥     : %s" % (("已配置 %s…%s" % (key[:6], key[-4:])) if key else "未配置"))
    print("联系邮箱      : %s" % (cfg.get("NCBI_EMAIL") or "未配置（礼貌池速率较低）"))
    print("S2 密钥       : %s" % ("已配置" if cfg.get("S2_API_KEY") else "未配置（限速，易触发 429）"))
    print("归档根目录    : %s" % (cfg.get("SAVE_ROOT") or ""))
    print("-" * 56)
    http = Http(cfg, use_cache=False)
    checks = []

    probe = http.get_json("%s/einfo.fcgi" % EUTILS, dict({"db": "pubmed", "retmode": "json"}, **pubmed_params(cfg)),
                          source="pubmed", retries=1)
    if probe is None:
        checks.append(("PubMed", "不可用（请求失败）"))
    elif isinstance(probe, dict) and probe.get("error"):
        checks.append(("PubMed", "密钥无效：NCBI 返回 %s" % probe.get("error")))
    else:
        checks.append(("PubMed", "可用（密钥生效 → 10 次/秒）" if key else "可用（无密钥 → 3 次/秒）"))

    simple = [
        ("Europe PMC", lambda: http.get_json("%s/search" % EUROPEPMC,
                                             {"query": "CRISPR", "format": "json", "pageSize": 1},
                                             source="europepmc", retries=1)),
        ("OpenAlex", lambda: http.get_json("%s/works" % OPENALEX,
                                           {"search": "CRISPR", "per-page": 1,
                                            "mailto": cfg.get("OPENALEX_MAILTO") or None},
                                           source="openalex", retries=1)),
        ("Crossref", lambda: http.get_json("%s/works" % CROSSREF,
                                           {"query": "CRISPR", "rows": 1,
                                            "mailto": cfg.get("CROSSREF_MAILTO") or None},
                                           source="crossref", retries=1)),
        ("arXiv", lambda: http.get(ARXIV, {"search_query": "all:CRISPR", "max_results": 1},
                                   source="arxiv", retries=1, validate=xml_complete)),
    ]
    for name, probe_func in simple:
        try:
            # 注意：失败时 HTTP 层返回 b"" / None，必须用真值判断，
            # 否则空响应会被误判成「可用」。
            ok = bool(probe_func())
        except Exception as exc:  # noqa: BLE001 - 自检需吞掉任何异常并如实报告
            checks.append((name, "不可用：%s" % exc))
            continue
        checks.append((name, "可用" if ok else "不可用（详见下方错误）"))

    headers = {"x-api-key": cfg["S2_API_KEY"]} if cfg.get("S2_API_KEY") else None
    s2 = http.get_json("%s/paper/search" % S2, {"query": "CRISPR", "limit": 1, "fields": "title"},
                       source="semanticscholar", headers=headers, retries=1)
    if s2:
        suffix = "（密钥生效）" if cfg.get("S2_API_KEY") else "（无密钥，限速）"
        checks.append(("Semantic Scholar", "可用" + suffix))
    elif cfg.get("S2_API_KEY"):
        checks.append(("Semantic Scholar",
                       "密钥已配置，但本次返回 429：入门配额为全局共享的 1 次/秒，高峰期会限流，稍后重试即可"))
    else:
        checks.append(("Semantic Scholar", "不可用：未配置密钥，共享池已被限流"))

    scholar = http.get(SCHOLAR, {"q": "CRISPR", "hl": "en", "num": 20},
                       source="scholar", use_cache=False, retries=1)
    if not scholar:
        checks.append(("Google Scholar", "不可用（被限流或需要代理）→ 走浏览器方式"))
    elif re.search(r"not a robot|unusual traffic|/sorry/", scholar.decode("utf-8", "ignore"), re.I):
        checks.append(("Google Scholar", "触发人机验证 → 改用浏览器方式"))
    else:
        checks.append(("Google Scholar", "可用（抓取模式，注意限速）"))

    checks.append(("Elsevier/Scopus", "未配置（无 API 密钥，跳过）"))
    for name, status in checks:
        print("%-17s %s" % (name, status))
    print("-" * 56)
    if http.errors:
        print("本次请求错误：")
        for item in http.errors:
            print("  - %s: %s" % (item["source"], item["error"]))
    return 0


SOURCE_ALIAS = {"pm": "pubmed", "pubmed": "pubmed",
                "epmc": "europepmc", "pmc": "europepmc", "europepmc": "europepmc",
                "oa": "openalex", "openalex": "openalex", "cr": "crossref", "crossref": "crossref",
                "arxiv": "arxiv", "s2": "semanticscholar", "semanticscholar": "semanticscholar",
                "gs": "scholar", "scholar": "scholar"}


def select_sources(raw) -> list:
    if not raw or raw == "all" or (isinstance(raw, list) and "all" in raw):
        return list(DEFAULT_SOURCES)
    items = raw.split(",") if isinstance(raw, str) else raw
    resolved = []
    for item in items:
        name = SOURCE_ALIAS.get(str(item).strip().lower())
        if not name:
            raise SystemExit("未知数据源：%s\n可选：%s" % (item, ", ".join(ALL_SOURCES)))
        if name not in resolved:
            resolved.append(name)
    return resolved


def run_search(cfg, query, sources, limit, sort, year_from=None, year_to=None, verbose=False, strict=False):
    http = Http(cfg, verbose=verbose)
    per_source = max(limit, 5)
    collected = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(5, max(1, len(sources)))) as pool:
        futures = {pool.submit(SOURCE_FUNCS[s], http, cfg, query, per_source, sort, year_from, year_to,
                               strict=strict): s
                   for s in sources}
        for future in concurrent.futures.as_completed(futures):
            source = futures[future]
            try:
                collected.extend(future.result() or [])
            except Exception as exc:  # noqa: BLE001 - 单源失败不影响整体
                http.record_error(source, "执行失败：%s" % exc)
    if strict or sort == "cited":
        tokens = query_tokens(query)
        before = len(collected)
        collected = [r for r in collected if passes_query(r, tokens)]
        http.filtered = before - len(collected)
    merged = rank_records(merge_records(collected), sort)[:limit]
    for record in merged:
        record.pop("_meta", None)
    return merged, http


def cmd_search(args, cfg: dict) -> int:
    if str(args.source).strip().lower() in ("", "all"):
        # 配置了 Semantic Scholar 密钥时纳入默认源：它并行请求，不拖慢整体，
        # 但能补上引用数与开放获取 PDF 链接。
        sources = list(DEFAULT_SOURCES) + (["semanticscholar"] if cfg.get("S2_API_KEY") else [])
    else:
        sources = select_sources(args.source)
    args.sources = sources
    records, http = run_search(cfg, args.query, sources, args.limit, args.sort,
                               args.year_from, args.year_to, verbose=args.verbose, strict=args.strict)
    if not records:
        print("没有命中结果。建议：放宽关键词、去掉年份限制，或加上 --source scholar 扩大覆盖面。", file=sys.stderr)
        return 2
    if args.format:
        sys.stdout.write(render_records(records, args.format))
    else:
        print(to_markdown_table(records))
        if args.abstracts:
            print("\n## 摘要\n")
            for index, record in enumerate(records, 1):
                print("### %d. %s\n" % (index, record.get("title", "")))
                print("- 出处：%s %s" % (record.get("journal") or "-", record.get("year") or ""))
                print("- DOI：%s" % (record.get("doi") or "-"))
                print("- 摘要：%s\n" % (record.get("abstract") or "（该源未提供摘要）"))
    if args.save:
        info = save_bundle(records, args, http, cfg)
        print("\n已归档：%s（%d 篇）" % (info["folder"], info["count"]), file=sys.stderr)
    if getattr(http, "filtered", 0):
        print("[信息] 严格模式按题名/摘要闸门过滤掉 %d 条擦边结果。" % http.filtered, file=sys.stderr)
    if http.errors and not args.verbose:
        for item in http.errors:
            print("[警告] %s: %s" % (item["source"], item["error"]), file=sys.stderr)
    return 0


def cmd_fetch(args, cfg: dict) -> int:
    http = Http(cfg, verbose=args.verbose)
    record = fetch_publication(http, cfg, args.id)
    if not record:
        print("未找到该文献：%s" % args.id, file=sys.stderr)
        return 2
    if args.format and args.format != "md":
        sys.stdout.write(render_records([record], args.format))
    else:
        print("# %s\n" % record.get("title", ""))
        print("- 作者：%s" % (", ".join(record.get("authors") or []) or "-"))
        print("- 出处：%s %s" % (record.get("journal") or "-", record.get("year") or ""))
        print("- DOI：%s" % (record.get("doi") or "-"))
        print("- PMID：%s" % (record.get("pmid") or "-"))
        print("- PMCID：%s" % (record.get("pmcid") or "-"))
        print("- arXiv：%s" % (record.get("arxiv") or "-"))
        print("- 被引：%s" % (record.get("citations") if record.get("citations") is not None else "-"))
        print("- 开放获取：%s" % ("是" if record.get("oa") else ("否" if record.get("oa") is False else "未知")))
        print("- 链接：%s" % (record.get("url") or "-"))
        print("\n## 摘要\n\n%s" % (record.get("abstract") or "（该源未提供摘要）"))
    if args.cite:
        print("\n## 引文（%s）\n\n%s" % (args.cite, format_citation(record, args.cite)))
    if args.save:
        info = save_bundle([record], args, http, cfg, kind="fetch")
        print("\n已归档：%s" % info["folder"], file=sys.stderr)
    return 0


def cmd_ids(args, cfg: dict) -> int:
    print(json.dumps(resolve_ids(Http(cfg), cfg, args.id), ensure_ascii=False, indent=2))
    return 0


def cmd_cite(args, cfg: dict) -> int:
    record = fetch_publication(Http(cfg), cfg, args.id)
    if not record:
        print("未找到该文献：%s" % args.id, file=sys.stderr)
        return 2
    for style in args.style:
        print("--- %s ---" % style.upper())
        print(format_citation(record, style))
        print()
    return 0


def cmd_related(args, cfg: dict) -> int:
    http = Http(cfg)
    pmid = args.pmid
    if not pmid and args.id:
        pmid = resolve_ids(http, cfg, args.id).get("pmid", "")
    if not pmid:
        print("需要一个 PMID，或能解析出 PMID 的标识符（DOI / PMCID）。", file=sys.stderr)
        return 2
    records = related_articles(http, cfg, pmid, args.limit)
    if not records:
        print("没有找到相关文章。", file=sys.stderr)
        return 2
    print(to_markdown_table(records))
    if args.save:
        args.query = args.query or "related:%s" % pmid
        args.topic = args.topic or "相关文献"
        info = save_bundle(records, args, http, cfg, kind="related")
        print("\n已归档：%s" % info["folder"], file=sys.stderr)
    return 0


def pdf_like(payload: bytes) -> bool:
    """确认拿到的是 PDF 而不是登录页/摘要页。"""
    return bool(payload) and payload.lstrip()[:5] == b"%PDF-"


def discover_pdf_url(http, page_url: str) -> str:
    """从文章落地页里读 citation_pdf_url（出版社通用的标准 meta 标签）。"""
    if not page_url:
        return ""
    payload = http.get(page_url, source="pdf", use_cache=True, retries=1,
                       headers={"Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"})
    if not payload:
        return ""
    text = payload.decode("utf-8", "ignore")
    for pattern in (
        r'<meta[^>]+name=["\']citation_pdf_url["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']citation_pdf_url["\']',
    ):
        match = re.search(pattern, text, re.I)
        if match:
            return html.unescape(match.group(1)).strip()
    return ""


def oa_pdf_url(http, cfg, record: dict) -> tuple:
    """兼容旧接口：返回第一个候选与说明。"""
    candidates, reason = oa_pdf_candidates(http, cfg, record)
    if candidates:
        return candidates[0]["url"], candidates[0]["label"]
    return "", reason


def oa_pdf_candidates(http, cfg, record: dict) -> tuple:
    """列出可以尝试的开放获取 PDF 地址（按成功率排序），不做下载。

    返回 (candidates, reason)：candidates 是 [{"url","label","browser"}]，
    browser=True 表示该地址通常需要真实浏览器才能取到（PMC/Europe PMC/MDPI 等）。
    """
    candidates, seen = [], set()

    def add(url, label, browser=False):
        if url and url not in seen:
            seen.add(url)
            candidates.append({"url": url, "label": label, "browser": browser})

    info = {}
    for candidate in publisher_pdf_candidates(record):
        add(candidate["url"], candidate["label"], browser=candidate.get("browser", False))
    if record.get("doi"):
        info = oa_lookup(http, cfg, record["doi"])
        if info.get("pdf_url"):
            add(info["pdf_url"], "开放获取直链：" + "；".join(info.get("evidence") or [])[:90])
    pmcid = (record.get("pmcid") or "").strip() or (info.get("pmcid") or "").strip()
    if pmcid:
        add("https://europepmc.org/articles/%s?pdf=render" % pmcid, "Europe PMC", browser=True)
        add("https://www.ncbi.nlm.nih.gov/pmc/articles/%s/pdf/" % pmcid, "PubMed Central", browser=True)
    if record.get("doi"):
        if info.get("best_url"):
            add(info["best_url"], "开放获取页面：" + "；".join(info.get("evidence") or [])[:90],
                browser=True)
            # 落地页往往带 citation_pdf_url，下载阶段会再解析一次
            candidates[-1]["resolve"] = True
        if info.get("is_oa") is False and not pmcid and not candidates:
            return [], "无开放获取版本（需机构订阅）"
    if not candidates:
        return [], "未找到开放获取入口（需机构订阅）"
    return candidates, ""


def publisher_pdf_candidates(record: dict) -> list:
    """按出版社规律直接推导 PDF 地址。

    有些出版社的落地页会被 WAF 拦掉（MDPI 就是典型），但它们自己的 CDN 可以直接访问。
    这些规律由实测得出，取不到时后面的候选会自动接管。
    """
    out = []
    doi = norm_doi(record.get("doi") or "")
    if not doi:
        return out
    if doi.startswith("10.3390/"):  # MDPI
        match = re.match(r"^([a-z]+)\d+$", doi.split("/", 1)[1])
        volume = str(record.get("volume") or "").strip()
        article = str(record.get("pages") or "").strip()
        if match and volume and article.isdigit():
            code = match.group(1)
            base = "%s-%s-%05d" % (code, volume, int(article))
            out.append({
                "url": "https://mdpi-res.com/d_attachment/%s/%s/article_deploy/%s.pdf" % (code, base, base),
                "label": "MDPI CDN",
            })
    return out


def download_pdf(http, url: str, folder: str, filename: str, overwrite: bool = False) -> dict:
    """下载并落盘；校验必须是真 PDF。"""
    payload = http.get(url, source="pdf", use_cache=False, retries=2, timeout=180,
                       validate=pdf_like,
                       headers={"Accept": "application/pdf,application/octet-stream,*/*;q=0.8"})
    if not pdf_like(payload):
        return {"saved": False, "reason": "返回内容不是 PDF（可能是登录页或摘要页）：%s" % truncate(url, 70)}
    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, filename + ".pdf")
    if os.path.exists(target) and not overwrite:
        if os.path.getsize(target) == len(payload):
            return {"saved": True, "path": target, "skipped": True, "size": len(payload)}
        index = 2
        while os.path.exists("%s (%d).pdf" % (os.path.join(folder, filename), index)):
            index += 1
        target = "%s (%d).pdf" % (os.path.join(folder, filename), index)
    with open(target, "wb") as handle:
        handle.write(payload)
    return {"saved": True, "path": target, "size": len(payload)}


NODE_CANDIDATES = [
    os.environ.get("LKY_NODE") or "",
    "/Applications/ChatGPT.app/Contents/Resources/cua_node/bin/node",
    "/opt/homebrew/bin/node",
    "/usr/local/bin/node",
    "/usr/bin/node",
]


def find_node() -> str:
    for candidate in NODE_CANDIDATES:
        if candidate and os.path.exists(candidate):
            return candidate
    return shutil.which("node") or ""


def browser_proxy(cfg: dict) -> str:
    """给 Chrome 用的代理地址。

    macOS 的 Chrome 不读 http_proxy 环境变量（vpnctl p 只设环境变量），
    因此这里把环境变量或配置里的代理显式传给浏览器；都没有时探测本地分流代理端口。
    """
    for key in ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY", "all_proxy", "ALL_PROXY"):
        value = (os.environ.get(key) or "").strip()
        if value:
            return value.replace("socks5h://", "socks5://")
    if cfg.get("HTTP_PROXY"):
        return cfg["HTTP_PROXY"]
    try:
        with socket.create_connection(("127.0.0.1", 7890), timeout=0.4):
            return "http://127.0.0.1:7890"
    except OSError:
        return ""


def browser_available() -> bool:
    return bool(find_node()) and os.path.exists(os.path.join(SKILL_DIR, "scripts", "browser_pdf_fetch.mjs"))


def browser_fetch_pdf(url: str, out_path: str, page_url: str = "", proxy: str = "", timeout: int = 200) -> dict:
    """调用 Chrome（无头、独立临时配置）抓取被 Cloudflare 之类拦住的开放获取 PDF。"""
    node = find_node()
    if not node:
        return {"ok": False, "reason": "未找到 node，无法使用浏览器抓取"}
    command = [node, os.path.join(SKILL_DIR, "scripts", "browser_pdf_fetch.mjs"),
               "--url", url, "--out", out_path]
    if page_url:
        command += ["--page", page_url]
    if proxy:
        command += ["--proxy", proxy]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "浏览器抓取超时"}
    output = (completed.stdout or "").strip().splitlines()
    for line in reversed(output):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                continue
    return {"ok": False, "reason": (completed.stderr or "浏览器抓取未返回结果").strip()[:200]}


def download_pdf_with_fallback(http, cfg, record: dict, url: str, folder: str, filename: str,
                               overwrite: bool, allow_browser: bool) -> dict:
    """先走直连；被拦时改用浏览器抓取。"""
    result = download_pdf(http, url, folder, filename, overwrite=overwrite)
    if result.get("saved") or not allow_browser or not browser_available():
        return result
    page_url = record.get("url") or ("https://doi.org/%s" % record["doi"] if record.get("doi") else "")
    os.makedirs(folder, exist_ok=True)
    temporary = os.path.join(folder, ".lky-tmp-download.pdf")
    outcome = browser_fetch_pdf(url, temporary, page_url=page_url, proxy=browser_proxy(cfg))
    if not outcome.get("ok"):
        return {"saved": False, "reason": "%s（浏览器抓取也未成功：%s）" % (result.get("reason", ""),
                                                                        outcome.get("reason", ""))}
    target = os.path.join(folder, filename + ".pdf")
    if os.path.exists(target) and not overwrite:
        index = 2
        while os.path.exists("%s (%d).pdf" % (os.path.join(folder, filename), index)):
            index += 1
        target = "%s (%d).pdf" % (os.path.join(folder, filename), index)
    os.replace(temporary, target)
    return {"saved": True, "path": target, "size": os.path.getsize(target),
            "viaBrowser": True, "strategy": outcome.get("strategy", "")}


def collect_identifiers(args) -> list:
    """从 --ids / --doi-file / --from-manifest 汇总待处理文献。"""
    items = []
    if getattr(args, "ids", None):
        items.extend(part.strip() for part in args.ids.split(",") if part.strip())
    if getattr(args, "doi_file", None):
        with open(args.doi_file, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line and not line.startswith("#"):
                    items.append(line)
    if getattr(args, "from_manifest", None):
        with open(args.from_manifest, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        for entry in manifest.get("results") or []:
            ident = entry.get("doi") or entry.get("pmid") or entry.get("arxiv")
            if ident:
                items.append(ident)
    seen, unique = set(), []
    for item in items:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def cmd_metrics(args, cfg: dict) -> int:
    http = Http(cfg)
    record = {}
    if args.id:
        record = fetch_publication(http, cfg, args.id)
    elif args.doi:
        record = fetch_publication(http, cfg, args.doi)
    if args.journal:
        record["journal"] = args.journal
    if args.issn:
        record["issn"] = args.issn
    if not record:
        print("需要 --id / --doi / --issn / --journal 之一。", file=sys.stderr)
        return 2
    metrics = journal_metrics(record.get("issn", ""), record.get("eissn", ""), record.get("journal", ""))
    if not metrics:
        print("未在本地指标库中找到：%s（ISSN %s）" % (record.get("journal") or "-", record.get("issn") or "-"),
              file=sys.stderr)
        return 2
    print("期刊      : %s" % metrics["journal_full"])
    print("中科院分区: %s 区%s%s" % (metrics["cas_zone"] or "?", "（Top）" if metrics["cas_top"] else "",
                                 ("（%s）" % metrics["cas_category"]) if metrics["cas_category"] else ""))
    print("JCR 分区  : Q%s%s" % (metrics["jcr_quartile"] or "?", ("（%s）" % metrics["jcr_year"]) if metrics["jcr_year"] else ""))
    print("影响因子  : %s" % (format_if(metrics["impact_factor"]) or "未知"))
    if record.get("title"):
        print("拟用文件名: %s.pdf" % build_pdf_name(record, metrics, args.name_template,
                                                   with_year=args.with_year))
    return 0


def cmd_download(args, cfg: dict) -> int:
    if not args.out:
        print("请用 --out 指定保存目录（下载位置由你决定）。", file=sys.stderr)
        return 2
    identifiers = collect_identifiers(args)
    if not identifiers:
        print("没有待下载的文献：请用 --ids、--doi-file 或 --from-manifest 指定。", file=sys.stderr)
        return 2
    folder = os.path.expanduser(args.out)
    os.makedirs(folder, exist_ok=True)
    http = Http(cfg)
    done, pending, blocked, failed, previews = [], [], [], [], []
    for ident in identifiers:
        record = fetch_publication(http, cfg, ident)
        if not record:
            failed.append({"id": ident, "title": "", "doi": "", "filename": "",
                           "reasons": ["找不到该文献的元数据（标识符可能有误）"]})
            continue
        metrics = journal_metrics(record.get("issn", ""), record.get("eissn", ""), record.get("journal", ""))
        filename = build_pdf_name(record, metrics, args.name_template, with_year=args.with_year)
        if args.dry_run:
            previews.append({"id": ident, "filename": filename + ".pdf",
                             "journal": metrics.get("journal_full") or record.get("journal", ""),
                             "cas": metrics.get("cas_zone"), "jcr": metrics.get("jcr_quartile"),
                             "impact_factor": metrics.get("impact_factor")})
            print("%s.pdf" % filename)
            continue
        candidates, reason = oa_pdf_candidates(http, cfg, record)
        if not candidates and "订阅" not in (reason or ""):
            # 有开放获取线索但没能拿到可用地址，单独归类，避免误导成「需要订阅」
            blocked.append({"id": ident, "title": record.get("title", ""), "doi": record.get("doi", ""),
                            "filename": filename + ".pdf", "reason": reason})
            print("[需浏览器] %s（%s）" % (filename, reason), file=sys.stderr)
            continue
        if not candidates:
            pending.append({"id": ident, "title": record.get("title", ""),
                            "doi": record.get("doi", ""), "filename": filename + ".pdf",
                            "reason": reason})
            print("[待机构访问] %s（%s）" % (filename, reason), file=sys.stderr)
            continue
        result, used, failure_reasons = None, "", []
        for candidate in candidates:
            attempt = download_pdf(http, candidate["url"], folder, filename, overwrite=args.overwrite)
            if not attempt.get("saved") and candidate.get("resolve"):
                # 落地页不是 PDF：读它的 citation_pdf_url 再试一次
                resolved = discover_pdf_url(http, candidate["url"])
                if resolved and resolved != candidate["url"]:
                    retry = download_pdf(http, resolved, folder, filename, overwrite=args.overwrite)
                    if retry.get("saved"):
                        retry["resolvedFrom"] = resolved
                        attempt = retry
                    else:
                        failure_reasons.append("落地页解析出的 PDF 地址也取不到：%s" % truncate(resolved, 70))
            if (not attempt.get("saved") and candidate.get("browser") and args.browser_fallback
                    and browser_available()):
                page_url = record.get("url") or (
                    "https://doi.org/%s" % record["doi"] if record.get("doi") else "")
                os.makedirs(folder, exist_ok=True)
                temporary = os.path.join(folder, ".lky-tmp-download.pdf")
                outcome = browser_fetch_pdf(candidate["url"], temporary, page_url=page_url,
                                            proxy=browser_proxy(cfg))
                if outcome.get("ok"):
                    target = os.path.join(folder, filename + ".pdf")
                    if os.path.exists(target) and not args.overwrite:
                        index = 2
                        while os.path.exists("%s (%d).pdf" % (os.path.join(folder, filename), index)):
                            index += 1
                        target = "%s (%d).pdf" % (os.path.join(folder, filename), index)
                    os.replace(temporary, target)
                    attempt = {"saved": True, "path": target, "size": os.path.getsize(target),
                               "viaBrowser": True}
                else:
                    failure_reasons.append("%s → %s" % (candidate["label"], outcome.get("reason", "失败")))
            if attempt.get("saved"):
                result, used = attempt, candidate["label"]
                break
            failure_reasons.append("%s → %s" % (candidate["label"], attempt.get("reason", "未取到 PDF")))
        if result and result.get("saved"):
            done.append({"id": ident, "path": result["path"], "size": result.get("size"),
                         "source": used, "journal": metrics.get("journal_full") or "",
                         "cas_zone": metrics.get("cas_zone"), "jcr_quartile": metrics.get("jcr_quartile"),
                         "impact_factor": metrics.get("impact_factor"),
                         "skipped": result.get("skipped", False),
                         "viaBrowser": result.get("viaBrowser", False)})
            print("已保存：%s%s" % (os.path.basename(result["path"]),
                                  "（浏览器抓取）" if result.get("viaBrowser") else ""))
        else:
            # 有开放获取入口但都被拦：这是「出版社拦截脚本」，不是「没有权限」
            blocked.append({"id": ident, "title": record.get("title", ""), "doi": record.get("doi", ""),
                            "filename": filename + ".pdf", "reasons": failure_reasons})
            print("[需浏览器] %s（%s）" % (filename, "；".join(failure_reasons)[:150]), file=sys.stderr)

    if not args.dry_run:
        log = {"generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
               "folder": folder, "nameTemplate": args.name_template or "C{cas}Q{jcr}-{if} {title}",
               "downloaded": done, "pendingInstitutionalAccess": pending,
               "openAccessButBlocked": blocked, "failed": failed}
        log_path = os.path.join(folder, "_lky-downloads.json")
        with open(log_path, "w", encoding="utf-8") as handle:
            json.dump(log, handle, ensure_ascii=False, indent=2)
        print("\n合计：下载 %d 篇；需机构订阅 %d 篇；开放获取但被出版社拦截 %d 篇；失败 %d 篇"
              % (len(done), len(pending), len(blocked), len(failed)))
        print("台账：%s" % log_path)
        if blocked:
            print("\n以下文献本身开放获取，但出版社拦截脚本下载。请在浏览器里打开链接另存到同一目录，"
                  "再用 `lky_search.py rename` 统一改名：")
            for item in blocked:
                print("  - %s  %s" % (item["doi"] or item["id"], item["title"][:60]))
        if pending:
            print("\n以下文献没有开放获取版本，请把 DOI 交给 nature-downloader skill 走机构授权下载，"
                  "下载后再用 `lky_search.py rename --dir \"%s\"` 按同一规则改名：" % folder)
            for item in pending:
                print("  - %s  %s" % (item["doi"] or item["id"], item["title"][:70]))
    return 0


def pdf_doi_hint(path: str, max_bytes: int = 400000) -> str:
    """从 PDF 原始字节里找 DOI（很多出版社把 DOI 写在未压缩的元数据区）。"""
    try:
        with open(path, "rb") as handle:
            chunk = handle.read(max_bytes)
    except OSError:
        return ""
    match = re.search(rb"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", chunk)
    if not match:
        return ""
    return norm_doi(match.group(0).decode("latin-1").rstrip(").,"))


def title_similarity(left: str, right: str) -> float:
    tokens_left = set(query_tokens(left))
    tokens_right = set(query_tokens(right))
    if not tokens_left or not tokens_right:
        return 0.0
    return len(tokens_left & tokens_right) / float(len(tokens_left | tokens_right))


def match_record_for_pdf(path: str, records: list) -> tuple:
    """把磁盘上的 PDF 对应到一条文献记录：先看 DOI，再看标题相似度。"""
    base = os.path.basename(path)
    lowered = base.lower()
    hint = pdf_doi_hint(path)
    if not hint:
        found = re.search(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", lowered)
        hint = norm_doi(found.group(0)) if found else ""
    if hint:
        for record in records:
            if norm_doi(record.get("doi") or "") == hint:
                return record, "DOI 精确匹配"
    # 出版社常把文件名写成 DOI 尾号（如 ijms26010001）或 PMID
    for record in records:
        suffix = (norm_doi(record.get("doi") or "").split("/")[-1] or "").lower()
        if len(suffix) >= 6 and suffix in lowered:
            return record, "DOI 尾号匹配"
        pmid = str(record.get("pmid") or "")
        if len(pmid) >= 7 and pmid in lowered:
            return record, "PMID 匹配"
    best, best_score = None, 0.0
    for record in records:
        score = title_similarity(base, record.get("title") or "")
        if score > best_score:
            best, best_score = record, score
    if best is not None and best_score >= 0.6:
        return best, "标题相似度 %.2f" % best_score
    return None, ""


def cmd_rename(args, cfg: dict) -> int:
    if not args.dir:
        print("请用 --dir 指定要整理 PDF 的目录。", file=sys.stderr)
        return 2
    folder = os.path.expanduser(args.dir)
    if not os.path.isdir(folder):
        print("目录不存在：%s" % folder, file=sys.stderr)
        return 2
    records = []
    http = Http(cfg)
    if args.from_manifest:
        with open(args.from_manifest, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        for entry in manifest.get("results") or []:
            ident = entry.get("doi") or entry.get("pmid") or entry.get("arxiv")
            if ident:
                record = fetch_publication(http, cfg, ident)
                if record:
                    records.append(record)
    for ident in (collect_identifiers(args) if (args.ids or args.doi_file) else []):
        record = fetch_publication(http, cfg, ident)
        if record:
            records.append(record)
    if not records:
        print("没有可用于比对的文献记录：请给 --from-manifest 或 --ids。", file=sys.stderr)
        return 2

    pdfs = sorted(f for f in os.listdir(folder) if f.lower().endswith(".pdf"))
    if not pdfs:
        print("目录里没有 PDF：%s" % folder, file=sys.stderr)
        return 2
    renamed, unmatched = [], []
    for name in pdfs:
        path = os.path.join(folder, name)
        record, how = match_record_for_pdf(path, records)
        if not record:
            unmatched.append(name)
            continue
        metrics = journal_metrics(record.get("issn", ""), record.get("eissn", ""), record.get("journal", ""))
        target_name = build_pdf_name(record, metrics, args.name_template, with_year=args.with_year) + ".pdf"
        target = os.path.join(folder, target_name)
        if os.path.abspath(target) == os.path.abspath(path):
            continue
        index = 2
        while os.path.exists(target):
            target = os.path.join(folder, "%s (%d).pdf" % (
                build_pdf_name(record, metrics, args.name_template, with_year=args.with_year), index))
            index += 1
        if args.dry_run:
            print("%s  →  %s   [%s]" % (name, os.path.basename(target), how))
            continue
        os.rename(path, target)
        renamed.append({"from": name, "to": os.path.basename(target), "matched": how})
        print("%s  →  %s" % (name, os.path.basename(target)))
    if not args.dry_run:
        print("\n共改名 %d 个，未匹配 %d 个" % (len(renamed), len(unmatched)))
        for name in unmatched:
            print("  未匹配：%s" % name)
    return 0


def cmd_oa(args, cfg: dict) -> int:
    http = Http(cfg)
    doi = args.doi or ""
    if not doi and args.id:
        record = fetch_publication(http, cfg, args.id)
        doi = (record or {}).get("doi", "")
    if not doi:
        print("无法确定 DOI：%s" % (args.doi or args.id or "-"), file=sys.stderr)
        return 2
    info = oa_lookup(http, cfg, doi)
    print(json.dumps(info, ensure_ascii=False, indent=2))
    print()
    if info.get("is_oa"):
        print("→ 存在开放获取版本，可直接下载：%s" % (info.get("best_url") or "（未给出直链，从 DOI 页面找 PDF）"))
    else:
        print("→ 无开放获取版本。中文文献或订阅内容请交给 nature-downloader skill 走机构授权。")
    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lky_search.py",
        description="LKY Search：公共学术数据库检索与抓取引擎",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
               "  python3 lky_search.py doctor\n"
               "  python3 lky_search.py search --query \"brain computer interface consciousness\" "
               "--topic \"Brain-Computer Interface\" --year-from 2023 --save\n"
               "  python3 lky_search.py fetch --id 10.1038/s41593-025-01905-6 --cite apa\n"
               "  python3 lky_search.py oa --doi 10.1038/s41593-025-01905-6\n",
    )
    parser.add_argument("--verbose", action="store_true", help="打印每个数据源的错误细节")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="自检配置与数据源连通性").set_defaults(func=cmd_doctor)

    search = sub.add_parser("search", help="多源检索")
    search.add_argument("--query", required=True, help="检索词；支持 PubMed 语法")
    search.add_argument("--source", default="all",
                        help="逗号分隔：pubmed,europepmc,openalex,crossref,arxiv,semanticscholar,scholar（默认 all=前五个）")
    search.add_argument("--limit", type=int, default=20, help="返回条数，默认 20")
    search.add_argument("--sort", default="relevance", choices=["relevance", "cited", "date"])
    search.add_argument("--strict", action="store_true",
                        help="把检索范围收窄到题名/摘要，提高精度（按被引排序时自动开启）")
    search.add_argument("--year-from", type=int, help="起始年份")
    search.add_argument("--year-to", type=int, help="截止年份")
    search.add_argument("--format", help="直接输出：md / csv / ris / bib / json")
    search.add_argument("--abstracts", action="store_true", help="Markdown 输出时附带摘要")
    search.add_argument("--save", action="store_true", help="归档到知识库（需配合 --topic）")
    search.add_argument("--topic", help="检索方向，作为知识库中的主题文件夹名")
    search.add_argument("--root", help="归档根目录，默认取配置 SAVE_ROOT")
    search.set_defaults(func=cmd_search, sources=DEFAULT_SOURCES)

    fetch = sub.add_parser("fetch", help="按 PMID / DOI / arXiv ID 精取单篇")
    fetch.add_argument("--id", required=True)
    fetch.add_argument("--format", help="输出格式：md / csv / ris / bib / json")
    fetch.add_argument("--cite", help="附带引文：apa / vancouver / bibtex / ris")
    fetch.add_argument("--save", action="store_true")
    fetch.add_argument("--topic")
    fetch.add_argument("--root")
    fetch.set_defaults(func=cmd_fetch, query=None, sources=[], sort="relevance", year_from=None, year_to=None)

    ids = sub.add_parser("ids", help="DOI ↔ PMID ↔ PMCID 互转")
    ids.add_argument("--id", required=True)
    ids.set_defaults(func=cmd_ids)

    cite = sub.add_parser("cite", help="生成引文")
    cite.add_argument("--id", required=True)
    cite.add_argument("--style", action="append", default=[], help="apa / vancouver / bibtex / ris")
    cite.set_defaults(func=cmd_cite)

    related = sub.add_parser("related", help="相关文章")
    related.add_argument("--pmid")
    related.add_argument("--id", help="或任意可解析的标识符")
    related.add_argument("--limit", type=int, default=10)
    related.add_argument("--save", action="store_true")
    related.add_argument("--topic")
    related.add_argument("--root")
    related.set_defaults(func=cmd_related, query=None, sources=[], sort="relevance",
                         year_from=None, year_to=None)

    oa = sub.add_parser("oa", help="判定开放获取可得性")
    oa.add_argument("--doi")
    oa.add_argument("--id")
    oa.set_defaults(func=cmd_oa)

    metrics = sub.add_parser("metrics", help="查询期刊的中科院分区 / JCR 分区 / 影响因子")
    metrics.add_argument("--id", help="DOI / PMID / arXiv ID")
    metrics.add_argument("--doi")
    metrics.add_argument("--issn", help="期刊 ISSN 或 EISSN")
    metrics.add_argument("--journal", help="期刊名")
    metrics.add_argument("--name-template", default="", help="自定义命名模板，如 \"C{cas}Q{jcr}-{if} {title}\"")
    metrics.add_argument("--with-year", action="store_true", help="文件名前缀带上发表年份")
    metrics.set_defaults(func=cmd_metrics)

    download = sub.add_parser("download", help="下载开放获取全文，并按分区/影响因子命名")
    download.add_argument("--ids", help="逗号分隔的 DOI / PMID / arXiv ID")
    download.add_argument("--doi-file", help="每行一个标识符的文件")
    download.add_argument("--from-manifest", help="读取检索批次的 manifest.json，批量下载其中条目")
    download.add_argument("--out", required=True, help="保存目录（由你指定）")
    download.add_argument("--name-template", default="",
                          help="命名模板，占位符：{cas} {jcr} {if} {title} {journal} {year} {doi}")
    download.add_argument("--with-year", action="store_true", help="标题前加上发表年份")
    download.add_argument("--overwrite", action="store_true", help="同名文件覆盖而不另存")
    download.add_argument("--dry-run", action="store_true", help="只预览将要生成的文件名，不下载")
    download.add_argument("--browser-fallback", action="store_true",
                          help="直连被拦时，用本机 Chrome 抓取（best-effort，无法通过 Cloudflare 人机校验）")
    download.set_defaults(func=cmd_download, query=None, sources=[], sort="relevance",
                          year_from=None, year_to=None)

    rename = sub.add_parser("rename", help="把目录里已有的 PDF 按分区/影响因子规则改名")
    rename.add_argument("--dir", required=True, help="要整理的目录")
    rename.add_argument("--from-manifest", help="用检索批次 manifest.json 里的条目做比对")
    rename.add_argument("--ids", help="逗号分隔的 DOI / PMID")
    rename.add_argument("--doi-file")
    rename.add_argument("--name-template", default="")
    rename.add_argument("--with-year", action="store_true")
    rename.add_argument("--dry-run", action="store_true", help="只预览改名结果")
    rename.set_defaults(func=cmd_rename, query=None, sources=[], sort="relevance",
                        year_from=None, year_to=None)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "cite" and not args.style:
        args.style = ["apa"]
    cfg = load_config()
    try:
        return args.func(args, cfg)
    except KeyboardInterrupt:
        print("\n已中断。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
