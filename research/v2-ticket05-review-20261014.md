# V2-05 review — 2026-10-14

Outcome: CORRECTIONS REQUIRED; not accepted. Two isolated code-review axes reviewed current changes against pinned ticket4 checkpoint `ee168466e9e418eb2f72452509ec73b7c5b923d2`. No production implementation changes, paid calls, commit or push.

## Standards

- **P2 — Two-candidate summary skips artifact checks** (`app/flyer.py:451,536–537`). Historical outcome=ok counts as a valid candidate before current file validation. With two successful attempts and no explicit selection, corrupt/missing files still produce awaiting_selection and “Two valid candidates exist,” even if neither can be used. Violates HANDOUT's every-read integrity rule. Validate selectable artifact state first, retain candidate-specific failures and expose a storage/blocker state when none is valid. Also found independently by spec reviewer.

## Spec

- **P1 — Same tool batch can verify a review before image delivery** (`app/flyer.py:1082–1089,1194–1203`). inspect_flyer stores image_part_sent from the worker capability prediction before returning its multimodal result. A subsequent review_flyer in the same assistant tool batch trusts that inspection, although no later model request has received its pixels. The hash is already available in the generation/read records. Installed Hermes executes multi-tool batches without an intervening model response (reviewer inspected run_agent.py:1314–1337 and agent/tool_executor.py:1785–1792). Violates spec6: no review success without actual pixels. Bind eligibility to an actual prior model-input/response boundary and reject same-batch reviews; capability prediction alone is insufficient. Scope tests must exercise multiple tools in one assistant message.
- **P2 — Cached response mixes attempt and selected-flyer state** (`app/flyer.py:702–709`). Returned candidate ID/image belong to the latest attempt, while status/note describe the selected candidate. Reachable example: first candidate has defects, second passes, agent explicitly selects first; repeated correction returns second image under first's unresolved label. Return a coherent selected result or distinguish attempt and final states explicitly. Violates spec7–8's candidate/review/final-output linkage.
- Two-invalid-artifact finding above also violates spec6's no-valid-candidate blocker requirement.

## Independent evidence

- `tests/flyer_review_test.py`: **36/36**, isolated `.scratch/review-v2-05-20261014`; real Hermes/server plus local scripted Gemini/reasoning/ad stand-ins and placeholder images. No real runtime/secrets copied. Covers normal pixel delivery, one correction, limits, selection and restart, not the three findings.
- `.\lint.bat`: exit0.
- Root source inspection confirms premature inspection flag and cached candidate/status mismatch. Root isolated probe damaged both fake candidate files, supplied no selection, and reproduced awaiting_selection with error=null; original bytes restored. Cached replies returned latest IDs with selected first's unresolved status. No production files were touched.
- Other broad regressions remain Claude-reported. Scripted image controls prove delivery/decision wiring, not real review accuracy or Gemini fidelity.

Next: prioritize delivery-bound verification in a fresh, tightly scoped correction session, then the two result-state corrections. Direct Codex checks afterward, no repeat two-reviewer pass. Ticket6/live evaluation remains undispatched and separately authorized.
