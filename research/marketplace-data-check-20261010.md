# Ticket02 diagnostic preparation (historical)

Superseded: authorized live sample completed by Codex2026-10-10. See marketplace-live-sample-20261010.md; do not follow the pending-key status below as current.

Date: 2026-10-10. Author: Claude Code. Ticket: .scratch/marketplace-listing/issues/02-marketplace-data-check.md.

## Verdict: PENDING CREDENTIALS. Feasibility is NOT established, and NOT shown insufficient.

No ScrapeCreators key exists in this project's configuration or process environment, so no live request was made, no credits were spent and no listing or photo was retrieved. The diagnostic is built and tested with mocked responses only. Nothing here is live scraper evidence, and downstream tickets (03 is independent; 04 and 05 need this) must not be treated as unblocked by it.

**What Arjun must do:** add one line to `secrets/local.env` (the project's git-ignored secrets file, same file as the Nebius settings):

```
SCRAPECREATORS_API_KEY=<your ScrapeCreators API key>
```

(`secrets/local.env.template` now carries the blank field.) The process environment variable of the same name also works. Then run, from the project folder, with the Hermes venv Python (`%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe`):

```
python scripts\marketplace_check.py status      # shows key configured / MISSING and requests used, never the key
```

and ask Claude to run the bounded sample (plan below), or run it by hand.

## Documented access (read 2026-10-10 from docs.scrapecreators.com)

All three endpoints: `GET https://api.scrapecreators.com/v1/facebook/marketplace/...`, header `x-api-key`, **1 credit per request** (as documented; not yet measured). Documented status codes 200/400/403/404/500; error bodies are not documented.

| Endpoint | Parameters (documented) | Response fields used |
|---|---|---|
| `location/search` | `query` (required) | `locations[]`: `name`, `subtitle`, `latitude`, `longitude`, `city`, `page_id`, `postal_code`; top level `success`, `credits_remaining`, `credits_charged` |
| `search` | `query`, `lat`, `lng` (required); `category_id`, `radius_km`, `min_price`, `max_price`, `sort_by` (suggested, distance_ascend, creation_time_descend, price_ascend, price_descend), `delivery_method` (all, local_pickup, shipping), `condition` (new, used_like_new, used_good, used_fair), `date_listed`, `availability` (available, sold, all), `cursor` | `listings[]`: `id`, `url`, `title`, `price{amount, formatted_amount}`, `location{city, state, display_name}`, `primary_photo{id, url}`, `category_id`, `is_live/is_sold/is_pending`, `delivery_types`; top level `cursor`, `has_next_page` |
| `item` | `id` or `url` | `title`, `description`, `price{amount, currency, formatted_amount_zeros_stripped}`, `location_text`, `location{latitude, longitude}`, `attributes[{attribute_name, value, label}]`, `photos[{id, url, width, height, accessibility_caption}]`, `seller`, `creation_time` |

Documentation gaps that matter to the product and can only be settled by a live call:
- `item.seller` is `null` in the documented example and its fields are not documented, so whether a seller identifier is exposed at all is unknown. The 3-distinct-sellers target depends on it. The diagnostic records `seller.exposed` and the field names that appear, keeps only an id, and treats a missing id as unknown.
- `search` results have a single `primary_photo`; full photo lists, description and condition attribute come only from `item` (one more request per listing).
- Search prices carry no `currency`; the item response does.
- Whether `condition=new` is honoured for textiles, and how many listings a page returns, are not documented.
- The location example shows ambiguous names (Austin, IL / GA / Texas). The diagnostic prints all candidates and requires an explicit pick (for Dallas: the entry named Dallas, Texas).
- Cursor pagination is documented; `creation_time_descend` may insert newer listings between pages.

## Diagnostic (built)

`scripts/marketplace_check.py` (stdlib + the Pillow already in the Hermes venv; standalone; not registered with any agent; no model, no Nebius).

- Reads `SCRAPECREATORS_API_KEY` from `secrets/local.env` or the environment; never prints, logs or stores it (provider error bodies and exception text are scrubbed). TLS verification stays on (uses `runtime/ca_bundle.pem` when present).
- Hard budget: 20 API requests total across ALL invocations, counted in `runtime/marketplace_check/ledger.json` BEFORE sending, failures included, no automatic retries; the ceiling can be lowered, not raised. Photo downloads are separate (CDN, no key, no credits), capped at 6.
- Only documented parameters and enum values are accepted; arbitrary URLs/params are rejected locally (nothing sent).
- Normalizes to: listing id, source URL, title, description, price/currency, location, seller id (only if exposed; name and picture dropped), photos, retrieval timestamp, and provenance (endpoint, query, filters, request number). Absent fields stay `null`.
- Keeps a keyword heuristic as a hint only; relevance is recorded by manual `review` (relevant / irrelevant / unsure + note) after looking at the data and photos.
- Photo check: HTTP status, content-type, size, sha256 and a full Pillow decode with dimensions; saved only under git-ignored `runtime/marketplace_check/images/`.
- `fixture` writes `tests/fixtures/marketplace_sample.json` only from live requests (refuses empty or injected ledgers): seller ids pseudonymised, phone/email patterns and signed photo query strings removed, photo bytes not stored (third-party images, public repo).
- `report` prints requests/credits (reported by the API vs the documented 1/request), listing counts, distinct known sellers among relevant listings, relevant listings with an unknown seller, photo-check outcomes.

## Planned sample (not run)

Candidate city Dallas, TX, a candidate and not a validated choice. At most 20 requests: 1 location search; about 4 searches with `condition=new` (for example "comforter set", "curtains", "throw blanket", "bedding set") plus at most 1 follow-up page or adjusted query/radius; up to about 13 item details for the most comparable listings; 1 spare. Then 3 photo downloads, viewed and decoded. Adjust queries or city if early results are unsuitable. Success target (suggested, not a quota): 15 relevant image listings across 3 distinct known sellers. Because seller identity needs an item call per listing, 20 requests may be unable to establish sellers for 15 listings; the report will state that rather than extrapolate.

Measured vs estimated: credits will be reported as the API's own `credits_charged` / `credits_remaining`; the documented 1 credit per request is an estimate until then.

## Diagnostic tests (mocked; NOT live evidence)

`tests/marketplace_check_test.py`: 84/84 pass (33 original + 32 correction regressions + 19 storage-write checks, see ticket 02) with a mocked transport and synthetic payloads shaped like the documentation. Covers: missing key (exit 4, names file and field, nothing sent, nothing counted); key from file reported but never printed; invalid enum/undocumented parameter/arbitrary URL rejected before any request; documented flow and parameter mapping; normalization and merge of search plus item; absent fields stay unknown; seller name/picture not retained; key scrubbed from provider errors and exceptions in output, ledger and evidence; 401/403 explicit, single request, batch stops, no retry; empty results distinct from provider error, HTTP 500, 429, non-JSON and timeout; image outcomes (usable, 404, HTML instead of image, truncated image, network fault, oversized, no URL); budget exhaustion across fresh clients/processes with failures counted and no network call after the 20th; fixture refused without live evidence and redaction on synthetic data. A mutation check (scrubbing and budget guard disabled) made the corresponding tests fail (29/33), so they are not vacuous.

## Limits

- No live API behaviour observed: auth-failure shape (401 vs 403), real response sizes, latency, seller exposure, image URL lifetime and CDN access are all unverified.
- Mock payloads reuse documented field names; real responses may differ.
- Relevance is a manual judgment on a small sample; the keyword heuristic is only a hint.
- Facebook photo URLs are signed and may expire; the fixture deliberately holds no image bytes.
- Ticket 03 (does our Hermes model path accept image pixels?) is not covered here.

## Correction after review (2026-10-10, Claude): awaiting Codex re-review
The review in research/ticket02-review-20261010.md found three defects, now fixed (test-first; 39/65 before, 65/65 after, mocked, no live calls): the budget ledger and evidence files fail closed (only an absent file starts fresh; damaged, unreadable or invalid state stops before any request and is left untouched), evidence merges field by field so later searches never erase a known seller id or currency, and 200 responses are validated per endpoint so error-only or collection-less bodies are failures and only a valid empty `listings` array is empty inventory. A reproduced mini-audit finding was also fixed: simultaneous invocations over-spent the cap and crashed, so state-changing commands now take an OS file lock. Live feasibility is still pending a key.

## Storage-write correction (2026-10-10, Claude): awaiting focused Codex verification
Local state writes now fail explicitly and accurately by stage: a failed ledger write before sending sends nothing; a failed outcome or evidence write after sending is reported as sent, counted and not fully saved (exit 6), never replayed; refused file replacements are retried locally (20 x 50 ms) and API calls never; temp files are cleaned and saved evidence entries type-checked. 84/84 mocked checks (previous script 65/84). Live feasibility still pending a key.
