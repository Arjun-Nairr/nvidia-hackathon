# V2-03 — Social specialist retrieves and inspects Facebook image ads

Status: ACCEPTED2026-10-13 after direct Codex correction verification (ad80/80, analyst57/57, lint). Scripted implementation only; live US coverage/model quality unverified. Report research/v2-ticket03-corrections-verification-20261013.md.
Blocked by: nothing for scripted wiring (V2-01 accepted; V2-02 documentation accepted). Live US coverage/reach/card schema need a separately authorized bounded probe.
Parent: `research/social-media-flyer-v2-spec.md`, decisions3–4 and acceptance3–4.

## Outcome
One specialist goal produces saved US Facebook image-ad references, actual-image observations and an honest reach-availability result. No market-analyst handoff or Gemini generation yet.

## Scope
- Narrow backend ad search/company/detail/photo tools using verified contracts; structured identifiers/filters, backend-only credentials and source-bound safe image downloads. Persist source IDs/URLs/text/advertiser/variant grouping/time/image hashes and available metrics.
- Grants only for social_media; agent chooses/refines queries, selects comparables and inspects actual pixels. Marketplace evidence cannot masquerade as ad evidence.
- Backend finite persisted API/photo allowances, atomic pre-send reservations, failed attempts counted, successful same-run cache and unknown-outcome no replay. Reuse suitable V1 utilities without a generic scraping framework.
- Reported reach informs relevant comparable selection only when semantically verified; unknown stays unknown, ranking-disabled status explicit, research continues. No metric substitutions or effectiveness claims.
- Expose saved normalized research through read API and existing chat/Activity. No new dashboard needed.

## Acceptance
- Existing chat/tool/read seams produce source-linked recorded research on isolated documented-shape fixtures; deliberately irrelevant/empty results produce agent adaptation or honest blocker.
- Test actual-image delivery separately from scripted model observations; never call mocked responses visual proof.
- Reach-present and absent fixtures preserve meaning/source/period/geography; absent reach disables ranking only. Variants do not inflate independent-ad counts.
- Unauthorized role/tool/URL/budget inputs rejected; provider failure, exhausted limits, redirect and storage failure explicit; concurrent/resumed requests cannot reset allowance or replay unknown fetches.
- Research/evidence survive restart with no scraper/model requests on retrieval; existing analyst/Marketplace workflow unaffected.

## Completion evidence
Show one saved research package and reach-gate state, source/photo lineage, actual call accounting and focused checks. Separate mocked wiring, documented capability and any separately authorized live evidence. Update ticket/index/HANDOUT.

## Result (Claude, 2026-10-12)
Note `research/v2-03-facebook-ad-research-result-20261012.md`; one saved scripted package `research/v2-03-scripted-package-example-20261012.json`.
- Six specialist-only tools for `social_media` (`fb_ads_find_advertiser`, `fb_ads_search`, `fb_ad_detail`, `fb_ad_image`, `save_ad_research`, `read_ad_research`) in `app/ads.py`, granted through the existing backend-validated `requested_tools` path; Marketplace tools stay ineligible for social, ad tools ineligible for the analyst. No fixed research sequence exists in code.
- Persisted: trusted run/request/agent/company identity, distinct ad ids + public links, advertiser, text, cards/images, campaign grouping (separate from ad counts), retrieval times, image hashes, available metrics, observations/selected references, reach-gate snapshot, exact call accounting. Read APIs `/api/ads/*`; retrieval needs no provider request.
- Allowance: per manual request 8 scraper attempts / 4 image downloads (operator settings), per-scope total; atomic reservation before send; failures and unknown outcomes counted and never replayed; no hidden retries; cannot be replenished by new request ids, restarts, parallel calls or model arguments.
- Reach: reported only for Meta's documented EU field (labelled EU, not US); anything else ambiguous/unavailable stays unknown; ranking disabled without two comparable values; impressions/spend kept as non-reach metrics. Absence never stops visual research.
- Checks: `tests/ad_research_test.py` 63/63 (scripted); regressions social 38, ticket01 28, onboarding 26, workers 22, e2e 24, chat API 18, research 79, listing 57, image path 31, archive 15, marketplace diagnostic 85, routing_e2e (real Laya) 23, route_table (real Laya) 54/55 (the one known miss, identical to baseline). Existing social specialists keep their grants and SOUL; new tools come only from creating a new specialist with them.
- Not covered: live US coverage, real card schema, real reach fields, failed-call charging, real model/vision behaviour, Nebius/NVIDIA, Gemini, flyer flow (tickets 04-06).

## Corrections (Claude, 2026-10-12) - accepted by Codex 2026-10-13
Note `research/v2-03-corrections-result-20261012.md`; corrected scripted package `research/v2-03-corrected-package-example-20261012.json`. Scripted only; no live call, no runtime reset, no commit/push.
1. **Inspection ownership:** inspections are persisted with the backend-supplied request id and the run that downloaded the image; `save_ad_research` accepts only an inspection bound to its own request and run. Legacy unbound rows never establish current-request evidence; analyst behaviour unchanged. Regression: request A downloads, request B inspects identical bytes, resumed A is refused (`image_not_inspected`); A's own inspection saves (C1-C3b, B8b, D3d).
2. **Terminal pagination:** `next_page` uses the latest successful page of the exact search; no continuation cursor there returns `no_next_page` (last page) without a provider call; separate queries/advertisers page independently (C4-C6).
3. **Platform eligibility:** a known platform list without Facebook excludes the ad in search results and later detail/search updates (not fetchable, detail-able or citable; disclosed with platforms); Facebook-only and mixed ads qualify; missing metadata stays `unknown` (C7-C10, B11).
4. **Reach comparability:** ranking needs the same metric, geography and an established measurement period. No documented field states the period, so `REACH_PERIOD_FIELD` is `None` and the gate is `disabled_period_unknown`; `reach_ranked` is rejected, relevance-only research and reported values/provenance are preserved; ad dates are never a period (A21, C11-C15, B11).
- Checks: ad research 80/80 (Part A 44/61 failing before the fix, 61/61 after); social 38, ticket01 28, onboarding 26, workers 22, e2e 24, chat API 18, research 79, listing 57 (D3d extended), image path 31, archive 15, marketplace diagnostic 85, reset 12, routing_e2e (real Laya) 23, route_table 54/55 (the known 'yes please' miss, identical to before) - all on isolated copies, scripted; `.\lint.bat` exit 0.
- Limits: scripted only; real ranking stays off until a documented period field exists; real platform spellings and live coverage unverified.
