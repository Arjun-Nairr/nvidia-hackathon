# Ticket04 review — 2026-10-10

Decision: corrections required before acceptance or ticket05. Code reviewed, not modified.

## Review basis
Matt code-review skill, two fresh isolated reviewers (standards and spec). No Git repository: explicit current-file snapshot. Sources: PROTOTYPE_SCOPE.md, ticket04, marketplace-listing-spec.md, HANDOUT standards. Claude's recorded live result inspected; no live inference or scraping rerun.

## Standards
- Backend/UI separation and backend-derived specialist identity are sound for this slice.
- P2, app/listing.py:174: price guard recognizes dollar-prefixed amounts but not plain currency amounts or currency mismatches. Correct amount/currency are supplied catalogue facts, not semantic guesses.
- P2, app/listing.py:283: known image hash mismatches are recorded but do not affect completeness (285-291). False provenance must be rejected or explicitly partial, not complete.
- P2, app/listing.py:275: saved detailed evidence omits description/photo references returned to the specialist. A fixture hash cannot reconstruct those facts after input removal. Persist the relevant source content used.

## Spec
- P1, app/listing.py:283-291: a replaced image can be attributed to a recorded Marketplace listing and satisfy complete status. Scope acceptance1-3 require actual observations, honest failure and valid source provenance.
- P2, app/listing.py:174-176: descriptions 'Price: 79 USD.' and 'Price: $89 EUR.' pass against the89USD catalogue. Ticket04 requires accurate price/currency.
- P2, app/hermes_plugin.py:75-86 and app/listing.py:239-291: image preparation is logged before model delivery; text-only fallback still creates the same inspection record. Backend accepts supplied observations on that record as complete visual evidence. Preserve a distinction between prepared pixels and a supported vision path; unsupported fallback must not satisfy visual completeness. This is a source-traced issue, not a new live-model reproduction. Do not invent a guarantee that the model actually understood the image.
- P2, app/listing.py:275-278: description-supported rationale loses its supporting content when the evidence fixture changes/removes. Scope requires durable used evidence, not only references/hashes.

## Independent verification
- Unmodified isolated tests/listing_draft_test.py:34/34 passed (scripted model and real Hermes workers; not real vision). Sandbox setup failed at the existing Hermes CLI path; the same isolated suite completed with approved access to the existing installation. No real credentials or network inference.
- Additional pure-backend reproduction: registered saver + inspection hash of64zeros for listing1638806271151287. 'Price: 79 USD.', 'Price: $89 EUR.' and correct '$89 USD' all saved complete with matches_recorded_photo_hash=false. Stored listing keys omitted description/photos.
- Existing tests explicitly accept mismatched synthetic stand-ins as complete, explaining why the suite misses the defect.
- Claude's live sample demonstrates one correct draft, restart retrieval and replayed evidence on openai-codex/gpt-5.6-terra. That successful example does not cover these failures. No Nebius/scraper credits spent by this review.

## Portability and next step
Catalogue/evidence paths are configurable; UI is replaceable. Default demo catalogue is not yet bound to the user's company. A second merchant/product input should be checked before V1 completion; multi-company storage/additional roles are not requirements for this correction.
Ask Claude for one narrow correction slice addressing the four findings, with regression cases and no new providers, scraping, frontend, roles or speculative semantic-validator framework. Ticket05 remains blocked pending correction review.

## Snapshot SHA256
- app/listing.py:5570E878C61D0736A9CF35E2DCD22FA4CDA30F3C2E184F86C86F47C2BEF44017
- app/core.py:509B9FF26C95504CDF6910355A79F152901ADE65AF1F6C5C0961241E78D8C58F
- app/hermes_plugin.py:39C20A6D83549F3ED2AEBE65092E915CF6CD0417E892B49E21EA726DF7C8406C
- app/worker.py:8A244BE655626092A503062275DECDE15FA2960ED07480FD665569DFA2214F8E
- app/server.py:953ECB8D708F4ACFFF4E1D18CA74049895CE9CC7EC8149F7320321D99DA5D9A3
- tests/listing_draft_test.py:7A1190EC8330B094808CB5EC36781B0605DF67B37E26CFA3AFEB8F15F7F0591A
