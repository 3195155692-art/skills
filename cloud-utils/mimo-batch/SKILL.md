---
name: mimo-batch
description: "Automate Xiaomi MiMo Batch API jobs: generate and validate batch JSONL, submit batches, poll status, download results, and join outputs by custom_id. Use for offline multi-request MiMo inference, labeling, evaluation, extraction, translation, or regression tasks; do not use for single real-time completions."
---

# MiMo Batch

Use this skill when the user provides a dataset or a task to apply MiMo to many inputs asynchronously. The goal is to prepare a valid Batch API payload, submit it without manual console upload, wait for the platform to finish, and deliver joined results plus errors.

## Non-negotiable constraints

- Base URL defaults to `https://batch-api-cn.xiaomimimo.com/v1`; override only with `MIMO_BATCH_BASE_URL` or `--base-url`.
- Supported batch models are lowercase `mimo-v2.6-flash` and `mimo-v2.6-pro`. Default to `mimo-v2.6-flash` unless the user asks for higher-quality reasoning.
- Batch is asynchronous and platform-scheduled. Do not claim that execution is local or immediate.
- A batch file is JSONL, one request object per line. Each request needs a unique string `custom_id`, `method: POST`, an allowed `url`, and a JSON-object `body`.
- The platform limits one batch to 128 MB and 50,000 requests. Automatically split larger inputs and merge all batch results.
- The current Batch API contract effectively uses `completion_window=24h`; the web console exposes a 1–14 day wait field. Use `24h` by default. A requested longer window may be accepted but normalized by the API to `24h`; record the returned value and tell the user rather than claiming a longer deadline.
- Batch files and result files are retained for 30 days. Save results locally and warn the user to back them up.
- Never write the API key to `SKILL.md`, source files, manifests, output files, logs, or command-line arguments. Read `MIMO_BATCH_API_KEY` or the macOS Keychain item `mimo-batch-api-key`.
- Every network-capable command must be invoked through the user's local proxy wrapper:

  ```bash
  ~/.codex/bin/vpnctl p python3 /Users/oldma/.codex/skills/mimo-batch/scripts/mimo_batch.py ...
  ```

## End-to-end workflow

1. Understand the user's input and desired output. If input is already OpenAI Batch JSONL, preserve its `custom_id` and request `body`; otherwise generate requests from CSV/JSON/JSONL/plain text plus the user's instruction.
2. Create a task directory under `work/mimo-batch/<timestamp>-<id>`. Keep the manifest and raw API files there.
3. Use `prepare` to generate normalized `input.jsonl`, strict local validation, and chunk files. It handles the 50,000-request and 128 MB limits automatically.
4. Use `submit` to upload each chunk with `purpose=batch` and create one Batch job per chunk. Do not resubmit chunks that already have a `batch_id`.
5. Use `wait` to poll every chunk. Print progress with `request_counts`; stop when every batch is terminal (`completed`, `failed`, `expired`, or `cancelled`).
6. Use `download` to fetch both `output_file_id` and `error_file_id` whenever available, including partial results after failure or cancellation.
7. Use `report` to join results by `custom_id` and write user-facing outputs to `outputs/mimo-batch/<task-id>/`:
   - `results.jsonl`
   - `errors.jsonl`
   - `results.csv`
   - `status.json`
   - `report.md`
8. If a long job is interrupted, use `resume`; it continues polling, downloading, and reporting without creating duplicate paid jobs.

## Input generation

For structured input, use `prepare --input <file> --instructions '<task>' --model mimo-v2.6-flash`. The script serializes each item into a user prompt and creates OpenAI `chat/completions` requests by default. Use `--endpoint /v1/responses` or `/v1/messages` only when the user explicitly requests that protocol.

For existing batch JSONL, use `validate` first. Reject malformed rows before upload; do not rely on console-side row validation.

## Operational defaults

- Task name: a concise description generated from the user's request, capped at 200 characters.
- Custom IDs: `req-000001`, `req-000002`, ... unless input already supplies unique IDs.
- Completion window: `24h` for the current API; longer requested windows may be normalized by the service.
- Polling: start at 30 seconds and back off to at most 5 minutes; preserve a resumable manifest for multi-hour or multi-day jobs.
- Automatic retries: none. Batch API has no in-task retry or continuation. On partial failure, download the error file and report failed IDs; create a new batch only if the user explicitly asks to retry.
- Cancellation: run `cancel` only when requested or when the user explicitly wants to stop a running job.

## API details

Read [references/api.md](references/api.md) when you need the endpoint shapes, JSONL formats, status semantics, or output/error record schemas. The helper script implements these operations; the reference is for diagnosing platform-specific responses.

## Reporting

Report actual status and counts. Do not turn `request_counts.completed` into a claim that all outputs are valid until the output file has been downloaded and joined. Include the batch IDs, model, endpoint, file locations, failures, and the 30-day retention warning.

If the task is not actually batch inference, leave this skill unused and handle it with the ordinary workflow.
