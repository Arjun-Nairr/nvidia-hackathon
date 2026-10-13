# V2-04 code review — 2026-10-13

Outcome: CORRECTIONS REQUIRED; not accepted. Two isolated axes reviewed the working changes plus new flyer module/tests against pinned Git checkpoint `9d9ecbedd2a6aa220114ac0fae63be4899549ada`. No production code changes, paid calls, commit or push.

## Standards

No actionable introduced standards finding. Reviewer confirmed backend role/grant and trusted request checks, atomic pre-send reservations, isolated asset/read boundaries and API-driven UI. This is scoped static inspection, not a security audit or live provider verification.

## Spec

1. **P2 — Stored artifact integrity is not rechecked** (`app/flyer.py:324–331,385–396`). Successful persisted outcome alone drives unchecked/success state. The endpoint serves current file bytes without validating the saved hash/size/decoding. A missing file yields404 while the record still advertises a usable flyer; a damaged/replaced file is served. Violates unreadable-output/storage-failure requirements and unchanged saved retrieval. Validate the persisted artifact on read, report storage/integrity failure consistently, and never regenerate automatically. Codex reproduced by replacing one isolated test artifact with invalid bytes: image_file served them and get_flyer remained unchecked; original bytes restored afterward.
2. **P2 — Malformed response containers escape classification** (`app/flyer.py:245–247,532`). `steps: 1` or model-output `content: 1` raises TypeError after transport completes. Attempt remains dispatched without terminal error/status/timing/usage, and retries report uncertainty. Violates explicit provider failure and durable outcome requirements. Validate container types and persist a consumed malformed-response failure. Codex independently reproduced the steps TypeError through a pure helper probe.
3. **P2 — No-image diagnostic can expose an echoed credential** (`app/flyer.py:252–253,540`). Provider text is incorporated into persisted/user-visible error without the key redaction used by other error paths. Violates private credentials requirement. Redact provider-derived diagnostics consistently before storage or exposure. Codex independently used a fake sentinel, not a real key: the returned diagnostic contained it.

Reviewer checked the official Interactions reference and found the current model/request/response contract consistent. Missing live assets/credentials/provider evidence remain explicit dependencies, not additional defects.

## Independent verification

- `.\lint.bat`: exit0 (Ruff/ESLint).
- `tests/flyer_test.py`: **32/32**, isolated `.scratch/review-v2-04-20261013`; real Hermes/server and local scripted Gemini/reasoning stand-ins, no real secrets/runtime copied. Verified grants, original selected input bytes/context, atomic attempts, errors, read APIs/UI wiring and restart retrieval without calls.
- Additional root probes confirmed all three reported gaps; existing32 checks do not exercise them. Other broad regression results are Claude-reported, not repeated here.

Next: one scoped correction prompt for these issues and focused self-audit. Direct Codex verification afterward; no repeat two-reviewer pass for this ticket. Ticket5 remains undispatched; real Gemini quality and Nebius/NVIDIA compatibility remain unverified.
