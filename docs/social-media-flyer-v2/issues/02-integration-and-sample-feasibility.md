# V2-02 — Verify API contracts and prepare the persistent sample

Status: ACCEPTED as documentation feasibility after direct Codex correction verification2026-10-11. Campaign grouping, unmeasured cost and billing wording corrected. Partial readiness: sample/photos/facts missing, Gemini key absent locally, billing project unconfirmed, live capability unverified. Verification: research/v2-ticket02-corrections-verification-20261011.md. Earlier review remains historical.
Blocked by: none.
Parent: `research/social-media-flyer-v2-spec.md`, decisions2–6 and verification dependencies.

## Outcome
The next tickets have cited real Facebook/Gemini contracts and a clearly configured usable merchant/product sample, or named dependencies explaining what cannot yet be tested. No paid-call inference from this ticket.

## Scope
- Read official ScrapeCreators US image-ad search/company/detail schemas, variants/cards, source links/images and reach fields. Cite exact endpoint shapes; if reach is undocumented/unavailable, choose ranking-disabled by default pending authorized verification. Do not substitute Marketplace/posts/another region or invent reach.
- Read official Gemini image-generation selected-photo input/edit docs, supported model IDs/response formats/credential requirements, cost and SDK retry behavior. Recommend one concrete supported path behind a narrow tool, retaining current Hermes reasoning provider/model. No SDK installation or paid probe without explicit scoped authorization.
- Inspect existing assets/configuration without exposing secrets. Prepare one persistent configured home-textile sample with2–3 actual supplied product photos, correct declared price/specs and simple brand direction; record provenance and registered mapping. Preserve original runtime. If actual photos/facts are absent, report the exact required inputs; do not use competitor assets or a synthetic illustration as real merchant photography.
- Specify conservative operator research/download/model-generation caps and one proposed total live-demo allowance for later approval. Two-generation limit is already fixed, not adjustable by agent.

## Acceptance
- Cited durable feasibility note contains verified versus unverified endpoint/model facts, missing credentials/assets and chosen tool inputs/output/error semantics.
- Reach meaning and availability are explicitly recorded; no public engagement or impression value relabelled as reach.
- Gemini selected merchant-photo input and any correction/edit support are documented; provider limitations and automatic retry configuration recorded, with no claim of a live test.
- Sample persists with matching merchant/catalogue and2–3 real registered photos, or sample-dependent tickets stay explicitly blocked. No missing fact is fabricated.
- Findings identify which03/04 prerequisites are usable separately. No paid service, credential disclosure, tool installation, publication or company reset.

## Completion evidence
Return the compact source-backed findings, sample manifest or missing-input list, proposed caps and precise readiness of03/04. Update HANDOUT/index without marking missing live verification as passed.

## Result (Claude, 2026-10-11)
Note: `research/v2-integration-feasibility.md` (cited; documentation vs source reading vs recommendation vs untested separated). No paid scraper, Gemini, model or Nebius call; no install, provisioning, reset or UI change.
- **Facebook:** ScrapeCreators `search/companies`, `company/ads`, `search/ads`, `ad` contracts, fields, variants/cards and source identifiers recorded. **US image-ad coverage unverified; every reach value is null in all documented examples and undefined by ScrapeCreators; Meta documents reach only for EU/UK (and political/issue) ads, none for US commercial ads.** Ranking disabled by default; generation unaffected; no proxy metric. Narrow tool contracts proposed.
- **Gemini:** `gemini-nano-banana-2.1` via the Interactions REST endpoint (`POST /v1beta/interactions`), text + up to 10 high-fidelity merchant photos, 4:5 at 2K, PNG, `store=false`; edit by re-sending the candidate (fidelity untested); paid tier only; image-output charge $0.0504 per 2K image (input and text/thinking charges extra; total spend unmeasured). **Python SDK retries by default and `attempts=1` still permits one retry in the Interactions client**, so use one plain HTTP POST per reserved slot.
- **Sample: BLOCKED.** No actual merchant product photos or verified product facts exist (only the labelled synthetic illustration and competitor photos). Missing-input list in section 4 of the note; nothing fabricated or downloaded.
- **Credentials:** ScrapeCreators present; Gemini key absent locally; billing-enabled project unconfirmed.
- **Proposed total live call allowance (counts only; not a dollar ceiling, not authorization to spend):** ScrapeCreators <= 11 attempts, <= 5 ad-image downloads, Gemini <= 4 calls (2 probe + 2 demo), reasoning model <= 26 requests.
- **Readiness:** ticket 03 contract/caps ready, live coverage/reach unverified; ticket 04 contract ready, live blocked by Gemini key and sample. Recommended next: V2-01.

## Corrections (Claude, 2026-10-11) - historical heading; accepted after direct verification (research/v2-ticket02-corrections-verification-20261011.md)
Responds to `research/v2-ticket02-review-20261011.md` (kept as historical evidence). Documentation only; no paid call, install, runtime change or sample.
1. **Campaign grouping:** `collation_id` = "Facebook's internal ID for related ads in a campaign", `collation_count` = "The number of ads in the campaign", `ad_archive_id` = "The *actual* ad id" (official Company Ads and Search ads field descriptions). Not proof of identical creative: distinct `ad_archive_id` records are preserved; campaign id/count stored separately; no creative dedupe from these fields. The "unexplained" claim and "group_no" dedupe rule were removed.
2. **Cost:** the unsupported "well under $1" assurance was removed. Four 2K image outputs = $0.2016 at the documented $0.0504; input and text/thinking charges are additional, so total spend is unmeasured and conditional. The call allowance is not a dollar ceiling or authorization to spend.
3. **Billing:** "Gemini key absent locally; billing-enabled project unconfirmed" everywhere (note, handout, this ticket).
Unchanged and still disclosed: missing merchant photos/facts, unverified US coverage/reach/edit fidelity.

