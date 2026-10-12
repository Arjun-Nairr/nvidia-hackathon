# V2 social-media flyer tickets

Created 2026-10-11 using to-tickets. Parent: `research/social-media-flyer-v2-spec.md` (unchanged). Local tickets define work; they are not Claude prompts or implementation/paid-use authorization.

| ID | Outcome | Blocked by | Status |
|---|---|---|---|
| 01 | Independent social-media specialist created through main/Laya | None | Accepted 2026-10-11: two-axis review found no introduced defects; independent isolated checks 38/38 (scripted model). Report research/v2-ticket01-review-20261011.md |
| 02 | Verified integration plan and persistent usable product sample | None | Documentation accepted after direct Codex correction verification2026-10-11. Actual sample/local Gemini key missing, billing/live capabilities unverified. Report research/v2-ticket02-corrections-verification-20261011.md |
| 03 | Specialist researches Facebook image ads with honest reach gating | 01, 02 Facebook findings | Corrections required: four P2 issues; isolated checks63/63 passed. Report research/v2-ticket03-review-20261012.md |
| 04 | Specialist selects product photos and generates one stored/displayed flyer | 01, 02 Gemini/sample findings | Blocked |
| 05 | Actual-image review and at most one correction complete the agent flow | 03, 04 | Blocked |
| 06 | One preserved live demonstration and user visual evaluation | 05; separately authorized live budget/credentials | Blocked |

Recommended sequential execution: 02 -> 01 -> 03 -> 04 -> 05 -> 06. Checking API/sample availability first avoids implementing against guesses; 01 can still proceed if an external dependency is missing. No automatic parallel dispatch. 03 and 04 have independent prerequisites but Arjun's workflow remains one ticket at a time.

01 is the targeted preparatory role expansion. Preserve the existing analyst path while adding the new role; migrate only the relevant assumptions, without a broad framework rewrite. 03/04 are separately usable vertical slices, with explicit recorded/scripted evidence permitted during wiring and no claim of a live complete V2. 05 combines them into the specified independent-agent flow.

Every Claude prompt loads HANDOUT.md, PROTOTYPE_SCOPE.md and its ticket, consulting parent sections as needed. Each ticket returns concrete output, focused verification and a handout update below400 lines. Paid probes need a separately stated total budget, no hidden retry. Missing keys do not block unrelated surrounding work or permit fake live results.

Code-review skill at most once per meaningful implementation ticket; correction rounds direct verification. Documentation-only feasibility and final demonstration need evidence review, not an automatic two-reviewer code audit. No Git setup/publication/commit required solely for workflow compliance.

Artifacts persist locally; V1 spec/tickets/evidence remain. Arjun's V1 commercial-usefulness judgment and final Nebius/NVIDIA compatibility are not silently marked passed by V2 work.
