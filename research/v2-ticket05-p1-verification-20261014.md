# V2-05 P1 direct verification — 2026-10-14

Outcome: P1 ACCEPTED at the scripted evidence level. Ticket5 remains NOT accepted: its two P2 result-state findings are open. No code-review skill/team or paid calls.

## Mechanism inspected

Application-owned pre_api_request/post_api_request hooks observe pending inspection image hashes in actual model input and require the corresponding response boundary. Review no longer trusts the capability prediction alone. Same-batch calls refuse without saving an immutable premature review. Candidate and selected merchant-image material must match; failed dispatch/text fallback cannot authorize correction. Pending worker state clears at turn end; confirmed ownership remains scoped in persisted inspection records.

Confirmed the hook names/payload/id sequence in installed Hermes `agent/turn_api_request.py`, `turn_response_intake.py` and `conversation_loop.py`; no shared Hermes source change. Worker/plugin and additive schema paths inspected.

## Independent checks

- `tests/flyer_review_test.py`: **43/43**, isolated `.scratch/verify-v2-05-p1-20261014`; local scripted Gemini/reasoning/ad providers and real Hermes/server. No real credentials/runtime copied. Full output saved in ignored `p1-verification.log` rather than printed into context.
- Real multi-tool-batch regression rejects fabricated pass, then valid later pixel delivery enables the defect review and normal one-correction path.
- Provider rejection followed by Hermes text fallback leaves review unverified and result unchecked; no correction allowed. This is reasoning-transport fallback, not an extra Gemini image generation.
- Same-request/candidate/hash ownership, refused-review recovery, stale pending state, bounds, final choice and read-after-restart checks passed.
- `.\lint.bat`: exit0. Other broad regressions are Claude-reported, not independently repeated here.

## Reflection and limits

HANDOUT stayed around10KB/88lines rather than its prior106KB history dump. Source inspection and test summaries were targeted; no measured Claude transcript/token comparison is available, so do not claim the overall600–800K context problem solved.

Claude reports intermittent large local HTTP-response resets and same-request test replay; cause undiagnosed. Retain as a separate known issue before live evaluation, rather than labeling it harmless or folding diagnosis into these P2 corrections.

Exact URL-byte matching is established on scripted chat-completions requests, not live subscription Responses or Nebius/NVIDIA requests. If images are transformed/stripped, the mechanism should fail closed; live accuracy/attention/fidelity remain unproven. Stored reviews from older code are not retroactively revalidated.

Next: narrow slice for cached candidate/status consistency and artifact-aware two-candidate summaries. No commit/push, ticket6 or paid probe performed by this verification.
