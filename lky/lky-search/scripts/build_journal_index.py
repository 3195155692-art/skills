#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建本地期刊指标库（供 lky-search 生成 "C1Q1-18.1 标题" 这类文件名）。

数据来源：https://github.com/hitfyd/ShowJCR 的中科院分区表升级版与 JCR 原始数据文件
（第三方整理的镜像数据，非官方接口；中科院分区表与 JCR 原始版权归各自发布方）。
本脚本只在本机建立索引供个人检索使用，数据不随技能分发。

用法：
    python3 build_journal_index.py              # 下载并重建 data/journals.db
    python3 build_journal_index.py --offline    # 用 data/raw/ 里已有的 CSV 重建
    python3 build_journal_index.py --check 10.1038/s41467-025-xxxx-x
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(SKILL_DIR, "data")
RAW_DIR = os.path.join(DATA_DIR, "raw")
DB_PATH = os.path.join(DATA_DIR, "journals.db")

REPO = "https://raw.githubusercontent.com/hitfyd/ShowJCR/master/"
FOLDER = urllib.parse.quote("中科院分区表及JCR原始数据文件") + "/"

# JCR 年份优先级：先用最新，缺项时用上一年补
JCR_FILES = ["JCR2025-UTF8.csv", "JCR2024-UTF8.csv"]
CAS_FILE = "FQBJCR2025-UTF8.csv"


def fetch(name: str, offline: bool) -> str:
    os.makedirs(RAW_DIR, exist_ok=True)
    path = os.path.join(RAW_DIR, name)
    if offline:
        if not os.path.exists(path):
            raise SystemExit("离线模式但缺少文件：%s" % path)
        return path
    url = REPO + FOLDER + urllib.parse.quote(name)
    request = urllib.request.Request(url, headers={"User-Agent": "lky-search/journal-index"})
    sys.stderr.write("下载 %s …\n" % name)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = response.read()
    except (urllib.error.URLError, OSError) as exc:
        if os.path.exists(path):
            sys.stderr.write("  下载失败（%s），改用本地已有副本\n" % exc)
            return path
        raise SystemExit("下载失败且无本地副本：%s（%s）" % (name, exc))
    with open(path, "wb") as handle:
        handle.write(payload)
    sys.stderr.write("  已保存 %s（%.1f MB）\n" % (path, len(payload) / 1048576))
    return path


def name_key(name: str) -> str:
    """期刊名归一化：大写、去标点与常见后缀，用于跨库匹配。"""
    text = (name or "").upper()
    text = text.replace("&", " AND ")
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"[^A-Z0-9\u4e00-\u9fff]+", " ", text)
    text = re.sub(r"\b(THE|JOURNAL|INT J|INTL)\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def clean_issn(value: str) -> str:
    value = (value or "").strip().upper()
    if value in ("", "N/A", "NA", "NONE"):
        return ""
    match = re.search(r"\d{4}-?\d{3}[\dX]", value)
    if not match:
        return ""
    digits = match.group(0).replace("-", "")
    return "%s-%s" % (digits[:4], digits[4:])


def to_float(value: str):
    value = (value or "").strip().replace(",", "")
    try:
        return float(value)
    except ValueError:
        return None


def quartile(value: str):
    match = re.search(r"Q([1-4])", (value or "").upper())
    return int(match.group(1)) if match else None


def cas_zone(value: str):
    match = re.match(r"\s*([1-4])\b", value or "")
    return int(match.group(1)) if match else None


def yes_no(value: str) -> int:
    return 1 if (value or "").strip() in ("是", "Yes", "Y", "TRUE", "true") else 0


def read_csv(path: str) -> list:
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_jcr(path: str, year: str) -> dict:
    """JCR：取所有学科分类里最好的分区，并记录 IF。"""
    out = {}
    for row in read_csv(path):
        name = (row.get("Journal") or "").strip()
        if not name:
            continue
        best = None
        for index in range(1, 7):
            quart = quartile(row.get("IF Quartile(%s)_%d" % (year, index)) or "")
            if quart and (best is None or quart < best):
                best = quart
        record = {
            "name": name,
            "issn": clean_issn(row.get("ISSN") or ""),
            "eissn": clean_issn(row.get("EISSN") or ""),
            "impact_factor": to_float(row.get("IF(%s)" % year) or ""),
            "jcr_quartile": best,
            "jcr_year": year,
            "wos": (row.get("Web of Science") or "").strip(),
        }
        out.setdefault(name_key(name), record)
    return out


def parse_cas(path: str) -> dict:
    out = {}
    for row in read_csv(path):
        name = (row.get("Journal") or "").strip()
        if not name:
            continue
        issn_pair = (row.get("ISSN/EISSN") or "").split("/")
        record = {
            "name": name,
            "issn": clean_issn(issn_pair[0] if issn_pair else ""),
            "eissn": clean_issn(issn_pair[1] if len(issn_pair) > 1 else ""),
            "cas_zone": cas_zone(row.get("大类分区") or ""),
            "cas_category": (row.get("大类") or "").strip(),
            "cas_top": yes_no(row.get("Top") or ""),
            "cas_review": yes_no(row.get("Review") or ""),
            "cas_year": (row.get("年份") or "").strip(),
        }
        out.setdefault(name_key(name), record)
    return out


def build_db(cas: dict, jcr_years: list) -> tuple:
    """把中科院分区与 JCR 合并成一张表，按名字对齐，再用 ISSN 兜底补齐。"""
    merged = {}
    for key, record in cas.items():
        merged[key] = dict(record)
    for jcr in jcr_years:  # 由新到旧，缺项才补
        for key, record in jcr.items():
            target = merged.setdefault(key, {"name": record["name"]})
            if not target.get("impact_factor") and record.get("impact_factor") is not None:
                target["impact_factor"] = record["impact_factor"]
                target["jcr_year"] = record["jcr_year"]
            if not target.get("jcr_quartile") and record.get("jcr_quartile"):
                target["jcr_quartile"] = record["jcr_quartile"]
            for field in ("issn", "eissn", "wos"):
                if not target.get(field) and record.get(field):
                    target[field] = record[field]

    # 名字对不上但 ISSN 相同的，按 ISSN 让中科院分区落到 JCR 记录上
    by_issn = {}
    for record in list(merged.values()):
        for field in ("issn", "eissn"):
            if record.get(field):
                by_issn.setdefault(record[field], record)
    for record in list(merged.values()):
        if record.get("cas_zone") or record.get("jcr_quartile"):
            continue
        for field in ("issn", "eissn"):
            twin = by_issn.get(record.get(field) or "")
            if twin and twin is not record:
                for key in ("cas_zone", "cas_category", "cas_top", "cas_review", "cas_year"):
                    if twin.get(key) is not None and record.get(key) is None:
                        record[key] = twin[key]
                break

    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE journals (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            name_key TEXT NOT NULL,
            issn TEXT, eissn TEXT,
            cas_zone INTEGER, cas_top INTEGER, cas_review INTEGER,
            cas_category TEXT, cas_year TEXT,
            jcr_quartile INTEGER, impact_factor REAL, jcr_year TEXT,
            wos TEXT
        )
    """)
    rows = []
    for key, record in merged.items():
        rows.append((
            record.get("name") or key, key,
            record.get("issn") or "", record.get("eissn") or "",
            record.get("cas_zone"), record.get("cas_top"), record.get("cas_review"),
            record.get("cas_category") or "", record.get("cas_year") or "",
            record.get("jcr_quartile"), record.get("impact_factor"), record.get("jcr_year") or "",
            record.get("wos") or "",
        ))
    conn.executemany("INSERT INTO journals (name, name_key, issn, eissn, cas_zone, cas_top, "
                     "cas_review, cas_category, cas_year, jcr_quartile, impact_factor, jcr_year, wos) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.execute("CREATE INDEX idx_name ON journals(name_key)")
    conn.execute("CREATE INDEX idx_issn ON journals(issn)")
    conn.execute("CREATE INDEX idx_eissn ON journals(eissn)")
    conn.commit()
    conn.close()
    full = sum(1 for r in rows if r[4] and r[9] and r[10] is not None)
    return len(rows), full


def main() -> int:
    parser = argparse.ArgumentParser(description="构建 lky-search 的期刊指标库")
    parser.add_argument("--offline", action="store_true", help="只用 data/raw/ 里已有的 CSV")
    parser.add_argument("--check", help="构建后按 DOI 或期刊名验证一条")
    args = parser.parse_args()

    cas_path = fetch(CAS_FILE, args.offline)
    jcr_paths = []
    for name in JCR_FILES:
        try:
            jcr_paths.append((name[3:7], fetch(name, args.offline)))
        except SystemExit as exc:
            sys.stderr.write("跳过 %s：%s\n" % (name, exc))
    if not jcr_paths:
        raise SystemExit("没有可用的 JCR 数据文件")

    cas = parse_cas(cas_path)
    jcr_years = [parse_jcr(path, year) for year, path in jcr_paths]
    total, full = build_db(cas, jcr_years)
    sys.stderr.write("\n索引完成：%d 条期刊，其中 %d 条同时有中科院分区与 JCR 指标\n" % (total, full))
    sys.stderr.write("数据库：%s（%.1f MB）\n" % (DB_PATH, os.path.getsize(DB_PATH) / 1048576))

    if args.check:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        probe = args.check.strip()
        row = None
        if re.search(r"10\.\d{4,9}/", probe):
            sys.stderr.write("--check 需要 ISSN 或期刊名；DOI 请用 lky_search.py metrics --doi\n")
        elif re.fullmatch(r"\d{4}-?\d{3}[\dX]", probe.upper()):
            issn = clean_issn(probe)
            row = conn.execute("SELECT * FROM journals WHERE issn=? OR eissn=? LIMIT 1",
                               (issn, issn)).fetchone()
        else:
            row = conn.execute("SELECT * FROM journals WHERE name_key=? LIMIT 1",
                               (name_key(probe),)).fetchone()
        if row:
            print("命中：%s | 中科院 %s 区(Top=%s, %s) | JCR Q%s | IF %s (%s)" % (
                row["name"], row["cas_zone"], row["cas_top"], row["cas_category"],
                row["jcr_quartile"], row["impact_factor"], row["jcr_year"]))
        else:
            print("未命中：%s" % probe)
    return 0


if __name__ == "__main__":
    sys.exit(main())
