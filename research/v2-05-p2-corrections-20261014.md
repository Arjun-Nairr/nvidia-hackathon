# V2-05 P2 corrections — coherent cached results and artifact-validity-based selection state, 2026-10-14

Status: **implemented, awaiting direct Codex verification; ticket5 NOT declared accepted by Claude.** P1 (delivery-bound review) untouched. Scripted stand-ins, isolated copies, no credential/paid call/runtime reset.

## Defects (research/v2-ticket05-review-20261014.md)
1. `_existing_reply` returned the latest attempt's candidate/image with the *selected* candidate's status and note (older defective candidate selected, newer passed -> second image labelled "unresolved").
2. `_effective` / `_flyer_summary` counted historical `outcome=ok` records as valid candidates: two damaged/missing files still gave "Two valid candidates exist / awaiting selection".

## Contract chosen (`app/flyer.py`)
- **Cached generate/correct reply = one attempt result** (`scope: "attempt"`): `candidate_id`, `image`, `status`, `note`, `review`, `unresolved_issues` all belong to the returned (latest) attempt and come from `_cand_status` (its own file via the shared `_artifact` check + its own verified review). Flyer-level facts are separate fields: `flyer_status` and `final` (selected candidate, rationale, effective candidate). An integrity failure of that attempt keeps `artifact_integrity_failed` and carries the same separate flyer fields.
- **Flyer summary/detail/list/specialist read/managed image** share `_effective(run_id, atts, final_id)`:
  - selected candidate: that candidate only - a damaged selection is `storage_failure`, never the other candidate; a damaged *superseded* candidate is not even consulted;
  - no selection: candidates are filtered by the shared artifact check. Two valid -> `awaiting_selection` (no default image); one valid + one damaged -> the survivor stands with its own review status, not recorded as a selection (`final.selected: false`), the damaged candidate listed in `damaged_candidates` and named in `note`, and it cannot be finalized (`artifact_integrity_failed`); none valid -> `storage_failure` with no image reference (error names each candidate's problem), image endpoint 409.
- Computed on every read; restoring the original bytes restores the previous state. Attempts, reviews and allowance are never touched; nothing is regenerated.

## Failing before / passing after
New checks in `tests/flyer_review_test.py` (Part A seams R14a, R14b, R14b2, R14b3, R14c/d; Part B B16 through the real app with restart):

| | Before the fix | After |
|---|---|---|
| R14a cached replies, older defective candidate selected (plain + correction repeat; before and after selection) | FAIL (second image under the first's status) | PASS |
| R14b both files truncated/missing, no selection | FAIL: `awaiting_selection` | PASS: `storage_failure`, no image |
| R14b2 one valid + one damaged | FAIL: `awaiting_selection` | PASS: survivor + damaged candidate named |
| R14b3 restored bytes -> awaiting selection; R14c selected damaged; R14d superseded damaged | already correct (kept) | PASS |
| B16 real app: list/detail/image 409/read_flyer, damaged -> restart -> partly restored -> restored | not run before (needs the fix) | PASS |
| whole `flyer_review_test.py` | R14a, R14b, R14b2 FAIL (red run stopped at R14d on the then-missing `flyer_status` field) | **49/49** (32 seam + 17 real server/worker) |

Other results: ticket-4 `flyer_test.py` 44/44 on the final code (its read helper now re-reads an idempotent GET after the local reset below; three earlier attempts died on that reset at `GET /api/chat/<agent>`, a ~72 KB history this change does not touch), chat API 18/18, social 38/38, `.\lint.bat` exit 0. Logs in ignored `.scratch/` (`p1_p2red.txt` before, `p1_p2final2.txt` after).

## Limits / adjacent notes
- `review_flyer`'s own result carries the *flyer-level* `status` next to the *reviewed candidate's* verdict; after a selection, reviewing the other candidate mixes the two labels. Not in the two P2 findings, left unchanged (adjacent; candidate-level fields are correct).
- Each list/detail read now validates up to two files (full decode) when nothing is selected; negligible at prototype scale.
- The new summary field `damaged_candidates` appears only for damaged candidates the flyer does not stand for: an always-present or duplicated field pushed the specialist's `read_flyer` listing over the stored Activity output cut (3000 chars) and broke the ticket-4 test's JSON parse.
- Same local transport flake note as P1 (chat responses occasionally reset on this PC; the suite replays the request id).
