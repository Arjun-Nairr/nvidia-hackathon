# Ticket02 corrections review, 2026-10-10

Two fresh isolated code-review agents reviewed Standards and Spec separately. Current-file review because no Git baseline exists. Historical report remains research/ticket02-review-20261010.md. No production code, credentials or real runtime data changed; no live requests or credits used.

## Standards

- [P2] Storage write errors escape handling (scripts/marketplace_check.py:81-85,237-242,599-607). save_json can raise PermissionError/OSError, but outcome persistence and main do not handle them. Reviewer injection confirmed an initial-write failure crashes with zero requests sent, and an outcome-write failure crashes after one request and one saved ledger entry, before evidence is saved. Root observed two actual PermissionError failures during isolated tests; the underlying Windows cause is not established. Engineering judgment against scope's honest failure reporting: handle persistence errors explicitly, distinguishing no request sent from counted request whose outcome/evidence could not be saved. Keep the existing spending count; never replay the API call to recover a local write. Temporary-file cleanup and bounded local replacement retries may be appropriate.
- Reviewer [P2]: saved evidence entries are only shallowly validated (scripts/marketplace_check.py:123-127,318-328). A listings entry containing a string passes loading; a search for the same ID sends/counts a request then crashes in merge. Isolated mocked reproduction confirmed it. Engineering judgment on the added fail-closed evidence boundary. Root disposition: lower-priority follow-up, not a new live-sampling blocker; no ordinary live response shown to create this stored shape. A small entry-type check is reasonable while touching the loader; no general schema framework needed.

## Spec

Pass for all three original corrections and the concurrent-invocation guard; no additional material spec finding. Reviewer independently verified: truncated ledger stops transport and preserves bytes; item then search retains seller/currency/detail while supplied price updates; error-only200 and missing listings fail distinctly from valid empty arrays. Independent14-process mocked run with10 remaining requests sent exactly10, retained20 sequential ledger entries, and produced no tracebacks.

## Root verification

Two unmodified suite runs passed the original33 checks and several correction checks before PermissionError from ledger replacement stopped execution. A third full run passed65/65 with an in-memory replacement-retry wrapper installed as a diagnostic; its retry counter was ZERO, so no retry was exercised and source code remained unchanged. This confirms the logical checks can pass but does not erase the two observed native storage failures. Tests used isolated project-contained temporary roots and mocked transports only. Claude's failing-before39/65 remains Claude-reported evidence.

## Disposition

Original findings resolved. One focused storage-error correction remains before live sampling; no new feature ticket or architecture redesign required. Malformed saved-entry validation is a small optional adjacent fix. Live feasibility remains pending ScrapeCreators credentials and real listing/photo evidence. Tickets04/05 remain blocked;03 not dispatched.

## Reviewed SHA256

- scripts/marketplace_check.py: F1C638BC1A0DAF72FA3EDB711581D340C1303A1B08B6F866A1485D1740C3017B
- tests/marketplace_check_test.py: 11A80E39C5C1AF2674338F6E23522A6BA26F1E90C135845AB94AD446E6B3E584
