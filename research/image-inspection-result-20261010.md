# Ticket 03 result: actual image inspection through the Hermes specialist runtime

Date: 2026-10-10. Author: Claude Code. Ticket: .scratch/marketplace-listing/issues/03-image-path-check.md. Status: implemented, live-verified once on the development provider; awaiting Codex review. NVIDIA/Nebius compatibility is UNVERIFIED.

## Verdict
Acceptance is met for the development provider: actual pixels reached `openai-codex` / `gpt-5.6-terra` through a real specialist worker and the specialist used the observations. One live run, 6 model requests, 88.2 s wall. Nothing here says anything about the Nebius/NVIDIA model or provider path.

## What was inspected before building
- Hermes already ships `vision_analyze` (toolset `vision`): it takes ANY local path or URL (not suitable to hand a specialist), and its native fast path only engages when Hermes' catalogue says the model is vision-capable. `openai-codex` is on Hermes' list of providers whose tool results may carry images and the Codex Responses adapter converts image parts in tool results to `input_image`, but `gpt-5.6-terra` is not in the catalogue (`_lookup_supports_vision` returns None, image mode `text`). Without a declared capability Hermes replaces tool-result images with a text summary (`_tool_result_content_for_active_model`).
- So: the transport can carry pixels, but only if the model is declared vision-capable and the tool returns Hermes' multimodal envelope.

## Mechanism (the smallest working path)
1. `core.prepare_image(image_id)` (new): takes a REGISTERED image ID only (not a path or URL), resolves it under the image roots (default `runtime/marketplace_check/images/`, where the file name is the listing ID; `ECOM_IMAGE_DIRS` overrides for isolated tests), and fully decodes it with Pillow BEFORE any model call. Missing, corrupt/truncated, non-image, unsupported-format, oversized files and path-like IDs return structured errors (`image_not_found`, `image_unreadable`, `image_unsupported`, `image_too_large`, `bad_image_id`) carrying the `image_id` and the hint not to describe the image. Valid images are re-encoded as JPEG (long edge at most 1568 px, transparency on white) and the original size, format and sha256 are reported.
2. Plugin tool `inspect_image(image_id)` (specialists only; toolset `ecom_images`): returns Hermes' multimodal envelope (`_multimodal`, a text note naming the `image_id` and the reporting rules, and an `image_url` data-URL part). Errors are a plain JSON string with no image part. The note tells the model to cite the image_id, list readable text exactly, state uncertainty, and label fabric composition, quality, authenticity and sales claims unverified unless text in the image says so.
3. Grant: `inspect_image` is an OPTIONAL eligible tool of `market_analysis` (main requests it like any eligible tool; the mandatory memory/skills/context tools are unchanged). The specialist's SOUL gets one reporting rule when it holds the tool. Hermes' built-in `vision_analyze` is NOT eligible.
4. Capability: `profile_config()` writes `providers.<provider>.models.<model>.supports_vision: true` ONLY for pairs in `core.VISION_VERIFIED` (currently `openai-codex` + `gpt-5.6-terra`, the pair proven below; `ECOM_VISION_MODELS` adds pairs for diagnostics). It is per exact model; any other model keeps Hermes' text-only default, and then the tool result's `text_summary` says pixels are not visible (it never claims the image was attached).
5. Observations reach the specialist as its own tool results in the same turn and remain in its conversation as text (Hermes persists the text summary, not the base64 pixels, so a later turn must call the tool again to re-see an image).

## Live run (isolated copy, real subscription login, no Nebius)
Controls (neutral names `ref-a`, `ref-b`; nothing in names, prompts or captions states the content): X = green triangle on yellow with the text `42`; Y = purple circle on white with the text `KX9`.

| Turn | Setup | Model requests | Wall | Result |
|---|---|---|---|---|
| 1 | fresh conversation, `ref-a`=X, `ref-b`=Y | 3 (skills, inspect x2, answer) | 34.3 s | ref-a: yellow background, green triangle, text `42`; ref-b: white background, purple circle, text `KX9`; both said nothing about material/quality/sales was visible |
| 2 | NEW session, pixels SWAPPED under the same IDs; plus Marketplace photo `1638806271151287`, a corrupt file and a missing ID | 3 | 53.9 s | ref-a now purple circle `KX9`; ref-b now green triangle `42` (observations followed the pixels); photo reported under its source ID with readable text; corrupt and missing IDs "could not be inspected" with no description |

- Model request latency (hook-measured, ms): turn 1 [5,270; 3,752; 5,349]; turn 2 [6,048; 3,124; 27,298 for the long final answer]. Image inspection itself costs two requests (the call round and the answer round); the specialist also loaded its two skills first, as instructed.
- Marketplace photo `1638806271151287` (private copy of the existing downloaded JPEG; no new download): the specialist reported a sealed clear-plastic bedding bag with a two-tone quilted comforter in coral/orange and beige, a styled-bed insert, and readable labels (`Vanguard Collection`, `7pc Comforter Set`, `Queen/King/Cal King Comforter Set`); it said fine print and glare prevent transcribing dimensions, and that nothing visible verifies fabric composition, thread count, fill, durability, quality, authenticity or sales performance. This agrees with Codex's earlier independent viewing (clear packaging, orange/red and beige, product label); it is a model description, not a ground-truth label.
- Tool outputs: `image_unreadable` for the truncated PNG and `image_not_found` for the missing ID, raised in the tool before any pixels were sent.
- The specialist then chose the Marketplace photo as the strongest hero image among the successfully inspected ones, citing its ID, and listed the limits (packaging, glare, busy background). It produced the "prioritised action" format from its baseline skill.
- Recorded output: research/image-inspection-live-result-20261010.json (turn texts, tool calls, counts). The harness's own checks scored 8/10 on the live run; the two misses were faults in the check logic (it required the specialist to call ONLY inspect_image, and it searched the wrong part of the answer for the hero ID). They were fixed and re-scored offline against the recorded output (10/10); no second live run was made.

## Tests (separate from the live evidence)
- `tests/image_path_test.py`, 31/31, scripted model, no vision claim: pixel hash follows the file under the same ID; missing/corrupt/non-image/oversized/path-like IDs; plugin envelope contract; grant isolation (granted specialist yes, non-granted specialist no, main never, `vision_analyze` ineligible); with the model declared vision-capable the request body carries exactly the prepared JPEG bytes, and after a swap the same reference sends the new bytes; with no declaration no pixels are sent and the result says so; `_write_profile` refuses to create a profile outside the project's Hermes home.
- Live harness: `tests/image_live_check.py` (isolated copy, login token life check, 6-request budget).

## Issues found and fixed on the way
- In-process `create_agent` without `HERMES_HOME` created a profile in the USER'S OWN Hermes home (reproduced by this run's first harness attempt, before any model call). Fixed: `_write_profile` now refuses unless `HERMES_HOME` is inside the project's private home; regression A12 uses a fake `create_profile`. One stray folder, `%LOCALAPPDATA%\hermes\profiles\listing-photo-analyst`, was created; its files were deleted but its three `state.db*` files were held open by a running Hermes gateway process and could not be removed (see HANDOUT).
- The first tool-result summary claimed the image was "attached" even when Hermes degraded it to text; corrected so it can never imply the model saw pixels.

## Limitations
- Live proof covers exactly `openai-codex` / `gpt-5.6-terra` on one run with synthetic controls plus one real photo. Observation accuracy on real listing photos is judged by reading, not by a labelled benchmark.
- Providers on a chat-completions path (the Nebius shape) were tested only with the scripted model: pixels flow only when the model is declared vision-capable, and whether any NVIDIA model on Nebius accepts images in tool results is unverified and needs an authorized check.
- Pixels are not retained in history; saved evidence for ticket 04 must store the observations (with image_id and sha256) rather than rely on re-viewing.
- No persistence of observations, no drafting, no UI. Ticket 04 stays blocked on review; this note does not start it.
