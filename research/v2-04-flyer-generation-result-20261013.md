# V2-04 flyer generation — result, 2026-10-13

Author: Claude Code. Ticket: `docs/social-media-flyer-v2/issues/04-generate-save-display-flyer.md`. Status: **implementation complete, awaiting Codex review; NOT accepted.**

**What this is and is not.** The slice is implemented and verified against **scripted stand-ins only**: a Gemini Interactions stand-in (`tests/mock_gemini.py`) that returns *generated placeholder* images, a rule-based specialist policy (`tests/mock_llm.py`) and *generated placeholder* "merchant photos". **No real Gemini call, no real Google credential, no paid call, no scraper, reasoning-model or Nebius call was made, and no real merchant photograph exists in the project.** Nothing below is evidence of real Gemini output, image quality, text legibility, product fidelity or cost. The live test remains blocked on (1) a Gemini key, (2) real merchant photographs and facts, (3) separate paid-call authorization.

## Prerequisites handled

- Checkpoint: the accepted V2-03 corrections and documentation were committed locally first (`9d9ecbe`, no push). `CODEX_NOTES.md` (a Codex edit) was deliberately left out of that commit and remains modified in the working tree.
- Baseline before editing: the suites below passed on the V2-03 tree (ad research 80/80, social 38, listing 57, image path 31, research 79, archive 15, diagnostic 85, reset 12, ticket01 28, onboarding 26, workers 22, e2e 24, chat API 18, routing_e2e 23, route_table 54/55). The single known Laya miss (`contextual yes`, "yes please") is the only route_table failure, before and after.

## Gemini contract, re-verified 2026-10-13 (official Google documentation)

Sources read: `ai.google.dev/gemini-api/docs/image-generation`, `.../docs/interactions`, `ai.google.dev/api/interactions-api` (the first fetches were truncated for the longest pages; the unread tails are noted as unverified below).

| Item | Verified | Used as |
|---|---|---|
| Model | `gemini-nano-banana-2.1` is the page's recommended default ("primary high-efficiency workhorse"); `gemini-3.1-flash-image` is the previous generation; `gemini-3.1-flash-lite-image` is not optimised for multiple reference inputs; `gemini-2.5-flash-image` is legacy | default `gemini-nano-banana-2.1`, configurable with `GEMINI_MODEL` |
| Endpoint | `POST https://generativelanguage.googleapis.com/v1beta/interactions`; Interactions API "Generally Available ... recommended for all new projects" (June 2026); `generateContent` legacy but supported | that endpoint, plain HTTPS POST, no SDK |
| Auth | header `x-goog-api-key` | header only; never in a URL |
| Request | `model`, `input` (blocks `{type:"text",text}` and `{type:"image",data,mime_type}`), `response_format`, `store` | exactly these four fields |
| Image output config | `response_format {type:"image", aspect_ratio, image_size, mime_type, delivery}`; `aspect_ratio` includes `4:5`; `image_size` `1K`/`2K`/`4K` (uppercase K); `delivery` `inline`\|`uri` | `4:5`, `2K` (configurable 1K/2K), `inline` |
| Response | `status` in `in_progress, requires_action, completed, failed, cancelled, incomplete, queued`; `steps[]` with `type:"model_output"` and `content[]` blocks `type:"text"` or `type:"image"` (`data` base64, `mime_type`, or `uri`); `usage.total_input_tokens/total_output_tokens/total_thought_tokens/total_tokens`; `errors[]` with `code`/`message` | accept only `status == completed` with exactly one inline image block |
| Input limits | up to 14 reference images in total, "up to 10 object images" for 2.1 (my reading of a flattened table); input types PNG/JPEG/WEBP/HEIC/HEIF/GIF/BMP/TIFF | cap 3 photos, JPEG/PNG/WEBP only |

**Material changes from the feasibility note (`research/v2-integration-feasibility.md` section 3):**

1. **Output mime type.** The API reference enumerates only `image/jpeg` for `response_format.mime_type`; the guide shows both jpeg and png in examples. The note recommended `image/png`. The backend now requests `image/jpeg` and checks that whatever comes back decodes as an allowed type and matches its label.
2. **`delivery` is a documented field.** The backend sets `inline` explicitly and never fetches a provider URI. **CORRECTED 2026-10-25:** the field is listed in the API reference, but the LIVE service rejected it (HTTP 400 `Image delivery mode is not supported.`, V2-06 probe); the backend now omits it (default is inline data) and still never fetches a provider URI.
3. The response shape (status, steps, usage names, `errors[]`) is now documented; the feasibility note had inferred parts of it.

**Still unverified** (not on the pages as fetched, or not testable without a key): that `store: false` is accepted for this model; HTTP error body shape (the code reads `error.message` or `errors[0].message` when present and otherwise the status); safety-block representation; cost per call (note section 3 figures are pricing-page values, total unmeasured); edit/regeneration fidelity; the unread tails of the two long pages; SDK retry behaviour was not restated on these pages, so the no-SDK decision rests on the earlier source reading.

## What was built

| Piece | Where |
|---|---|
| Multi-image catalogue (additive): product `images: [{image_id, kind, provenance...} | "id"]`, V1 single `image` still works; `read_catalogue` now lists `images` with inspectability; company matching unchanged | `app/listing.py` (`product_images`, `product_missing`, `read_catalogue`) |
| Merchant-only image roots (`ECOM_IMAGE_DIRS`, else the demo fixture folder): never the Marketplace diagnostic cache or ad-research images | `app/core.py` (`merchant_image_roots`) |
| Generation module: tools `generate_flyer` / `read_flyer`, Gemini transport, atomic reservation, integrity gate, storage, read views | `app/flyer.py` (new) |
| Additive tables `flyer_allowance`, `flyer_runs`, `flyer_attempts` | `app/core.py` |
| Role/grant plumbing, SOUL and baseline text, turn limits (a flyer turn is long-running), create_agent description | `app/core.py`, `app/roles.py`, `app/hermes_plugin.py`, `scripts/setup.py` |
| Read APIs `GET /api/flyers[?agent_id=]`, `/api/flyers/<id>`, `/api/flyers/images/<id>`, `/api/flyers/allowance`; `/api/status.image_generation_configured` | `app/server.py` |
| Minimal UI: "Saved flyers" card in the inspector, rendered from the API (UNCHECKED label, error, image, hash) | `app/static/index.html` |
| Empty `GEMINI_API_KEY` field appended to `secrets/local.env` and the template (existing credentials untouched) | `secrets/` |

## Rules enforced by the backend (not by the model)

- **Eligibility.** Tools exist only for `social_media` specialists whose stored grants include them; main, the analyst (even with edited grants), ungranted specialists and calls outside a manual request are refused. Existing specialists' grants/SOUL are never rewritten: a specialist gets the tools only by being created with them through main (`requested_tools` including `generate_flyer`, `read_flyer`).
- **Arguments.** `product_id`, 1-3 `selected_product_image_ids`, `prompt` (40-3000 chars), optional `reference_ad_image_ids`. Everything else (`model`, `api_key`, URL, path, run, candidate, attempt, size, allowance, `previous_candidate_id`, `corrections`) is rejected as `invalid_argument`.
- **Assets.** Only the selected product's catalogue-registered images; competitor ad ids, Marketplace ids, another product's images and unknown ids are `image_not_registered_for_product`. Catalogue company must match the saved company. Files must exist in a merchant root, decode fully, be JPEG/PNG/WEBP and total <= 12 MB; the ORIGINAL bytes are sent. **Synthetic stand-ins are refused** (`synthetic_asset_not_allowed`) when the catalogue is `demo`, labelled synthetic/fictional/placeholder, unless the operator sets `ECOM_FLYER_ALLOW_SYNTHETIC=1` (tests); real catalogues must state `provenance {owner, date, usage_statement}` per image or generation is a setup blocker (`asset_provenance_missing`). A saved record states whether its inputs were synthetic.
- **Reference ads** are provenance only: they must be images downloaded by THIS request's ad research, are recorded with source ad id/link/hash and are never sent.
- **Context.** The exact text sent = the specialist's prompt + a backend-built block of the catalogue's facts (name, declared price/currency, specifications, merchant, brand direction). Both the prompt and the full context are stored.
- **Attempts.** One initial attempt per manual request (`ATTEMPTS_ENABLED = 1`; the reviewed bound of two is recorded as `attempts_final_max` and enforced by ticket 5's path). The slot (plus a per-scope total, default 6, `ECOM_FLYER_SCOPE`/`ECOM_FLYER_MAX_ATTEMPTS`, fixed at first use) is reserved in ONE immediate transaction before the send. After the send every outcome consumes it: refusal/auth/rate/5xx, `failed` status, no image, **two images**, corrupt/undecodable bytes, bad base64, mislabelled type, URI-only, wrong dimensions, redirect, connection lost (unknown), and storage failure after a valid result (`ok_unsaved`). Repeated and concurrent calls get the stored result or an explicit `attempt_already_consumed` / `generation_outcome_unknown`; nothing is re-sent.
- **Before the send** (no attempt claimed): argument/grant/asset/provenance errors, missing key (`missing_credentials`, naming `GEMINI_API_KEY` and `secrets/local.env`), invalid provider settings (`ECOM_GEMINI_URL` must be https or loopback; `GEMINI_IMAGE_SIZE` 1K/2K). There is no fallback generator.
- **Output.** Exactly one inline image, <= 16 MB, fully decoded, JPEG/PNG/WEBP, each side 64-8192 px, label matches bytes, SHA-256 recorded, stored under `runtime/flyers/<run>/` and served only by validated id. Status is always **UNCHECKED**: file validity only; no agent review exists until ticket 5.

## Evidence

- `tests/flyer_test.py`: **32/32** (Part A 21 in-process seams incl. a 4-process race and a stopped-provider fresh process; Part B 11 through the real server, HTTP chat API, Hermes workers, scripted model, main's real `create_agent`, restart).
- Preserved scripted example: `research/v2-04-scripted-flyer-example-20261013/` — `flyer.jpg` (a generated placeholder, NOT a real flyer), `flyer-record.json` (the API detail: prompt, exact context, inputs and hashes, identity, attempt/usage, output hash), `provider-request-as-received.json` (what the stand-in received: model, header check, `response_format`, hashes/sizes of the two photographs), `model-pixels-seen-by-reasoning-model.json`, `inputs/` (the two placeholder "merchant photos").
- Regressions: flyer 32, ad research 80, social 38 (expectations updated for the new tools), listing 57, image path 31, research 79, archive 15, marketplace diagnostic 85, reset 12, ticket01 28, onboarding 26, workers 22, e2e 24, chat API 18, routing_e2e (real Laya) 23, route_table 54/55 (the known 'yes please' miss, identical to before) - all on isolated copies, scripted.
- `.\lint.bat`: exit 0.

## Missing real sample (what Arjun must supply for the live test)

1. **Gemini key:** put it on the existing empty line `GEMINI_API_KEY=` in `secrets/local.env` (template: `secrets/local.env.template`). Optional on the lines below it: `GEMINI_MODEL`, `GEMINI_IMAGE_SIZE`. The key must belong to a billing-enabled Google project; this has not been confirmed.
2. **2-3 actual product photographs** of one product you may lawfully use, as JPEG/PNG/WEBP files named `<image_id>.<ext>` in the image folder (`ECOM_IMAGE_DIRS`, default `tests/fixtures/demo_images`).
3. **A catalogue file for that merchant** (`ECOM_CATALOGUE_FILE`): merchant name equal to the saved company name, `product_id`, name, declared price/currency, specifications, and per image `{"image_id", "kind": "photograph", "provenance": {"owner", "date", "usage_statement"}}`. No "demo", "synthetic", "fictional" or "placeholder" wording.
4. Separate authorization for one paid Gemini call (and a decision on 1K vs 2K).

## Self-audit (scoped)

- `read_catalogue` adds `images` and keeps `image_inspectable`; analyst listing drafts still use the same catalogue helpers (listing 57/57, research 79/79). `record_inspection` kind detection now recognises any of a product's images.
- `merchant_image_roots()` is separate from `image_roots()` on purpose: ad/Marketplace roots can never supply a merchant photograph (`A13`).
- The tool handler's HTTP timeout is 180 s, below Hermes' default tool timeout (420 s in `agent/tool_executor.py`); a call Hermes aborted anyway would leave a `dispatched` attempt that is reported as uncertain, not retried.
- A deliberate non-feature: `generate_flyer` does not require inspecting the photographs first; the baseline/SOUL tells the specialist to.
- Tests that encoded "image generation is not connected" for social specialists were updated to the new honest wording (social 38 and the ad-research description check); behaviour for specialists without the flyer tools is unchanged.

## Limits and what is not covered

Real Gemini behaviour (acceptance of `store:false`, edit/photo fidelity, text legibility, safety blocks, actual cost, latency); real merchant photographs; vision review of the generated flyer, the correction attempt and the final-flyer selection (ticket 5); preserved live demo (ticket 6); Nebius/NVIDIA reasoning compatibility. The 1K/2K choice, the 4:5 aspect and the 180 s timeout are untested defaults. The UI card is minimal and unstyled by design.
