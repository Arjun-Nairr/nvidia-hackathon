# HANDOUT archive: latency diagnosis and persistent workers (2026-10-09)

Moved verbatim from HANDOUT.md on 2026-10-13 to keep the handout under 400 lines. Superseded in effect by the persistent-worker design (current in HANDOUT).

## Latency diagnosis (tag `ecomtiming`, 2026-10-09, provider openai-codex / gpt-5.6-terra)

Instrumentation (opt-in, no-op unless `ECOM_TIMING=1` in the server's environment; `app/timing.py`, spans in `worker.py`/`core.py`/`server.py`, Hermes hooks pre/post_api_request + post_tool_call registered by the plugin): writes `runtime/timing.jsonl` with stage names, durations, counts and numeric usage only (no prompts, replies, tool args, credentials). Disable by not setting the variable; delete `app/timing.py` plus its few call sites to remove. Rerun: `set ECOM_TIMING=1` then `run.bat`, or `...\venv\Scripts\python.exe tests\timing_diag.py` (live: 4 requests, adds turns to the main conversation, created agent `ecomtiming-diagnostic-analyst`; both deliberately kept).

Measured, one run each (ms; every turn spawns a fresh worker process, so every request is "cold"):

| stage | simple-1 | simple-2 | context question | create specialist |
|---|---|---|---|---|
| **total (server handler)** | **18,261** | **17,531** | **25,672** | **29,063** |
| auth check (`hermes auth status`, cached 30 s) | 1 | 1 | **3,149** | 1 |
| worker process start to first line | 343 | 341 | 331 | 367 |
| import Hermes modules | 5,710 | 5,037 | 5,051 | 4,844 |
| open SessionDB | 229 | 218 | 236 | 231 |
| load history (14-22 msgs) / resolve provider | 12 / 17 | 10 / 22 | 10 / 16 | 12 / 18 |
| AIAgent init (incl. plugin load, tool schemas) | 5,140 | 3,797 | 3,969 | 3,729 |
| model requests (count) | 4,906 (1) | 6,533 (1) | 11,161 (2) | 17,691 (2) |
| tool execution (count) | 0 | 0 | 54 (1) | 481 (1) |
| run_conversation residual, unmeasured | 1,056 | 962 | 1,022 | 1,023 |
| exit after result written (teardown) | 832 | 594 | 660 | 652 |
| backend DB writes around the turn | 12 | 12 | 11 | 13 |

Notes: tool breakdown for create_agent: validate 0.2, write_profile 423 (inside the 481), registry insert 5. Residual = run_conversation minus API minus tools (prompt build, persistence, etc.; not separable with available hooks). Cross-process start gap uses wall clock (about +/-16 ms on Windows). Per-request numbers: model calls took 3.5-12.5 s each; time to first stream chunk 1.0-2.5 s, but 2.2 s ttfb then 4.3 s more for 5 output tokens in simple-2, so the post-first-chunk wait is NOT explained by output length (what the first chunk is, is unverified). Prompts are about 6.3-7.1K tokens per call with only 2 tools (4.6-5.6K served from cache).
- Everything except model+tools (worker spawn, Hermes import, agent init, teardown, residual) is about 11.0 s per turn = 63% of a simple reply and 38% of the creation turn. Model calls are 27-61%. The `create_agent` tool is under 2%. Auth check: 3.1 s every time the 30 s cache expired (also on every cold page load: `/api/status` took 3,041 ms in the browser). Backend and HTTP handling are negligible (about 5 ms); dashboard re-render after a reply is 37-96 ms; page shell loads in 1.7 s and the cold status fetch (3.0 s) completes after it, so the banner/status block appears about 3 s late.
- First vs later requests: no real difference (18.3 vs 17.5 s) because nothing is kept between turns; the only cold effect is the auth cache.
- Reasoning: the app passes no `reasoning_config` (agent.reasoning_config=None, no `agent.reasoning_effort` in profile config), so Hermes' Codex transport default applies (source: "medium"; the wire value was not captured by the hook). Observed reasoning tokens were 0-34 per call, so reasoning is not the driver on these prompts; output generation is (create_agent call: 12.5 s for 305 output tokens).
- Buffering vs latency: Hermes streams from the provider internally (ttfb recorded) but the app has no stream consumer, the worker prints nothing until `RESULT:`, and the HTTP call blocks, so the UI shows a static "working..." for 17-29 s. Actual latency is real (above); the lack of visible progress is a separate, additional problem.
- Largest measured contributors: (1) per-turn Hermes startup, about 9.3-10 s (import 5 s, agent init 3.7-5.1 s, plus 0.3 s spawn); (2) model requests 5-18 s; (3) auth-check subprocess 3.1 s intermittently; (4) teardown 0.6-0.8 s.
- Recommended smallest next fix (IMPLEMENTED, see Persistent workers below): one long-lived worker per agent profile plus a cheap auth check.


## Persistent workers (2026-10-09, same provider/model gpt-5.6-terra; real runtime, `tests/worker_live_diag.py`)

Change: workers are kept alive per profile (above). Auth check no longer spawns `hermes auth status`: `core.codex_auth_error()` calls Hermes' own read-only credential status (`resolve_codex_runtime_credentials(read_only=True)`) in-process with HERMES_HOME forced to the project home (no refresh, no write, no Codex-CLI adoption); cached 10 min when signed in, 3 s when not. Nebius: key presence check only. `GET /api/status` went from 3,041 ms (cold) to 18 ms.

Measured live, one run each (ms). Baseline = table above (fresh process every turn). Model time is variable and reported separately.

| request | total | model | tools | non-model overhead | worker |
|---|---|---|---|---|---|
| main, first (cold: spawn + import 3,058 + agent init 4,659) | 12,651 | 3,341 | 0 | 9,310 | spawned |
| main #2 / #3 | 2,462 / 2,245 | 2,372 / 2,152 | 0 | 90 / 93 | reused (pid unchanged, agent_inits=1) |
| specialist, first (cold: import 5,553 + agent init 4,938) | 16,207 | 3,788 | 0 | 12,420 | spawned |
| specialist #2 / continuity / tool listing | 1,875 / 1,983 / 4,190 | 1,796 / 1,905 / 4,111 | 0 | 79 / 78 / 79 | reused |
| main tool listing | 4,378 | 4,291 | 0 | 87 | reused |
| main creates `workertest-diagnostic-analyst` (2 model calls, 1 tool) | 11,274 | 10,464 | 639 | 171 | reused |
| specialist after app restart (cold) | 14,977 | 2,994 | 0 | 11,983 | spawned (no worker existed before first use) |
| specialist after its idle worker was killed | 14,355 | 3,069 | 0 | 11,286 | spawned (recovered) |

- Startup savings: non-model overhead on reused turns is about 80-95 ms (history re-read 15-21 ms, credential re-resolve, DB writes, Hermes bookkeeping) versus about 11 s per turn before: roughly 10.9 s saved on every turn after the first. The first turn per agent (and after restart/crash) still pays about 9-12 s (import 3.1-5.8 s + agent init 4.1-4.9 s + spawn); that is the lazy-start cost and was not prewarmed. Simple replies are now bounded by the model: 1.8-2.5 s here (earlier runs had 4.9-6.5 s for the same prompt, so do not read a fixed latency from these numbers).
- Verification, live: reuse confirmed by `/api/workers`-style fields (same pid, `agent_inits_total` stays 1, no `import_hermes`/`agent_init` spans after turn 1); continuity (specialist answered the saved sign-off 'Ferrous Heron' in the reused conversation and again after an app restart); tool isolation (specialist listed memory/read_company_context/skills tools without `create_agent`; main listed `create_agent`, `read_company_context`); test agent created through main's reused worker; restart kept 4 agents, all transcript row counts and memory files; killing an idle worker recovered on the next request.
- Verification, isolated copy with scripted model (`tests/workers_mock.py`, 22/22; wipes its own runtime, refuses to run without `WORKERS_MOCK_I_AM_A_COPY=1`): lazy start, reuse across turns, specialist has its own worker, exactly +2 Hermes rows per plain turn (no duplicate history), growing history seen by the model, preference reaches a brand-new session after restart, workers exit with the server, idle kill recovery, mid-turn kill gives an explicit not-replayed error (the model saw the turn exactly once) and the next request recovers, timeout stops the worker and recovers, model change restarts the worker on the new model, switching to codex without login gives the login error with zero model requests. `tests/e2e_mock.py` re-run on a fresh copy: 24/24.
- Not verified: token expiry across a long-lived worker (the live runs were minutes long; reuse relies on Hermes' per-turn resolve plus its 401 refresh path); behaviour with many simultaneously active agents (each worker holds a full Hermes runtime, no idle shutdown yet).
