# Ticket05 correction verification — 2026-10-11

Decision: MOST CORRECTIONS VERIFIED; one small item-identity correction remains. Ticket05/V1 live acceptance also remains incomplete because the original archive was deleted. No extra live run or new reviewer agents.

## Method
Direct Codex inspection against research/ticket05-review-20261010.md and the inline correction prompt. No code-review skill or spawned agents. Tests ran from a fresh isolated copy with fake API/model/CDN services and the existing Hermes installation. No real credentials, subscription inference, live scraper/CDN requests or Nebius spending.

## Independent results
- tests/research_test.py:70/70 PASS. Cached A/B/cached-A selection, terminal ok_unsaved behavior across search/item/photo, mismatched and absent item IDs, API redirect refusal, every-hop photo allowlist, actual serving host, budget/grants, adaptation and restart retrieval verified by scripted checks.
- tests/research_archive_test.py:10/10 PASS. Normal archive, failures before/after initial archive, hard-exit copy retention, secret scrubbing and explicit live-mode requirement verified. This is scripted evidence, not a recovered live run.
- tests/marketplace_check_test.py:85/85 PASS on approved access to local test transport. Initial sandbox attempts hit the inherited Avast SSLKEYLOGFILE issue, then local transport returned network_error rather than302; unchanged suite passed with SSLKEYLOGFILE removed and approved existing-runtime access. TLS verification remained enabled.
- Scoped source inspection confirms the corrected backend/UI split and additive persistence. Broader regressions in Claude's note were not repeated by Codex.

## Remaining reproduced P2
app/research.py:531-539 validates a source URL only when the response id is absent. If id matches the requested listing but url explicitly names another listing, id_match wins and the response is merged.
Pure-backend reproduction, no HTTP: seed listing9001, request9001, supply {id:'9001',url:'https://www.facebook.com/marketplace/item/9002/',description:'Conflicting identity response'}. item returns ok:true; stored listing_id9001, identity:id_match and source_url for9002. The normalization retains that conflicting URL, so saved source provenance is inconsistent.
This is the same identity/provenance correction, not a new feature: validate both supplied identifiers independently. Any explicit contradiction must reject before merge, count the existing attempt once, preserve prior evidence and be terminal on identical retry. Add matching-id/wrong-URL and wrong-id/matching-URL checks. Missing id/URL still follows the documented unconfirmed policy. Do not broaden into a generic URL validation framework.

## Acceptance gap
The original draft88e26641f5/full live run archive remains missing. The new scripted archive checks establish improved preservation behavior, not recovery of those hashes/credits/timestamps. No further live execution is authorized here. After the small fix, code can be accepted separately from the pending live evidence completion.

## Snapshot SHA256
- app/research.py:B36D6848C476548CF2DB0D1087C2AC959128C10B69FE7AEC3BFE5337F8F7A84A
- scripts/marketplace_check.py:5A72501A3260894B21E702CDCB3E539425DA27C81251BA145962236EF713BA6A
- scripts/research_live_launch.py:F852C1BFFD377A42B767DB08C10459C4D67D95EF1E0934A73AB012EA2E50705F
- tests/research_live_check.py:F1D7E2130A5C4FF55EFE7D0608B2135884E86420E21F0777149625EF6BC0F07A
- tests/research_test.py:D2B24251A86E488F4147F32455C5E05904D42ABC68CD91F3F76225F5AA82B87A
- tests/research_archive_test.py:EF80517D18C7A617167B8106A76E8EC42343F5C5784522343CDB6FD79D3A148E
