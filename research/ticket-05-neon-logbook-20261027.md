# Ticket 05 - minimal execution logbook (file name kept; host is now Supabase Postgres) - 2026-10-27

**Current status 2026-10-28: LIVE-VERIFIED against Supabase Postgres - see the last section ("Supabase connection and live verification"). The setting is now `LOGBOOK_DATABASE_URL`; the earlier `NEON_DATABASE_URL`/"Neon" wording below is history.**

Latest disposition — direct Codex verification 2026-10-28: **accepted at SCRIPTED level after all five corrections**. Independently inspected the fixes and ran the fresh-copy logging suite **33/33 passed**. No repeat review agents, additional live calls, driver installation or real-runtime changes. Live Neon/Postgres insert/read remains pending credentials and driver; logging changes are still uncommitted/unpushed. Earlier status and limitation paragraphs below describe prior stages; the corrections section and this disposition supersede them. Verification log: ignored `.scratch/codex-neon05-corrections-verification.txt`.

**Historical status (2026-10-27, superseded by the Supabase section): implemented at SCRIPTED level, awaiting Codex review; the live check was pending.**

## What it is

One append-only table `ecom_execution_events` in a Neon (Postgres) database, filled best-effort by one bounded background writer in the server process (`app/logbook.py`). SQLite remains authoritative for application state, permissions, artifacts and attempt limits; the logbook only records evidence and never decides anything. There is no dashboard, no Langfuse/Laminar/OpenTelemetry, no judge, no backfill and no new agent memory store.

### Schema (created with `CREATE TABLE IF NOT EXISTS`; nothing else is touched)

```sql
CREATE TABLE IF NOT EXISTS ecom_execution_events(
  event_id TEXT PRIMARY KEY, request_id TEXT, agent_id TEXT, event_type TEXT NOT NULL, ts TIMESTAMPTZ NOT NULL,
  duration_ms DOUBLE PRECISION, provider TEXT, model TEXT, tool_name TEXT,
  outcome TEXT NOT NULL CHECK (outcome IN ('success','failure','unknown')),
  prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER, inputs JSONB, result JSONB);
CREATE INDEX IF NOT EXISTS ecom_execution_events_request_idx ON ecom_execution_events(request_id, ts);
```

Inserts are parameterized (`INSERT ... ON CONFLICT (event_id) DO NOTHING`). Missing token counts or durations are NULL (unknown), never 0.

### Events (one row per event, no second representation of the same fact)

| event_type | written by | when / content |
|---|---|---|
| `request.start` / `request.end` | server `chat()` | start: message length, a 300-char preview, Customize flag. End: outcome, duration, route outcome, `handled_locally`, tool names, error, and the final answer preview **labelled `model_provided_final_answer_preview`** (a model claim, not verified evidence). Locally answered routing requests have only these two events. |
| `request.duplicate` | server `chat()` | a completed request re-submitted (served from the stored result, `executed_again: false`) or a still-running one re-submitted (refused 409). It is never recorded as a model or tool run. |
| `model.start` | Hermes `pre_api_request` hook (worker) | written when a provider request is SENT: outcome always `unknown`, provider, model, `api_request_id`, call/retry counters, message/tool counts, approximate input tokens, no usage and no prompt text. It is not an attempt count: the executed/billable attempts are the `model.call` rows; a start with no matching `model.call` has an unobserved outcome (killed worker, still running). |
| `model.call` | Hermes `post_api_request` / `api_request_error` hooks (worker) | one row per COMPLETED provider attempt (linked to its `model.start` by `inputs.api_request_id`): provider, model, duration, reported prompt/completion/total tokens, finish reason, names of tools the model requested, time to first byte, reasoning/cache tokens; or the failure type, status code, retry fields and redacted message. No prompt, reply or reasoning text. A Hermes retry is its own row. |
| `tool.call` | Hermes `post_tool_call` hook (worker) | recorded when the tool actually returned: tool name, duration, the model's arguments (labelled `model_arguments`), the **backend's observed result reduced to allowed fields** (`ok`, `code`, `error`, counts and every `*_id`, e.g. `agent_id`, `draft_id`, `flyer_id`, `candidate_id`, `package_id`), Hermes' status. Outcome comes from the real result, not from the call: `ok:false` / `error` / error status = failure. Generation, inspection, review, saved outputs, `create_agent` and `customize_specialist` are all covered by this one event through their existing results. |
| `context.save` | `core.update_company` | only for saves that did NOT come through main's tool (web form -> agent `operator`, onboarding -> `main`); main's own saves are already its `tool.call`. |
| `onboarding.source` / `onboarding.answers` | `onboarding` steps | outcome, state, code; each step gets its own request id that its main model turns and the shared-context save also carry. |

Identity: the backend request id now reaches the worker for main's routed path too (previously only specialists got it; onboarding turns had none). Worker rows carry `turn_state.request_id` and `ECOM_AGENT_ID`.

### How rows get to Neon

Workers do **not** hold the credential. A worker's hook sends its row as one JSON line (`{"event":"log","rows":[...]}`) over the existing worker protocol (no database round trip on any tool's path); the server re-validates and re-bounds it and enqueues it. One bounded queue (1000) and one writer thread batch-insert (up to 50 rows), connect lazily (5 s timeout, 5 s statement timeout) and, after a failure, wait 15 s before reconnecting (rows arriving meanwhile are counted as lost).

### Redaction and bounds

`sanitize()` / `bounded()` at every entry point (worker and server): secret-named keys (`api_key`, `authorization`, `password`, `token`, `secret`, `cookie`, `database_url`, ...) become `<redacted>`; this project's own configured secret values and any `NEON_DATABASE_URL` are scrubbed wherever they occur; URLs with passwords, bearer/basic values, `key=value` secrets, `data:` URLs and long base64 runs are removed; strings are cut at 600 characters, lists at 20 items, dicts at 30 keys, depth at 5, and the serialized payload at 6,000 characters. Tool results are never stored raw (allowed-field summary only); images appear as ids/hashes only.

## Configuration (this project only)

1. Put the dedicated Postgres connection URI (Supabase: session pooler) in the ignored `secrets/local.env` as `LOGBOOK_DATABASE_URL=postgresql://user:password@host:5432/db?sslmode=require` (the tracked template has the empty entry; the retired name `NEON_DATABASE_URL` is no longer read). Empty/absent = logging off and nothing else changes. `ECOM_LOGBOOK=off` also forces it off.
2. Install the driver into the Hermes Python only when turning it on: `"%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe" -m pip install -r requirements-logbook.txt` (`psycopg[binary]==3.3.4`; the Hermes venv has no Postgres driver today, I did not install anything). Without it the logbook reports `driver: missing` and logs nothing.
3. Check the connection (inserts and reads back ONE synthetic event; prints no secret): `"%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe" -m app.logbook`.
4. Start the app as usual (`.\run.bat`). `GET http://127.0.0.1:8800/api/logbook` shows `enabled`, `reason`, `driver`, `queued`, `accepted`, `written`, `dropped_queue_full`, `lost_write_failed`, `batches_failed`, a redacted `last_error` and `last_ok_ts`; it never contains the connection string. "Saved" means `written` counted it.

### Inspect one request

```sql
SELECT ts, event_type, agent_id, tool_name, model, outcome, duration_ms, prompt_tokens, completion_tokens, result
FROM ecom_execution_events WHERE request_id = '<request id from the chat response>' ORDER BY ts, event_id;
```

## Verification (isolated copies, scripted model, real backend/workers/hooks; SQLite stands in for Neon)

- `tests/logbook_test.py` (new): **25/25**. Unit: redaction and bounds, tool-result allow-list and outcome-from-result, full queue never blocks or raises (kept 2, dropped counted), disabled = no-op, worker rows re-bounded by the server. End to end: one request's request/model/tool events share request id and agent (main routing path included), model-call count equals what the provider really received (2); provider/model/duration/usage recorded; success vs failure tools distinguished by real results (`update_company` ok vs `unknown_field`; `create_agent` ok vs `role_exists`; `read_catalogue` without a catalogue); customization recorded under the specialist's identity; web-form saves as `context.save`; duplicate completed and in-flight requests run nothing again and appear once as `request.duplicate`; hostile message (project key, `api_key=`, URL with password, bearer header, 7,000 characters) and an inspected image leave no secret, base64 or data URL in the table and every payload within the bound; onboarding steps carry their model turns and the context save under one request id; logging disabled, unreachable database (error text containing a password), failing writer, and a real `postgresql://` URL with no driver/host all leave the agent's tool path, status and provider-request count unchanged and `/api/logbook` admits the loss with no credential in it; a request answered locally by routing records only start/end and uses no worker or model.
- Mutation evidence (deliberate defects in an isolated copy, tests went red): request id not passed to main -> LB-9; tool outcome ignoring real results -> LB-3/12/14/15; no scrubbing -> LB-1/18; replay logged as a new start -> LB-16; blocking queue -> LB-4.
- Affected regressions (fresh copies, one at a time): `chat_api_test` 18/18, `onboarding_test` 39/39, `specialist_config_test` 44/44, `e2e_mock` 24/24, `ticket01_regression` 28/28, `social_role_test` 38/38. `.\lint.bat` once after the last code change: passed. No live model, scraper, Gemini or Neon call; the real runtime, profiles, history, secrets and allowances were not touched.

## Limitations

- **Live Neon unverified.** The Postgres statements were executed on SQLite (`JSONB`/`TIMESTAMPTZ` are Postgres types; the test-only URL scheme `ecom-test-sqlite:` maps them). `%s::jsonb`, `to_timestamp(%s)`, `ON CONFLICT` and the psycopg 3 calls are standard but not exercised against a server or against psycopg inside the Hermes venv (not installed there). Run `python -m app.logbook` once the connection and driver exist.
- Best-effort delivery: no durable queue or replay. Rows are lost when the queue is full, while the database is unreachable (15 s back-off), when a write fails, or if the server dies abruptly (a short flush runs at normal exit). A worker killed mid-turn loses only what it had not yet sent.
- `model.call` appears when Hermes reports completion or an error; a call that never returns has no row (the enclosing `request.end` shows the failure). A failed turn that crashes before `request.end` (e.g. a database error after the turn) has no end row.
- Counters in `diagnostics()` are approximate under concurrency (plain integer increments).
- Rejections other than duplicates (agent busy, onboarding gate) are not logged. Hermes' auxiliary calls (title/compression) go through other hooks and are not recorded.
- The model's tool arguments and its answer preview are model claims, stored only under labelled keys; no hidden reasoning is collected. Operator message text is stored as a 300-character redacted preview, so business facts the operator types do appear in Neon.
- No UI, no retention policy, no per-request cost computation (usage fields only).

## Audit of adjacent touched paths

- Fixed with the work: main's routed chat path did not forward `request_id` to the worker, and onboarding turns had none (the identity requirement); the worker's protocol writer now takes a lock because hook threads of parallel tool calls can send log rows.
- Reported, not changed: the `done` replay cache is in-process memory (a server restart forgets completed requests, as before); `chat()` has no `request.end` if the final transcript write raises.

## Review corrections - 2026-10-28 (five findings, `research/ticket-05-neon-review-20261027.md`)

Status: **corrections implemented, awaiting direct Codex verification. Live Neon check still pending.** Method: for each finding a focused check was written first and shown RED against the unfixed code (fast in-process run `ev_lbfix_red_fast`: 7/12, the five new checks LB-24..LB-28 failing), then the fix, then green (`ev_lbfix_green_fast` 12/12; full suite 33/33).

| # | Finding | Failing before (what the check showed) | Fix | Passing after |
|---|---|---|---|---|
| 1 | scalar columns bypass redaction | LB-24: the configured key was stored verbatim in `request_id`, `tool_name`, `provider`, `model` (emit and worker-row `accept()`) | `ident()` / `label()` in `emit()` and `accept()`: every text column is scrubbed and bounded; an identifier that is unsafe or over 80 characters becomes a deterministic `id-<sha256[:20]>` digest, so the backend row, a second backend row and the worker row for the same client id carry the same stored id, different ids differ and safe ids are unchanged; `event_id` must be 32 hex characters (else regenerated); numeric columns must be numbers | LB-24 (unit), LB-31 (end to end: request id containing the key; request.start, model.start, model.call, tool.call, request.end share one stored id; the key is nowhere in the table) |
| 2 | preview sliced before scrubbing | LB-25: with the secret starting at character 276, `...SECRETKEY-for-test-12345` (all but its last character) survived in both previews | `logbook.preview()` scrubs the complete text first and then takes the first 300 characters; used for the operator message and the final answer | LB-25 (neither the full secret nor an 8-character prefix survives in either preview; `<redacted>` present) |
| 3 | no model-attempt start | LB-28: no `pre_api_request` hook, no `model.start` | `model_start` observer on `pre_api_request` (see the event table); linked by `api_request_id`; outcome `unknown` | LB-28 (unit: success and failure completions link, a start without outcome stays `unknown`, only `model.call` rows count as attempts, no prompt text stored), LB-29 (scripted provider sleeping 4 s: the start is already in the table while no `model.call` exists, then exactly one start and one call with the same id), LB-30 (HTTP 500 provider: start + failure call per real attempt, same ids) |
| 4 | transcript-write exceptions skip the terminal event | LB-26: only `request.start` existed after an injected initial-write failure and after an injected final-write failure | `chat()` tracks its stage and has one `except BaseException` that emits ONE `request.end` failure (`stage`, exception type, message, whether the agent run had succeeded) unless the normal end was already emitted, then re-raises exactly as before; nothing is re-run | LB-26 (initial failure: start + one failure end, the agent ran 0 times; final failure: one failure end after exactly 1 agent run; a normal request still has exactly one end) |
| 5 | arriving events extend the reconnect deadline | LB-27: with an event every 10 s and a 15 s backoff the connector was attempted only at t=0 | `_flush_batch()` (the writer's per-batch logic, extracted so the clock is injectable) returns early while backing off without touching `next_try`; only a real failed connection/write sets it | LB-27 (attempts at t=0, 20, 40; the database recovers at 25; the events at t=40 and t=50 are written, no idle period needed) |

Checks: `tests/logbook_test.py` **33/33** (was 25/25; +LB-24..LB-31). Mutation evidence for the end-to-end checks (copy with the start hook unregistered and identifier protection removed): LB-24, 28, 29, 30, 31 fail. Regressions justified by the touched code, fresh copies: `chat_api_test` 18/18, `e2e_mock` 24/24, `specialist_config_test` 44/44. `.\lint.bat` once after the code changes: passed. No live Neon/model/scraper/Gemini call, no dependency installed, real runtime/profiles/secrets untouched, Hermes inference recovery unchanged.

Behavior notes and limits after the corrections:
- A secret-bearing request id is stored as a digest, so it can no longer be looked up by the raw id: query with the id shown in the stored rows (or compute the same digest). Safe ids (the normal case) are unchanged, so the one-request query is unchanged.
- During a backoff the events that arrive are lost (counted in `lost_write_failed`, not in `batches_failed`); recovery now happens at the first batch after the 15 s deadline.
- `model.start` appears once per provider attempt (a Hermes retry is another start); the start's timestamp is Hermes' own `started_at`.
- Still best effort: a start whose worker dies has no completion; the failure `request.end` for a transcript error is emitted only if the logbook itself is healthy. The SQL still ran only on SQLite.
- Adjacent audit: no further defect found in the touched paths. Not changed (unrelated): a failure of the final `UPDATE agents SET state='idle'` inside `chat()`'s `finally` would still replace the original exception, as before.

## Supabase connection and live verification - 2026-10-28

Arjun moved the logbook host from Neon to Supabase (direct SQL kept; no REST rewrite, tracing platform or redesign). Connection notes: `research/supabase-logbook-connection-20261028.md`. The operator saved the Supabase **session-pooler URI** (host `*.pooler.supabase.com`, port 5432, `sslmode=require`) in the ignored `secrets/local.env` as `LOGBOOK_DATABASE_URL`. It was read privately and never printed; the evidence below contains no URI, password or host.

**What changed (code/config).** `app/logbook.py`, `tests/logbook_test.py`, the tracked `secrets/local.env.template` and `requirements-logbook.txt` now use the neutral `LOGBOOK_DATABASE_URL`; the retired `NEON_DATABASE_URL` is not read. The configured value stays in the secret-redaction list. Offline tests remove BOTH names from their own and their servers' environments (LB-32), so an offline run cannot inherit the live connection. Historical reports keep their old wording.

**Adjacent defects found in the small connection diff and fixed with coverage** (all directly about the credential/connection):
1. LB-35: `run_turn` copied the server's whole environment into each Hermes worker, so a database URI set through the process environment (as the live test does) would have reached the workers, contradicting "workers hold no credential". `core.run_turn` now removes both variable names from the worker environment (red before the fix: `LOGBOOK_DATABASE_URL` was in the worker environment; green after). The secrets-file route never leaked it.
2. LB-34: a URI without `sslmode` would have used libpq's default `prefer` (plaintext fallback). `_default_connect` now passes `sslmode=require` only when the URI has no `sslmode`; an explicit one (for example `verify-full`) is never overridden. Mutation check: reverting the default makes LB-34 fail.
3. LB-33: the password inside the configured URI (raw and URL-decoded) is now redacted on its own, so a driver message that quotes the password but not the whole URI is scrubbed. Mutation check: reverting it makes LB-33 fail.

**Driver.** `requirements-logbook.txt` installed into the project's existing Hermes Python (`%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe`, Python 3.11) after a dry run: `psycopg 3.3.4` and `psycopg-binary 3.3.4` (binary libpq implementation) were the only packages added (`typing-extensions` and `tzdata` were already satisfied); `pip check` reports no broken requirements; `import psycopg` works. No other package and not Hermes itself was touched.

**Offline checks (fresh isolated copies, scripted model, SQLite stand-in).** `logbook_test` **37/37** (was 33; +LB-32..LB-35); the fast in-process run was 15/16 with only LB-35 red before the worker-environment fix and 16/16 after; regressions `chat_api_test` 18/18, `e2e_mock` 24/24, `specialist_config_test` 44/44; `.\lint.bat` once after the code changes: passed.

**Live synthetic insert/read (real Supabase).** `python -m app.logbook` with the Hermes Python: `PASS inserted and read back 1 synthetic event(s) for request synthetic-check-1793165898617249300`. This created the dedicated table `ecom_execution_events` and its index (`CREATE ... IF NOT EXISTS`); nothing else was created or altered. Read-only inspection afterwards: the project's `public` schema contains only that table; TLS in use (`ssl_in_use` true); **row level security is enabled on the table with no policies** (Supabase default for new tables), so the project's anon/authenticated API roles cannot read or write it even though they hold table grants; the logger connects as the database owner role, which is why direct SQL works. The insert, `ON CONFLICT`, `%s::jsonb`, `to_timestamp(%s)`, the `statement_timeout` startup option through the session pooler and the ordered read all ran on real Postgres for the first time (before this only on SQLite). No permissions, RLS settings or policies were changed.

**Actual scripted application -> Supabase request.** `tests/logbook_live_test.py` (isolated copy without secrets; the URI is passed only to the server process as `LOGBOOK_DATABASE_URL`; scripted model `tests/mock_llm.py`; synthetic company "Harbor Loom Co (synthetic)"; real backend, HTTP API, Hermes worker and hooks; no ChatGPT/NVIDIA/Gemini/scraper call): **7/7 passed**. Safe request id: **`live-supabase-20261028-054134`**. Stored under that one request id and agent `main`: `request.start`, 2 x `model.start` (outcome unknown), 2 x `model.call` (success, usage 10/5/15 as reported by the scripted provider), 1 x `tool.call` `read_company_context` (success; the observed tool result is stored) and `request.end` (success); each start links to its call by `api_request_id`. The server's writer reported every accepted row written and zero failed, lost or dropped rows. Neither the test key nor the URI appears in the stored rows. Evidence (ignored path): `.scratch/ev_live_supabase.txt`. Query: `SELECT ... FROM ecom_execution_events WHERE request_id = 'live-supabase-20261028-054134' ORDER BY ts, event_id`.

**Real evidence vs scripted behavior.** Real: the database connection over TLS, the table/index DDL, inserts, JSONB and timestamp handling, read-back, the background writer's accounting, and the backend/worker/hook event pipeline into a real Postgres. Scripted: the model replies, the usage numbers and the tool choice (`mock_llm.py`), and the company data. This shows nothing about real-model behavior, real-provider usage figures or load.

**Remaining limitations.**
- `sslmode=require` encrypts the connection but libpq does not verify the server certificate in that mode. Certificate verification needs `sslmode=verify-full` plus the Supabase root CA (`sslrootcert`); not configured, optional operator action.
- Best effort is unchanged: events can be lost (queue full, database down, abrupt stop); SQLite stays authoritative; no durable queue; no judge or evaluation work.
- The synthetic rows (one `logbook.check`, seven for the live request) remain in the table; they are labelled synthetic and harmless.
- Once the operator starts the real server with the setting configured, real business text previews (300 redacted characters) will be written to the hosted database. The real server was not started here.
- The SQLite stand-in remains for offline tests only.
