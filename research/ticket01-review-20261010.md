# Ticket 01 review, 2026-10-10

Code-review workflow: two fresh isolated reviewers, Standards and Spec axes. Scope is ticket01 corrections, not the future Marketplace feature. No Git baseline exists: current-file review with hashes, not a pinned-diff review. No production code changed.

## Standards
No material findings. Full read/merge/write transaction is backend-owned and protected by an OS-level cross-process file lock; failed saves return explicit errors. Mandatory grants flow consistently to registry, response and worker toolsets. No material architecture smells established. Standards reviewer inspected relevant code and regression coverage, but did not rerun the suite.

## Spec
Both material onboarding findings are resolved. Independent isolated verification: five processes each performing 30 disjoint updates produced 150 successes with correct final field values and no process errors. Injected replace failure preserved saved bytes, returned company_storage_error and cleaned the temporary file. Empty/omitted/partial tool requests received context, memory and skills; forbidden email was refused.

One P3, nonblocking validation finding: app/core.py:312 uses `a.get("requested_tools") or []`, coercing false, 0, empty string and empty object to an empty list before list validation. All four accepted cases independently reproduced. This predates the fix and grants no forbidden capability. It conflicts with ticket01's invalid-request rejection wording. Default only an omitted value and validate supplied values; add these cases to tests when next touching tool validation. No urgent runtime or permission issue established.

## Evidence distinction
Claude reports regression28/28, form-vs-tool overlap, worker skill/memory use and restart checks plus existing suites26/26,24/24,22/22,18/18,21/21,12/12. Reviewers inspected those tests, not a complete independent rerun. Independent tests above used disposable project-contained storage, then cleaned it; production data, credentials and live models were untouched. No Nebius credits used.

## Reviewed hashes (SHA256)
- app/core.py: 118CBD4B4F7613C7EFAAEBEBAAF2D85D020C390FF0203F16FBF0B452719AB308
- app/server.py: 80D37E42882F9BC55952FA1B4E50FA2EA479B9B88255B105F423818CF452DCC9
- tests/ticket01_regression.py: 1AC0923ED4D08D21CE2FD4E9D90C632D28C5583CAC4932D54D86E3D29416DDF0

## Disposition
Ticket01 accepted for its two material corrections, with the P3 tracked as nonblocking. Standards:0 material findings; Spec:1 minor validation finding. Onboarding V1 engineering review passes with that limitation; merchant walkthrough/architecture teaching remain useful before research expansion. No automatic next-ticket dispatch or live-access authorization.
