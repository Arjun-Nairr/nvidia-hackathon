# V2-06 readiness verification — 2026-10-15

Direct inspection, no code-review skill/team. Ticket5 checkpoint confirmed locally: `98758d97611ad2877ce40d5d4a4bb7270651445d`. No push performed here.

Offline preparation is usable; the proposed live execution plan requires correction before approval. No live calls or credential changes occurred during this review.

## Checked

- Read `scripts/v2_06_readiness.py`: offline file/Git/image checks, no provider dispatch or database write. Independently ran it; current state correctly NOT READY (Gemini key empty, catalogue absent). Photo/provenance checks cannot run until a catalogue exists.
- `.\lint.bat`: passed. Private template/photo paths are Git-ignored and no runtime/secrets were tracked in the checkpoint according to the reviewed commit/file listing and earlier staged scan report.
- The large added-line count is predominantly the accepted ticket5 checkpoint (5239 additions including2362-line scripted trace and1254-line review tests), not a new readiness framework. Uncommitted readiness code is one small offline checker plus documentation.
- `GEMINI_MODEL` and image-size fields remain implicit defaults; explicit demo configuration is still needed before live execution. Offline input readiness alone does not verify billing, auth, harness or provider capability.

## Correct before live execution

1. **Credential isolation:** readiness note proposes copying the project's refreshable `auth.json`, then acknowledges the copy could refresh a single-use token and invalidate the original login. Deleting it afterward does not prevent that damage. Replace with a supported single canonical credential/refresh owner or a separately authenticated demo session, validated against Hermes behavior. Do not approve cloning refresh tokens as the default. Original login must remain usable.
2. **Budget semantics:** reasoning43 is calculated from iteration counts, not an enforced API-attempt budget; transport retries, fallback/auxiliary calls and provisioning phase allocation are not fully accounted. Clearly distinguish hard caps from estimates and place main provisioning in the phase where it is actually performed. Probe generation/review must share the trusted manual request because candidate review ownership is request-bound; a separate turn with a different request ID cannot review the probe candidate. Document one executable request sequence before implementing the harness. No need for a general metering framework.
3. **Cost estimate:** Gemini summary omits charged text/thinking output and asserts expected input cost under$0.01 without measured token usage. [Official pricing checked2026-10-15](https://ai.google.dev/gemini-api/docs/pricing#gemini-nano-banana-21): input$1.50/1M, text/thinking$7.50/1M, image output$30/1M ($0.0504 for2K). Three2K image-output components total$0.1512; input/text/thinking are additional and unmeasured. Remove unsupported total expectations and third-party ScrapeCreators price guesses; account/credit cost unknown until verified.

## Remaining dependencies

Live Gemini key/billing,2-3 real merchant photos and verified facts/provenance, a small scripted-tested live harness and separately approved execution allowance. The read-only helper currently checks inputs, not complete operational readiness. Local HTTP resets remain undiagnosed. No paid budget, API call, profile creation or ledger reset authorized by this review.

Next: narrow plan correction, then input collection and scoped harness preparation. Preserve current accepted app code; no new full review team needed for a documentation correction.

## Direct follow-up verification — 2026-10-15

Claude corrected the plan: no cloned OAuth file, generation/inspection/review within one trusted probe request, separate provisioning phase, and complete Gemini charge components with unknown usage disclosed. Inspected the updated readiness note, handout, ticket and index. No app-code changes or live calls in this correction. Whitespace check passed; no reason to repeat application suites for documentation.

Installed Hermes source confirms `agent.api_max_retries: 1` and `auto_recovery_cycles: 0` are supported. Project `sync_profiles()` preserves these extra config keys; newly created specialist config must be patched before its first worker starts, as proposed. The retry table is still not an exhaustive inference-attempt ceiling: auxiliary/fallback/transport paths need a scripted harness check before claiming that. Do not use the default-three row as a hard ceiling while auto-recovery remains enabled.

Remaining execution conditions, to settle in the small harness task rather than another broad documentation round:
- A separate login on the same account is explicitly documented as potentially revoking the original. It does not yet meet ticket6's unchanged-credentials requirement. Choose a supported shared canonical refresh arrangement, or obtain Arjun's explicit acceptance of the re-login tradeoff; do not silently choose another account or login.
- Do not automatically rerun an incomplete/failed turn on connection loss. In-memory completed-request replay is safe only while the original server remains alive and confirms completion. Unknown completion must stop and preserve evidence; request-ID reuse alone is not general restart-safe idempotency.
- Treat reasoning totals as iteration estimates until actual attempts and configured retry/fallback behavior are checked. Keep the small harness scoped; no generic metering framework.

Result: documentation correction inspected; offline harness preparation is the next useful work. Live execution remains blocked on that verification, actual inputs and explicit allowances. No second reviewer team, credential changes, model calls, commits or push performed.
