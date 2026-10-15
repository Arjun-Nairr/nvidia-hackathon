# V2-05 actual-image review and at most one correction — result, 2026-10-13

Author: Claude Code. Ticket: `docs/social-media-flyer-v2/issues/05-review-and-one-correction.md`. Status: **implemented with scripted stand-ins, awaiting Codex review; NOT accepted.**

**Everything here is scripted**: a Gemini stand-in (`tests/mock_gemini.py`, solid control-colour images through its `colors` control), a rule-based specialist policy (`tests/mock_llm.py` `review_policy`), invented ad data (`tests/mock_fb_ads.py`) and generated placeholder "merchant photos". No real credential was loaded, no live Gemini, scraper, reasoning-model or Nebius call was made, no runtime or profile was reset, nothing was pushed. The scripted reviewer's verdicts follow the pixels it receives (a strongly red candidate is "wrong price"), which shows that image bytes reached the model and that decisions bind to the right candidate; **it says nothing about real visual-review accuracy or real Gemini editing fidelity.**

## Checkpoint first

V2-04 (accepted, incl. its three corrections) was committed locally before any ticket-5 work: `ee16846`, after `.\lint.bat` exit 0. Staged by explicit path (32 files: app, tests, docs, research notes, scripted example). Left out on purpose: `CODEX_NOTES.md` (Codex's working memory, modified in the tree) and `research/matt-skills-install-options-20261013.md` (an unrelated Codex note). Secret scan of the staged diff: only the empty `GEMINI_API_KEY=` placeholder text. No push, no visibility change.

## What was built

| Piece | Behaviour |
|---|---|
| `inspect_flyer(candidate_id)` | Candidate must belong to THIS agent's run of THIS request and pass the shared integrity check (`_artifact`). Returns the Hermes multimodal envelope: the candidate's pixels FIRST, then the merchant photographs of the product (original bytes, hashes re-checked against the first attempt's recorded inputs), the supplied facts and the brief that was sent. The backend writes the inspection row (`image_inspections`, kind `flyer_candidate`: agent, request, run, candidate id, file hash, delivery as Hermes decided it, reference hashes). The text-only fallback summary carries no hash. |
| `review_flyer(...)` | One review per candidate. Needs an inspection of THIS candidate's CURRENT bytes in THIS request; echoed `candidate_sha256` must equal the stored hash; exactly three checks (`product_appearance`, `required_text_price`, `layout_readability`) each pass/fail/uncertain with an observation; every failed check needs a numbered defect with a specific correction; verdict `passed` / `defects_found` / `inconclusive` is DERIVED by the backend. Counts as a completed review only when delivery was `image_part_sent`; otherwise stored `unverified` (no defects exposed as verified, no correction possible, result stays UNCHECKED). Text claiming human approval/guarantee is refused. |
| `generate_flyer` correction | `previous_candidate_id` + `corrections [{defect_no, instruction}]` (both or neither). Eligible only for the FIRST candidate of this request with a stored VERIFIED review of verdict `defects_found` naming those defect numbers. Everything else is re-used from the first attempt (product, photographs, prompt, references); an identical re-send is accepted, a different product/prompt/images/references is refused (`correction_cannot_change_original`). Changed catalogue facts (`original_facts_changed`), a replaced/changed/missing photograph or changed provenance (`original_input_changed`, `merchant_image_missing`) fail BEFORE any reservation. The request carries: original merchant photographs (same bytes/order) + the previous draft as the LAST image; the text is the stored original context plus the numbered corrections. |
| Attempt bound | `ATTEMPTS_ENABLED = 2`. The correction slot is reserved in one immediate transaction (`_reserve_correction`: run exists, only the first attempt exists, it is `ok`, verified review with defects; scope allowance of the run's own scope; UNIQUE(run, attempt_no) as last guard) BEFORE the send and consumed by any outcome. A second attempt that already exists returns its stored result; a second correction gets `correction_limit_reached`. No transport retry (unchanged one-POST path, shared `_dispatch`). |
| `finalize_flyer(candidate_id, rationale)` | Explicit, once, idempotent for the same choice. Candidate must be valid (integrity) and belong to the request. Stores rationale, time and a snapshot of the request's ad-research link. The flyer's status then follows THAT candidate. |
| Status (computed, never stored) | `agent_review_passed` · `unresolved_issues` (UNAPPROVED draft; defects listed) · `unchecked` (no verified review) · `awaiting_selection` (two valid candidates, none chosen: no default image) · `storage_failure` (integrity, distinct from content) · `failed` · `in_progress_or_unknown`. |
| APIs | `GET /api/flyers[?agent_id=]` (summary incl. review, unresolved issues, final), `/api/flyers/<id>` (candidates with prompt/inputs/references/corrections/review/integrity, research link, history, attempt accounting), `/api/flyers/images/<flyer_id or candidate_id>` (409 `final_not_selected` for an undecided flyer id; 409 `artifact_integrity_failed` unchanged). SQLite only: no provider, no credentials. |
| UI | the existing "Saved flyers" card: labels for the new statuses, candidate/correction/selection line, review line, unresolved issues. |
| Instructions | SOUL flyer paragraph (review, one correction, explicit selection, "agent review passed", unresolved = unapproved draft), baseline skill subsection, create_agent guidance, main's SOUL. Existing specialists keep their stored grants and SOUL (a specialist gets the new tools only by being created with them). |

## Gemini correction path (documentation re-read 2026-10-13)

Official image-generation guide: editing sends a `text` block plus an `image` block in the same `input` array of `POST /v1beta/interactions`; up to 10 object images on `gemini-nano-banana-2.1`; "multi-turn conversation is the recommended way to iterate", via `previous_interaction_id`. We use the inline re-send path: multi-turn needs a stored interaction (`store=true`), which this project keeps off, and a lost/unknown prior interaction could not be replayed anyway. Request images are bounded at 20 MB total. **Editing fidelity is untested**: nothing here promises that Gemini preserves the product while changing the named defect.

## Failing before, passing after

- **Before** (`tests/flyer_review_test.py` against the unmodified code, isolated copy): the first check aborts at `flyer.inspect` ("module 'app.flyer' has no attribute 'inspect'"): none of the review, correction or selection surface existed. Output: `research/v2-05-test-output-20261013.txt`.
- **After:** `tests/flyer_review_test.py` **36/36** (Part A 22 seams, Part B 14 real server/worker/chat-API scenarios). Ticket-4 suite `tests/flyer_test.py` **44/44** (expectations updated for the intended changes: two enabled attempts, a correction needs both arguments, review-aware SOUL).
- Regressions on isolated copies (scripted): flyer 44, chat API 18, social 38, ad research 80, e2e 24, workers 22, listing 57, image path 31, research 79, archive 15, ticket01 28, onboarding 26, reset 12, marketplace diagnostic 85, routing_e2e (real Laya) 23 (isolated copies, scripted); `.\lint.bat` exit 0.

### What the checks cover (acceptance list)

| Requirement | Checks |
|---|---|
| Acceptable first candidate: one generation | R1, B2 |
| Defective first: one specific correction + second review | R2, R2b, B4, B5 |
| Defective second: no third generation, issues visible | R3, B6 |
| Wrong/stale/unbound hash or candidate, missing pixels, text fallback | R4, R4b, R4c, R4d, B10 |
| Concurrent / duplicate / restarted / uncertain cannot exceed two | R5, R5b, R6, R6b, R6c, R6d, R9 |
| Original facts and input hashes survive; missing/changed fail explicitly | R7 |
| Integrity failures distinct from content defects | R8, R8b |
| No relevant ads / missing merchant assets: honest blockers | B8, B9, R5b |
| Explicit final selection (not newest), research and reach-gate links | R10, R10b, R11, B7 |
| Final image and evidence unchanged after restart with zero calls | R6d, B11 |
| Existing analyst/ads/generation/UI behaviour intact | ticket-4 suite 44/44 and the regression list; B12, B13 |
| Image bytes actually reach scripted model requests | R1 (pixel means of the envelope), B3, B5 (request log of the scripted model) |

## Preserved scripted evidence

`research/v2-05-scripted-trace-example-20261013/`: `full-trace-scripted.json` (three complete scripted runs: acceptable first candidate; defective first candidate + one correction, with the exact Gemini requests as received, the model-pixel log and the final record; defective second candidate with the refused third attempt), `first-candidate-defective.jpg` and `final-candidate-one-correction.jpg` (solid control colours: wiring evidence, not designs).

## Self-audit (scoped; no review team launched)

- A review row can be created only by `review_flyer`, which requires a backend-written `flyer_candidate` inspection of the same request, run, candidate and bytes; `inspect_image` cannot show a candidate (it resolves registered roots only) and `record_inspection` never assigns that kind.
- The model-echoed hash proves nothing by itself; the authority is the stored delivery value and the stored hash. A text-only model can read the hash through `read_flyer` and save an UNVERIFIED review (explicit, never counted).
- Integrity is computed on every read (unchanged `_artifact`); a damaged candidate cannot be inspected, reviewed, corrected or selected, and the status says storage failure, not a defect.
- The correction slot is charged to the run's recorded scope, so changing the environment cannot move a request onto a fresh scope.
- Removed: the V2-04 auto-selection of the sole candidate at generation time (`final_candidate_id`); a single unreviewed candidate is still shown as the only valid one (UNCHECKED), two valid ones are never auto-picked.

## Limitations and live uncertainties

- No real Gemini output, no real editing/correction fidelity, no real merchant photographs, no real visual-review accuracy; Nebius/NVIDIA image-in-tool-result delivery unverified (`image_part_sent` is Hermes' own gate for the development provider only).
- A correction sends the previous draft inline; Gemini may keep the defect or alter the product. The review of the corrected candidate is the only guard and is fallible.
- Review quality depends on the real model reading three images at once (candidate + up to three photographs); long flows may need the iteration cap (`ECOM_FLYER_MAX_ITERATIONS`, default raised 28 -> 40) and timeout re-tuned.
- One review per candidate: an unverified or mistaken review cannot be redone within the request (by design: no re-review loop to pass a check).
- The stored Activity output is cut at 3000 characters; `read_flyer` detail exceeds that, so the API (not Activity) is the full record.
- Live demonstration (ticket 6) still needs the Gemini key, real photographs with provenance and separate paid-call authorization.
