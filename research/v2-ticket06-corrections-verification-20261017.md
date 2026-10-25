# V2-06 runner corrections — direct verification, 2026-10-17

Direct Codex inspection of the five findings in `research/v2-ticket06-offline-runner-review-20261016.md`; no code-review skill/team repeated. Original implementation checkpoint remains `98758d9`; corrections are in the working tree. No production app module changed, live calls, credential operations, commits or push performed by this verification.

## Inspected fixes

1. `phase_outcome` reads request/agent/scope-bound flyer and research records and verifies artifact integrity, actual-image inspection and delivery-verified review. Successful chat without these records becomes incomplete and cannot unlock the demo. Negative but verified content reviews are valid technical probe outcomes. Demo also requires research evidence and explicit final selection with rationale.
2. Stack teardown discovers owned descendants, terminates/waits/kills and records confirmation. Unknown completion remains unknown. Unconfirmed shutdown marks the runtime unstable and prevents a verified snapshot/retrieval claim. Uses existing installed psutil; no new dependency installation.
3. Command entry holds a per-demo OS lock before loading phase state, through execution. OS release covers process death; temporary state filenames are per-process. Read-only status does not acquire the mutation lock.
4. Supplied catalogue/registered photos are copied into the isolated demo at preparation. Archive checks catalogue and photo hashes against generation records and preserves matching bytes, including provenance. Missing/replaced files are disclosed and do not receive a completed archive claim.
5. Restart retrieval uses a separate app/runtime copy without Hermes home, OAuth files or API-key configuration; the app must report inference unavailable. It checks served image hashes, unchanged dispatch records, environment and credential inventory. Original/demo OAuth files remain untouched by retrieval.

## Verification

- Independent Ruff/ESLint and whitespace checks passed.
- Independent correction regression suite **40/40 passed** against local scripted providers. Log `.scratch/v206-codex-corrections-20261017.log`; inspectable artifacts `.scratch/v206-fix-20261017T231929`. Dummy credentials and synthetic images only. Covered missing/unknown/unverified probe outcomes, honest negative reviews, research/final requirements, worker quiescence, unconfirmed teardown, concurrent invocations, input snapshots/mismatches, dummy OAuth exclusion, restart image hashes/zero provider requests and bounded pre-turn startup recovery. The deliberate simulated archive crash is an expected test, not a remaining failure.
- Accepted main/specialist and provider behavior is unchanged. No reason to repeat unrelated analyst, UI or paid compatibility suites for runner-only changes.

## Limits

Scripted wiring/enforcement is distinct from real model behavior, Gemini output quality and commercial usefulness. The live runner path, demo authentication arrangement, real merchant inputs, approved allowances and NVIDIA/Nebius compatibility remain unverified. Reasoning totals remain observed/iteration-bounded, not an exhaustive hard API-attempt budget. Existing local loopback resets/startup stalls remain undiagnosed; bounded startup retries happen before a turn is sent, never replay a paid turn.

Result: the five corrections and offline runner are accepted at the scripted evidence level. No new blocking finding in these touched paths. V2-06 itself remains incomplete until its separately authorized live demonstration and Arjun's visual judgment. Next: real inputs/auth arrangement, then the approved probe; no further speculative runner hardening.
