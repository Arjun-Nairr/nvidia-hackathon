# V2-03 correction verification — 2026-10-13

Outcome: ACCEPTED for scripted implementation and the four scoped corrections. Direct Codex inspection/checks only; no code-review skill, reviewer agents, live inference or paid scraping.

## Verified changes

1. Inspection schema gains additive trusted request/run columns. Ad package validation selects only same-agent, same-request, same-run inspections of the registered hash; legacy unbound rows cannot satisfy ad verification. Worker-generated records and saved provenance carry those identities.
2. Pagination selects the latest successful matching search page before reading its cursor. A terminal page stops continuation, including repeated attempts and independent query/advertiser paths.
3. Search, cached views, detail updates, downloads and package selection consistently exclude explicitly non-Facebook ads. Mixed Facebook/Instagram remains eligible; missing metadata stays unknown. Exclusions are disclosed and excluded ads do not influence reach gating.
4. Reach comparison requires established compatible measurement periods. Current normalization has no documented period field, so reported values remain available but real ranking stays gated. Relevance-based research continues; ad dates do not establish measurement periods.

## Independent checks

- `tests/ad_research_test.py`: **80/80**, isolated `.scratch/verify-v2-03-corrections-20261013`, real Hermes/server plus local scripted provider/model. Includes all correction regressions, actual image-part delivery, worker-bound inspection identity, restart retrieval and durable allowances.
- `tests/listing_draft_test.py`: **57/57**, separate isolated `.scratch/verify-v2-03-analyst-20261013`. Confirms additive schema compatibility, preserved analyst draft/image behavior and restart retrieval.
- `.\lint.bat`: exit0 (Ruff and ESLint).
- `git -c core.whitespace=cr-at-eol diff --check`: exit0. Default whitespace checking flags Windows CRLF here; no source reformatting performed.
- Inspected corrected saved fixture: two references bound to its request/run, `image_part_sent`, complete relevance-only package, `disabled_period_unknown`, ranking false. Scripted provenance remains labelled as such; not live inventory/vision-quality evidence.

## Limits and next step

Live US ad coverage/platform spellings, model research/vision quality, real metrics and Nebius/NVIDIA remain unverified. Resumed-request ownership regression uses fresh turn state with the persisted database; HTTP completed-request replay and actual restart retrieval have separate checks. Unknown platform metadata is allowed with an explicit unknown label. Historical saved packages are not retroactively revalidated.

No production code changed by Codex, no runtime reset, commit or push. Ticket4 can now be scoped; a small live research evaluation remains separately authorized, as do Gemini credentials/sample and later generation checks. Changes are currently uncommitted.
