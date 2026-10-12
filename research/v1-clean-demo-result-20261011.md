# V1 clean demonstration: result (2026-10-11)

Author: Claude Code. Status: **one fresh bounded live demonstration completed and archived; awaiting Codex inspection of the archive and Arjun's judgment of draft usefulness. Not marked accepted.** Provider/model: openai-codex (ChatGPT subscription) / gpt-5.6-terra. No Nebius. NVIDIA remains unverified.

## What ran
1. **Isolated demo runtime** (no existing business, agent, conversation or allowance touched): a fresh copy at `demo/v1-clean-20261011/` with its own `runtime/`, project-local `HERMES_HOME`, a fresh `main` profile and a fresh allowance scope `v1-clean-demo-20261011` (10 ScrapeCreators attempts, 3 photo downloads). Only the provider/model lines, the ScrapeCreators key and the login were copied in for the run.
2. **Company and catalogue** (clearly labelled fictional): company "Acme Linens (fictional demo merchant)" saved through the backend form path (no model); catalogue `tests/fixtures/demo_catalogue.json` (merchant "Acme Linens (fictional demo merchant)", one product `acme-cloud-quilt-queen`, specifications, configured price 89.00 USD, market Dallas TX 50 km, image `demo-quilt-front` = synthetic illustration, not a photograph).
3. **Creation through the real main-agent flow:** one natural-language request to main; real local Laya routed it `create_market_agent` (7.1 s); main read the company context, called `create_agent` once (accepted first time) and replied. Created `acme-linens-marketplace-analys` ("Acme Linens Marketplace Analyst") with `marketplace_locate/search/item/photo`, `inspect_image`, `read_catalogue`, `save_listing_draft` plus the mandatory read_company_context/memory/skills, and WITHOUT `read_recorded_evidence`. Main wrote two custom skills; the baseline skill was added by the backend.
4. **One research request** to the specialist in natural language ("research comparable products ... near Dallas and save one grounded listing draft; choose the searches and listings yourself, look at their photos"). It chose every step itself (decisions in the archive).

## Bounds (enforced by the backend)
- ScrapeCreators: 7 of 10 attempts (none failed); 7 credits charged (1 each; remaining balance 7007 -> 7001 across the run). Photos: 3 of 3 downloads.
- Model requests: **12 of 16** (3 for main's creation turn, 9 for the research turn). Enforcement: the demo server ran with `ECOM_CHAT_MAX_ITERATIONS=4` and `ECOM_RESEARCH_MAX_ITERATIONS=10` (each turn = iterations + at most one summary request, so (4+1)+(10+1) = 16 worst case). Both caps are server-environment settings (new, default 12/14 unchanged); neither the model nor the chat API can change them. The count is also verified after the fact from recorded request events. Tokens: input 32,575 uncached + 98,560 cache-read, output 3,299 (total 134,434).
- Wall time: creation turn 81.9 s (includes cold Laya load ~46 s), research turn 124.8 s (model time 108.6 s of that across all 12 requests).

## Live evidence vs fictional facts vs uncertainty
- **Live (ScrapeCreators + CDN, retrieved 2026-10-11 10:55-10:56 UTC):** three Dallas-area Marketplace listings (see the draft below), each with detail text, price, and one downloaded photo (hash recorded, pixels shown to the model: `image_part_sent`, `hash_match`). 42 listings were recorded from two searches; only 3 got details/photos.
- **Fictional merchant facts (supplied, not live):** company, product, specifications, the $89 USD price, the illustration.
- **Uncertain:** asking prices only; one photo per listing; label/package text and seller descriptions are claims; two of the three comparables share one (pseudonymised) seller and are not independent samples; the third is a quilt-and-shams set (a different product); searches were sorted newest-first by the agent's choice, not by relevance; the agent made two paid location lookups for the same place ("Dallas, TX" and "Dallas, Texas"); `image_part_sent` shows the image went with the tool result, not proof of model comprehension (the observations quote readable label text, consistent with the pixels).

## The draft (`draft-223013fa34`, status complete, evidence `live_research`, run `run-23b4f116f9`)
**Title:** Cloud Weave Quilted Coverlet – Queen, Oatmeal

**Description:** Cloud Weave Quilted Coverlet in Oatmeal for a queen bed. This listing is for 1 coverlet, sized 90 x 96 in. It has a 100% cotton shell with polyester fill and is machine washable. Condition: new. Price: $89 USD.

**Image brief:** Use clear, well-lit photographs of the actual oatmeal coverlet. Lead with a full view spread neatly across a queen bed so the quilted pattern and overall colour are easy to see. Add close views of the quilting and a product label or packaging view that shows the supplied size and care information. Avoid filters and props that obscure the coverlet.

**Rationale (source-linked):**
1. Use a full-bed primary image with the quilting and colour visible; comparable listings used product-focused photos of their coverlets or packaged bedding. Listings 971869868676687, 1626437119130791, 1582579973018838; images the same ids.
2. Include a close view of the product label or packaging, because comparable photos visibly presented a brand/product label or packaging. Listings 971869868676687, 1626437119130791.

**Limitations (saved with the draft):** asking prices not completed sales; three live listings, one photo each; the merchant image is a synthetic illustration, not a photograph; competitor materials, sizes, pieces and condition are listing claims or visible labels, not verified.

| Listing | Source URL | Retrieved (UTC) | Asking | Photo sha256 (full), host | Visible in the inspected photo (agent's observation) |
|---|---|---|---|---|---|
| 971869868676687 "Full/Queen Space Dyed Cotton Linen Quilt, Khaki - Woven Coverlet", Dallas | https://www.facebook.com/marketplace/item/971869868676687/ | 10:55:53 | $50 | f795b89d5bfd0317a61260cdb67c677823c24d92fa56c19ea15e89d4534502bf, scontent.fsac1-2.fna.fbcdn.net | folded light-beige quilt in clear plastic with a centred label; text "THRESHOLD", "SPACE DYE QUILT", "FULL/QUEEN" |
| 1626437119130791 "Oake Full/Queen Coverlet Solid Color 100% Cotton Bedroom", Dallas | https://www.facebook.com/marketplace/item/1626437119130791/ | 10:55:57 | $65 | 46d905a92e63f939f2803c87de42a33a8d8e507f237003ca1ea68ee8ca47e751, scontent-phl2-1.xx.fbcdn.net | folded dark-blue quilted coverlet with ribbon and paper band; "oake", "FULL/QUEEN COVERLET", "100% Cotton"; seller text: packaging damaged but new |
| 1582579973018838 "NIB Queen Boho Quilt and Shams", Lewisville | https://www.facebook.com/marketplace/item/1582579973018838/ | 10:56:01 | $40 | af7ea6fec61056968db2c7da00ac137452384a1df5291406c44d319dd9c91ba6, scontent-phl2-1.xx.fbcdn.net | folded multicolour floral bedding in a clear plastic bag beside a patterned box; bag text "WARNING" (suffocation warning) |

Draft sources: each source URL is the provider's item URL (identity `id_match` for all three). The Acme price ($89) is the merchant's configured price; the draft makes no price-positioning claim against the $40-$65 asking prices.

## Agent decision trace (tool outcomes, all ok)
read_catalogue, read_company_context, 3 x skill_view; marketplace_locate "Dallas, TX", marketplace_locate "Dallas, Texas"; marketplace_search "quilted coverlet" (50 km, newest first), marketplace_search "cotton coverlet"; marketplace_item x3; marketplace_photo x3; inspect_image x3 competitor photos + the catalogue illustration; save_listing_draft (accepted on the first save; `save_errors` empty).

## Restart and preservation
- After a server restart with the scraper unreachable the draft and run record were byte-identical and no model or scraper request was made; the registry still held exactly the one specialist and the company.
- The sanitized result, harness log, setup log, timing log and manifest were written and verified (sha256) BEFORE anything else; the key, login tokens and signed photo URLs appear in none of the archived or retained files (scanned).
- **Archive:** `research/live-archive/20261011T105324Z-live/` (`result.json` sha256 `4e4e795e3478e2a478991188674462650c7b7e6cad0f1d9eb889046f0fb0b8ce`, `harness.log`, `setup.log`, `timing.jsonl`, `manifest.json`). Harness: 12/12 checks passed.
- **Retained runtime:** `demo/v1-clean-20261011/` (database, profiles incl. the specialist's SOUL/skills/memory, the three downloaded competitor photos under `runtime/research/run-23b4f116f9/images/`). The copied login and API keys were removed from it after archiving (a retained copy holding the single-use Codex refresh token could otherwise invalidate the real login). So there it can be viewed, but chat and live research are disabled until a login/key is provided.

## Changes made for this demonstration (small; audited)
- `app/core.py`: `ECOM_CHAT_MAX_ITERATIONS` / `ECOM_RESEARCH_MAX_ITERATIONS` (whole numbers 1-40 else defaults 12/14; server environment only).
- `tests/research_live_check.py` (+ `RESEARCH_LIVE_VIA_MAIN`, `RESEARCH_LIVE_SCOPE`): company saved, specialist created by main, no fallback creation, combined model-request count, per-call usage, creation record, restart registry check. `scripts/research_live_launch.py`: `--via-main`, `--scope`, `--retain-runtime` (credentials removed, not deleted), ambient override variables removed for real runs.
- Tests (scripted only): `research_archive_test` 15/15 (new A10 via-main run + retained runtime, A11 creation-failure path with no fallback and no scraper request, A12 caps, A12b live cap sum), `research_test` 79/79 unchanged.
- Audit findings: the first scripted via-main run was blocked at a 9-iteration research cap (the stand-in model makes one tool call per request; the first live run used 10 requests for research), so the live caps became 4/10 (sum 16) and the scripted run uses 4/12; the offline routing pre-check (real Laya, no model) confirmed the creation request routes `create_market_agent` before any live spend.

## Remaining gaps
- Codex has not inspected this archive; Arjun's judgment of usefulness is pending. One sample, one market, one provider/model; Nebius/NVIDIA unverified.
- The draft is the product of three comparables (two from one seller). It offers presentation guidance and an accurate listing text but no price positioning.
- Main used 3 of its 4 allowed iterations; a creation that needed more would have failed without fallback (by design).
- Diagnostic photo checks still follow redirects unguarded (no credential attached). V2 not started.
