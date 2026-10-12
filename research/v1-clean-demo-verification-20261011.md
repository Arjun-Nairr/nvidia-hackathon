# V1 clean demonstration: Codex direct verification

Date: 2026-10-11. Direct inspection only; no reviewer agents, new live inference, scraping, downloads or Nebius spending.

## Evidence inspected
- `research/live-archive/20261011T105324Z-live/`: all four manifest file hashes independently match; result is readable, mode live, via-main, complete, no failure, 12/12 recorded live checks.
- Laya routed the creation request to create_market_agent. Main made a successful create_agent call; the retained registry has exactly one specialist with the needed research/image/catalogue/draft tools and no recorded-evidence tool. Baseline plus two company-specific skills were provisioned.
- Recorded usage: 7 API attempts, per-call credits sum 7; three photo downloads; main 3 and specialist 9 model requests (12 total). Backend allowance records 7/10 and 3/3. No new live execution by Codex.
- Retained SQLite draft title, description, visual brief, status and research_run_id match the archive. All three retained competitor photos match their archived SHA256 values. Codex viewed all three; visible packaging, labels and colours are consistent with the saved observations.
- Restart harness compares draft and full run unchanged with the scraper unreachable and no additional recorded model calls. Codex inspected this test and the recorded pass; did not repeat the paid demonstration.
- Retained demo auth.json is absent; local.env contains only provider/model keys. The original runtime is not reset. Retained demo is inspection-only until separately authenticated/configured.

## Source changes
Compared app/core.py against the previous independent identity-review snapshot: only operator-controlled iteration caps and their use in run_turn changed. Defaults remain 12/14. Inspected launcher/harness changes for real-main creation, combined accounting, early archive, retained state and credential removal.

## Product judgment
Technically demonstrates the core path: user request -> Laya -> main -> persistent customized analyst -> live tools and actual images -> saved draft and restart retrieval.

The draft accurately restates the supplied product facts and price, with a practical photo brief. Its analysis remains basic: three comparables, two from one seller; no price-positioning explanation despite $40/$50/$65 comparisons to the supplied $89. A full-bed photo is a recommendation, not a feature observed in the three inspected competitor photos, which show folded/packaged goods. Do not describe this sample as proven commercially useful or infer sales performance.

Non-blocking existing issue: main SOUL/setup still says research is not connected; clarify main's own capabilities versus available specialist capabilities in the next scoped change. No unrequested fix made here.

## Verification status
Independent isolated scripted archive regression: 15/15 PASSED in `.scratch/review-v1-clean-20261011`. The first sandbox attempt could not start the fake server; the permitted local-service rerun passed. No real credentials or paid services were used. Earlier research79/79 remains the last independently verified research suite; research logic was not changed in this demonstration.

Decision: TECHNICAL DEMONSTRATION ACCEPTED on the development provider. No blocking defect found in this scoped direct review. The preserved live result resolves the missing-archive acceptance gap; it does not recover the original lost run.

Arjun's draft-usefulness judgment and Nebius/NVIDIA compatibility remain pending. No V2 or further paid rerun authorized.
