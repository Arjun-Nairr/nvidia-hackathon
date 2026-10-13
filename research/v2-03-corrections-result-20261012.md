# V2-03 review corrections — result, 2026-10-12

Author: Claude Code. Ticket: `docs/social-media-flyer-v2/issues/03-facebook-ad-research.md`. Review: `research/v2-ticket03-review-20261012.md`. Status: **implementation complete, awaiting direct Codex verification; NOT accepted.**

Scope: only the four review findings and their regression coverage. Scripted provider (`tests/mock_fb_ads.py`) and scripted model only; no live ScrapeCreators, reasoning-model, Gemini or Nebius call; no runtime/profile reset; no commit or push. The earlier note `research/v2-03-facebook-ad-research-result-20261012.md` still describes the original implementation; where it differs (reach gate, inspection lookup, platform handling, pagination) **this note supersedes it**.

## Failing before, passing after

The new checks were written first and run against the unmodified code (isolated copy, Part A only): **44/61 passed, 17 failed** = the changed expectation `A21` plus `C1`–`C15`, each for the stated defect. After the fix the same Part A is **61/61** and the full file (Part A + real server/worker Part B) **80/80**.

| # | Finding | Failing before (unmodified code) | After |
|---|---|---|---|
| 1 | Inspection not bound to the request/run | `C1`: request B inspected identical bytes, resumed request A saved its package (`OK`); `C3`: a legacy row with no request/run satisfied the save (`OK`); `C2`/`C3b`: the columns did not exist | `C1` `image_not_inspected`, nothing saved, nothing sent; `C2` A's own inspection saves, rows and package carry request + run ids; `C3` legacy row refused; `C3b` non-ad inspections keep kind/table, gain request id; real worker `B8b`; migration `D3d` |
| 2 | Terminal page reused an older cursor | `C4`: after page 1 (cursor) and page 2 (terminal) a third `next_page` returned `OK` (cached page 2) every time, with no stop; `C5`, `C6` same for a second query and an advertiser | `C4`/`C6` explicit `no_next_page` ("last page") with **zero** provider calls and no allowance used; `C5` another query pages independently and the stop holds after re-reading page 1 from the store |
| 3 | Instagram-only ads qualified | `C7`: the Instagram-only ad was returned and its image/detail requestable; `C8`–`C10`: a row identified as Instagram-only by a later detail or search stayed downloadable/selectable | `C7` Facebook-only, mixed and unknown qualify, Instagram-only excluded + disclosed + not fetchable; `C8` unknown → Instagram-only via detail becomes ineligible (even with the file downloaded); `C9` cannot be cited, package discloses; `C10` a later search updates the stored ad |
| 4 | Unknown reach periods compared | `A21`/`C11`/`C14`/`C15`: two EU values with unknown periods gave `enabled` and `reach_ranked` was accepted; an excluded ad's value counted | `A21`/`C11` `disabled_period_unknown` (different or identical ad dates alike); `C14` `reach_ranked` rejected (`reach_ranking_unavailable`) and the same research saves as `relevance_only` with values kept; `C12` no lookalike field is read as a period; `C13` gate logic with a *hypothetical* documented period; `C15` excluded ads add no value; Part B `B11` replaced |

## What changed

| File | Change |
|---|---|
| `app/core.py` | `image_inspections` gains nullable `request_id` and `run_id` (additive `ALTER`, same pattern as `delivery`). |
| `app/listing.py` | `record_inspection` stores the backend turn state's request id and the run that downloaded the image (ad run for `live_ad_image`, research run for live Marketplace photos, else NULL). No behaviour of the analyst path changes. |
| `app/ads.py` | Pagination, platform eligibility (`exclusion`, `platform_status`, `_ineligible`), inspection binding in `save_package`, reach period and gate states, disclosure fields (`skipped.excluded_non_facebook_ads`, `excluded_ads`, `ads_considered[].platforms/excluded`, `counts.ads_excluded`, `references[].inspection_request_id/run_id`, `reach_gate.period`). |
| `app/roles.py`, `app/hermes_plugin.py` | One-clause guidance updates (period, platform skip, last page). Existing specialists' stored SOUL/skills are not rewritten (unchanged policy). |
| `tests/ad_research_test.py`, `tests/mock_fb_ads.py` | New checks A21 (replaced), C1–C15, B8b, B11 (replaced); mock controls `pages`, `list_platforms`, `detail_platforms`; `ADS_PART_A_ONLY=1` for quick iteration. `tests/listing_draft_test.py` D3d extended (legacy rows gain NULL request/run). |

## Design decisions (so Codex can disagree precisely)

1. **Inspection ownership.** `save_ad_research` accepts an inspection only when `agent_id`, `kind='live_ad_image'`, `request_id` = the request's id and `run_id` = this request's ad run all match (plus the existing hash and creation-time bounds). Rows written before the columns existed are NULL and can never match. Identity comes from the worker's turn state (`turn_state.request_id`, `turn_state.ad_run_id`), never from model arguments. The analyst's own lookup (`listing.py` by agent and image id) is intentionally unchanged.
2. **Pagination.** The cursor comes from the **latest** successful page of the exact search (same parameters minus `cursor`). No cursor on that page = last page = explicit `no_next_page` before any provider request. Older cursors are never consulted.
3. **Platforms.** A recorded ad is ineligible when its platform list is known and **no entry contains FACEBOOK**. This covers Instagram-only and also any other list without Facebook (e.g. Messenger- or Audience-Network-only); a Facebook+Instagram ad qualifies; a missing or empty list stays `unknown` and is never filled in. Eligibility is **derived from the record's current fields**, so the latest explicit platform data (search or detail) decides; the ad stays recorded (numbering stable, shown under `ads_considered` with its platforms) but is not offered by search pages (counted under `skipped`), cannot be detailed, downloaded or cited, and contributes nothing to the reach gate. Unknown-platform ads remain usable and are labelled `platform_status: unknown`. Video ads keep their previous handling.
4. **Reach.** `reach_gate` is `enabled` only when ≥2 eligible ads report the same metric, the same geography **and an equal, established period**. The period is read only from `REACH_PERIOD_FIELD` in `app/ads.py`, which is `None`: no documented ScrapeCreators/Meta field names the measurement window of `eu_total_reach` (the recorded feasibility note `research/v2-integration-feasibility.md` and Meta's archived-ad reference name none; no new documentation lookup was made in this task). Ad start/end dates are never used. Consequently **real ranking is gated off today**; `reach_ranked` is rejected with the gate state, relevance-only research is unaffected, and reported values keep metric, value, EU geography, `period: null` and source. New states: `disabled_period_unknown` (shared metric/geography, a period missing) and `disabled_incompatible_metrics` (now also different stated periods). If a documented period field appears, set `REACH_PERIOD_FIELD` to it and add the real contract to the test.

## Preserved package

`research/v2-03-corrected-package-example-20261012.json` — one scripted package from the real server/worker path (`B11`): two cited ads with **reported EU reach and unknown period**, `reach_gate.state = disabled_period_unknown`, `selection_basis = relevance_only`, an Instagram-only ad listed in `ads_considered` with `excluded: not_on_facebook`, and each reference carrying `inspection_request_id` / `inspection_run_id`. Invented fixture data, not live.

## Checks

- Condensed before/after output of the new and changed checks: `research/v2-03-corrections-test-output-20261012.txt`.
- `.\lint.bat`: exit 0 (Ruff + ESLint).
- `tests/ad_research_test.py`: **80/80** (Part A 61, Part B 19) — Part A before the fix 44/61.
- Regressions (isolated copies, scripted): social 38, ticket01 28, onboarding 26, workers 22, e2e 24, chat API 18, research 79, listing 57 (D3d extended), image path 31, archive 15, marketplace diagnostic 85, reset 12, routing_e2e (real Laya) 23, route_table 54/55 (the known 'yes please' miss, identical to before) - all on isolated copies, scripted
- Not run: anything live; the V1 demo scripts.

## Self-audit of adjacent paths

- `_merge`: later partial records never erase platform data, and the newest non-empty list replaces the older one (so a detail can both exclude and re-qualify an ad); covered by `C8`/`C10`.
- Cached search view and `fb_ad_detail` re-read eligibility from current records; no stale cache path can re-offer an excluded ad. `image()` checks eligibility **before** the stored-file shortcut.
- Fresh and cached search results disclose the same `skipped` keys; package `ads_considered` and the save result list exclusions with platforms.
- `reach_gate` ignores ineligible ads for values, counts and ambiguity.
- Platform list cap raised from 6 to 12 entries so a late `FACEBOOK` is never truncated away.
- Inspection rows for non-ad kinds record the request id and (for live Marketplace photos) the research run id; nothing reads them yet, so analyst behaviour is unchanged (listing 57 and research 79 suites).

## Remaining limitations and separate observations

- **Still scripted.** Nothing here validates live US coverage, real `publisher_platform` spellings, real reach fields, failed-call charging, URL expiry, model query/vision quality or Nebius/NVIDIA.
- **Ranking cannot turn on with real data** until a documented period field exists (by design of the correction).
- **Platform spellings.** Matching is "an entry contains FACEBOOK" (case-insensitive); an undocumented spelling of Facebook would be mis-excluded and a list that names only unlisted surfaces is excluded. Unverified live.
- **Resumption is modelled in-process** (same database, fresh turn state, request id reused): the chat API replays a completed request id from the store instead of resuming it, so there is no HTTP-level 'resume' to drive. The worker-level proof is `B8b` (real worker rows carry the ids).
- **Pre-existing, not changed:** a resumed turn must call an ad tool (even a cached one) before `inspect_image`, because ad image visibility is bound to the turn's `ad_run_id`; packages saved before this correction are not re-validated (none exist outside scripted copies).
- Unknown-platform ads can still be cited; they are labelled `unknown` per ad and in `ads_considered`, not downgraded to `partial`.
