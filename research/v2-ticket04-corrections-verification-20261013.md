# V2-04 correction verification — 2026-10-13

Outcome: ACCEPTED for the scripted ticket4 slice and all three review corrections. Direct Codex inspection and focused checks; no code-review skill or subagents.

## Verified

- Shared persisted-artifact validation enforces managed path, file availability/readability, bounded and recorded size, saved hash, complete image decode, MIME and dimensions. List/detail/cached generation/image endpoint agree about failures. Original generation outcome and consumed attempt remain intact; no regeneration. Restoring original bytes restores valid retrieval.
- Provider container validation and interpretation guard finalize malformed observed responses as consumed terminal bad_response failures, recording available HTTP status/timing/usage. No stuck dispatched attempt or transport-uncertainty substitution for an observed malformed reply.
- Provider-derived messages and applicable exceptions are sanitized before persistence/exposure. Exact fake-key echo tests cover diagnostic text, status, interaction ID, MIME, provider errors and transport errors; no unsanitized duplicate found in inspected paths.

## Independent evidence

- `tests/flyer_test.py`: **44/44** on `.scratch/verify-v2-04-corrections-20261013`, real Hermes/server with local scripted Gemini/reasoning stand-ins and placeholder inputs. No real runtime/secrets copied; no paid calls.
- End-to-end negative cases: corrupted artifact yields storage_failure/no image reference and image HTTP409; restart does not regenerate; malformed response remains consumed/terminal; echoed fake key absent from tool/Activity/chat/read surfaces.
- `.\lint.bat`: exit0.
- Additional root pure probes: integer steps/content both return bad_response; text-only fake-key echo yields no_image with the key absent.
- Claude reports relevant broader regression suites passed; Codex did not repeat them because the scoped flyer suite and direct connected-path inspection passed.

## Limits and next step

Evidence proves wiring/enforcement, not real Gemini quality/product fidelity or live provider compatibility. Real merchant photos/facts, Gemini credentials and separately authorized live budget remain missing. Exact key values are redacted; encoded variants are outside this correction. Each image list read decodes artifacts; acceptable for the current small prototype, no speculative cache added. UI error data/rendering code inspected; browser rendering was Claude-reported, not independently repeated.

Next: checkpoint accepted ticket4 after reviewing staged exclusions, then ticket5 actual-image content review and at most one correction. No commit/push or paid dispatch performed in this verification.
