# V2-04 — Selected merchant photos produce one saved flyer

Status: ACCEPTED2026-10-13 after direct Codex correction verification: flyer44/44 and lint passed. Scripted wiring/enforcement only; real Gemini quality unverified. Report research/v2-ticket04-corrections-verification-20261013.md.
Blocked by: nothing for the scripted slice (V2-01/02/03 accepted). The LIVE Gemini test is blocked on a Gemini key (secrets/local.env GEMINI_API_KEY), real merchant photographs + catalogue provenance, and separate paid-call authorization.
Parent: `research/social-media-flyer-v2-spec.md`, decisions2,5,7–8.

## Outcome
The social specialist selects product photos, writes a feature-informed prompt, invokes the configured Gemini tool and returns one valid saved/displayed flyer. Content status is UNCHECKED until05, not approved.

## Scope
- Backward-compatible multi-photo catalogue and registered asset selection, matching merchant/product facts. No arbitrary image paths/URLs or competitor-as-product substitution.
- Dedicated narrow Gemini tool with backend-bound company/agent/request/product/candidate IDs, stored prompt/context/input hashes, explicit configured model/auth and no hidden SDK generation retries.
- Add durable run/attempt/candidate/final-artifact persistence before dispatch. Initial-generation path only in this slice: second attempt rejected until05 introduces the reviewed correction path. Backend enforces the final two-attempt maximum and handles duplicate/concurrent/restart/unknown outcomes safely from the outset.
- File type/size/full decode/dimensions/hash gate; unreadable bytes never displayed as success. Registered managed output image and flyer list/detail/image read APIs; keys/signed URLs private, no traversal.
- Minimal chat/result card for saved image, unchecked status and errors; renderer consumes backend records. Retrieve with credentials unavailable and without inference.

## Acceptance
- Through specialist chat with scripted Gemini/local responses, chosen supplied image IDs and exact stored context reach the tool; one persisted candidate/flyer displays and retrieves unchanged after restart.
- Recorded references labelled; unknown/mismatched merchant assets rejected. Configured alternate product/merchant works without role-code changes; V1 single-image catalogue still works.
- Concurrent/duplicate/failed/unknown first generation reserves and consumes allowance durably; no automatic replay or silent second generation. Provider absence/refusal/corrupt file/storage failure explicit.
- Image/read API serves only managed registered files; UI never interprets model text as approval or hides unchecked status.
- If an authorized real generation is run, retain actual image/source/model/usage evidence; fake-model checks are not real Gemini proof. No agent content-review loop, posting or UI redesign yet.

## Completion evidence
Return one sample saved flyer or explicit blocker, selected input images, prompt snapshot, candidate status/hash, call accounting and read-after-restart results. Update ticket/index/HANDOUT. Preserve generated/evidence artifacts before any isolated-copy cleanup.

## Result (Claude, 2026-10-13) - historical heading; ticket accepted 2026-10-13 after its corrections (research/v2-ticket04-corrections-verification-20261013.md)
Note `research/v2-04-flyer-generation-result-20261013.md`; preserved scripted example `research/v2-04-scripted-flyer-example-20261013/` (placeholder image and inputs: wiring evidence only).
- Catalogue: additive `images` list (V1 single `image` kept), `read_catalogue` exposes registered images; merchant-only image roots; competitor/Marketplace ids can never be a merchant photo.
- Tools `generate_flyer` / `read_flyer` (social_media only, granted at creation via `requested_tools`; existing specialists untouched). Gemini Interactions contract re-verified 2026-10-13 (recorded changes: output mime `image/jpeg` only per API reference, `delivery: inline`); explicit `GEMINI_MODEL`, one plain HTTPS POST, no SDK/retries, `store=false`.
- Durable `flyer_runs`/`flyer_attempts`: trusted agent/company/product/request/candidate ids, prompt + exact context, input hashes, provider/model/request settings, outcome/usage/timing, one candidate artifact. One initial attempt per request, reserved atomically before send; every outcome after send consumes it; duplicates/concurrency/restart retrieve or report, never re-send; second attempt left to ticket 5 (final bound 2 recorded).
- Integrity: one inline image, bounded, fully decoded, permitted type, dimensions, hash, private storage; always UNCHECKED. APIs `/api/flyers`, `/api/flyers/<id>`, `/api/flyers/images/<id>`; minimal saved-flyer card in the existing UI; retrieval needs no key, provider or model.
- Checks: `tests/flyer_test.py` 32/32; flyer 32, ad research 80, social 38 (expectations updated for the new tools), listing 57, image path 31, research 79, archive 15, marketplace diagnostic 85, reset 12, ticket01 28, onboarding 26, workers 22, e2e 24, chat API 18, routing_e2e (real Laya) 23, route_table 54/55 (the known 'yes please' miss, identical to before) - all on isolated copies, scripted; `.\lint.bat` exit 0.
- Not covered: real Gemini output/fidelity/cost, real merchant photographs, review/correction/final selection (05), preserved live demo (06), Nebius/NVIDIA.

## Corrections (Claude, 2026-10-13) - accepted by Codex after direct verification
Note `research/v2-04-corrections-result-20261013.md`; condensed before/after output `research/v2-04-corrections-test-output-20261013.txt`; refreshed scripted example `research/v2-04-scripted-flyer-example-20261013/` (+ `corrections/`). Scripted only: placeholder images, no real Gemini.
1. **Artifact integrity on retrieval:** one shared check (`_artifact`: managed path, existence/readability, bounded size, saved size + hash, full decode, type, dimensions) is applied on every list/detail, cached generation result and image lookup. Failure = explicit `storage_failure` / `artifact_integrity_failed` (HTTP 409 on the image endpoint), no image reference, original outcome and attempt count untouched, never regenerated; the UI renders it. Computed on read, so a repaired file is valid again.
2. **Malformed responses:** container shapes are validated before iteration; a completed 200 with `steps: 1`, `content: 1`, non-object items or a non-object body is a terminal, consumed `bad_response` with HTTP status, timing and usage recorded (an uninterpretable response can no longer leave the attempt `dispatched`).
3. **Redaction:** all provider- or exception-derived diagnostics (text blocks, status, interaction id, mime labels, error messages, exception strings) pass one `_clean` (key redacted, bounded) before storage or exposure.
- Checks: `tests/flyer_test.py` 44/44 (30 seams + 14 real server/worker; before the fix the new checks failed); flyer 44, chat API 18, social 38, ad research 80, e2e 24, workers 22, listing 57 (isolated copies, scripted); `.\lint.bat` exit 0; UI rendering confirmed in the browser pane against a stub API.
- Limits: scripted only; integrity check re-reads and decodes each saved image on every list (fine for a handful of flyers); only the exact key value is redacted (not encoded variants).
