# V2-06 live-test readiness, 2026-10-15 (plan corrected after research/v2-ticket06-readiness-review-20261015.md)

> HISTORICAL LIVE-RUNNER PLAN: superseded 2026-10-25 by HANDOUT.md. The demo will use the existing project login/runtime with reviewed data preservation; do not follow this note's second-sign-in instructions or expand its isolated live runner. Its scripted evidence and accounting cautions remain reference material. No new live run authorized.

Three separate levels, none of which is live validation:
1. **Input readiness**: private inputs exist and pass `python scripts/v2_06_readiness.py`. Status: NOT READY (Gemini key empty, catalogue absent).
2. **Executable-plan readiness**: the plan below is agreed AND harness items H1-H4 are built and scripted-tested. Status: met at scripted level. The offline runner (H1-H4, section 7) and its five review corrections (section 7a) were accepted 2026-10-17 (independent 40/40 + lint; research/v2-ticket06-corrections-verification-20261017.md). Real authentication, real inputs, Gemini billing and approved allowances remain unresolved.
3. **Live validation**: the probe and the demonstration have run and been judged. Status: **none; no provider, scraper, Gemini or Nebius call has been made.**

Checkpoint: accepted ticket5 is local commit `98758d9` (later push status unverified). Ticket6's live demonstration is not claimed. No app code, credential, runtime, profile, ledger or company/agent state was changed by the plan correction.

## 1. Input checklist (offline)
| Item | State |
|---|---|
| `secrets/local.env` ignored by Git | yes |
| `GEMINI_API_KEY` | field present, **empty** |
| `GEMINI_MODEL`, `GEMINI_IMAGE_SIZE` | absent; code defaults `gemini-nano-banana-2.1` / `2K` apply (add an explicit `GEMINI_MODEL=` line before the live run) |
| `SCRAPECREATORS_API_KEY` | set (balance unknown) |
| Reasoning provider/model | `openai-codex` / `gpt-5.6-terra` (unchanged) |
| Live evidence that images reach this model | V1 `inspect_image`, 2026-10-10. V2-05 delivery confirmation on the live Responses payload is **unproven** (probe item); a mismatch fails closed to UNCHECKED |
| Merchant catalogue / photos / provenance | **absent** (default catalogue is the fictional fixture, which generation refuses) |
| Input folder ignored by Git | yes (`demo/`; the checker re-verifies) |

**Where to put things**
- Key: `secrets\local.env`, existing line `GEMINI_API_KEY=`. Never paste it into chat.
- Photos: `demo\v2-06-inputs\images\`; 2-3 real photographs of ONE home-textile product, JPEG/PNG/WEBP, 8 MB or less each; file name without extension = `image_id`.
- Catalogue: copy `demo\v2-06-inputs\catalogue.TEMPLATE.json` to `catalogue.json` there and fill it (`README.txt` beside it).
- Facts: product name and id; real specifications; price amount and currency. Per photo: what it shows and provenance (owner, date, usage statement). `merchant.name` must equal the demo company's saved name.

## 2. Authentication arrangement (corrected)
**Rejected:** copying the project's `runtime/hermes_home/auth.json` into the demo and deleting it afterwards. Hermes login tokens are single-use with rotation; if the copy refreshes first, the original's refresh token is already spent and deleting the copy does not undo that (Hermes: `hermes_cli/auth_codex.py` `_refresh_codex_auth_tokens`, `_save_codex_tokens` docstring; OpenAI Codex CI/CD guide: "Do not share the same file across concurrent jobs or multiple machines"). Also rejected: moving the original file (takes the real install's login away while it is in use).

**Proposed (Arjun has not chosen yet): a separately authenticated demo session, one refresh owner per chain.**
| Credential | Owner (only process that refreshes it) | Demo may |
|---|---|---|
| Original project login `runtime\hermes_home\auth.json` | the real app and `.\login_codex.bat` | never read, copy, refresh or delete |
| Demo login `<demo>\runtime\hermes_home\auth.json` | the demo copy's Hermes root; its specialist profiles fall back to it and write refreshed tokens back to it (supported: `_provider_state_transaction`, write-through in `_save_codex_tokens`) | create once by sign-in, refresh, delete at cleanup |
| Personal `~/.hermes`, `~/.codex` | personal tools | never touched; `core.profile_config()` writes `auth.adopt_external_logins: false` into every project config, so automatic adoption of `~/.codex/auth.json` is off. Answer **N** to the interactive "import Codex CLI login?" prompt |
| Gemini and ScrapeCreators keys | static API keys, no rotation | copied by name into the demo's `secrets/local.env` (values never printed) |

**Setup.** If the arrangement is accepted, the demo needs its own sign-in stored only in `<demo>\runtime\hermes_home\auth.json`. The runner neither performs nor copies in a login (`login_codex.bat` is not part of the demo copy), so the exact sign-in command is still to be settled. **Arjun performs the one interactive sign-in**; the agent never logs in, handles tokens or sees them. Do it immediately before the probe, not earlier.

**Residual risk, stated plainly.** Hermes documents (`website/docs/user-guide/features/credential-pools.md`, `auth_commands._warn_same_codex_account`, issue #47096) that two logins of the same OpenAI account can share one token family so the older one is revoked. OpenAI's Codex authentication pages are silent on separate logins invalidating each other; I did not test it and cannot without signing in. Consequences: after the demo sign-in the original login might need `.\login_codex.bat` again (re-sign-in only; no data loss). Zero-risk variant: sign the demo in with a different ChatGPT account (that account's subscription limits then apply). Arjun chooses; the plan works with either.

**Cleanup.** After the archive is verified the runner removes the API-key lines from `<demo>\secrets\local.env`; deleting `<demo>\runtime\hermes_home\auth.json` is Arjun's manual step (the demo's own grant only; it removes the local file, it does not revoke the grant upstream). The original login and personal tools are not part of cleanup. If the real app later reports "not signed in", run `.\login_codex.bat` there.
**Do not reuse** `scripts/research_live_launch.py` unchanged: it copies the real `auth.json` (V1 pattern, now superseded for V2).

## 3. Executable sequence
Server environment is read at start-up (iteration caps, `ECOM_ADS_*`, `ECOM_FLYER_*`), so each phase starts the server fresh on the SAME persistent demo runtime with its own scope names. A scope's cap is fixed at its first use and never re-sized, so a phase cannot borrow from another.

| # | Step | Needs approval | Provider traffic |
|---|---|---|---|
| 0 | Offline: inputs READY (checker); runner built, scripted-tested and accepted 2026-10-17 | Arjun | none |
| 1 | Build demo copy; Arjun's one sign-in (section 2) | go-ahead | OpenAI sign-in only, no inference |
| 2 | **Provisioning.** Save company through the backend form (no model). ONE main/Laya message creates ONE social specialist with ad research, `inspect_image`, `read_catalogue` and the flyer tools. The harness sends exactly one message; if main asks something it stops and reports. Env: `ECOM_CHAT_MAX_ITERATIONS=6`; scrapers and Gemini scopes at 0 | with the plan | reasoning only (Laya is local) |
| 3 | Verify specialist, tools and company; stop; report | - | none |
| 4 | **Probe**, ONE specialist message = ONE manual request id. In that same request the specialist generates one flyer from one real photo with no competitor research, then `inspect_flyer`, then `review_flyer` on that candidate (review is bound to agent + request, so it cannot happen in another request). It must not correct or select. Env: `ECOM_FLYER_SCOPE=v2-06-probe`, `ECOM_FLYER_MAX_ATTEMPTS=1`, `ECOM_ADS_SCOPE=v2-06-probe`, `ECOM_ADS_API_MAX=0`, `ECOM_ADS_IMAGE_MAX=0`, `ECOM_FLYER_MAX_ITERATIONS=8` | **separate go** | 1 Gemini call, specialist reasoning |
| 5 | Archive probe evidence; stop; report key, billing, model, request shape, integrity, delivery confirmation, measured token usage. A failed probe consumed its one attempt; a rerun needs a NEW approved scope, never a reset | - | none |
| 6 | **Demonstration**, ONE message = ONE manual request id: ad research (US Facebook image ads), inspect merchant photos, generate, inspect/review, at most one correction, one selected final. Env: `ECOM_FLYER_SCOPE=v2-06-demo`, `ECOM_FLYER_MAX_ATTEMPTS=2`, `ECOM_ADS_SCOPE=v2-06-demo`, `ECOM_ADS_API_MAX=8`, `ECOM_ADS_IMAGE_MAX=4` (run caps 8/4 default), `ECOM_FLYER_MAX_ITERATIONS=30` | **separate go after Arjun reads the probe report** | scraper, downloads, Gemini, reasoning |
| 7 | Archive (sanitized result, manifest hashes, candidate and reference images, prompts, review traces, usage, timing) BEFORE any cleanup | - | none |
| 8 | **Restart retrieval** from the credential-free copy of the demo (section 7): fetch final image and flyer data over the app's own API; verify hashes and unchanged ledgers (zero provider requests) | - | none |
| 9 | Cleanup (section 2) | - | none |

No automatic rerun, reset, or second message in any phase, and no automatic resubmission of a paid turn. A lost local HTTP answer (undiagnosed resets) is resolved by read-only polling and reading the backend transcript; if that does not confirm a finished turn the phase stays `unknown_completion` (section 7). Only a local start-up stall BEFORE a turn is sent is retried (once, on fresh ports, recorded).

## 4. Allowances: hard limits versus estimates
**Hard, backend-enforced counts** (ledgers in `app.db`; failures and unknown outcomes count)
| | Provisioning | Probe | Demo | Combined |
|---|---|---|---|---|
| ScrapeCreators API requests | 0 | 0 | 8 | 8 |
| Ad image downloads | 0 | 0 | 4 | 4 |
| Gemini generations | 0 | 1 | 2 (initial + at most one correction) | 3 |

The probe's zeros rely on `_env_int` accepting 0; the scripted tests confirm a 0 cap refuses before any request.

**Reasoning requests are not ledger-limited.** The only enforced bound is the per-turn iteration cap on the main agent loop (one model request per iteration when nothing retries; an exhausted turn adds one summary request). It does not cap every API attempt. Hermes also retries a failed attempt up to `agent.api_max_retries` (default 3) and has post-exhaustion auto-recovery cycles (default 5); the project's generated config sets neither.
| | Provisioning | Probe | Demo | Combined |
|---|---|---|---|---|
| Main-loop count, assuming one request per iteration (+1 summary) | 6+1 = 7 | 8+1 = 9 | 30+1 = 31 | 47 |
| Main-loop calculation if Hermes defaults stay (from one scripted observation: 18 requests for ONE failing iteration, 3 retries x 6 recovery cycles) | up to 126 | 162 | 558 | 846 |
| Measured (V1 live, one sample) / unmeasured estimate | **3** measured (V1 main turn) | 4-5, design estimate, unmeasured | roughly 15-25, unmeasured (V1 analyst turn used 9 for 20 tool calls) | about 25-35, unmeasured |

Recommended **harness setting**, no app-code change: write `agent: {api_max_retries: 1, auto_recovery_cycles: 0}` into the demo copy's root and profile `config.yaml` files before provisioning (main) and again after the specialist is created and before the probe. With that setting the main-loop count above assumes one request per iteration and no other model-request path; a transient failure ends the turn and is reported, not retried. Without it the larger row is the matching calculation. Measured, scripted only (2026-10-15, the project's own worker): a provider answering HTTP 500 received 18 requests for one user turn under the default settings (306 s) and exactly 1 with the demo settings (15 s); `tests/v2_06_demo_test.py` 6a asserts the 1. Both rows are conditional calculations, not exhaustive API-attempt limits. Auxiliary Hermes requests (for example context compression), fallback providers and any other uncounted path are unverified and no hard cap is claimed for them; the per-turn `api_calls` timing log records what was observed, and whether Hermes' retried attempts appear in that log is unverified.

## 5. Cost accounting
**Documented rates** (Google official pricing page, standard paid tier for `gemini-nano-banana-2.1`, "last updated 2026-10-15 UTC", read today: https://ai.google.dev/gemini-api/docs/pricing#gemini-nano-banana-21):
- Input tokens (text/image): $1.50 per 1M. Text and thinking output: $7.50 per 1M. Image output: $30.00 per 1M tokens = $0.0336 (1K, 1,120 tokens), $0.0504 (2K, 1,680 tokens), $0.113 (4K, 3,780 tokens). No free tier.
- Image-output component for the combined cap of 3 generations at the configured 2K: 3 x $0.0504 = **$0.1512** (documented rate x maximum count; assumes one 2K image per call; whether failed or blocked calls are billed is unknown).
- Input and text/thinking components are **not estimated**: token counts for 1-3 photos plus prompt, and any thinking output, are unmeasured. Rate arithmetic only: each 100k input tokens is $0.15 and each 100k text/thinking output tokens is $0.75.
- The app stores each Gemini response's `usage`; the probe will turn these into **measured** per-call numbers.

| | Documented rate | Measured | Unmeasured estimate / unknown |
|---|---|---|---|
| Gemini image output | $0.0504 per 2K image | none (no call ever made) | ceiling $0.1512 for 3 |
| Gemini input / text / thinking | $1.50 / $7.50 per 1M | none | token counts unknown |
| ScrapeCreators | vendor documents credit units per request; price per credit not asserted | none in V2; V1 allowances already consumed | account plan, balance and credit price unknown (unit not re-verified here) |
| Reasoning (openai-codex subscription) | no per-request dollar charge | request counts only (V1: 3 and 9) | plan usage limits and accounting unknown |
| Google billing account | - | - | billing enabled? fees/taxes/rounding unknown |

**The call counts above are not a dollar ceiling.** Only the image-output component is bounded by the 3-generation ledger. Input/thinking tokens, retries and account-side charges are not capped by this plan. A provider-side spending cap, if wanted, is an account setting I have not verified.

## 6. Dependencies and blockers
**Needed from Arjun**
1. Gemini key from a billing-enabled Google project in `secrets\local.env` (and an explicit `GEMINI_MODEL=` line).
2. 2-3 real photos and the filled catalogue (facts, provenance), merchant name equal to the demo company name.
3. Authentication choice: separate sign-in on the same account (risk in section 2) or a different account; availability for the one interactive sign-in.
4. Approval of the counts (section 4), or different ones.
5. A separate go for the probe, and another for the demonstration after the probe report is read.

**Implementation dependencies:** H1-H4 are built as `scripts/v2_06_demo.py` + `tests/v2_06_demo_test.py` + `tests/v2_06_demo_fixes_test.py` (sections 7, 7a), scripted-tested and accepted at scripted level only. Still open: the live code path (provider URLs real, Laya environment, demo sign-in) has never run; the authentication arrangement; `GEMINI_MODEL=` and key; real inputs.

**Other blockers/risks:** V2-05 delivery confirmation on the live Responses payload is unproven (probe item, fails closed); the local connection-reset issue on large responses is undiagnosed and not fixed; US Facebook image-ad coverage is unverified and reach is expected to stay gated; review accuracy and Gemini correction fidelity are unverified (one sample judged by Arjun is not evidence of effectiveness); catalogue/company name mismatch blocks the run; Nebius/NVIDIA path is untouched and unverified.

## 7. Offline demo runner (implemented 2026-10-15; accepted at scripted level 2026-10-17; scripted providers only, not live-proven)
Files: `scripts/v2_06_demo.py` (runner), `tests/v2_06_demo_test.py` and `tests/v2_06_demo_fixes_test.py` (behavioural tests), `tests/mock_llm.py` (+ an `LLM_500` marker so retry behaviour can be counted). No application code changed. Phases are separate invocations; each is recorded in `<dir>/runner_state.json` BEFORE its request is sent and a paid phase can never be started again in that directory (only the read-only archive and retrieval phases may be repeated after a crash or failure).
```
python scripts/v2_06_demo.py prepare   --dir demo/v2-06-live-<stamp> --mode scripted        (live: --mode live --env-source F --catalogue C --images I --auth-arrangement demo-own-signin-accepted)
python scripts/v2_06_demo.py provision --dir D          [--live-authorized in live mode]
python scripts/v2_06_demo.py probe     --dir D          [--live-authorized in live mode]
python scripts/v2_06_demo.py demo      --dir D --approve-demo [--live-authorized]
python scripts/v2_06_demo.py archive   --dir D
python scripts/v2_06_demo.py retrieve  --dir D
```
- **Isolation:** copies only `app/`, `scripts/setup.py`, `scripts/marketplace_check.py` (code the app imports) and, scripted only, the three stand-ins; creates its own `runtime/`, `secrets/local.env` (dummy values in scripted mode; named lines from `--env-source` in live mode, values never printed). Never reads the real project's runtime, secrets or auth files and never logs in, imports or refreshes a login. Its only auth-file reads are of the isolated demo's OWN auth files, scanned for OAuth token values so they can be redacted from archives and verified absent from the retrieval copy; real project and personal credentials stay out of scope.
- **Scopes (separate, durable, created once):** provisioning flyer 0 / scraper 0 / downloads 0; probe 1 / 0 / 0; demonstration 2 / 8 / 4. Per-phase iteration caps: main 6, probe 8, demonstration 30 (+1 summary request each). Demo-only `agent.api_max_retries: 1`, `auto_recovery_cycles: 0` are written into the root, main and (before its first worker) the new specialist's config.
- **Observed, not enforced:** per phase the runner records the stand-in request counts (scripted) and the timing log's `api_end` events; the demo-only retry setting was checked against a provider that answers HTTP 500: 1 request with the demo settings, 18 with Hermes' defaults. Not counted/enumerated: auxiliary Hermes requests (for example context compression), any Hermes retry path outside those two settings, and in live mode there is no independent provider-side counter.
- **No resubmission:** one POST per phase; a timeout, reset, unreadable answer or failed turn is followed by read-only polling for `--settle` seconds. If the backend transcript then shows this turn's agent/error row, the outcome is taken from it (`answer_lost_in_transit`, `confirmed_from_transcript`; the local reset really did drop a finished demonstration answer once); otherwise the phase is `unknown_completion` (exit 3), and a `failed` turn also exits 3. The runner never replays a request id (same-server replay is not restart-safe idempotency) and never resubmits a paid turn. Only read-only GETs are re-read after a transport fault (up to 5 tries, each fault recorded under `read_retries`): the undiagnosed local reset hit 4 of 30 reads of a ~109 KB transcript during development and once crashed an archive before this was added. The reset is still undiagnosed and not fixed.
- **Live guards:** live phases refuse without `--live-authorized`, while the authentication arrangement is `unresolved` (the default), and without the demo's own `runtime/hermes_home/auth.json`. The runner does not create that file; the sign-in is Arjun's separate step and the same-account risk in section 2 stands.
- **Evidence:** `archive/<stamp>/` with manifest and hashes, ledgers, agents, transcripts with tool activity, flyer detail JSON (prompts, attempts, reviews, usage where reported), candidate/final/reference images, ad runs and packages, the merchant catalogue (with provenance) and photos actually used (`inputs/`, `inputs_check.json`), timing log, observed counts. Secret values (API keys and the demo's OAuth tokens) are replaced before writing and re-scanned after. Key lines (not provider/model lines) are then removed from the demo's `secrets/local.env`. The demo's own sign-in file, if one exists, is left for Arjun to delete.
- **Retrieval:** archive hashes are re-read from an isolated, credential-free COPY of the demo (`<demo>/retrieval/<stamp>/`: app code, runtime database and managed files only; no Hermes home, no `auth.json`, no certificate bundle, env file without keys). The application's own provider-readiness check, asked inside that process, must report inference unusable; the retrieval process environment must hold no key/token variable; stand-ins (scripted) must see zero requests; dispatch tables and ledgers must be unchanged in both the copy and the demo. In live mode the Gemini/scraper URLs point at a dead port as an extra guard, but that is NOT the evidence that Codex inference is disabled: the missing login is.

### 7a. Corrections after the offline-runner review (implemented 2026-10-16; accepted at scripted level 2026-10-17, independent 40/40 + lint; NOT live-proven)
`research/v2-ticket06-offline-runner-review-20261016.md` found five defects; each was reproduced by a failing regression first (`tests/v2_06_demo_fixes_test.py`, 5/36 passing before the fixes) and then fixed in the runner only.
1. **Outcomes are validated from backend records, not chat success.** A probe is `completed` only with a flyer run of this agent/request/probe scope, a valid generated candidate, and a delivery-verified review bound to this agent/request and to an inspection of exactly that candidate's pixels. A verified review reporting content defects IS a valid probe result (recorded as `review_verdict`). Otherwise the phase is `incomplete` (exit 3) with the reasons in `outcome.problems`, evidence preserved, and the demonstration stays locked. A demonstration additionally needs this request's non-blocked ad-research package cited by the flyer, an explicit final selection with rationale, and a delivery-verified review of the selected candidate (unresolved issues are reported as such, never converted to a pass).
2. **Teardown stops and waits for owned processes.** Stopping the app server on Windows skips its worker cleanup, so teardown now collects every descendant of the processes the stack spawned plus python processes started during the stack's life whose working directory is inside the demo, stops them (terminate, then kill), waits, rescans and records `teardown.<phase>`. Nothing else is touched (not the real project, not personal Hermes). An unconfirmed shutdown sets `unstable_teardown`: the archive then reports `unstable_snapshot` (manifest `stable_snapshot: false`) and retrieval is refused. Stopping local processes cannot undo a request they already dispatched: that stays an unknown completion, with consumed allowances preserved.
3. **Exclusive claim.** Every phase command first takes an OS-held lock (a file in the system temp folder keyed by the demo path; released on exit or process death) before it reads state; a competing invocation is refused with "another invocation holds this demo directory" before it starts a server or sends anything. The state file's temporary name is per process.
4. **Merchant inputs are preserved and validated.** `prepare` COPIES the catalogue and the registered photos into the demo (`inputs/`) and records their hashes; the demo reads only its own copy, so later changes or removal of the external originals cannot alter or hide what was used. `archive` stores the catalogue and photos only if their current hashes equal the hashes the flyer attempts recorded (or the prepare-time snapshot when nothing was generated); a changed or missing file is disclosed in `inputs_check.json`, is not archived as the original, and makes the archive `inputs_mismatch` (exit 3) while all other evidence is still written.
5. **Retrieval is credential-inaccessible** (see Retrieval above); the credential scan now includes OAuth tokens found in the demo's own auth files.

Adjacent notes (not fixed here): the archive step still serves its read-only GETs from the demo directory itself, where the demo's own OAuth file is reachable (it sends no model request, but the same copy arrangement could be used); the lock files in the system temp folder are small and never deleted; a Windows loopback stall once left a readiness probe waiting for minutes, so readiness waits now have a hard wall-clock bound and a short per-request timeout.
