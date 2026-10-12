# Ticket04 corrections verification — 2026-10-10

Decision: ACCEPTED for ticket04 on the development path. Ticket05 may now be scoped; no automatic implementation or paid access authorization.

## Method
Direct Codex inspection and one focused independent regression run, following Arjun's once-per-ticket review rule. No additional reviewers. Checked app/listing.py, core.py, worker.py, turn_state.py, hermes_plugin.py against the four findings and compared the worker vision probe with installed Hermes agent/vision_message_prep.py's actual gates.

## Results
- Known source-photo hash mismatch returns image_provenance_mismatch. Missing recorded hashes are distinguished from matches and keep results partial.
- Recognizable stated price amounts and currencies are checked. Original79USD /89EUR repros fail; correct USD forms pass. A second configured merchant/product catalogue priced49.90EUR works without editing application code; wrong amounts/currencies fail.
- Worker probes the same model/provider/list-content rejection gates as Hermes. Text fallback/unknown/legacy inspection rows cannot satisfy complete visual evidence. Scripted worker checks independently confirmed zero image parts for fallback/partial and actual image parts for supported/complete.
- Saved supporting description/photo references use the same bounded whitelist as the read tool. Restart retrieval survives removal of the evidence input and causes zero model calls.
- Backend/UI separation, tool grants and specialist memory isolation remain intact in the exercised paths.

## Independent checks
Unmodified tests/listing_draft_test.py:57/57 PASS in a fresh isolated copy, real Hermes workers with local scripted model. No real credentials or live inference/scraping/Nebius. First attempt stopped while printing the rupee symbol under Windows cp1252; rerun with PYTHONUTF8=1 completed. This was console encoding, not failed application behavior.
Claude-reported broader regressions were inspected in research/ticket04-corrections-result-20261010.md, not repeated by Codex. Historical live evidence remains the pre-correction demonstration; no new live model result is claimed.

## Limits and next step
Price checks remain bounded heuristics. Vision status represents Hermes' image-content decision at inspection time, not provider acceptance or model understanding; first provider rejection can only be learned afterwards. Source hash proves byte provenance, not product authenticity. Persisted source descriptions capped at800characters with truncation flagged; photo references capped at12.
Catalogue portability now demonstrated at the backend seam, not via real merchant onboarding; catalogue file is still globally configured, not merchant-bound. No multi-company or new-role support is claimed. Ticket05 live agent research still needs a scoped prompt and explicit finite usage allowance; never reset ticket02's19/20 diagnostic ledger.

## Snapshot SHA256
- app/listing.py:A5F77998B549848F5862E5FFBBF1CE5BF905B0A56AC62E7A1487A6D6CE008C6D
- app/worker.py:587EB7B1B56E74966B51EF3B1268F2C956F7F966333B0C1BA60DB70B67217E3E
- app/turn_state.py:5C0CDED1ABA3A003BC2E606147E6F90D5983FDFD9DAD25A0138E05E9C00830D1
- app/hermes_plugin.py:3BB9C0EDB1C17F44A809310B83F4AE5F1FB5EC2495D2D17B66FDF095949D6461
- app/core.py:BE981FDDB951E202DD0B4A16D970B16FDE938DB8B4BDE0FE364F8DD68B618434
- tests/listing_draft_test.py:EA77DBA8219C90ABFFE633722F01E21C02089BE91186BEC43F9FDEB779DD37C2
