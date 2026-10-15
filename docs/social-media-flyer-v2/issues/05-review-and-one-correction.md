# V2-05 — Review actual output and allow one specific correction

Status: ACCEPTED2026-10-14 at scripted implementation/wiring level: P1 and both P2 corrections directly verified, independent49/49 + lint. Live effectiveness unverified. Report research/v2-ticket05-p2-verification-20261014.md.
Blocked by: none (V2-03 and V2-04 accepted; V2-04 checkpoint `ee16846`).
Parent: `research/social-media-flyer-v2-spec.md`, decisions6–8 and acceptance5–7.

## Outcome
One independent social-agent goal runs research -> feature/prompt/photo selection -> generation -> file gate -> actual-pixel review -> optional ONE correction -> final saved flyer. No other agent participates.

## Scope
- Role baseline/tool contract makes candidate pixels plus product references/facts available for review of appearance, required text/price and requested layout/readability. Persist candidate-hash-bound checks, defects, uncertainty and actual delivery status.
- Correction tool accepts the prior candidate, specific failed checks/corrections and preserved required facts/selected images; reuse verified Gemini edit mode or explicitly regenerate as supported. Backend validates correction linkage; text-only or absent review cannot claim review-passed.
- Extend durable first-attempt storage with at most one correction; <=2 dispatched generation attempts total. Failed/corrupt/unknown calls count, no transport replay or reset via changed model prompt/product/run arguments. No second correction.
- Select one final candidate, preserve both attempts and their evidence. After unresolved correction, output readable unapproved draft with issues; no readable image -> error/blocker. Reviewer decisions are fallible, not human approval.
- Existing Activity/result card shows review state, missing reach gate and unresolved issues; optional short rationale only if trivial.

## Acceptance
- High-level scripted scenarios: acceptable first result makes1generation; defective first result permits1specific correction and second review; defective second cannot trigger third generation. Original facts persist in correction.
- Deterministic integrity failure and content-review failure remain distinct. Actual known-control images test pixel review where provider verification is authorized; scripted review text is not actual-image accuracy evidence.
- Concurrent/duplicate/restarted/uncertain outcomes cannot evade2attempts. Claiming success without actual image delivery stays unchecked/explicitly failed; wrong reference/hash cannot bind another candidate's review.
- Reach unavailable still permits the full flow; zero/poor ad results or missing real merchant photos are explicit, no silent fixture substitution.
- Saved image, research, selected inputs, prompts, both reviews and final status survive restart; retrieval uses no paid calls. V1 analyst still independent.

## Completion evidence
Show the complete recorded/scripted decision trace, final flyer/status, specific correction example and durable bound/restart checks. Preserve actual-pixel versus scripted evidence separately. Update ticket/index/HANDOUT; no new paid call authorization implied.

## Implementation (Claude, 2026-10-13) - awaiting Codex review, not accepted
Note `research/v2-05-review-correction-result-20261013.md`; condensed before/after output `research/v2-05-test-output-20261013.txt`; preserved scripted trace and one-correction example `research/v2-05-scripted-trace-example-20261013/`. Scripted only.
- **Tools** (social_media only, granted via `requested_tools`): `inspect_flyer` (candidate pixels first, then the merchant photographs, supplied facts and brief; backend writes a `flyer_candidate` inspection bound to agent/request/run/candidate/hash/delivery), `review_flyer` (one per candidate; three checks, numbered defects with specific corrections, backend-derived verdict; counts only when the pixels were delivered, else stored UNVERIFIED), `finalize_flyer` (explicit, once, with rationale and a snapshot of the request's ad-research link). `generate_flyer` gains `previous_candidate_id` + `corrections` (the ONE correction).
- **Correction:** only the first candidate with a VERIFIED review of verdict `defects_found`, naming recorded defect numbers; the original product facts, merchant-photo bytes/provenance, prompt and references are re-used and checked (changed/missing = explicit failure before any reservation); request = original photographs + previous draft (inline edit path; fidelity untested) + stored context + numbered corrections.
- **Bound:** `ATTEMPTS_ENABLED=2`; the correction slot is reserved atomically (run scope, UNIQUE(run, attempt_no)) before the send and consumed by any outcome; stored results answer duplicates, restarts and uncertain attempts; a second correction is `correction_limit_reached`.
- **Result:** status computed from the selected (or only valid) candidate: `agent_review_passed`, `unresolved_issues` (UNAPPROVED draft), `unchecked`, `awaiting_selection`, `storage_failure` (integrity, distinct), `failed`, `in_progress_or_unknown`. APIs expose candidates, reviews, corrections, selection, research/reach-gate link and history; UI card extended minimally.
- **Checks:** `tests/flyer_review_test.py` 36/36 (22 seams + 14 real server/worker/restart scenarios; none could run before the implementation); `tests/flyer_test.py` 44/44; flyer 44, chat API 18, social 38, ad research 80, e2e 24, workers 22, listing 57, image path 31, research 79, archive 15, ticket01 28, onboarding 26, reset 12, marketplace diagnostic 85, routing_e2e (real Laya) 23 (isolated copies, scripted); `.\lint.bat` exit 0.
- **Limits:** scripted review verdicts are not visual accuracy; Gemini correction fidelity, real merchant photographs, Nebius/NVIDIA image delivery and ticket 6's live budget remain unverified or missing.
