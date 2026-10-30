# Nebius / NVIDIA fresh end-to-end demo journey - 2026-10-30

Author: Claude Code. Status: **one real journey completed on `nvidia/Nemotron-3.5-Super-VL` through Nebius Token Factory; all nine stages passed without a paid retry; awaiting Codex verification.** One run shows capability, not a success rate. Nothing was posted, sent or published. No code was changed in this task.

## Direct Codex verification — 2026-10-30

Accepted as evidence of one functional live NVIDIA workflow, not autonomous flawless provisioning or output quality. Root read authoritative SQLite via mode=ro: onboarding ready, both expected agents/grants, complete live_research draft6fcdb4deb9 linked to its request/run, final flyer2cf6c18252 with selected candidate79ba8fae3e, verified passed reviewc2d588db87, and counters matching this report. No application imports/migrations were used for this SQLite inspection.

Separately read configured provider/model and executed a SELECT-only Supabase transaction for the TWO current onboarding request ids plus nb-* journey requests:24 model.call rows, all provider nebius-token-factory/model nvidia/Nemotron-3.5-Super-VL,397198prompt/26599completion tokens. Exact current-request filter yields97 total events:67success and30unknown (start events), no failure outcomes. The report's104 count includes older onboarding events, so it is not the current journey alone. Matched start/end hooks do not prove absence of every internal transport recovery attempt. USD0.143 is an estimate of reported token usage, NOT a guaranteed billing upper bound or measured balance.

Root read the saved actual responses: creation reports ad tools NOT connected before operator Customize; analyst mentions draft id; flyer reply says No defects were found. These lapses are observed, not hypothetical. The social specialist WAS created and tool availability was later changed through supported operator Customize, so describe the journey as operator-assisted provisioning rather than claiming completely automatic tool selection.

Personally viewed .scratch/nebius_journey/flyer_view.jpg: inset covers lower-right quilt corner/border, and Learn more CTA lacks supplied destination. Demonstration only appears at the top and required catalogue text/price are visible. Automated review missed real layout/content problems; do not present its pass as human-quality approval.

No new inference/scraper/Gemini calls, no DB writes, real reset, provider switch, code edit, broad review team or lint run in this verification. Next limited polish should correct misleading availability language and unsupported no-defects claims; consider a simpler no-overlap/no-unsupplied-CTA flyer direction before recording, with any new generation separately authorized. Do not expand Laya to arbitrary multi-intent planning or run broad benchmarks on deadline day. Stable launch instructions/assets, README/license, judge-access route and video/submission remain required.

## What actually ran
- **Provider/model:** `LLM_PROVIDER=nebius-token-factory`, `LLM_MODEL` empty, `NEBIUS_MODEL=nvidia/Nemotron-3.5-Super-VL`, the existing Nebius key (never printed). `GET /v1/models` with the key listed the model before any inference (context 1,048,576; USD 0.30 / 0.90 per million input / output tokens; image price 0). Every `model.call` row of the journey reads provider `nebius-token-factory`, model `nvidia/Nemotron-3.5-Super-VL`. Vision gate: only the exact override `ECOM_VISION_MODELS=nebius-token-factory:nvidia/Nemotron-3.5-Super-VL`. Laya (routing classifier) stayed ON. Hermes transport recovery unchanged.
- **Live:** NVIDIA inference for every agent turn (no scripted model, no forced tool-call messages; plain-language requests through the normal chat/onboarding API), ScrapeCreators Facebook Marketplace + Ad Library + CDN image downloads, Gemini `gemini-nano-banana-2.1`, Supabase logbook.
- **Prepared (not live):** the fictional website snapshot (never fetched), the Northloom catalogue and three licensed Met quilt photographs (`demo/v2-06-inputs`), and synthetic operator answers (the same demonstration facts as 2026-10-28, labelled as synthetic in the correction text). USD 79 is an arbitrary test value.
- **Reset:** one confirmed fresh-demo reset through `scripts/fresh_demo.py --yes` (app not running = definite absence) archived the previous demo to `runtime/demo_archives/20261030-115802-235500`. Private pre-change backup (no credentials, do NOT restore): `backups/pre-nebius-20261030/`.

## Stages (request ids are in the local ignored `.scratch/nebius_journey/*.json`)
| # | Stage | Result | Time | Model calls / tool calls | Reported tokens in/out |
|---|---|---|---|---|---|
| 1 | Website entry, main's summary + 5 questions (`onboarding-1793361515827343700`) | PASS | 21.1 s | 1 / 0 | 6,444 / 2,518 |
| 2 | Answers -> shared context -> chat unlock (`onboarding-1793361551527517300`) | PASS | 4.0 s | 1 / 0 | 7,788 / 1,030 |
| 3 | Main creates a market analyst (`nb-main-create-analyst-2`) | PASS (first wording needed a rephrase, see findings) | 2.8 s local + 26.7 s | 3 / 2 | 19,108 / 3,158 |
| 4 | Analyst: Marketplace research + one listing draft (`nb-analyst-task-1`) | PASS | 86.6 s | 7 / 15 | 90,595 / 9,945 |
| 5 | Main creates the social specialist (`nb-main-create-social`) | PASS, but without the ad-research tools | 8.9 s | 2 / 1 | 15,484 / 2,045 |
| 5b | Operator Customize adds the ad tools (`nb-social-customize-1`) | PASS | 18.5 s | 2 / 1 | 19,213 / 751 |
| 6 | Social: ad research -> inspected references -> Gemini flyer -> actual-image review -> final (`nb-social-flyer-1`) | PASS | 90.6 s (Gemini 27.9 s inside) | 8 / 15 | 238,566 / 7,152 |
| 8 | Normal restart: chats, results, associations, grants | PASS (snapshot before/after identical) | - | - | - |
| 9 | Supabase logbook | PASS | - | - | - |

Totals (Nebius, this journey): 397,198 input / 26,599 output reported tokens = **about USD 0.143** at the full published rates (upper bound: cached input is cheaper; usage-derived, NOT reconciled with Nebius billing, the account balance was not read) against the USD 10 ceiling. Gemini: 2,675 in / 2,208 out / 1,156 thought tokens (provider-reported). The logbook shows equal `model.start` and `model.call` counts per request, so no repeated (recovered) inference was visible.

## Artifacts
- Agents: `northloom-demo-studio-market-a` (market analyst, 11 tools: marketplace_locate/search/item/photo, inspect_image, read_catalogue, read_recorded_evidence, save_listing_draft, + mandatory), `northloom-demo-studio-social-m` (social, 16 tools after Customize). Both ids are cut at 30 characters by the existing slug rule.
- Draft `draft-6fcdb4deb9` (complete, `live_research`), research run `run-bb079a0e95`: three New York Marketplace listings ($50 twin bed quilt, $75 antique quilt top, $200 cathedral-window quilt), three photos downloaded and inspected (`live_listing_photo`).
- Ad research `adrun-93b37e09cc` / package `adpkg-b1c5d19b0d`: one keyword search "quilt" (30 ads recorded), two ad images (Project Repat, UGG) downloaded and inspected; reach gate `disabled_reach_unavailable` (0 of 30 ads carried reach), selection `relevance_only`; no metric invented, no other platform used.
- Flyer `fly-2cf6c18252` / candidate `cand-79ba8fae3e`, review `rev-c2d588db87` (verified, `image_part_sent`, verdict passed), status `agent_review_passed`. Gemini received only the merchant photos `quilt-view-01` and `quilt-view-03` (`references` from ads: `sent_to_provider: false`). One initial attempt; the correction was not permitted (no verified defect).

## Allowances consumed (new scopes, never reused or resized)
| Scope | Cap | Used |
|---|---|---|
| `nebius-20261030-research` | 24 API / 8 photos | 5 API (1 locate, 1 search, 3 item) / 3 photos |
| `nebius-20261030-ads` | 16 API / 8 images | 1 API (search) / 2 images |
| `nebius-20261030-flyer` | 4 attempts | 1 |
Per-run caps: research 12 API / 4 photos, ads 8 API / 4 images (existing defaults, set explicitly). No scope was renewed or created to get around a cap; no paid retry was made. Scope names verified in source (`ECOM_RESEARCH_SCOPE`, `ECOM_ADS_SCOPE`, `ECOM_FLYER_SCOPE` plus `*_API_MAX`, `*_IMAGE_MAX`, `*_RUN_*`, `ECOM_FLYER_MAX_ATTEMPTS`).

## Judging the performance
- **Did main understand the business and create appropriate specialists?** Yes. Onboarding summary and questions matched the snapshot; the saved context holds the answers verbatim. Both specialists got role-appropriate, company-specific objectives and instructions (calm tone, no invented competitors/prices, catalogue facts only). Main chose a sensible tool set for the analyst on its own. For the social specialist it granted only what my literal wording implied (a flyer from catalogue photos) and told me the ad-research tools were "NOT connected", which is misleading (they are an eligible optional grant); it took an operator Customize turn to add them.
- **Sensible tool selection / adapting to failure:** tool choice was sensible and efficient (analyst: locate -> search -> 3 items -> 3 photos -> inspect -> save; social: catalogue -> keyword ads -> 2 ad images -> inspect -> save package -> generate -> inspect -> review -> finalize). Nothing failed in this run, so **adaptation to a failed search was not demonstrated** (the backend validators did not reject the draft either).
- **Conclusions supported by evidence:** the draft's claims cite listing and image ids, state asking prices only, say the merchant's own catalogue photos were not inspected, and call the $79 a demonstration value. The comparables are loose (general antique quilts, no chintz-appliqué match) and the draft says so. The agent chose the search location "New York, NY" itself (no merchant location supplied) and the draft says "New York area".
- **Concise replies / correct display:** replies were short and result-first, with the results as cards under the right reply in both chats (UI checked). Two lapses against the reply rule: the analyst's reply names the draft id, and the social reply ends "No defects were found and there are no unresolved issues", stronger than the card's honest "Automated review passed - not human approval".
- **Product details, price and wording:** headline, specifications, USD 79 (as "US$79.00") and "Demonstration only." are exact on the flyer. The draft's own description omits the demonstration wording and price; the stored catalogue notice appears in the card anyway (UI-02 correction working as intended).
- **Flyer problems the automated review missed (my own look at the 1856x2304 image):** (1) the inset detail photo overlaps the quilt's lower-right corner and hides a bird and part of the border, the same class of defect seen on 2026-10-28, yet the review reported "no defects"; (2) "Learn more ->" is a button-like call to action with no destination, supplied by the agent and not in the catalogue; (3) the "Demonstration only." label is small (readable). The quilt's lower-left notch comes from the source photo. Overall the flyer is clean and usable as a demonstration.
- Hidden reasoning is not claimed as verified; stated rationales are model claims.

## Visual evidence (ignored local) `.scratch/ui-demo/screenshots/nebius-journey/`
n01 main, n02 analyst draft card (Demonstration notice, description, photo direction), n03 sources open (3 Marketplace listings + Met catalogue links), n04 social ad-research and flyer cards, n05 enlarged flyer, n06 dark, n07 dark 390px (no horizontal overflow, no console errors). Flyer view: `.scratch/nebius_journey/flyer_view.jpg`. Visible UI notes: both specialists show as "Northloom Demo Studi..." in the sidebar (long names; the role line disambiguates).

## Supabase logbook (read-only SELECT, existing table)
104 rows for the journey's requests (plus the two earlier ChatGPT onboarding requests of 2026-10-28 in the same filter). Every journey request has `request.start`/`request.end`, each `model.start` has a matching `model.call` (provider nebius-token-factory), 0 non-success rows, tool calls recorded (analyst 15, social 15, creates 2 + 1, customize 1). Laya-handled message `nb-main-create-analyst` has only request rows (no model call), as designed.

## Findings and fixes
- No code change and no test was needed; nothing blocked the journey.
- Laya treats a message with several intents as a mixed request and answers locally with a clarification question (no model call). My first analyst request was one create clause plus research and drafting clauses; a single-intent wording worked. Operators should ask main for one thing at a time.
- Main's tool choice for a specialist follows the wording; ad research needed the explicit Customize step (and main's statement that ad tools are "not connected" is inaccurate).
- Carried over, unchanged: shared context omits the demo disclaimers (they live in the catalogue/notice), agent review misses inset overlap, one run only.

## Limitations
- Single run; usefulness of the draft and flyer, repeatability and cost per task unmeasured. Token cost is usage-derived, not billed. Real-model quality of the concise-reply rule is only partly met (two lapses). A failed-search recovery and the Gemini correction path were not exercised. Reach ranking was unavailable (as expected for this account).

## Resume instructions (no credentials)
The demo is left running on port 8800 (server process id at the time of writing 18356, started from `.scratch/nebius_server.sh`, which sources `.scratch/nebius_env.sh`). To resume after a stop: from the project folder run `bash .scratch/nebius_server.sh`, or in any shell set exactly

`ECOM_TIMING=1 ECOM_CATALOGUE_FILE=<project>\demo\v2-06-inputs\catalogue.json ECOM_IMAGE_DIRS=<project>\demo\v2-06-inputs\images ECOM_VISION_MODELS=nebius-token-factory:nvidia/Nemotron-3.5-Super-VL ECOM_RESEARCH_SCOPE=nebius-20261030-research ECOM_RESEARCH_API_MAX=24 ECOM_RESEARCH_IMAGE_MAX=8 ECOM_RESEARCH_RUN_API_MAX=12 ECOM_RESEARCH_RUN_IMAGE_MAX=4 ECOM_ADS_SCOPE=nebius-20261030-ads ECOM_ADS_API_MAX=16 ECOM_ADS_IMAGE_MAX=8 ECOM_ADS_RUN_API_MAX=8 ECOM_ADS_RUN_IMAGE_MAX=4 ECOM_FLYER_SCOPE=nebius-20261030-flyer ECOM_FLYER_MAX_ATTEMPTS=4 ECOM_FLYER_MAX_ITERATIONS=24 ECOM_AD_MAX_ITERATIONS=20 ECOM_RESEARCH_MAX_ITERATIONS=16`

then `run.bat` (it resumes the current demo; the scope rows keep their original caps and used counts). `secrets/local.env` already holds the Nebius provider/model (ignored). Do NOT use `fresh_demo.bat` unless you want a restart (it archives this demo first). Further paid steps need new authorization; the three scopes above have 19 research API, 5 photo, 15 ad API, 6 ad image and 3 flyer attempts left in principle, but nothing further is authorized by this task. To return to ChatGPT: restore `LLM_PROVIDER=openai-codex`, `LLM_MODEL=gpt-5.6-terra` (values in `backups/pre-nebius-20261030/local.env.nonsecret.txt`).
