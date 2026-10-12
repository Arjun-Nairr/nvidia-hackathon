# Ticket05 review — 2026-10-10

Decision: CORRECTIONS REQUIRED. Live acceptance evidence is incomplete. No fixes or extra live run dispatched.

## Basis
Matt code-review skill: two fresh isolated reviewers, standards and spec kept separate. Current-file snapshot because no Git repository exists. Sources: PROTOTYPE_SCOPE.md, ticket05, relevant marketplace-listing-spec.md clauses and HANDOUT standards. Root independently inspected the affected paths, ran the unmodified isolated research suite and reproduced findings without live calls.

## Standards
1. P2 — app/research.py:140-146: done/ok_unsaved is not terminal. Search/item/photo successful fetches whose local persistence failed are marked ok_unsaved (429/467/549); an identical retry reserves and sends again. Violates documented no replay after successful-but-unsaved request. Return a storage blocker without another external fetch; test local storage failures and repeated identical tool calls.
2. P2 — app/research.py:220-221,519-530 with scripts/marketplace_check.py:77: default urllib redirects forward custom X-api-key to a different host, and photo host/scheme checks validate only the initial URL. Violates backend-owned credentials, CDN allowlist and TLS requirements. Reject API redirects or enforce safe destination/credential handling; validate all photo redirect hops. Test with local scripted redirect endpoints; no external calls needed.
Atomic reservations, backend grants, worker serialization and backend/UI independence otherwise appear sound in exercised paths.

## Spec
1. P2 — app/research.py:342-344,355-358,376-386: locate Dallas, then Austin, then cached Dallas returns Dallas but search resolves numbered places using latest inserted lookup Austin. Agent-led location changes silently choose wrong market. Persist current selected lookup or use stable run-scoped references; test A/B/cached-A and keep cache reads free.
2. P2 — app/research.py:140-146: successful-but-unsaved retry issue above violates Included finite/no-replay behavior.
3. P2 — app/research.py:460: requested ID replaces supplied provider ID without validating identity. B's response for A is stored under A with A's canonical source URL; B photos can later pass byte-hash provenance. Reject an explicitly different returned ID before merging; handle absent ID separately without inventing verification. Test that the mismatched response spends one attempt but leaves A's evidence intact.
4. Acceptance proof gap — research/live-research-result-20261010.md explicitly reports that the sole live run's database was deleted after archive failure. Full source URLs, retrieval times, hashes, per-call credits and first save-error record were lost. Treat narrative as Claude-reported live demonstration, not independently inspectable complete acceptance evidence. The fixed harness has not been rerun. Do not silently repeat the already-used one-run authorization; preserve failures/output before deleting future copies.
Configured catalogue/company guards and recorded/live separation are represented in code and checks. Multi-business/new-role requirements were not applied.

## Independent verification
- Unmodified tests/research_test.py:51/51 PASS in fresh isolated copy with real Hermes workers, local scripted model/provider/CDN. No real credentials, live inference, scraping or Nebius credits used.
- Additional pure-backend probe: _begin_call(item A), _finish_call(ok_unsaved), identical _begin_call returned go twice; usage2. No HTTP sent.
- Additional pure-backend location probe using scripted transport: Dallas/Austin/cached-Dallas returned Dallas to agent but _last_locations resolved Austin for search.
- Additional pure-backend item probe: return idB and B description to requested idA; item returned ok, stored idA, B description and A source URL.
- Offline default HTTPRedirectHandler probe: cross-host302 retained sentinel X-api-key header. No real key or network used. Initial-only photo allowlist follows same unguarded redirect transport; source-traced risk.
- No surviving full live archive found in project research/.scratch file inventory. Do not infer provider-reported credits from documented nominal cost as exact measured credits.

## Next step
One focused correction prompt for these four code defects, direct Codex correction verification (no second reviewer pass). Improve scripted archive/failure preservation checks without new live calls. Final live evidence completion needs separately agreed bounded demonstration or surviving artifact recovery; no automatic rerun.

## Snapshot SHA256
- app/research.py:C4ED4D58193BA4606C5B7BA33460159468C6275C254B3BFE2C25CF9DBCB9413A
- app/listing.py:4BBF790FC1C2FAEA54D4B6FC4350B794D92A0AA5387E49DE9A01FE99403EC850
- app/core.py:359AA87E5A5170D0E65E90358F956DB9C0E2F5200B78851297AAF11536357616
- app/hermes_plugin.py:1CF4AA8EFF9D2F9EEBB6899E48F856A5E88B633EA029F53BC02686B9ED305A79
- app/worker.py:67385BABAF8B61392F9C0C503F1329238F58E046C98762B6865F32DBA10376A7
- app/workers.py:A0E6CEBF6B072BA2A5797A0CA4DD25E9E5E206BC93638BF4E98A71002EF2F991
- app/server.py:DAAB7D36292695642ABC6A6B23A0A70C8B43B83831995A13A393C4E523E42281
- tests/research_test.py:82DAC378E78542660B7FEF2F0F2340514508476DEBD037A3218B6DE3726A1629
