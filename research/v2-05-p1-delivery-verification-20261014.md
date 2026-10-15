# V2-05 P1 correction — delivery-bound visual verification, 2026-10-14

Status: **implemented, awaiting direct Codex verification; ticket5 still NOT accepted** (two P2 findings outstanding: cached candidate/status mismatch, damaged two-candidate summary). Scripted stand-ins only: no real credential, provider, runtime reset or paid call.

## Defect
`inspect_flyer` recorded Hermes' capability *prediction* (`image_part_sent`) and `review_flyer` trusted it. Hermes runs several tool calls of one assistant message without an intervening model request, so `[inspect_flyer, review_flyer]` in one batch produced a VERIFIED review of pixels no model request had carried (the candidate hash was already visible in `generate_flyer`/`read_flyer`).

## Confirmation mechanism (actual)
Two supported Hermes plugin observer hooks, registered by `app/hermes_plugin.py` for every specialist (`pre_api_request`, `post_api_request`; names from `hermes_cli.plugins.VALID_HOOKS`; invoked synchronously in the agent thread; no change to installed Hermes):

1. `inspect_flyer` (unchanged envelope) additionally registers a **pending inspection** in worker memory (`turn_state.pending_images`): SHA-256 of every `data:image` URL of its review material (candidate pixels + the merchant photographs).
2. `pre_api_request` -> `flyer.note_request(request_messages, api_request_id)`: walks the payload actually being sent for that attempt; the inspection is marked as carried only if **all** of its images are byte-identical in that payload (any provider payload shape). A later attempt without them (parts stripped after a 400, text fallback) withdraws the mark.
3. `post_api_request` -> `flyer.note_response(api_request_id)`: a model response completed. Every pending inspection gets `boundary_at`; the one whose images were in *that* request also gets `delivered_at` (additive REAL columns of `image_inspections`). Pending entries are then dropped; the worker also clears them at each turn end.
4. `review_flyer` (`app/flyer.py`): no `boundary_at` -> refused `image_not_yet_delivered` (nothing stored, no immutable premature review, corrective hint); `boundary_at` without `delivered_at` -> stored UNVERIFIED, delivery `unknown` (explicit unchecked, no defects exposed, no correction); `delivered_at` -> VERIFIED. The newest *delivered* inspection of the same agent/request/run/candidate/hash is used, so a later premature re-inspection cannot void it. Model-supplied claims, the capability prediction, an envelope or a stale confirmation from another candidate/hash/request never verify.

Because the hook sequence is request -> response -> tool execution of that response, a `review_flyer` in the *next* assistant message (or any later one) sees the confirmation; a review in the same message as `inspect_flyer` cannot.

## Failing before / passing after
Test additions in `tests/flyer_review_test.py` (isolated copy, scripted):
- **R13a-e** (seams, using the hook entry points as Hermes calls them): same-batch refusal that stores nothing and cannot authorise a correction (`review_required`); inspection -> image-bearing request -> response -> review verified after an earlier refusal, then the normal correction; failed request (no response) cannot verify; text-fallback request + response stores UNVERIFIED (`review_not_verified` for a correction); request carrying only the candidate (not the review material) stays UNVERIFIED; another candidate/request cannot reuse a delivery; restart drops an unconfirmed inspection (stale response cannot complete it) while a persisted confirmation survives.
- **B14** (real server + real Hermes worker + chat API): the scripted model (`mock_llm` option `BATCH_REVIEW`) sends `inspect_flyer` + a fabricated "pass" `review_flyer` in ONE assistant message; the review is refused, the model then looks at the pixels (red-control candidate), records the defect, ONE correction follows and the final passes on the corrected candidate's own verified review. 
- **B15** (real loop): the provider 400s the image-bearing request, Hermes strips the parts and retries with text; the result is UNCHECKED, no verified review.

| | Before (hooks absent, defect present) | After |
|---|---|---|
| `tests/flyer_review_test.py` | 37/43 (R13a-e FAIL; B14 FAIL: first candidate "passed" blindly) | **43/43** (27 seam + 16 real server/worker checks; final code passed in 4 of 4 runs, three of which needed the replay noted below) |
| other checks | | flyer_test 44/44, ad research 80/80, social 38/38, chat API 18/18, workers 22/22, image path 31/31, listing 57/57, e2e 24/24, ticket01 28/28; `.\lint.bat` exit 0 |

Logs (ignored): `.scratch/p1_red2.txt` (before), `.scratch/p1_fin3.txt` / `p1_fin4.txt` (after).

## Scoped self-audit
- Only the hooks write `delivered_at`/`boundary_at`; no tool, argument or model text can. A failure inside a hook fails closed (unverified/refused).
- The pre/post pair is matched by `api_request_id`; retries re-evaluate the payload each attempt.
- Old inspection rows (NULL `boundary_at`) cannot back a new review: re-inspect. Stored reviews are untouched.
- The refused premature call is not an attempt, a review or a status change; Gemini is not called.

## Limitations
- Exact-bytes matching assumes Hermes forwards the tool-result image data URLs unchanged. Verified through the real chat-completions path of the scripted provider; **not verified for the development provider's Responses payload or for Nebius/NVIDIA**. If a provider payload re-encodes images, reviews fail closed (UNVERIFIED), never open. Hermes' 413 image-shrink recovery also yields UNVERIFIED.
- "Delivered" means the provider accepted a request that carried the pixels and responded; it cannot prove the model attended to them.
- Worker-memory pending state is lost on restart by design (refuse until re-inspected).
- **Local transport flake (not caused by this fix; cause undiagnosed).** Large (~70-90 KB) chat responses of the app server were intermittently reset on this PC while the server stayed up and had already stored the finished turn (seen before the fix with only test stubs, and once in the unrelated ticket-4 suite; a minimal in-process idle/large-response probe did not reproduce it). `tests/flyer_review_test.py` therefore replays the same `request_id` (up to 6 times, printing a NOTE line); replay returns the stored result and runs nothing (B7). It masks nothing in the product logic, but a UI user on this machine could meet the same reset on a long answer.
- Running two copies of the suite concurrently collides on the fixed test ports (Windows lets both processes bind); orphaned mock servers from crashed runs did the same until swept. Run suites one at a time.
