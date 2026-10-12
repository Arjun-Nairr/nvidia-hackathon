# Ticket 04 corrections: results

Date: 2026-10-10. Author: Claude Code. Responds to `research/ticket04-review-20261010.md` (four findings). Status: **implemented, awaiting Codex verification; not accepted.** No live inference, scraping, CDN download, Nebius call, runtime reset or UI change was made for these corrections. The live demonstration in `research/listing-draft-result-20261010.md` (draft `draft-e0f22d293e`) predates them and is kept as historical evidence; it is not a post-fix run.

## Method
Failing regressions were added first to `tests/listing_draft_test.py` and run against the UNMODIFIED code in an isolated copy (12 failures, plus a crash in the scripted phase because the inspection log had no delivery state). The smallest complete fixes followed; the suite and the relevant regressions were then re-run from fresh isolated copies. `HERMES_HOME` is set project-local at the top of the suite; the profile-creation guard is unchanged.

## Findings, fixes and evidence
| # | Finding | Fix | Failing before | Passing after |
|---|---|---|---|---|
| 1 | A cited photo whose file hash differs from the hash recorded for the listing still counted toward a complete draft | A cited recorded-listing photo whose inspected hash differs from the recorded one is **rejected** (`image_provenance_mismatch`, names listing and both hash prefixes; nothing saved). No recorded hash -> saved `partial`, provenance `no_recorded_hash`, `matches_recorded_photo_hash: null` (distinct from a match); a matching hash -> `hash_match`. Competitor status is decided from the evidence in force at save time, not only the kind logged at inspection (adjacent hardening, D3e). Test fixtures now carry truthful hashes of their own synthetic stand-ins | D1, D2, B4b | D1, D1b, D2, D2b, B4b, D3e, C13 (through the worker tool) |
| 2 | `Price: 79 USD.` and `Price: $89 EUR.` passed against 89 USD | Bounded price/currency validation (`price_problem`): optional lead word (price/priced/cost), currency symbol or ISO code before or after the amount, a few currency words, decimal comma and thousands separators. Amount AND currency must equal the catalogue's. A bare number with no mark/lead word (dimension, quantity, percentage, temperature, year) is not a price. The declared amount/currency come from whatever catalogue file is configured | D4b, D4d, D4f | D4, D4b, D4c, D4d (USD); D4e, D4f (EUR 49.90, other merchant and product ID, configuration only) |
| 3 | The inspection log proved image preparation even when Hermes sent only the text fallback | `image_inspections.delivery` (additive column) = `image_part_sent` / `text_fallback` / `unknown`, set by the worker from Hermes' own gate for the live agent (`_model_supports_vision`, provider list-content support, learned rejections). Only `image_part_sent` counts as verified visual evidence; text fallback, unknown and pre-correction rows (NULL) save as `partial`, name the image, and the snapshot carries `delivery` and `counts_as_verified_evidence: false`. Observation text is kept but never makes a draft complete. The fallback tool text now also says not to submit observations for an unseen image | D3 x3, D3b, D3d; scripted phase crashed (`KeyError: 'delivery'`) | D3, D3b, D3c, D3d, C7 (text fallback, no image part reached the mock model, `partial`), C7b (supported path, image part reached the mock, `complete`) |
| 4 | Saved evidence omitted the source description and photo references | Each cited listing snapshot now stores `supporting` = {description (<=800 chars, `description_truncated` flag), photo_count, photos[<=12] {photo_id, width, height, caption}}, built by the same whitelist function the read tool uses, so persisted == exposed. Manual review notes, seller fields, coordinates, attributes, secrets and raw payload are not stored. Photo CDN URLs are not stored | D5 | D5, D5b, D5c, D5d, C11 (restart with the evidence file removed: draft and supporting content identical, zero model requests), C11b |

Delivery is a statement about how the image was sent, never that the model understood it.

## Test totals (fresh isolated copies)
- `tests/listing_draft_test.py`: **57/57** (was 34; before the fixes the new checks gave 12 failures plus the scripted-phase crash). Pure backend plus scripted model through the real server and Hermes workers; not a vision or reasoning test; scripted delivery is not new live vision proof.
- Regressions: image path 31/31, ticket01 28/28, onboarding 26/26, workers 22/22, chat API 18/18, routing with real Laya 21/21, e2e 24/24.
- Not re-run: marketplace diagnostic (84; script untouched, no shared code changed). Live harness `tests/listing_live_check.py` gained one assertion (every cited image `image_part_sent`) and was NOT run.
- D3e was added after the failing-before run, so it has no recorded failing-before output.

## Changed files
`app/listing.py`, `app/core.py` (additive `delivery` column), `app/turn_state.py`, `app/worker.py` (`vision_status`), `app/hermes_plugin.py` (delivery passed to the log, tool descriptions), `tests/listing_draft_test.py`, `tests/listing_live_check.py` (assertion only), plus HANDOUT, ticket 04, INDEX, PROTOTYPE_SCOPE and this note.

## Remaining limitations
- `delivery` is Hermes' decision for the provider/model at inspection time. It does not prove the provider accepted the image part or that the model understood it, and a provider rejecting list tool content mid-turn is only learned after its first failure. Only openai-codex / gpt-5.6-terra has live image proof (ticket 03); Nebius/NVIDIA unverified. Models on the text fallback now always produce `partial` drafts.
- Price validation is a bounded heuristic: fixed symbol/ISO-code/word list; informal wording ("89 bucks") or unlisted currencies are not recognised; a bare `$` is accepted for any dollar currency; "price of 2 sets" would be read as a price; rationale text is not price-checked.
- Hash provenance proves the inspected file equals the bytes recorded for that listing, not that the photo shows the product. Any cited image that is not verified keeps the draft `partial`.
- Descriptions are kept to 800 characters (flagged) and photo references to 12; photos are referenced by ID/size/caption, not URL.
- Drafts saved before this change (none exist outside isolated copies) would lack `supporting`/`delivery`. The real runtime database gains the column only when the app next starts.
- Claim guards elsewhere remain keyword heuristics; one product; replayed Dallas sample with 3 cached photos. Ticket 05 not started.
