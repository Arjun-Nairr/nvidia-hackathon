# Specification: first useful Marketplace listing concept

Date: 2026-10-10. Author: Codex using to-spec.
Status: scoped product and architecture specification; dependent integration choices require the feasibility checks below. This is not authorization to implement, spend credits, publish or start the next milestone. Active onboarding scope remains separate.

## Problem statement
A home-textile merchant needs useful listing ideas grounded in competing products and actual product images. Generic copy lacks evidence; manual comparison and drafting consume time. The merchant needs a controllable specialist that can investigate and return a draft worth using or editing.

## Solution
On a manual request, one company-specific market-analysis specialist reads a small merchant catalogue, chooses relevant Facebook Marketplace searches/listings, inspects listing images and produces at least one listing concept: title, description, visual brief and linked rationale. The agent chooses its research approach and can change queries based on results. Prebuilt capabilities provide reliable data access, persistence and permissions; main configures the specialist for the merchant.

One strong concept is the minimum. Return three distinct concepts only if this is a small extension of the same implementation. No new agent team or draft-count framework is required.

## User stories
1. As a merchant, I want a specialist tailored to my products, audience and goal so its work is relevant to my business.
2. As a merchant, I want to provide a small catalogue with photos, specifications and actual prices so drafts reflect products I sell.
3. As a merchant, I want to manually request a listing concept so I control when research begins.
4. As a merchant, I want the specialist to choose and refine competitor searches so I do not have to preselect every listing.
5. As a merchant, I want real image inspection so visual recommendations reflect what competitors actually show.
6. As a merchant, I want a title, description, visual brief and evidence-linked rationale so I can evaluate and use the result.
7. As a merchant, I want uncertainty and missing data stated clearly so I do not mistake assumptions for observations.
8. As a merchant, I want drafts and evidence to survive restart so I can revisit the work.
9. As a merchant, I want a clear partial-result or failure message when research cannot complete so I can decide what to do next.
10. As a merchant, I want drafts without automatic publishing so external changes remain under my control.

## Established context and dependencies
- Agreed niche: US home-textile retail, initially bedding, curtains and throws. Use one fixed test merchant and a small catalogue; do not fabricate its facts or competitor evidence.
- Source scope: Facebook Marketplace image listings. Marketplace listings are distinct from Page posts and paid-ad-library data. Sellers are not assumed to be identifiable businesses.
- Current application uses one main Hermes profile and independent specialist profiles, long-lived workers, app SQLite records, profile conversation databases and file-based skills/memory.
- Laya routes main chat only. Direct specialist chat is not classified; no classifier expansion is part of this feature.
- Observed code includes editable company storage, a main company-update tool and baseline role skills. Shared handout/scope have not yet confirmed completion or tests for those onboarding changes. Review that increment before integrating this one.
- No live research tools are currently granted. Current worker conversation path is text input; image support through the selected provider/runtime is unverified. Text-model success does not establish vision or NVIDIA compatibility.

## Implementation decisions

### 1. Merchant and catalogue input
Keep the single saved company profile. Add a small structured catalogue accessible through the backend, initially a local fixture for the selected test merchant rather than Shopify integration or an upload system.

Each product contains a stable product ID, name, image reference, basic specifications and actual price/currency. Use a small set of products; one target product is sufficient for the first successful run. Delivery details are not required. Missing or unreadable images must be reported, not described speculatively.

The manual request identifies a product or goal; the specialist asks for clarification when the target cannot be determined. It reads current merchant data at run time rather than relying only on creation-time instructions.

### 2. Main agent and semi-prebuilt specialist
Extend the existing market_analysis role; do not create a separate social-content role in this increment.

Prebuilt foundation: responsibilities, baseline evidence/research skill, tool implementations, memory lifecycle and permission enforcement. Main decides specialist identity, company objective/instructions, optional context, eligible tools, priorities and complementary custom skills. Generated skills supplement the baseline rather than replacing it.

Backend validation determines actual grants. The specialist cannot create further agents, alter merchant facts, invent permissions or publish listings. Remove outdated 'research not connected' instructions only when tools are actually connected; surface missing credentials/capabilities explicitly.

### 3. Marketplace tools
Provide narrow backend tools for location resolution, keyword/location listing search and listing-detail retrieval using ScrapeCreators' documented endpoints. Accept structured search parameters, not arbitrary request URLs or model-supplied credentials.

Return normalized listing IDs, source URLs, titles, available descriptions, prices/currencies, location, seller identifiers where exposed, photo references and retrieval timestamps. Missing fields remain missing. Retain source provenance without dumping complete provider payloads into every model prompt.

The specialist chooses search terms, relevant comparisons and follow-up detail requests. Prefer comparable new goods and reject obvious irrelevant results or duplicates. It may refine the query or broaden a location within the run allowance; it must not pretend poor results are adequate.

Manual initiation authorizes bounded read-only research for that run; this does not authorize posting, contacting sellers or ongoing monitoring. Backend applies a configurable finite request/image allowance so credit use is bounded. Exact allowance is an implementation default to determine from the feasibility sample, not a settled user requirement. Preserve existing conversation-loop limits unless evidence requires a change.

### 4. Image inspection
Actual image pixels must reach a verified vision-capable model path. Returning a photo URL or analyzing the listing text alone is insufficient.

Prefer a working image-input path in the selected Hermes runtime/provider. If unsupported, explicitly specify and validate a narrow image-analysis tool rather than silently assuming the text model sees images. That tool would return observations linked to image/listing IDs for the specialist's reasoning. Model/provider choice remains open pending the spike; no extra provider, installation or paid use is authorized by this spec.

Image observations distinguish visible features from inference: framing, background, visible packaging, staged setting and readable text where available. Do not infer fabric composition, quality, conversion or sales success solely from appearance. Inspect merchant imagery as needed for feasible visual briefs.

### 5. Agent decision loop
The normal loop is goal -> read merchant/product facts -> choose search -> inspect candidates -> select relevant details/images -> assess evidence -> draft -> check against merchant facts -> save and return.

This describes responsibilities and a checkable result, not a fixed script of queries or tool calls. The specialist decides whether evidence warrants additional investigation and adapts to irrelevant listings, missing fields or failed tools. It ends with a complete draft, an explicitly partial result or a clear blocker; it does not loop indefinitely.

### 6. Evidence, drafts and persistence
Store completed draft records and the evidence actually used in project persistence, accessible through a backend interface. Reuse the existing app SQLite store with additive tables/records if suitable; avoid a new database system.

Minimum draft fields: draft/run ID, specialist ID, product ID, merchant-facts snapshot or version reference, title, description, visual brief, rationale, cited listing/image IDs, timestamps and completion status. Evidence fields include source URL, relevant observed facts, price/currency when used, image observations and retrieval time. A retrieved photo URL is not guaranteed permanent availability; do not promise permanent image access without implementing it.

Separate current shared merchant facts from specialist memory and research records. Durable specialist preferences belong in its existing memory; large research payloads belong in evidence storage. A cross-specialist knowledge-sharing system is excluded.

### 7. API and temporary UI
Use the existing direct specialist chat endpoint for the manual trigger. Tool access, research decisions, validation and persistence belong in the backend; the UI displays the result and existing Activity records.

Provide a read interface for saved draft/evidence records, using IDs to retrieve the result after restart. No independent dashboard redesign, visual editor or elaborate new run UI is necessary. Keep the implementation replaceable when the frontend is redesigned.

## Feasibility checks before locking integration decisions
1. Using authorized ScrapeCreators access, run a small live home-textile search in a candidate US city. Verify useful prices/descriptions/photos and distinct sellers; retain a redacted sample. Suggested initial target: 15 relevant image listings across three sellers. This is a proposed dataset check, not a hardcoded agent workflow or established inventory count.
2. Confirm actual image inspection on the current runtime/model with known test images. Record the chosen supported path and observed result. Do not call text-only mocks a vision test.
3. Confirm onboarding completion and the actual saved catalogue/profile structure before implementing against it. Do not reset merchant data again as part of research integration.

Failure of a check narrows or revises the dependent decision. Do not fabricate a dataset or secretly substitute another platform.

## Testing decisions and acceptance
Test through existing chat/tool/backend interfaces where possible; avoid tests coupled to private helper structure. Use isolated runtime copies for destructive, failure and regression checks.

- Fixture-based integration: manual request produces a persisted draft with accurate catalogue facts, source links and image observations; no unsupported discount/material/delivery claim or publish call.
- Agency evidence: a deliberately irrelevant first result causes a changed search or justified alternate step. Tools are selected from observations rather than a single rigid query sequence.
- Failure cases: empty listings, missing image, provider error and exhausted allowance produce honest partial/error outcomes; unavailable tools never masquerade as success.
- Restart: company, specialist, conversation and saved draft/evidence remain retrievable without rerunning research.
- Permissions: main configures only eligible tools; specialist cannot create agents or perform external writes; current Laya creation controls still apply.
- Live acceptance: real Marketplace retrieval plus actual model image inspection yields at least one draft Arjun considers useful enough to use or edit. Report scraper, vision and text-reasoning results separately, along with elapsed time and request usage.
- Model compatibility: subscription development tests do not establish Nebius/NVIDIA compatibility. That check remains explicit and requires authorized credentials/spending before the final demo.

## Out of scope
Automatic/scheduled monitoring, image generation, publishing, seller contact, video analysis, Facebook Page posts, paid-ad-library research, Instagram/other platforms, news/trends, Shopify integration, extra specialist roles, recursive delegation, multi-business/accounts, shared specialist knowledge infrastructure, fine-tuning, context optimization, deployment, public repository publication and claims of sales uplift.

## Further notes and next step
This spec captures the agreed next useful outcome without changing the active onboarding scope. Complete/review onboarding, perform the small feasibility checks, update dependent decisions, then write one scoped inline Claude implementation prompt. Build one complete manual-request-to-draft slice first; split into tickets only if the verified implementation exceeds one manageable increment.

Sources: [ScrapeCreators Marketplace search](https://docs.scrapecreators.com/v1/facebook/marketplace/search/), [listing details](https://docs.scrapecreators.com/v1/facebook/marketplace/item/), [Matt Pocock to-spec](https://github.com/mattpocock/skills/blob/main/skills/engineering/to-spec/SKILL.md). Product decisions derive from Arjun's grilling answers, consolidated into this spec and summarized in HANDOUT.md; current-state claims derive from inspected code and HANDOUT.md, not from a newly executed test run.
