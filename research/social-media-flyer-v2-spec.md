# Specification: V2 independent social-media specialist

> HISTORICAL (2026-10-25): original V2 specification, kept as implementation/evidence reference. Current scope and decisions live in HANDOUT.md; conflicting demo-login, public-onboarding and extra-role proposals here are superseded.

Date: 2026-10-11. Codex using to-spec. Status: ready for ticket decomposition; settled product scope with explicit integration feasibility dependencies. This document is not authorization to install, implement, run paid probes, publish or deploy.

## Problem
A home-textile merchant wants an original promotional flyer grounded in relevant competitor advertising and accurate merchant product facts. V1 proves independent specialist provisioning, live Marketplace research, image inspection and saved drafts, but does not retrieve paid advertisements or generate flyers. Adding a useful second role must preserve that existing functionality and avoid duplicate/confusing agent creation.

## Solution
Main onboards the merchant and configures an independent semi-prebuilt `social_media` specialist. On one manual goal, that specialist retrieves US Facebook image-ad references, examines their actual images, selects useful visual features and merchant-supplied product photos, writes a Gemini prompt, generates one flyer, inspects the output and optionally requests one specific correction. Backend validates file integrity and enforces a maximum of two generation attempts. One final flyer is saved and shown through minimal UI support.

The market analyst remains independent. There is no agent-to-agent evidence handoff, paired provisioning or mandatory market analyst for this workflow. Shared merchant facts do not imply shared specialist memory or conclusions.

## User stories
1. As a merchant, I want main to configure a social-media specialist for my company, so that advertising work reflects my business.
2. As a merchant, I want to keep using my existing market analyst independently, so that adding a role does not change its work.
3. As a merchant, I want a persistent prepared product with real photos, price, specifications and brand context, so that I can test without repeatedly entering data.
4. As a merchant, I want to request one flyer in a direct specialist chat, so that I control when research and generation start.
5. As a merchant, I want the specialist to choose relevant US Facebook image advertisements and inspect them, so that the design has concrete references.
6. As a merchant, I want reported reach used only when available, so that invented metrics do not influence reference selection.
7. As a merchant, I want flyer creation to continue when reach is unavailable, so that a missing metric does not prevent useful work.
8. As a merchant, I want the specialist to choose my relevant product photos and design instructions, so that I do not manually compose an image-model prompt.
9. As a merchant, I want the generated flyer checked against my product and requested content, so that visible mistakes can be identified before presentation.
10. As a merchant, I want at most one corrective generation, so that cost and waiting remain bounded.
11. As a merchant, I want corrupted images, missing inputs and failed services reported clearly, so that I do not mistake failure for success.
12. As a merchant, I want unresolved review issues disclosed, so that I can decide whether the output is usable.
13. As a merchant, I want one saved flyer retrievable after restart, so that I do not pay to regenerate it.
14. As a merchant, I want no automatic publishing, so that I retain control over external account actions.

## Existing implementation and required seams
- `app/core.py`: company store, role registry, validation, profile creation/configuration, tool grants and run_turn. Several profile descriptions, baseline-skill selections and toolset lookups currently assume market_analysis.
- `app/roles.py`: existing market-analysis foundation. Provide role-specific baseline guidance without forcing both roles through an analyst baseline.
- `app/routing.py`: Laya already recognizes social_media but returns unsupported_role; creation authorization currently depends on create_market_agent. Extend the role-aware routing/permission path consistently, preserving analyst and unsupported-role behavior.
- `app/hermes_plugin.py`: tool registration and create_agent schema/guidance currently describe one role. Role grants must govern availability; classification is not permission enforcement.
- `scripts/setup.py`: main instructions currently describe one role and contain obsolete research-not-connected wording. Update supported capabilities without implying main itself has research/generation tools.
- `app/listing.py` and `app/research.py`: useful catalogue, image, storage and bounded-request behavior, but Marketplace-specific data/rules must not be presented as ad data. Reuse suitable utilities without turning V2 into a speculative general framework.
- `app/worker.py`, `app/workers.py`, `app/turn_state.py`: persistent isolated worker/profile, trusted request identity and multimodal delivery path. Preserve these rather than creating a separate gateway per specialist.
- `app/server.py` and temporary static UI: existing chat, Activity, busy/error handling and saved-result read seams. Backend owns research, validation, limits and persistence; frontend only renders and submits.
- Current deployment remains local, single-company, unauthenticated loopback. V1 is technically demonstrated on openai-codex/gpt-5.6-terra; Nebius/NVIDIA compatibility remains unverified. No Gemini provider/tool is established by V1.

## Decisions

### 1. Scope, initiation and roles
Keep one company and two independent supported roles: market_analysis and social_media. No mandatory pair creation or automatic recreation of existing agents. Main should identify an existing suitable specialist and offer/direct its reuse when relevant, while preserving explicit user-requested creation behavior.

Main remains the onboarding/provisioning agent. Role foundations, capability rules, baseline skills and tool implementations are predefined; main supplies identity, company objective, instructions, optional context, priorities and complementary custom skills. Backend validates all grants. Social-media specialist cannot create agents, edit company facts, contact sellers or publish.

Retain existing required company fields, with role-neutral merchant-goal wording. Merchant/product/brand details come from supplied context, never invented. Direct specialist chat remains the manual task trigger; do not expand Laya into specialist-turn classification or fine-tune it.

### 2. Prepared merchant assets
Use a persisted prepared home-textile merchant and one product, with 2–3 actual supplied product photos, accurate declared price/currency, specifications and simple brand direction. Assets must have lawful usable provenance; do not call synthetic illustrations actual product photos or scrape competitors as merchant assets.

Use configured data and registered image IDs, extending the catalogue's single-image representation compatibly to expose multiple assets. Existing V1 catalogue still works. Product/merchant names, image roots and IDs must be configurable, not embedded in role logic. Catalogue-company matching remains enforced. A new fixture/sample must not reset the real company or old agents. Missing real photos/context produce a clear setup blocker; no invented substitute.

The agent selects one or more eligible product photos and states the required message/layout/content in its prompt. Gemini receives that prompt/context and the selected merchant photos. Competitor images influence the specialist's reasoning, not the identity of the generated product. Passing competitor images to Gemini is not required or authorized by this scope.

### 3. Facebook image-ad research
Add a narrow read-only Facebook Ad Library retrieval capability through verified ScrapeCreators endpoints. Accept structured advertiser/search/ad identifiers and US filters supported by the actual API; no arbitrary URLs, credentials or request-budget arguments from the model. Normalize source ad ID/link, advertiser identity when exposed, text, image references, retrieval time and available metadata. Distinguish variants/cards from independent ads.

Ad tools and cached images are separate from Marketplace evidence. A source's absence, unavailable US coverage or failed request must be explicit; never fall back silently to V1 Marketplace fixtures or a different platform.

Agent chooses advertisers/queries, relevant comparisons and follow-up images within configured finite research/download limits. Backend reserves attempts before sending, accounts for failures and caches successful same-run retrieval; unknown outcomes are not replayed automatically. Reuse V1 protections for credentials, TLS, redirect checks and source-bound photo retrieval as appropriate. Exact research caps are operator settings selected during endpoint feasibility/ticket scoping, not an unbounded agent decision.

### 4. Reach capability gate
Relevant product/audience/image format takes priority over raw reach. When verified reach is supplied, the agent may use it to prioritize relevant comparable ads and must expose the source, period/geography or range if provided. Compare only metrics with compatible meaning; no arbitrary cross-period/global versus US totals treated as equivalent.

Store missing reach as unknown. Backend/tool responses expose reach availability and provenance; disable reach-based ranking when unavailable. The agent may still select relevant visual references and generate a flyer, disclosing that reach ranking was unavailable. Do not substitute impressions, estimated audience size, likes, ad duration, views or invented scores for reach. Reach is exposure, not evidence of conversions or commercial effectiveness.

Instagram retrieval and its reach capabilities are deferred. No change to geography simply to obtain a metric.

### 5. Image generation and file gate
Provide a dedicated Gemini image-generation tool to this role, separate from the Hermes reasoning provider. Exact Gemini model, SDK/API, auth and image-input/edit mode require official-documentation and working-path verification. Keep current subscription reasoning configuration unchanged unless separately approved; Gemini calls consume separately authorized credentials/budget.

Suggested narrow contract: generate_flyer takes product_id, registered selected_product_image_ids, prompt/design requirements, cited ad/image references and an optional previous candidate ID plus specific corrections. Backend binds company, specialist, manual request, attempt number and provider config. No arbitrary paths, remote URLs, model-controlled credentials or budget reset. Return candidate ID, structured status, registered output image ID, dimensions/hash and remaining generation attempts; never expose secrets or huge image payloads to the dashboard.

Register/store generated bytes in private managed storage. Validate permitted format, bounded file size, full decoding and sensible nonzero dimensions before making a candidate eligible for display or model inspection. Hash the actual stored image. File validity is distinct from content review. Invalid output yields a structured error, consumes the reserved attempt and cannot be labelled a usable flyer.

### 6. Actual-image review and correction
After integrity validation, specialist receives actual candidate pixels through the verified vision path, alongside supplied product references/facts and the requested brief. Review required text/price, observable product appearance and requested layout/readability. Record checks, observed defects, uncertainty and model delivery status against the candidate hash. Do not treat a URL, successful download or text-only response as completed visual review.

When review detects a defect, the specialist may issue one correction request, preserving original facts/requirements and specifying concrete changes. Include the previous candidate only if the verified Gemini API supports the chosen edit/reference mode; otherwise regenerate with the corrected prompt and selected merchant photos. Do not promise editing fidelity before testing it. Review the corrected candidate's actual pixels as well.

Backend enforces a total of at most TWO generation attempts for the manual request: initial plus one correction. Reserve each slot atomically before provider dispatch, persist it across restart and parallel tool calls, and count failed/corrupt/unknown outcomes. Do not reset by changing product, prompt, agent-provided run ID or retrying the same request. Existing duplicate-submit handling must not silently rerun generation after lost connections/restarts; completed stored results are retrieved, uncertain in-flight work is explicitly reported. No automatic transport retries that create an extra generation.

No second correction. If the corrected image still fails review, return a clearly flagged unapproved draft with unresolved issues when file-valid; if no valid candidate exists, return a blocker/error. A review claiming success without actual pixels is unchecked, not approved. Model review remains fallible; wording such as 'agent review passed' must not imply human approval or guaranteed exact product fidelity.

### 7. Saved result and persistence
Use existing app SQLite and private image storage with additive role/run/candidate/flyer records. Keep specialist memory isolated; large ad payloads and generated bytes belong in artifact/evidence storage, not durable conversational memory.

Persist at least:
- Trusted run ID, request ID, specialist/company/product IDs, timestamps, terminal/in-progress status and enforced allowance counters.
- Merchant/product/brand snapshots, selected merchant image IDs and hashes, source ad references/text/metadata/retrieval times, available reach and gate state, reference observations/features.
- Per-attempt candidate ID, generation prompt/context or version snapshot, provider/model, selected input assets, predecessor/correction instructions, attempt status/error, output image ID/hash/type/dimensions, available usage/timing.
- Per-candidate content review, delivery status, checks/defects/uncertainty and final chosen candidate/review status.
- One final flyer record per manual request, linking the selected candidate and its evidence. Earlier candidate may remain supporting history, not a second final flyer.

Choose the final candidate explicitly. Do not overwrite first-attempt evidence with corrections. Retrieval after restart reads stored records/images without scraping or model calls. Original signed CDN URLs and keys are private; public source-ad links and normalized evidence are sufficient for user-facing provenance. Short explanation is optional and uses existing output fields; no separate report engine.

### 8. API and minimal UI
Use existing POST /api/chat/<agent_id> with trusted request_id for initiation. Provide role-neutral read interfaces for flyer list/detail and a managed generated-image endpoint keyed by validated IDs. Return final status, image reference, optional short explanation, reach-gate state and unresolved review issues. API must not allow path traversal or arbitrary local-file reads.

Add a saved image/result card or equivalent minimal display to the existing specialist chat, showing one flyer and plain status/error. Preserve per-agent busy state, Activity and existing conversations. Refresh/restart must allow opening the saved flyer even when provider credentials are unavailable. No prompt-editor, upload flow, design canvas, dashboard redesign, continuous monitoring or manual multi-flyer revision workflow required.

## Verification dependencies before affected implementation
1. Read current official ScrapeCreators ad-search/company-ad/ad-detail schemas. Verify US image-ad retrieval, variant behavior, source identifiers and actual reach fields/availability; if absent, document the disabled ranking path. No paid sample without separately scoped authorization.
2. Read current official Gemini image-generation documentation; choose a supported model/path for text plus selected merchant-photo input, and identify editing support, response format, cost and automatic SDK retry behavior. Confirm credentials/config are available without exposing values. Missing keys do not justify fake live success.
3. Confirm Hermes' selected reasoning model receives generated candidate pixels and merchant image references through the existing multimodal path. V1 vision evidence supports reuse but does not prove new Gemini outputs or final NVIDIA compatibility.
4. Establish the prepared sample's actual product-photo provenance and filesystem/catalogue mapping. Do not invent photos/facts to complete setup.

Failures narrow the dependent integration or produce an honest blocker; core independent-role/persistence work can proceed in separately approved tickets. Do not switch image vendors, geography or source platforms without an explicit scope change.

## Testing and acceptance
Use existing chat/tool/read APIs and an isolated runtime as the highest practical seams. Scripted models/providers test wiring, permissions, budgets and failures; label them clearly, never call them image-quality or live reach evidence.

1. Main can create social_media via Laya with role-specific baseline plus company customization; market_analysis creation/chat/memory/tools still work. Unsupported roles remain rejected; main/analyst/ungranted specialists cannot call Gemini or ad tools. Social specialist cannot recursively create agents or inherit analyst conclusions.
2. Prepared merchant/product/photos persist; a second configured product/merchant input through the same isolated single-company seam does not require role-code edits. No claim of multi-business support.
3. A manual specialist goal chooses useful image-ad research steps and selected merchant photos, then generates a stored flyer. A scripted irrelevant first result prompts an adapted search or an honest blocker, not a fixed query chain.
4. Reach present/absent cases preserve its meaning/provenance and gate ranking only; absence never blocks otherwise sufficient image-reference generation or masquerades as zero/reach estimates.
5. Known-control images establish actual pixel review, including correct/incorrect price/product/layout cases. Integrity failures, text-only review, missing assets and provider errors yield explicit status.
6. First acceptable candidate makes one generation call; a failed first review may make exactly one correction and a second review; a failed second review cannot cause a third generation. Concurrent/duplicate/restarted/unknown-outcome tests verify durable bounds and no hidden replay.
7. A saved flyer, source evidence, generation inputs and review status survive restart and are retrieved without provider requests. Minimal UI displays real stored image/error states through API data; business logic remains backend-owned.
8. One separately authorized bounded live demonstration uses real US ad references, actual merchant photos, real Gemini generation and actual-pixel review on the development provider. Preserve output/evidence/timing/model and scraper usage before cleanup. Arjun judges visual usefulness; technical success does not substitute for that judgment.
9. Nebius/NVIDIA reasoning/image-tool compatibility remains an explicit later check before final hackathon acceptance; subscription or Gemini success alone does not establish it.

## Out of scope
Market-analyst/social-agent handoffs, mandatory paired agents, extra roles beyond social_media, Instagram integration, Marketplace-to-ad substitution, reach estimation/proxy scores, sales-effectiveness claims, scheduling, publishing/account writes, video ads, more than one final flyer per request, more than one corrective generation, upload onboarding, full UI redesign, multi-business/auth/deployment, fine-tuning, repository publication and private-project reuse.

## References and next step
Product decisions: authoritative final section of `research/creative-agent-direction-20261011.md` and HANDOUT.md. Codebase facts: inspected modules listed above. V1 proof: `research/v1-clean-demo-verification-20261011.md`.

Primary-source pointers already inspected: [ScrapeCreators Facebook ad details](https://docs.scrapecreators.com/v1/facebook/adlibrary/ad/), [Facebook post metrics (different source)](https://docs.scrapecreators.com/v1/facebook/post/), [Meta Ad Library reach restrictions](https://br-fr.facebook.com/ads/library/api/). Gemini source/model details deliberately remain unverified rather than asserted from memory.

Next: to-tickets decomposes this specification into dependency-linked increments with endpoint/model feasibility first where needed. Claude implementation prompts remain inline. No tracker/repository setup, tickets, paid probes or production changes are dispatched by creating this spec.
