# V2-04 review corrections — result, 2026-10-13

Author: Claude Code. Ticket: `docs/social-media-flyer-v2/issues/04-generate-save-display-flyer.md`. Review: `research/v2-ticket04-review-20261013.md`. Status: **corrections implemented, awaiting direct Codex verification; NOT accepted.**

Scope: only the three review findings and their regression coverage. **Everything here is scripted**: a Gemini stand-in (`tests/mock_gemini.py`), a rule-based specialist policy, generated placeholder images and a FAKE sentinel key (`TEST-GEMINI-KEY-SENTINEL`). No real credential was loaded, no paid or live call was made, no runtime or profile was reset, and nothing was committed or pushed. None of this proves real Gemini quality or behaviour.

## Failing before, passing after

The new checks were written first and run against the unmodified code (isolated copy, Part A only): **22/29 passed; C1–C6 failed**. After the fix the new Part A checks pass and the full file (Part A + real server/worker Part B) is **44/44** (it was 32/32 at review; +9 Part A, +3 Part B). Condensed output: `research/v2-04-corrections-test-output-20261013.txt`.

| # | Finding | Failing before (unmodified code) | After |
|---|---|---|---|
| 1 | Saved artifact not revalidated | `C2`: after deleting, truncating, replacing (another valid JPEG), zero-byting or turning the file into a directory, list/detail still reported `unchecked` with an image URL and the original output; the cached `generate_flyer` returned OK; `image_file` served the damaged/replaced bytes. `C3`: unreadable file and a database path pointing at `../../app.db` were still `unchecked` | `C1`–`C3b`: each case is `storage_failure` in list, detail, cached generation (`artifact_integrity_failed`) and the image lookup; no image reference; outcome stays `ok`, attempt count and scope usage unchanged; nothing sent; restoring the bytes makes it valid again (computed on read). Real app: `B12`/`B13` (409 on the image endpoint, read_flyer, restart, repair) |
| 2 | Malformed containers escape classification | `C4`: `steps: 1` and `content: 1` raised a TypeError (attempt left `dispatched`, status/timing/usage not recorded, a retry reported "outcome unknown"); `steps: [1]` and `content: ["x"]` were silently mislabelled `no_image` | `C4`/`C4b`: all five malformed shapes are a terminal `bad_response`: one send, attempt `done`, HTTP 200, timing, usage and a shape diagnostic recorded, consumed, retry returns `attempt_already_consumed`; fresh process (`C6`) and real app (`B14`) agree. `C4c`: a malformed `usage` alone does not fail a valid generation |
| 3 | Echoed key not redacted | `C5`: the sentinel appeared in the stored row, tool result, detail, list and read_flyer for a text-only completion, a status string, an image label and a provider error | `C5`: absent from every one of those surfaces and the exception path (`***` in its place). Real app `B14`: absent from tool results, Activity, chat history, list, detail and status |

## What changed

| File | Change |
|---|---|
| `app/flyer.py` | `_artifact` (the one shared validation) used by `_flyer_summary`, `get_flyer`, `image_state`/`image_file` and `_existing_reply`; new status `storage_failure`, fields `integrity`, `error_kind`; `_interpret` validates response containers and returns only terminal outcomes; `generate` wraps interpretation so nothing escapes after a send; `_clean` applied to every provider/exception-derived string and the interaction id |
| `app/server.py` | image endpoint answers 409 `artifact_integrity_failed` for a damaged artifact (404 only for an unknown id) |
| `app/static/index.html` | the saved-flyer card shows `STORAGE / INTEGRITY FAILURE`, `GENERATION FAILED` or `OUTCOME UNKNOWN` with the backend's error and no image |
| `tests/flyer_test.py`, `tests/mock_gemini.py` | new checks C1–C6 (+C3b, C4b, C4c), B12–B14; mock modes for malformed bodies and echoed keys; server readiness also waits for a database-backed endpoint |

## Design decisions

1. **Integrity is computed, not stored.** Nothing is written when an artifact fails, so the attempt record, scope allowance and outcome are exactly what generation produced; a repaired file is valid again and nothing ever regenerates.
2. **What is checked:** the stored reference is a managed `cand-<hex>.(jpg|png|webp)` of this candidate and resolves inside the run's folder (no symlink), the file exists and is readable, its size is within bounds and equals the saved size, its SHA-256 equals the saved hash, it fully decodes as a permitted type whose mime label and dimensions equal the saved metadata.
3. **Terminal malformed responses use the existing outcome `bad_response`** (HTTP status, timing, usage and a shape diagnostic like "steps is int, not an array" recorded). A final guard around interpretation maps any unforeseen exception to the same terminal outcome: an observed response is never reported as an unknown transport outcome.
4. **One sanitiser:** `_clean` redacts the configured key value, collapses whitespace and bounds length; it is applied inside `_interpret`, for exception strings, check messages and the interaction id, so no unsanitised duplicate is persisted or returned.

## Checks

- `tests/flyer_test.py`: **44/44** (Part A 30, Part B 14).
- Regressions on isolated copies: flyer 44, chat API 18, social 38, ad research 80, e2e 24, workers 22, listing 57 (isolated copies, scripted).
- `.\lint.bat`: exit 0.
- UI: the rendering was confirmed in the browser pane against a stub API (valid card with image; storage failure and generation failure cards with label and error, no image).
- One earlier full run reset a client connection immediately after a server restart (a test-harness race on the first read, not a product failure); two reruns passed and the harness now waits for a database-backed endpoint before reading.

## Preserved evidence (scripted)

`research/v2-04-scripted-flyer-example-20261013/` was regenerated by the corrected code: the valid scripted flyer (`flyer.jpg` is a generated placeholder, not Gemini output), its record (now with `integrity: valid`), the provider request as received, the inputs, and `corrections/` with the API views of a truncated artifact and the stored malformed-response and echoed-key records.

## Self-audit and remaining limitations

- `read_flyer`, `/api/flyers`, the detail view and the cached generation result all derive from the same summary, so they cannot disagree about integrity.
- Fixed adjacently: a provider error object without a `message` rendered as the string "None".
- Every list re-reads and decodes each saved image (fine for a handful; cache by size/mtime/hash if it ever matters). Only the exact key value is redacted, not encoded variants of it. A damaged artifact cannot be repaired by the app (by design: no regeneration; ticket 5 owns any correction path).
- Not covered: real Gemini output, fidelity and cost; real merchant photographs; review/correction/final selection (ticket 5); Nebius/NVIDIA compatibility.
