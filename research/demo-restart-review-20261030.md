# Fresh-demo restart review — 2026-10-30

Status: ACCEPTED after direct correction verification2026-10-30 (final section). Initial review findings below describe the pre-correction behavior. Pinned tracked baseline736bb42c93e0cfbe62298d7aaffa3bda547fe93e; reviewed uncommitted core/server/static/setup plus new demo_reset.py, fresh_demo.py/bat and tests. One code-review pass with isolated spec and standards axes. No real demo reset, paid model, scraper, Gemini, database-host or tracer calls.

## Spec axis

- **P1, app/demo_reset.py:183-189 — failed recovery removes the pending-reset guard.** After an archived reset stops during clearing, retry unconditionally replaces its pending marker and attempts a new archive of partial progress. If that new archive fails, reset deletes the marker and reports nothing cleared. Startup/admission can then accept the half-cleared demo. Preserve the original verified archive and pending state until clearing actually finishes; recovery should complete the existing operation rather than create a replacement snapshot.
- **P1, scripts/fresh_demo.py:14-21,71-78 — timeout is treated as permission for offline reset.** A running app whose status request times out or resets is classified as absent; the launcher then calls direct reset without that server's busy guard or worker shutdown. Only definite absence may allow the offline branch. Ambiguous connection/HTTP-read failures must stop safely. This is separate from the disclosed smaller port-check/startup race.

## Standards axis

Both safety findings independently identified by the standards reviewer (rated P2 by that axis). Root prioritizes the corrections before acceptance because they can clear progress while the app is active or remove incomplete-operation protection. No broader framework demanded. Ordinary server admission covers chat/Customize/onboarding/company changes, and accounting tables/root OAuth are preserved by the inspected normal path.

## Independent evidence

- Root ran tests/demo_reset_test.py with project-local TEMP/TMP and an isolated temporary app root:21/21 passed. No server sockets or model calls. The missing combinations are not covered by those assertions.
- Root injected an existing stage=clearing marker pointing to a previously verified archive, then mocked retry archive creation failure. Actual reset returned archive_failed; original marker retained=False; refuse_if_pending blocked startup=False. Reproduced entirely in a temporary app root, cleanup completed.
- Actual scripts/fresh_demo.py running() invoked with mocked status read timeout and ConnectionResetError: both returned False (app absent), which selects the unsafe offline reset path. No socket was opened and no real launcher/reset invoked.
- Claude reports scripted journey15/15, browser14/14 and listed regressions; root did not repeat full journeys or lint while reviewing read-only. Real-model fresh journey remains pending as expected, not a reason to run paid tests before these fixes.

## Disclosed limitations and judgment

- Main profile skills remain. Current MAIN_TOOLSETS at core.py:169 has only ecom_company/ecom_agents, so no supported current path for main to create its own skills was established. This is a retained-context caveat if such files exist, not a third proven active defect. Do not claim all conceivable profile content is reset. Main memory/history are cleared; specialists' old profiles are removed from active use.
- Worker/timing logs and archived/result/accounting evidence intentionally remain; that is compatible with preserving history. Direct API lookup by retired ID exposes stored history locally but current screens use new IDs; no new public multi-user access control task is justified.
- Separate process startup can still race the port check; do not represent it as solved. At minimum the ambiguous-probe bypass above must be fixed before operator testing; robust ownership during offline reset should be assessed within that narrow fix.

Next: focused correction prompt for the two safety paths, targeted failing-before/passing-after checks and direct Codex verification. No repeat full reviewer team, parallel fixture warmup, live reset or paid workflow yet. Preserve all accounting/auth and the current recoverable demo.

## Direct correction verification — accepted

Root reviewed read_marker/_archive_path/verify_archive and the stage-specific reset recovery, plus launcher probe/claim_port and routing. Pending JSON is written atomically; unreadable/malformed markers fail closed; recovery validates the original manifest/database/files and finishes the same archive, preserving its guard on failure. Timeout/reset/foreign/invalid responses now give uncertain, not absent. Offline reset takes an exclusive Windows socket on the target app port; running-app path uses the existing busy-gated API.

Independent tests/demo_reset_test.py run2026-10-30 under project-local temporary root:38/38 passed, including original21, recovery failure + subsequent success, invalid markers/missing or damaged archive, unchanged accounting, timeout/reset/malformed-response refusal, running/busy routes, definite absence, startup port race and Windows exclusive bind. These checks use synthetic state and local sockets; no inference, real demo changes or external service calls. No repeat reviewer team or broad suite/lint rerun during direct verification.

Acceptance is for scoped functionality and scripted evidence; live fresh-demo/NVIDIA workflow remains pending. Retained history/logs and raw retired-ID results are documented local evidence, not current-UI leakage. Main skills retention remains caveat; current main toolsets do not expose creation of those skills. Operators must not run a second instance on a different manually chosen port against this same runtime; that is outside the single8800 demo. An unresponsive app is safely refused by launcher; no process killing added.

Normal run.bat resumes; fresh_demo.bat (or menu Restart demo) confirms and resets active progress, not paid allowances. Recovery info is in each ignored runtime/demo_archives/<stamp>/README.txt; do not restore archived accounting wholesale. No actual real reset or runtime archival performed by Codex. Next: accepted checkpoint/push then one explicitly bounded real-model journey; Langfuse stays deferred.
