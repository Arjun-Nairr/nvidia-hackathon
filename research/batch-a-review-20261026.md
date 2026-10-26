# Batch A review — 2026-10-26

Result: corrections required; not accepted. One two-axis review of the uncommitted batch against HEAD f70acb0e1e5ec15826861af70662b230d06d69e0. No application code modified by reviewers.

## Spec
- P1 — Fresh runtime bypasses onboarding (app/onboarding.py:51-64). No onboarding row always means unlocked, including a brand-new installation. Direct ordinary chat and company saving remain available until the optional Start button is pressed. Requirement: fresh demo begins in onboarding; preserve genuinely existing installations without applying that exemption to an empty runtime. Independent offline reproduction: chat_blocked=False and chat_unlocked=True in an empty isolated root.
- P2 — Corrections have false attribution (app/onboarding.py:247-254). Name is always labelled source-derived and other labels depend on question topics, not corrections. Independent scripted reproduction: operator correction renames studio Cedar House, stored name Cedar House, provenance still says source (prepared demo snapshot). Keep attribution conservative and honest without a provenance framework.

## Standards / correctness
- P2 — Starting onboarding can interrupt an accepted main turn (app/onboarding.py:74-80,107-109; connected app/workers.py:90-92). Start uses a separate lock; source switches main conversation and worker manager stops the ordinary worker even if still answering. Standards reviewer reproduced with in-memory fake worker and actual onboarding/manager paths. Coordinate start and chat so an already accepted turn completes before switching; a busy response is sufficient, not a queue/framework.
- P2 — Failed answer submission clears answers/correction (app/static/index.html:95-101,120). Error path reloads state and recreates empty form. Preserve local entered values on recoverable model/save/validation failures; no new draft service required.

## Checks and boundaries
- Independent fresh isolated copy: tests/onboarding_test.py 33/33 passed. Existing tests do not establish the four missing cases; the initial-state expectation treats fresh and existing installs identically.
- Claude reported chat_api 18/18, social_role 38/38 and lint; these were not independently repeated. No lint rerun for this read-only review.
- Offline targeted reproductions for fresh gate and attribution used process-local scripted replies, no live model. No real runtime reset or live inference/scraper/Gemini calls.
- Remote main independently confirmed f70acb0e1e5ec15826861af70662b230d06d69e0. New onboarding batch stays uncommitted.
- Correction pass should address these four only, with regressions and a small adjacent audit. Direct Codex verification afterward; no repeated two-agent review.

## Direct correction verification — 2026-10-26
All four findings resolved at scripted level. Independently ran onboarding_test in a new isolated copy: 39/39, including fresh/legacy gates, correction attribution, busy main preservation and concurrent start/chat admission. Independently exercised the actual JavaScript snapDraft/restoreDraft functions with a minimal DOM double: option index 0, write-in and correction survive form replacement. This is a function check, not a new browser walkthrough. Claude recorded the failure/connection-loss browser checks above. No repeated lint or full two-agent review. Real-model behavior remains unverified. No new implementation blocker found; batch accepted at scripted level.
