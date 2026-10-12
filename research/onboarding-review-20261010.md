# Onboarding review, 2026-10-10

Read-only scoped current-file review by two fresh Codex subagents, separately evaluating standards and spec. No Git baseline exists; this is not a pinned-diff review. No live model calls or credentials inspected. No application code changed.

## Standards
Confirmed company-save race: app/core.py update_company reads, merges and replaces runtime/company.json without synchronization and shares company.tmp between writers. Form saves and main's company-update tool run in different threads/processes and may overlap. Reviewer reproduced two acknowledged partial updates (company name and products) with both returning ok:true but one field absent from final saved data, using isolated temporary storage that was then removed. This violates the agreed persistent user-provided company-facts behavior; it is material data loss, not a style finding.

Fix the full read/merge/write transaction across processes, not just the temp filename or an in-process thread lock. Verify simultaneous disjoint field updates survive and failures return explicit errors. Use the simplest storage/synchronization consistent with the existing application.

## Spec
Accepted requested_tools can omit memory and skills (including an empty list). app/core.py validation accepts this, create_agent only forces read_company_context, and run_turn derives toolsets from actual grants. A valid generated specialist may therefore lack skill_view and memory despite instructions to load its baseline and the handout claiming all foundation tools are backend-granted. Existing onboarding tests request all three tools and miss this case.

Grant mandatory foundation tools automatically or reject omission with a corrective error. Main should choose optional capabilities within eligible tools; mandatory baseline facilities must remain available. Verify an empty/partial eligible request cannot produce an unusable foundation and disallowed tools remain rejected.

## Evidence and limits
Claude reports scripted onboarding26/26, real-Laya scripted routing21/21, reset12/12, existing regressions24/24,18/18,22/22 and live subscription onboarding12/12. Codex inspected test implementation but did not rerun these suites or the live path. The live script permits form fallback; its pass count alone does not guarantee fully conversational onboarding for every input. Threshold tuning on the same routing cases is not independent classifier accuracy.

Codex independently confirmed actual runtime company file absent, only main profile present, registry agent count0 and transcript count0, plus backup manifest presence. Backup contents/integrity were not independently revalidated.

Next action: one scoped corrective Claude ticket for these two material findings, meaningful regression checks and handout/scope update. Do not add Marketplace research features yet or repeat the demo reset. Active onboarding increment remains awaiting fixes/review.
