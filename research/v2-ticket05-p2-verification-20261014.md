# V2-05 P2 direct verification — 2026-10-14

Outcome: both P2 corrections ACCEPTED at scripted evidence level. Together with previously accepted P1, ticket5 is ACCEPTED for implementation/wiring, not live Gemini/review effectiveness. No code-review skill/team or paid calls.

## Inspected contracts

- Cached generation/correction returns a coherent attempt-scoped result: candidate, image, review, issues, status and note describe that attempt. Selected-flyer state is explicitly separate in flyer_status/final. No new provider request or accounting change.
- Effective candidate selection uses shared current artifact validation. Two valid/unselected remain awaiting_selection; one valid plus damaged exposes survivor and damage without storing a final selection; no valid artifact gives storage_failure. Damaged selected candidate stays failed, never silently switches. Damaged superseded candidate does not spoil a valid selected final. Restored original bytes restore computed state without regeneration.
- Existing P1 delivery confirmation and attempt/ownership guards preserved in inspected paths.

## Independent checks

- `tests/flyer_review_test.py`: **49/49**, isolated `.scratch/verify-v2-05-p2-20261014`; real Hermes/server with local scripted Gemini/reasoning/ad stand-ins and placeholder inputs, no real credentials/runtime copied. Verbose log is ignored `p2-verification.log`.
- New cached-result regressions compare older selected defective and newer passed candidates before/after selection and on repeated generation/correction calls.
- Real app/restart negative cases: both damaged => list/detail/specialist failure plus HTTP409; one restored => surviving artifact plus explicit damaged peer; both restored => awaiting_selection. Zero external requests/accounting mutations on retrieval.
- P1 same-batch refusal and provider-image rejection/text fallback tests still pass, alongside normal one-correction and restart flows.
- `.\lint.bat`: exit0. Other regression suites are Claude-reported and not independently repeated here.
- This independent run logged one local connection-reset replay of the same request ID, with no failed assertions. The existing replay guard prevents a duplicate turn; this is retained evidence of the unresolved local transport flake, not proof the flake is fixed.

## Remaining limits

This is not live image quality, review accuracy, Gemini correction fidelity or subscription/NVIDIA payload validation. Merchant photos/facts, Gemini key and separately authorized live budget remain last-reported missing. Local large-response resets remain undiagnosed; no general audit was performed.

Claude separately notes review_flyer's returned verdict is candidate-level while status is flyer-level after selection; no image/status mixing in the fixed cached contract remains. Keep this API naming ambiguity for the agreed broader interface audit; not classified as a new blocker in this scoped verification. Activity stores truncated tool output; authoritative complete artifact evidence remains in SQLite/read APIs.

Next: checkpoint accepted ticket5, then scoped ticket6 live readiness/probe and preserved evaluation with explicit inputs/authorization. No commit, push, live test or ticket6 implementation dispatched by this verification.
