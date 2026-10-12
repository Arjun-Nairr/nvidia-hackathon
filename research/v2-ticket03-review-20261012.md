# V2-03 code review — 2026-10-12

Outcome: CORRECTIONS REQUIRED; ticket not accepted. Two isolated code-review axes compared current sources with `.scratch/baseline-v2-03-20261012`. No Git setup, production code changes or paid calls.

## Standards

- **P2 — Inspection request identity missing** (`app/ads.py:914–915,932–935`; `app/listing.py:182–183`). Inspections are selected by agent/image/hash and a creation-time lower bound, without trusted request/run identity. Request A can download without inspection, request B later inspect identical ad bytes, and resumed A credit B's inspection as its own. Persist and enforce trusted inspection ownership; legacy unbound rows must not establish current-request verification. Violates documented backend-owned request lineage. Also independently found by the spec reviewer.
- **P2 — Terminal pagination reuses an old cursor** (`app/ads.py:658–665`). Selecting the latest truthy cursor skips the terminal page, then selects an earlier cursor and returns the cached terminal page repeatedly. Select the latest matching page first and honor its absent cursor. Violates the narrow next-page contract and can waste model iterations. Codex reproduced the selection algorithm with terminal-page fixtures: it selected `page2` instead of stopping.

## Spec

- **P2 — Instagram-only rows qualify as Facebook references** (`app/ads.py:681–693`, platform normalization at361). Search excludes video but not explicit incompatible platform metadata. A row with `publisher_platform: ["INSTAGRAM"]` remains eligible for download/package inclusion. Filter explicitly incompatible platforms, disclose exclusions and preserve unknown metadata honestly. Violates Facebook-only scope and deferred Instagram retrieval. Codex independently normalized such a fixture: platforms INSTAGRAM, excluded null.
- **P2 — Reach comparison accepts unknown periods** (`app/ads.py:413–415,429–432`). Two same-metric/geography values enable ranking although their periods are always unknown. Preserve reported values but gate comparison until metric/geography/period compatibility is established; do not require identical ad lifetime dates as a substitute. Violates decision4's compatible-meaning/cross-period rule. Codex's pure gate probe enabled ranking for totals with differing ad dates and no established measurement period.
- Inspection ownership finding above also violates same-request actual-image lineage acceptance.

## Verification

Codex independently ran `tests/ad_research_test.py` on `.scratch/review-v2-03-20261012`: **63/63 passed**. Real server/Hermes workers, local scripted provider/model, no real secrets/runtime copied. Checked atomic caps, failures, source-bound images, grants, image-byte delivery, packages, restart and stored retrieval. These tests do not cover the four findings, and their current present-reach expectation permits the problematic unknown-period ranking. Passing is wiring evidence, not live coverage/vision quality or acceptance.

The first sandboxed attempt could not start the local test server. Approved isolated execution completed successfully. Production runtime remained untouched. Reviewer axes were read-only; root probes were isolated/pure.

Next: one scoped Claude correction prompt for these four issues with regression coverage and a small self-audit. Direct Codex verification afterward; no second two-reviewer pass for this ticket. V2-04 remains undispatched; live US coverage/reach and Nebius/NVIDIA remain unverified.
