# Ticket05 final identity verification — 2026-10-11

Decision: CODE CORRECTIONS ACCEPTED. Ticket05/V1 live acceptance remains pending preserved live evidence; original live archive remains missing. No further live execution authorized by this verification.

Direct Codex inspection only: no code-review skill, reviewer agents, code edits, live inference or paid calls.

## Verified
- app/research.py item validates BOTH supplied id and recognized Marketplace URL id independently against the requested listing. Explicit contradictions reject before merge, preserve prior facts/photos/source URLs and remain terminal on identical retry.
- Matching identifiers, missing id with matching URL, and disclosed unconfirmed status when both identifiers absent remain supported.
- Small adjacent fix: contradictory search-row id/URL pairs are dropped before storage and reported in result/run metadata; other rows remain available. This fits the same identity/provenance correction.
- Independent unmodified tests/research_test.py79/79 PASS in a fresh isolated copy. Real Hermes workers with local scripted API/model/CDN stand-ins, no real credentials. New R3f-R3k checks include conflicting pairs, one counted attempt, zero retry requests, unchanged evidence, valid and absent identifiers. Worker grants/adaptation/partial outcomes/budgets/restart retrieval also passed.
- Archive10/10 and diagnostic85/85 independently passed in the previous direct correction verification; unrelated suites not repeated here. Claude reports archive10/10 rerun, not independently repeated by Codex for this small change.

## Remaining limits
Recognized identity URL form remains bounded to /marketplace/item/<digits>; this is not a general URL validator. Unknown response identity is disclosed, not independently verified. Historical live demo is Claude-reported; full original draft/run archive and exact measured credits are missing. Scripted success does not replace live/provider/NVIDIA acceptance. Catalogue real merchant setup and final useful-output judgment still need user testing.

Next: agree one bounded live acceptance demonstration that retains its full sanitized archive and inspectable result; no automatic repeat of the previous authorization or V2 implementation.

## Snapshot SHA256
- app/research.py:1024A5BA89B70EFD75D72A674F47FB643FE78A1B5AA90DB17D4A0E2BAD109929
- tests/research_test.py:5022C6BB285F6B4D9A67B22E270443294F39AFB9837318487634B34E1C851F1F
- tests/mock_scrapecreators.py:C11EE13ADE7F56D90BA9B13FD5439047EE3567E8FC3759AA5BE23327D93522E9
