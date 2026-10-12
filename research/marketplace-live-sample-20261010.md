# Marketplace live sample, 2026-10-10

Author: Codex. Ticket02. Verdict: usable initial data established; ticket02 complete for the agreed small feasibility check. This is direct API evidence, not mock results or an agent-quality evaluation.

## Observed sample

Dallas, Texas selected explicitly as location2: latitude32.7774, longitude-96.7977. Four searches, condition=new, radius_km=50, no pagination:

| Query | Results | New unique listings |
|---|---:|---:|
| comforter set |16|16|
| curtains |15|15|
| throw blanket |15|15|
| bedding set |15|13|

59 unique listings, all with primary-photo references and advertised prices.13 item detail attempts:12 successful, one404. All12 successful details included description, USD price, new-condition attribute, photos and a seller ID; these represented12 distinct exposed seller IDs, not12 verified companies.

Manual relevance sample:15 candidates,12 reviewed using title/description/location/condition details and3 using search title/location/photo reference only. All15 had image references. Only3 photos were downloaded and visually inspected; this does NOT claim15 images individually inspected or accessible. One Dallas, Georgia result was marked irrelevant; the404 listing and two service/wholesale-estimate listings were marked unsure. Other results remain unreviewed.

## Photo evidence

All3 HTTP200 JPEGs decoded fully and were viewed by Codex:

-1638806271151287:720x960,97,866bytes. Bedding in clear packaging, orange/red and beige fabric; a staged product diagram on the label. Source: https://www.facebook.com/marketplace/item/1638806271151287/
-918521891138262:960x934,80,099bytes. Promotional graphic of dark gray curtain panels;52x84/Charcoal Gray Blackout overlay. Performance claims not verified visually. Source: https://www.facebook.com/marketplace/item/918521891138262/
-1135008265871828:444x960,72,460bytes. Phone screenshot of a folded pink/magenta throw tied with ribbon. Burgundy title differs from visible color; lighting/rendering could contribute. Source: https://www.facebook.com/marketplace/item/1135008265871828/

Pixels retained privately in runtime/marketplace_check/images/. These observations verify data availability through Codex, not Hermes specialist vision. Ticket03 must establish the latter independently.

## Usage and failures

19/20 diagnostic attempts counted:2 location attempts,4 searches,13 item attempts. One sandbox DNS failure never reached the provider but remains counted conservatively.18 requests reached ScrapeCreators:17 successful and one404. The API reported17 total credits charged (18 responses carrying credit fields); the404 charged0. The first successful response had7,031 credits remaining; the last7,015. No purchases or Nebius/model calls. Stopped with one diagnostic attempt unused.

Provider-reaching calls: median3.759s, minimum1.823s, maximum8.578s,74.249s total recorded across all attempts.3 separate CDN photo fetches, no API key attached, no additional ScrapeCreators credits reported. These are a small sample, not a latency guarantee.

Initial TLS construction failed because an inherited SSLKEYLOGFILE pointed at an inaccessible Avast device. Removed that environment variable only for these command processes; certificate verification and the project's CA bundle remained enabled. The next sandbox request failed DNS; network-approved execution worked. No global settings or application code changed. Item2626789881057695 returned404 and was not retried.

## Artifacts and reproduction

Private ledger/evidence: runtime/marketplace_check/{ledger,evidence}.json. Redacted live fixture: tests/fixtures/marketplace_sample.json (59 records, includes reviewed/uncertain/unreviewed candidates). Verified: key absent, seller IDs pseudonymous, photo query strings removed, no image bytes included. Fixture metadata is useful for replay tests; stripped/expiring photo URLs do not guarantee future downloads.

Commands: marketplace_check.py status; locate Dallas; search QUERY --location2 --condition new --radius-km50; item SELECTED_IDS; images --n3 IDS; report; fixture. Use actual separate arguments (`--location 2`, `--radius-km 50`, `--n 3`). Do not rerun the whole sequence: persistent budget is already19/20 and must not be reset silently. Script read the key locally; no secret was printed.

## Primary documentation

- [Location lookup](https://docs.scrapecreators.com/v1/facebook/marketplace/location/search/)
- [Listing search](https://docs.scrapecreators.com/v1/facebook/marketplace/search/)
- [Item details](https://docs.scrapecreators.com/v1/facebook/marketplace/item/)

Official pages rechecked during this run. Actual response evidence above takes precedence over earlier documentation-only hypotheses.

## Judgment and next step

The agreed feasibility target is met at a candidate-data level:15 relevant image-referenced listings and more than3 distinct known sellers, with real descriptions and3 accessible photo samples. This supports ticket03 then04; it does not prove commercial success, seller-company identity, strict radius enforcement, physical quality or autonomous research. Ticket03 is next: actual image inspection through the specialist/runtime using the development provider. Ticket04 still depends on ticket03; ticket05 depends on04. No implementation dispatched.
