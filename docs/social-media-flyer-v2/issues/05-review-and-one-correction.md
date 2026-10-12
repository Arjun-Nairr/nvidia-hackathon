# V2-05 — Review actual output and allow one specific correction

Status: BLOCKED.
Blocked by: V2-03; V2-04.
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
