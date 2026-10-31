#!/usr/bin/env python3
"""Automate Xiaomi MiMo Batch API preparation, submission, polling, download, and reporting.

The caller should run network-capable commands through the local proxy wrapper:
    ~/.codex/bin/vpnctl p python3 .../mimo_batch.py ...
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Iterable

DEFAULT_BASE_URL = "https://batch-api-cn.xiaomimimo.com/v1"
DEFAULT_MODEL = "mimo-v2.6-flash"
DEFAULT_ENDPOINT = "/v1/chat/completions"
ALLOWED_ENDPOINTS = {
    "/v1/chat/completions",
    "/v1/responses",
    "/v1/messages",
}
TERMINAL_STATUSES = {"completed", "failed", "expired", "cancelled"}
MAX_REQUESTS_PER_BATCH = 50_000
MAX_BYTES_PER_BATCH = 128 * 1024 * 1024
SUPPORTED_MODELS = {"mimo-v2.6-flash", "mimo-v2.6-pro"}
API_KEY_SERVICE = "mimo-batch-api-key"


class ApiError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, body: Any = None):
        super().__init__(message)
        self.status = status
        self.body = body


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def slugify(value: str, default: str = "mimo-batch") -> str:
    value = re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip()).strip("-").lower()
    return value[:80] or default


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{lineno}: invalid JSON: {exc}") from exc
            if not isinstance(obj, dict):
                raise ValueError(f"{path}:{lineno}: each JSONL row must be an object")
            rows.append(obj)
    return rows


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            count += 1
    return count


def encode_multipart(field_values: dict[str, str], file_field: str, filename: str, file_bytes: bytes) -> tuple[bytes, str]:
    boundary = f"----mimo-batch-{uuid.uuid4().hex}"
    parts: list[bytes] = []
    for key, value in field_values.items():
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
        parts.append(value.encode("utf-8"))
        parts.append(b"\r\n")
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    parts.append(f"--{boundary}\r\n".encode())
    parts.append(f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'.encode())
    parts.append(f"Content-Type: {mime}\r\n\r\n".encode())
    parts.append(file_bytes)
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), boundary


def get_api_key() -> str:
    value = os.environ.get("MIMO_BATCH_API_KEY", "").strip()
    if value:
        return value
    try:
        proc = subprocess.run(
            ["security", "find-generic-password", "-s", API_KEY_SERVICE, "-w"],
            capture_output=True,
            text=True,
            check=True,
        )
        value = proc.stdout.strip()
        if value:
            return value
    except (OSError, subprocess.CalledProcessError):
        pass
    raise RuntimeError(
        "MiMo API key not found. Set MIMO_BATCH_API_KEY or store it in macOS Keychain "
        f'with: security add-generic-password -s {API_KEY_SERVICE} -a "$USER" -w'
    )


class Client:
    def __init__(self, base_url: str | None = None, timeout: int = 120):
        self.base_url = (base_url or os.environ.get("MIMO_BATCH_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout
        self.api_key = get_api_key()

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        raw_body: bytes | None = None,
        headers: dict[str, str] | None = None,
        accept_json: bool = True,
    ) -> tuple[int, Any, bytes]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        request_headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json" if accept_json else "*/*",
            "User-Agent": "mimo-batch-skill/1.0",
        }
        if headers:
            request_headers.update(headers)
        data = raw_body
        if json_body is not None:
            data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=request_headers, method=method.upper())
        attempts = 4 if method.upper() == "GET" else 1
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as response:
                    body = response.read()
                    status = response.status
                    if not body:
                        parsed: Any = None
                    else:
                        try:
                            parsed = json.loads(body)
                        except json.JSONDecodeError:
                            parsed = body.decode("utf-8", errors="replace") if accept_json else body
                    return status, parsed, body
            except urllib.error.HTTPError as exc:
                body = exc.read()
                try:
                    parsed = json.loads(body)
                except Exception:
                    parsed = body.decode("utf-8", errors="replace")
                last_error = ApiError(f"HTTP {exc.code} {method} {path}: {parsed}", status=exc.code, body=parsed)
                if method.upper() != "GET" or exc.code not in {408, 425, 429, 500, 502, 503, 504} or attempt == attempts - 1:
                    raise last_error from exc
            except urllib.error.URLError as exc:
                last_error = ApiError(f"network error {method} {path}: {exc}")
                if method.upper() != "GET" or attempt == attempts - 1:
                    raise last_error from exc
            except (TimeoutError, OSError) as exc:
                last_error = ApiError(f"network error {method} {path}: {exc}")
                if method.upper() != "GET" or attempt == attempts - 1:
                    raise last_error from exc
            time.sleep(min(8.0, 1.0 * (2 ** attempt)))
        raise last_error or ApiError(f"request failed {method} {path}")

    def upload_file(self, path: Path) -> dict[str, Any]:
        data, boundary = encode_multipart({"purpose": "batch"}, "file", path.name, path.read_bytes())
        _, parsed, _ = self._request(
            "POST",
            "/files",
            raw_body=data,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        return parsed

    def create_batch(
        self,
        input_file_id: str,
        endpoint: str,
        completion_window: str,
        name: str,
    ) -> dict[str, Any]:
        payload = {
            "input_file_id": input_file_id,
            "endpoint": endpoint,
            "completion_window": completion_window,
            "name": name[:200],
        }
        _, parsed, _ = self._request("POST", "/batches", json_body=payload)
        return parsed

    def get_batch(self, batch_id: str) -> dict[str, Any]:
        _, parsed, _ = self._request("GET", f"/batches/{batch_id}")
        return parsed

    def cancel_batch(self, batch_id: str) -> dict[str, Any]:
        _, parsed, _ = self._request("POST", f"/batches/{batch_id}/cancel", json_body={})
        return parsed

    def download_file(self, file_id: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        _, _, body = self._request("GET", f"/files/{file_id}/content", accept_json=False)
        destination.write_bytes(body)
        return destination


def default_task_dir() -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path("work/mimo-batch") / f"{stamp}-{uuid.uuid4().hex[:6]}"


def load_input_items(path: Path) -> list[Any]:
    suffix = path.suffix.lower()
    if suffix in {".jsonl", ".ndjson"}:
        items: list[Any] = []
        with path.open("r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{lineno}: invalid JSON: {exc}") from exc
        return items
    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("requests", "items", "data"):
                if isinstance(data.get(key), list):
                    return data[key]
            return [data]
        raise ValueError("JSON input must contain an object or array")
    if suffix in {".csv", ".tsv"}:
        delimiter = "\t" if suffix == ".tsv" else ","
        with path.open("r", encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f, delimiter=delimiter))
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return lines


def make_request_row(
    index: int,
    item: Any,
    *,
    instructions: str,
    system: str | None,
    model: str,
    endpoint: str,
    custom_id_prefix: str,
) -> dict[str, Any]:
    custom_id = item.get("custom_id") if isinstance(item, dict) and item.get("custom_id") else f"{custom_id_prefix}{index:06d}"
    if isinstance(item, dict) and {"custom_id", "method", "url", "body"}.issubset(item):
        row = {
            "custom_id": str(custom_id),
            "method": str(item.get("method", "POST")).upper(),
            "url": str(item.get("url", endpoint)),
            "body": item["body"],
        }
        return row
    content = f"{instructions}\n\nInput:\n{json.dumps(item, ensure_ascii=False, sort_keys=True)}"
    if endpoint == "/v1/responses":
        body: dict[str, Any] = {"model": model, "input": content}
    elif endpoint == "/v1/messages":
        messages = []
        if system:
            messages.append({"role": "user", "content": f"System: {system}"})
        messages.append({"role": "user", "content": content})
        body = {"model": model, "messages": messages}
    else:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": content})
        body = {"model": model, "messages": messages}
    return {"custom_id": str(custom_id), "method": "POST", "url": endpoint, "body": body}


def validate_requests(
    rows: list[dict[str, Any]],
    *,
    endpoint: str | None = None,
    max_requests: int = MAX_REQUESTS_PER_BATCH,
    max_bytes: int = MAX_BYTES_PER_BATCH,
) -> dict[str, Any]:
    errors: list[str] = []
    seen: set[str] = set()
    total_bytes = 0
    for i, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            errors.append(f"row {i}: must be an object")
            continue
        custom_id = row.get("custom_id")
        if not isinstance(custom_id, str) or not custom_id:
            errors.append(f"row {i}: custom_id must be a non-empty string")
        elif custom_id in seen:
            errors.append(f"row {i}: duplicate custom_id {custom_id!r}")
        else:
            seen.add(custom_id)
        if str(row.get("method", "POST")).upper() != "POST":
            errors.append(f"row {i}: method must be POST")
        url = str(row.get("url", ""))
        if endpoint and url != endpoint:
            errors.append(f"row {i}: url {url!r} does not match expected endpoint {endpoint!r}")
        if url not in ALLOWED_ENDPOINTS:
            errors.append(f"row {i}: unsupported url {url!r}")
        body = row.get("body")
        if not isinstance(body, dict):
            errors.append(f"row {i}: body must be a JSON object")
            continue
        model = body.get("model")
        if model is not None and model not in SUPPORTED_MODELS:
            errors.append(f"row {i}: unsupported model {model!r}; use a lowercase supported MiMo model")
        if url == "/v1/chat/completions" and not isinstance(body.get("messages"), list):
            errors.append(f"row {i}: chat completions body requires a messages array")
        if url == "/v1/responses" and "input" not in body:
            errors.append(f"row {i}: responses body requires input")
        if url == "/v1/messages" and not isinstance(body.get("messages"), list):
            errors.append(f"row {i}: messages body requires a messages array")
        total_bytes += len(json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + 1
    return {
        "valid": not errors,
        "request_count": len(rows),
        "total_bytes": total_bytes,
        "max_requests_per_batch": max_requests,
        "max_bytes_per_batch": max_bytes,
        "chunks_needed": max(1, (len(rows) + max_requests - 1) // max_requests) if rows else 0,
        "errors": errors,
    }


def split_rows(rows: list[dict[str, Any]], max_requests: int, max_bytes: int) -> list[list[dict[str, Any]]]:
    chunks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_bytes = 0
    for row in rows:
        encoded_len = len(json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + 1
        if current and (len(current) >= max_requests or current_bytes + encoded_len > max_bytes):
            chunks.append(current)
            current = []
            current_bytes = 0
        current.append(row)
        current_bytes += encoded_len
    if current:
        chunks.append(current)
    return chunks


def save_manifest(path: Path, manifest: dict[str, Any]) -> None:
    manifest["updated_at"] = now_iso()
    atomic_write_json(path, manifest)


def load_manifest(task_dir: Path) -> dict[str, Any]:
    path = task_dir / "manifest.json"
    if not path.exists():
        raise FileNotFoundError(f"manifest not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def extract_response(record: dict[str, Any]) -> tuple[str, int | None, str, str]:
    response = record.get("response") or {}
    status_code = response.get("status_code") if isinstance(response, dict) else None
    body = response.get("body") if isinstance(response, dict) else None
    content = ""
    if isinstance(body, dict):
        choices = body.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            message = choices[0].get("message") or {}
            if isinstance(message, dict):
                content = str(message.get("content") or "")
        if not content and isinstance(body.get("output_text"), str):
            content = body["output_text"]
        if not content and isinstance(body.get("content"), str):
            content = body["content"]
    error = record.get("error") or {}
    error_code = str(error.get("code", "")) if isinstance(error, dict) else ""
    error_message = str(error.get("message", "")) if isinstance(error, dict) else str(error or "")
    return content, status_code, error_code, error_message


def report_task(task_dir: Path, output_dir: Path) -> dict[str, Any]:
    manifest = load_manifest(task_dir)
    chunks = manifest.get("chunks", [])
    result_records: list[dict[str, Any]] = []
    error_records: list[dict[str, Any]] = []
    for chunk in chunks:
        output_path = chunk.get("local_output_file")
        error_path = chunk.get("local_error_file")
        if output_path and Path(output_path).exists():
            result_records.extend(read_jsonl(Path(output_path)))
        if error_path and Path(error_path).exists():
            error_records.extend(read_jsonl(Path(error_path)))
    input_by_id: dict[str, dict[str, Any]] = {}
    input_file = manifest.get("input_file")
    if input_file and Path(input_file).exists():
        for row in read_jsonl(Path(input_file)):
            custom_id = row.get("custom_id")
            if isinstance(custom_id, str):
                input_by_id[custom_id] = row
    output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(output_dir / "results.jsonl", result_records)
    write_jsonl(output_dir / "errors.jsonl", error_records)
    with (output_dir / "results.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["custom_id", "status_code", "content", "error_code", "error_message", "input_json", "raw_response_json"])
        for record in result_records + error_records:
            content, status_code, error_code, error_message = extract_response(record)
            custom_id = str(record.get("custom_id", ""))
            source = input_by_id.get(custom_id, {})
            writer.writerow([
                custom_id,
                status_code if status_code is not None else "",
                content,
                error_code,
                error_message,
                json.dumps(source.get("body", source), ensure_ascii=False),
                json.dumps(record.get("response") or {}, ensure_ascii=False),
            ])
    counts = {"total": 0, "completed": 0, "failed": 0}
    for chunk in chunks:
        payload = chunk.get("status_payload") or {}
        for key in counts:
            counts[key] += int((payload.get("request_counts") or {}).get(key, 0) or 0)
    if not any(counts.values()):
        counts = manifest.get("request_counts", counts)
    report = {
        "task": manifest.get("name", task_dir.name),
        "task_dir": str(task_dir.resolve()),
        "output_dir": str(output_dir.resolve()),
        "batch_ids": [c.get("batch_id") for c in chunks],
        "status": manifest.get("status"),
        "request_counts": counts,
        "result_records": len(result_records),
        "error_records": len(error_records),
        "generated_at": now_iso(),
        "retention_note": "MiMo retains uploaded and result files for 30 days; download and back up results promptly.",
    }
    atomic_write_json(output_dir / "status.json", report)
    lines = [
        f"# MiMo Batch Report: {report['task']}",
        "",
        f"- Status: `{report['status']}`",
        f"- Request counts: `{counts}`",
        f"- Batch IDs: `{', '.join(str(x) for x in report['batch_ids'])}`",
        f"- Result records: {report['result_records']}",
        f"- Error records: {report['error_records']}",
        "",
        "## Files",
        f"- `results.jsonl`: {output_dir / 'results.jsonl'}",
        f"- `errors.jsonl`: {output_dir / 'errors.jsonl'}",
        f"- `results.csv`: {output_dir / 'results.csv'}",
        f"- `status.json`: {output_dir / 'status.json'}",
        "",
        "## Notes",
        "- Results are keyed by `custom_id`; use it to join outputs back to the original input.",
        "- MiMo Batch is asynchronous and scheduled by the platform. The local helper only creates, polls, and downloads tasks.",
        "- MiMo retains uploaded and result files for 30 days. Download and back up results promptly.",
    ]
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def cmd_prepare(args: argparse.Namespace) -> int:
    task_dir = Path(args.task_dir) if args.task_dir else default_task_dir()
    task_dir.mkdir(parents=True, exist_ok=True)
    input_path = Path(args.input)
    items = load_input_items(input_path)
    if not items:
        raise ValueError("input contains no rows")
    instructions = args.instructions or "Process the following input."
    rows = [
        make_request_row(
            i,
            item,
            instructions=instructions,
            system=args.system,
            model=args.model,
            endpoint=args.endpoint,
            custom_id_prefix=args.custom_id_prefix,
        )
        for i, item in enumerate(items, 1)
    ]
    validation = validate_requests(rows, endpoint=args.endpoint, max_requests=args.max_requests, max_bytes=args.max_bytes)
    if not validation["valid"]:
        for error in validation["errors"][:20]:
            print(error, file=sys.stderr)
        raise ValueError(f"validation failed with {len(validation['errors'])} errors")
    chunks = split_rows(rows, args.max_requests, args.max_bytes)
    input_file = task_dir / "input.jsonl"
    write_jsonl(input_file, rows)
    chunk_paths = []
    for i, chunk in enumerate(chunks, 1):
        path = task_dir / "chunks" / f"chunk-{i:04d}.jsonl"
        write_jsonl(path, chunk)
        chunk_paths.append({"path": str(path), "request_count": len(chunk)})
    name = args.name or instructions.replace("\n", " ")[:200]
    manifest = {
        "version": 1,
        "task_id": task_dir.name,
        "name": name[:200],
        "created_at": now_iso(),
        "base_url": args.base_url or DEFAULT_BASE_URL,
        "endpoint": args.endpoint,
        "model": args.model,
        "completion_window": args.completion_window,
        "source_input": str(input_path.resolve()),
        "input_file": str(input_file.resolve()),
        "validation": validation,
        "request_count": len(rows),
        "chunks": [
            {
                "index": i,
                "path": item["path"],
                "request_count": item["request_count"],
                "status": "prepared",
                "input_file_id": None,
                "batch_id": None,
                "status_payload": None,
                "local_output_file": None,
                "local_error_file": None,
            }
            for i, item in enumerate(chunk_paths, 1)
        ],
        "status": "prepared",
    }
    save_manifest(task_dir / "manifest.json", manifest)
    print(json.dumps({"task_dir": str(task_dir.resolve()), "request_count": len(rows), "chunks": len(chunks), "validation": validation}, ensure_ascii=False, indent=2))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    rows = read_jsonl(Path(args.input))
    result = validate_requests(rows, endpoint=args.endpoint, max_requests=args.max_requests, max_bytes=args.max_bytes)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


def cmd_submit(args: argparse.Namespace) -> int:
    task_dir = Path(args.task_dir)
    manifest = load_manifest(task_dir)
    client = Client(args.base_url or manifest.get("base_url"))
    for chunk in manifest.get("chunks", []):
        if chunk.get("batch_id"):
            continue
        path = Path(chunk["path"])
        uploaded = client.upload_file(path)
        chunk["input_file_id"] = uploaded.get("id")
        chunk["upload_payload"] = uploaded
        save_manifest(task_dir / "manifest.json", manifest)
        try:
            batch = client.create_batch(
                chunk["input_file_id"],
                manifest["endpoint"],
                manifest.get("completion_window", "24h"),
                manifest.get("name", task_dir.name),
            )
        except ApiError as exc:
            if manifest.get("completion_window") == "7d" and exc.status == 400:
                batch = client.create_batch(
                    chunk["input_file_id"],
                    manifest["endpoint"],
                    "24h",
                    manifest.get("name", task_dir.name),
                )
                manifest["completion_window"] = "24h"
                manifest["completion_window_fallback"] = True
            else:
                raise
        if batch.get("completion_window") and batch.get("completion_window") != manifest.get("completion_window"):
            manifest["requested_completion_window"] = manifest.get("completion_window")
            manifest["completion_window"] = batch["completion_window"]
            manifest["completion_window_note"] = (
                f"API normalized requested window {manifest['requested_completion_window']} "
                f"to {batch['completion_window']}."
            )
        chunk["batch_id"] = batch.get("id")
        chunk["create_payload"] = batch
        chunk["status"] = batch.get("status", "submitted")
        save_manifest(task_dir / "manifest.json", manifest)
    manifest["status"] = "submitted"
    save_manifest(task_dir / "manifest.json", manifest)
    print(json.dumps({"task_dir": str(task_dir.resolve()), "chunks": manifest["chunks"]}, ensure_ascii=False, indent=2))
    return 0


def _update_chunk_status(client: Client, manifest: dict[str, Any], task_dir: Path, chunk: dict[str, Any]) -> dict[str, Any]:
    if not chunk.get("batch_id"):
        return chunk
    payload = client.get_batch(chunk["batch_id"])
    chunk["status_payload"] = payload
    chunk["status"] = payload.get("status", chunk.get("status"))
    return payload


def cmd_status(args: argparse.Namespace) -> int:
    if not args.task_dir and not args.batch_id:
        raise ValueError("provide --task-dir or --batch-id")
    if args.task_dir:
        task_dir = Path(args.task_dir)
        manifest = load_manifest(task_dir)
        client = Client(args.base_url or manifest.get("base_url"))
        statuses = []
        for chunk in manifest["chunks"]:
            payload = _update_chunk_status(client, manifest, task_dir, chunk)
            statuses.append({"batch_id": chunk.get("batch_id"), "status": payload.get("status"), "request_counts": payload.get("request_counts")})
        statuses_terminal = all((item.get("status") or "").lower() in TERMINAL_STATUSES for item in statuses if item.get("batch_id"))
        if statuses_terminal:
            manifest["status"] = "terminal"
        save_manifest(task_dir / "manifest.json", manifest)
        print(json.dumps({"task_dir": str(task_dir.resolve()), "status": manifest.get("status"), "chunks": statuses}, ensure_ascii=False, indent=2))
    else:
        client = Client(args.base_url)
        print(json.dumps(client.get_batch(args.batch_id), ensure_ascii=False, indent=2))
    return 0


def cmd_wait(args: argparse.Namespace) -> int:
    task_dir = Path(args.task_dir)
    manifest = load_manifest(task_dir)
    client = Client(args.base_url or manifest.get("base_url"))
    started = time.monotonic()
    interval = args.interval
    while True:
        all_terminal = True
        progress = []
        for chunk in manifest["chunks"]:
            payload = _update_chunk_status(client, manifest, task_dir, chunk)
            status = str(payload.get("status", "")).lower()
            progress.append({"batch_id": chunk.get("batch_id"), "status": status, "request_counts": payload.get("request_counts")})
            if chunk.get("batch_id") and status not in TERMINAL_STATUSES:
                all_terminal = False
        save_manifest(task_dir / "manifest.json", manifest)
        print(json.dumps({"time": now_iso(), "chunks": progress}, ensure_ascii=False), flush=True)
        if all_terminal:
            manifest["status"] = "terminal"
            save_manifest(task_dir / "manifest.json", manifest)
            return 0
        if args.timeout and time.monotonic() - started >= args.timeout:
            raise TimeoutError("wait timeout; run resume later")
        time.sleep(interval)
        interval = min(args.max_interval, max(args.min_interval, interval * 1.2))


def cmd_download(args: argparse.Namespace) -> int:
    task_dir = Path(args.task_dir)
    manifest = load_manifest(task_dir)
    client = Client(args.base_url or manifest.get("base_url"))
    for chunk in manifest["chunks"]:
        if not chunk.get("batch_id"):
            continue
        payload = _update_chunk_status(client, manifest, task_dir, chunk)
        output_id = payload.get("output_file_id")
        error_id = payload.get("error_file_id")
        if output_id:
            chunk["local_output_file"] = str(client.download_file(output_id, task_dir / "raw" / f"chunk-{chunk['index']:04d}-output.jsonl").resolve())
        if error_id:
            chunk["local_error_file"] = str(client.download_file(error_id, task_dir / "raw" / f"chunk-{chunk['index']:04d}-errors.jsonl").resolve())
    save_manifest(task_dir / "manifest.json", manifest)
    print(json.dumps({"task_dir": str(task_dir.resolve()), "chunks": manifest["chunks"]}, ensure_ascii=False, indent=2))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    task_dir = Path(args.task_dir)
    output_dir = Path(args.output_dir) if args.output_dir else task_dir / "output"
    report = report_task(task_dir, output_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def cmd_cancel(args: argparse.Namespace) -> int:
    if not args.task_dir and not args.batch_id:
        raise ValueError("provide --task-dir or --batch-id")
    if args.task_dir:
        task_dir = Path(args.task_dir)
        manifest = load_manifest(task_dir)
        client = Client(args.base_url or manifest.get("base_url"))
        for chunk in manifest["chunks"]:
            if chunk.get("batch_id"):
                payload = client.cancel_batch(chunk["batch_id"])
                chunk["status_payload"] = payload
                chunk["status"] = payload.get("status", "cancelling")
        save_manifest(task_dir / "manifest.json", manifest)
        print(json.dumps({"task_dir": str(task_dir.resolve()), "chunks": manifest["chunks"]}, ensure_ascii=False, indent=2))
    else:
        client = Client(args.base_url)
        print(json.dumps(client.cancel_batch(args.batch_id), ensure_ascii=False, indent=2))
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    args.task_dir = args.task_dir
    cmd_wait(argparse.Namespace(task_dir=args.task_dir, base_url=args.base_url, interval=args.interval, min_interval=args.interval, max_interval=max(args.interval, 300), timeout=args.timeout))
    cmd_download(argparse.Namespace(task_dir=args.task_dir, base_url=args.base_url))
    output_dir = args.output_dir or str(Path("outputs/mimo-batch") / Path(args.task_dir).name)
    cmd_report(argparse.Namespace(task_dir=args.task_dir, output_dir=output_dir))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    task_dir = Path(args.task_dir) if args.task_dir else default_task_dir()
    prepare_ns = argparse.Namespace(
        input=args.input,
        task_dir=str(task_dir),
        instructions=args.instructions,
        system=args.system,
        model=args.model,
        endpoint=args.endpoint,
        custom_id_prefix=args.custom_id_prefix,
        name=args.name,
        base_url=args.base_url,
        completion_window=args.completion_window,
        max_requests=args.max_requests,
        max_bytes=args.max_bytes,
    )
    cmd_prepare(prepare_ns)
    cmd_submit(argparse.Namespace(task_dir=str(task_dir), base_url=args.base_url))
    cmd_wait(argparse.Namespace(task_dir=str(task_dir), base_url=args.base_url, interval=args.interval, min_interval=args.interval, max_interval=args.max_interval, timeout=args.timeout))
    cmd_download(argparse.Namespace(task_dir=str(task_dir), base_url=args.base_url))
    output_dir = args.output_dir or str(Path("outputs/mimo-batch") / task_dir.name)
    cmd_report(argparse.Namespace(task_dir=str(task_dir), output_dir=output_dir))
    return 0


def add_network_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base-url", default=os.environ.get("MIMO_BATCH_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--task-dir")
    parser.add_argument("--output-dir")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Xiaomi MiMo Batch API automation")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("prepare", help="Convert input data to validated batch JSONL chunks")
    add_network_options(p)
    p.add_argument("--input", required=True)
    p.add_argument("--instructions", default="")
    p.add_argument("--system")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--endpoint", default=DEFAULT_ENDPOINT, choices=sorted(ALLOWED_ENDPOINTS))
    p.add_argument("--custom-id-prefix", default="req-")
    p.add_argument("--name")
    p.add_argument("--completion-window", default="24h")
    p.add_argument("--max-requests", type=int, default=MAX_REQUESTS_PER_BATCH)
    p.add_argument("--max-bytes", type=int, default=MAX_BYTES_PER_BATCH)
    p.set_defaults(func=cmd_prepare)

    p = sub.add_parser("validate", help="Validate a JSONL request file")
    p.add_argument("--input", required=True)
    p.add_argument("--endpoint", default=DEFAULT_ENDPOINT, choices=sorted(ALLOWED_ENDPOINTS))
    p.add_argument("--max-requests", type=int, default=MAX_REQUESTS_PER_BATCH)
    p.add_argument("--max-bytes", type=int, default=MAX_BYTES_PER_BATCH)
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("submit", help="Upload chunks and create batch jobs")
    p.add_argument("--base-url", default=os.environ.get("MIMO_BATCH_BASE_URL", DEFAULT_BASE_URL))
    p.add_argument("--task-dir", required=True)
    p.set_defaults(func=cmd_submit)

    p = sub.add_parser("status", help="Query batch status")
    p.add_argument("--base-url", default=os.environ.get("MIMO_BATCH_BASE_URL", DEFAULT_BASE_URL))
    p.add_argument("--task-dir")
    p.add_argument("--batch-id")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("wait", help="Poll batch jobs until terminal status")
    p.add_argument("--base-url", default=os.environ.get("MIMO_BATCH_BASE_URL", DEFAULT_BASE_URL))
    p.add_argument("--task-dir", required=True)
    p.add_argument("--interval", type=float, default=30.0)
    p.add_argument("--min-interval", type=float, default=30.0)
    p.add_argument("--max-interval", type=float, default=300.0)
    p.add_argument("--timeout", type=float, default=0)
    p.set_defaults(func=cmd_wait)

    p = sub.add_parser("download", help="Download output and error files")
    p.add_argument("--base-url", default=os.environ.get("MIMO_BATCH_BASE_URL", DEFAULT_BASE_URL))
    p.add_argument("--task-dir", required=True)
    p.set_defaults(func=cmd_download)

    p = sub.add_parser("report", help="Join results and write a report")
    p.add_argument("--task-dir", required=True)
    p.add_argument("--output-dir")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("cancel", help="Cancel one batch or all chunks")
    p.add_argument("--base-url", default=os.environ.get("MIMO_BATCH_BASE_URL", DEFAULT_BASE_URL))
    p.add_argument("--task-dir")
    p.add_argument("--batch-id")
    p.set_defaults(func=cmd_cancel)

    p = sub.add_parser("resume", help="Wait, download, and report an existing task")
    p.add_argument("--base-url", default=os.environ.get("MIMO_BATCH_BASE_URL", DEFAULT_BASE_URL))
    p.add_argument("--task-dir", required=True)
    p.add_argument("--output-dir")
    p.add_argument("--interval", type=float, default=30.0)
    p.add_argument("--timeout", type=float, default=0)
    p.set_defaults(func=cmd_resume)

    p = sub.add_parser("run", help="Prepare, submit, wait, download, and report")
    add_network_options(p)
    p.add_argument("--input", required=True)
    p.add_argument("--instructions", default="")
    p.add_argument("--system")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--endpoint", default=DEFAULT_ENDPOINT, choices=sorted(ALLOWED_ENDPOINTS))
    p.add_argument("--custom-id-prefix", default="req-")
    p.add_argument("--name")
    p.add_argument("--completion-window", default="24h")
    p.add_argument("--max-requests", type=int, default=MAX_REQUESTS_PER_BATCH)
    p.add_argument("--max-bytes", type=int, default=MAX_BYTES_PER_BATCH)
    p.add_argument("--interval", type=float, default=30.0)
    p.add_argument("--min-interval", type=float, default=30.0)
    p.add_argument("--max-interval", type=float, default=300.0)
    p.add_argument("--timeout", type=float, default=0)
    p.set_defaults(func=cmd_run)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except (ValueError, FileNotFoundError, ApiError, RuntimeError, TimeoutError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
