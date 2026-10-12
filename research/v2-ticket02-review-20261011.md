# V2-02 review — corrections required

2026-10-11. Codex using code-review: separate fresh Standards and Spec reviewers, read-only. No Git checkout, so explicit current-file snapshot used per agreed workflow. Feasibility note SHA256: 8b27507eea4b8272a1bf308d8c20d393c9e2c2eb1b2c3248a4d9994765a9e3d2. Existing app/scripts/tests source and fixtures match prior `.scratch/review-v1-clean-20261011`; no changed runtime code. No paid service calls, installs or actual-secret outputs during review.

## Spec
- P2, `research/v2-integration-feasibility.md:32` and48: do not deduplicate distinct ad_archive_id records by collation_id as if it denotes the same creative. [Official Company Ads docs](https://docs.scrapecreators.com/v1/facebook/adlibrary/company/ads/) define collation_id as related ads in a campaign, collation_count as ads in the campaign, ad_archive_id as actual ad ID. Preserve each ad's identity, optionally store campaign grouping separately; correct the claim these fields are unexplained. Spec decision3 requires distinguishing variants/cards from independent ads. Root independently confirmed source.
- Google model, selected-photo input, Interactions/store=false and retry warning supported by current official docs/source; no unsupported consequential capability found there. Live US coverage/edit fidelity remain explicitly unverified, not failed acceptance disguised as success.

## Standards
- P2, feasibility note103 (contrast65): four2K image-output charges establish a $0.2016 image component, not a guaranteed total under$1. [Google pricing](https://ai.google.dev/gemini-api/docs/pricing) also charges input/text/thinking. Remove spending assurance or state explicit assumptions/caps before budget approval; current estimate is unmeasured. Governing documented-fact distinction and conservative ticket02 allowance requirement.
- P3, HANDOUT320 and ticket02 Result credentials bullet: locally absent key does not establish external billing project's absence. The note110 correctly says unconfirmed; summaries should say key absent locally, billing status unconfirmed. Keep facts separate from hypotheses.

## Decision and next action
Documentation corrections required before treating the feasibility recommendation as accepted. No broad code correction needed. V2-01 role foundation can proceed independently after a scoped prompt. Missing actual merchant photos/product facts and Gemini key are correctly disclosed setup dependencies; no sample was fabricated. Do not authorize paid probes or interpret documentation review as live capability proof.

One full code-review pass used for this ticket as Arjun explicitly requested. Verify its correction directly without further reviewer agents. Preserve underlying source note until correction is reviewed; this report records required changes, not applied fixes.
