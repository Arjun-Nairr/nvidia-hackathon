# V2-06 offline runner review — 2026-10-16

Used code-review's isolated Standards and Spec reviewers once for this ticket. Fixed base: local HEAD `98758d97611ad2877ce40d5d4a4bb7270651445d`; implementation is uncommitted, including untracked scripts/tests. Reviewed working-tree changes and new files, not an empty HEAD-to-HEAD comparison. No live calls, credential changes, commits or push.

Result: corrections required before accepting the offline runner or authorizing live execution.

## Standards

No root CODING_STANDARDS.md/CONTRIBUTING.md found. These are concrete lifecycle/state findings under the documented stop/isolation contracts, not formatting preferences.

- **P2 — Stop owned worker descendants.** `scripts/v2_06_demo.py:200–209` terminates only directly spawned processes. On Windows this skips the server's finally/atexit cleanup; Hermes workers are separate subprocesses and finish the current turn before reading stdin EOF (`app/server.py` cleanup, `app/workers.py` subprocess lifecycle, `app/worker.py` request loop). After an unknown busy timeout the runner can return while inference/tools and database changes continue. Stop/wait for the owned process tree and preserve unknown completion; do not replay. Regression: blocked worker, zero settle, teardown, no surviving owned worker or subsequent dispatch.
- **P2 — Claim the demo directory exclusively.** `scripts/v2_06_demo.py:220–238`, `save():69–73` operate on previously loaded unlocked state and a common temporary filename. Two invocations can both pass the phase guard and start separate stacks against the same runtime. Parent independently reproduced two stale readers both passing `begin` in `.scratch/v206-review-state-y5q7xwgw`. Use a small per-demo exclusive lock before loading state, held for the phase; test one accepted invocation and one refusal before POST.

## Spec

- **P2 — Validate probe/demo outcomes independently of chat success.** `scripts/v2_06_demo.py:492–521` leaves phase completion based on a successful agent reply, merely recording flyer outcomes. No flyer, failed generation, or unverified review can still unlock the demo. This violates the probe's generation/actual inspection/review contract and honest blocked outcomes. Parent reproduced `cmd_probe` exiting0/completed with no flyer or review and an explanatory failure reply using injected local stubs; evidence `.scratch/v206-noartifact-bwp5o3b1`. Validate authoritative artifacts/review identity and required phase result, preserve failures without unlocking the next paid phase. Do not equate a negative but verified content review with transport failure; record it honestly.
- **P2 — Preserve actual merchant inputs.** `scripts/v2_06_demo.py:591–595` archives current input hashes and merchant name, but no merchant photo bytes or full catalogue/provenance. Live inputs remain external paths. This misses ticket6's reference/input/output hashes/images requirement and can silently describe changed bytes rather than generation inputs. Preserve supplied input snapshots and validate against attempt-recorded hashes/catalogue identity; report mismatches. Test changed/missing external originals and inspectable archived inputs.
- **P2 — Prove credential-inaccessible retrieval.** `scripts/v2_06_demo.py:641–643` checks API-key fields only, while a demo Codex auth.json can remain available. Live inert mode disables Gemini/scraper endpoints but not Codex inference. This does not establish restart retrieval with inference credentials absent. Parent independently confirmed the absence check returns true with a dummy OAuth file present. Use an isolated retrieval arrangement without available inference credentials; never touch the original project's login. Test dummy OAuth as well as API keys and zero requests.

## Verification

- Independent Ruff/ESLint: passed.
- Independent pure local reproductions above: confirmed false phase success, non-exclusive phase claim and incomplete credential-absence check. Dummy data only, no server/provider calls.
- Full focused runner suite independently passed **41/41** with dummy providers and real LOCALAPPDATA explicitly set in the test process. Log: `.scratch/v206-codex-verification-20261016-unsandboxed.log`; artifacts `.scratch/v206-test-20261016T212646`. Initial default sandbox LOCALAPPDATA caused setup failure; after correcting this process-local environment, sandbox service startup stalled and that attempt was stopped, then the suite completed with local-server permission. Passing current tests does not cover the five findings above. Whitespace check passed.

Next: one scoped correction prompt for these findings and behavioral regressions. Direct Codex verification afterward; do not launch another reviewer team or add unrelated infrastructure.
