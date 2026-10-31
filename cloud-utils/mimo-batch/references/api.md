# MiMo Batch API reference

Use the helper at `scripts/mimo_batch.py` for normal work. This file captures the platform contract needed to interpret and diagnose responses.

## Authentication and base URL

```text
Base URL: https://batch-api-cn.xiaomimimo.com/v1
Authorization: Bearer <sk-... API key>
```

The API key must be kept out of source files and logs. Prefer `MIMO_BATCH_API_KEY` or the macOS Keychain item `mimo-batch-api-key`.

## File upload

```http
POST /v1/files
Content-Type: multipart/form-data
purpose=batch
file=<input.jsonl>
```

The response contains `id` (`file-...`), `purpose`, `filename`, `bytes`, `status`, `created_at`, and `expire_at`. Uploaded files expire after 30 days.

## Create batch

```http
POST /v1/batches
{
  "input_file_id": "file-...",
  "endpoint": "/v1/chat/completions",
  "completion_window": "24h",
  "name": "task description"
}
```

The page accepts a 1–14 day wait window and requires a task description of at most 200 characters. The API examples use `24h`, and live API responses currently return `24h` even when a longer value is requested. The helper defaults to `24h` and records any API normalization in the manifest.

A batch is limited to 128 MB and 50,000 requests. Split input into multiple files and create one batch per chunk.

## Query and cancel

```http
GET /v1/batches/{batch_id}
POST /v1/batches/{batch_id}/cancel
```

Known status values include `validating`, `in_progress`, `finalizing`, `completed`, `failed`, `expired`, `cancelling`, and `cancelled`. Treat any unknown status as non-terminal unless it is one of `completed`, `failed`, `expired`, or `cancelled`.

Response fields include `status`, `input_file_id`, `output_file_id`, `error_file_id`, `request_counts`, and timestamps. Cancellation is asynchronous: the first response may be `cancelling`; later it becomes `cancelled`, and partial files may still be available.

## Download files

```http
GET /v1/files/{output_file_id}/content
GET /v1/files/{error_file_id}/content
```

Save both files locally before reporting.

### Successful output record

```json
{"id":"batch_req_xxx","custom_id":"request-1","response":{"status_code":200,"body":{"choices":[{"message":{"content":"Hello!"}}]}},"error":null}
```

### Error record

```json
{"id":"batch_req_zzz","custom_id":"request-3","response":null,"error":{"code":"inference_failed","message":"400 Bad Request"}}
```

The input `custom_id` is preserved in output and error records. Use it to join records back to the original input.

## Supported input request shapes

The default is OpenAI chat completions:

```json
{"custom_id":"request-1","method":"POST","url":"/v1/chat/completions","body":{"model":"mimo-v2.6-flash","messages":[{"role":"user","content":"Hello"}]}}
```

The API also documents OpenAI responses (`/v1/responses`) and Anthropic messages (`/v1/messages`) shapes. Keep one endpoint per file. Model names must be lowercase.

## Limits and retention

- One file: at most 128 MB.
- One batch: at most 50,000 requests.
- Input and result files: retained for 30 days.
- Batch execution is asynchronous and scheduled by the platform.
- Batch API charges actual token usage at the documented batch rate; it does not use Token Plan quota.
