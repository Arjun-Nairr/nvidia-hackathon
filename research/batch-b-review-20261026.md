# Batch B review — 2026-10-26

Status: corrections required, not accepted. One two-axis code-review pass of the uncommitted batch against HEAD b6588598c6ffa06a87d88461356a1eeca11a35d5. No application source modified by Codex.

## Spec axis
No separate spec-completeness finding from the spec reviewer. Creation, operator-mode authorization, partial updates, runtime tool checks and next-turn prompt refresh follow the approved plan on their normal paths. Correctness findings below prevent acceptance.

## Standards / correctness axis
### P2 — Skill removal can report success while leaving the skill active
Location: app/core.py:960-963. Removed skill directories are deleted after committing registry/config-log changes, with shutil.rmtree(ignore_errors=True). Both the reviewer and root independently reproduced in isolated temporary profiles: mark custom SKILL.md read-only on Windows, remove that skill through customize_agent; result ok=True, registry no longer lists it, file still exists and remains available to Hermes. Re-adding the same name returns skill_name_taken. Removal failure must not produce a successful applied update with mismatched registry/profile state. Keep memory, baseline and agent-owned skills intact.

### P2 — Native skill_manage bypasses operator-managed skill ownership
Location: app/hermes_plugin.py:395-400; connected core.profile_config and installed Hermes tools/skill_manager_tool.py / tools/write_approval.py. The specialist hook restricts customize_specialist and optional ecom tools but not native skill_manage, which is available through mandatory skills. The standards reviewer confirmed a real native edit against an isolated temporary profile using app-equivalent settings: gate allow=True, edit success=True, file changed. Hermes skill-write approval is disabled by default; the comment about always staging does not apply unless that gate is enabled. Thus ordinary turns can edit registered operator custom skills/baseline files outside the managed configuration operation, bypassing the new ownership boundary and leaving registry/inspector stale. Protect baseline and registry-managed skill targets while retaining ordinary creation/editing of agent-owned procedural skills. Enabling another approval UI is not required.

## Independent checks
- Fresh isolated-copy tests/specialist_config_test.py: 28/28 passed; proves normal paths, not these missing failure/ownership cases.
- Root reproduced the Windows removal failure with no model or network call. Native bypass was reproduced independently by the standards reviewer using installed Hermes, no live profile/model/network.
- Other suite totals and lint in research/batch-b-specialists-20261026.md remain Claude-reported; no duplicate full regression/lint run.
- No runtime reset or live API calls. Batch stays uncommitted; no push. Only these two corrections plus focused regressions are needed next; correction verification will be direct, without another two-agent review.

## Direct correction verification — 2026-10-26
Result: NOT accepted yet. No repeated code-review skill or reviewer subagents. Independent fresh isolated-copy specialist_config_test: 37/37 passed; the original normal-path failures are fixed. Two remaining cases were independently reproduced by Codex with temporary profiles, without models/network or real runtime changes:

1. P2 — Recovery copy can be deleted on the next customization (app/core.py:954; _drop_staging at 851). Force a SOUL write failure after a skill was staged, and a failure moving that skill back. The operation correctly reports restoration trouble and keeps its sole staged copy. Once the lock is removed, an objective-only customization calls _drop_staging first, deletes that copy, returns ok, and leaves the registry referencing a missing skill. Repro output: first call customization_failed, active file False, staged copies 1; next objective update ok=True, registry skill retained True, active file False, staged copies 0. Preserve/recover unresolved staging rather than treating all leftovers as successfully removed garbage. Include restart/next-operation regression; a clear recovery-required block is sufficient if automatic restoration is not safe.

2. P2 — Windows trailing-dot alias bypasses the protected-skill guard (app/hermes_plugin.py:417). The guard compares raw last segments with protected names; Windows treats a trailing dot as the same directory. Reproduced native skill_manage(action=create, name=competitor-analysis-baseline., valid content) under app-equivalent temporary profile: app guard None, native success True, original baseline bytes changed. Normalize or reject these aliases before deciding a target is agent-owned; cover protected baseline and registered custom skills and preserve legitimate own-skill operations. Do not change installed Hermes.

Evidence: .scratch/codex-batch-b-fixes-verification.txt (37/37); temporary repro roots .scratch/b-rollback-review-* and .scratch/b-name-alias-review-* (ignored, no real credentials). No duplicate lint run; Claude-reported lint remains recorded. No new source changes, commit, push or paid calls. Next correction should address these two cases only, then direct verification.

## Final direct correction verification — 2026-10-26
Batch B ACCEPTED SCRIPTED. Independent fresh isolated copy specialist_config_test 44/44 passed, including recovery refusal/preservation across restart, restoration before later updates, normal removal/cleanup, real-worker native alias refusal and continued agent-owned skill editing. Root also reran the exact prior recovery and alias reproductions independently: both now pass. No new blocker found. No repeated code-review skill, subagents, broad suites or lint. Other regression/lint totals above remain Claude-reported. Real-model onboarding/customization and NVIDIA compatibility remain unverified; no live APIs or real runtime reset used. Authorized batch checkpoint includes only relevant code/tests/reports; unrelated learning and skill-install notes excluded.
