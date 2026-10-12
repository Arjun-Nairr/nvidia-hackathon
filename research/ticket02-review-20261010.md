# Ticket 02 review, 2026-10-10

Two fresh isolated code-review agents reviewed Standards and Spec separately. No Git baseline exists: this is a current-file review, not a pinned diff. No production code or credentials changed; no live API/model calls made.

## Standards

[P2] Nested evidence merging loses known details (scripts/marketplace_check.py:208-209). An item record with seller S-1 and currency USD, followed by an overlapping search record, loses both values because whole seller/price dictionaries are replaced with search defaults. Independently reproduced by the standards reviewer. This violates PROTOTYPE_SCOPE.md's accurate known-seller/price reporting requirement. Merge populated nested fields without treating missing search fields as deletions; cover item then search. No dedicated coding-standards file was found; the merge-granularity concern is architectural judgment, not an invented style rule.

## Spec

- [P1] Request budget fails open on damaged/unreadable storage (scripts/marketplace_check.py:87-94). load_json treats any read/parse failure as a fresh empty ledger. Root and spec reviewer independently injected truncated JSON: another mock request was sent and the ledger restarted at one. This violates ticket02's persisted maximum20 API calls across invocations. Only an absent ledger should initialize; invalid/unreadable state must stop before a request. Add a regression for damaged storage. Concurrent ledger access is also unsynchronized; the present review does not certify parallel invocation safety.
- [P2] Evidence is erased by overlapping searches (scripts/marketplace_check.py:208-209), independently reproduced by the spec reviewer as well. Ticket02 requires recording exposed seller IDs, prices and accurate counts. Preserve previously known nested fields when the incoming endpoint omits them.
- [P2] Malformed success responses become empty inventory (scripts/marketplace_check.py:139-140,339-348). A mocked HTTP200 JSON body containing an error but no success/listings is accepted; search exits0 and reports EMPTY. Missing listings is also treated as an empty array. This violates ticket02's distinction between provider errors, empty inventory and missing fields. Validate endpoint response shapes, reject explicit errors, and reserve EMPTY for a valid empty listings array; add malformed200 cases.

## Evidence and disposition

Root independently reran tests/marketplace_check_test.py:33/33 passed, isolated temporary storage and mocked transport only. The first attempt hit sandbox temporary-directory permissions; rerunning with a project-contained temporary directory passed. The existing tests do not cover the failures above. These are small diagnostic corrections; no broad runtime/UI redesign is required.

Diagnostic review: changes required. Live feasibility: pending ScrapeCreators credentials; no real listings/photos or fixture established. Ticket04/05 remain blocked. Ticket03 is independent, not dispatched.

## Reviewed SHA256

- scripts/marketplace_check.py: D2401507B9CA5ADDE91CEC10BFC02B29254B77937F5DF5789B584B3B0C8C4441
- tests/marketplace_check_test.py: CBE4BDB8D1E103AC5D9123339C2332B94F8FC7AEF9F0489F15D07BFE7F876E9F
