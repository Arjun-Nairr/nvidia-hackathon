# V2-02: integration feasibility and persistent sample (2026-10-11)

Author: Claude Code. Ticket: `docs/social-media-flyer-v2/issues/02-integration-and-sample-feasibility.md`. Documentation and setup work only: **no paid scraper, Gemini, subscription-model or Nebius call was made**; no install, provisioning, reset or UI change. Everything below is labelled **[D]** documented (with source), **[S]** read from official SDK source, **[R]** recommendation, **[U]** untested assumption, **[B]** blocker.

## 1. Verdict
| Area | Result |
|---|---|
| Facebook ads | Contracts documented. Recommend ScrapeCreators `search/companies` + `company/ads` (primary) and `search/ads` (keyword) + `ad` (detail), US only, image ads only. **US image-ad coverage and every reach value are unverified.** |
| Reach | Not usable. ScrapeCreators does not define it; its fields are nullable and null in every documented example. Meta documents reach only for EU/UK ads (and political/issue ads); **no reach is documented for US commercial ads**. Ranking is disabled by default; flyer workflow unaffected. |
| Gemini | Recommend `gemini-nano-banana-2.1` through the Interactions REST endpoint, called with plain HTTP (no SDK), `store=false`, one send per reserved attempt. Accepts text plus up to 10 high-fidelity object photos; edits by re-sending the candidate image. Paid tier only. Total spend is unmeasured (section 5). |
| Hidden retries | **The Python SDK retries by default (up to 3 retries on 408/409/429/5xx and connection errors) and `attempts=1` still allows one retry in the Interactions client.** Avoid by not using the SDK. |
| Sample | **Blocked: no actual merchant product photos or verified product facts exist.** Missing-input list in section 4. Nothing prepared, fabricated or downloaded. |
| Credentials | ScrapeCreators key present. **Gemini key absent locally** (not in `secrets/local.env`, not in the environment); **billing-enabled Google project unconfirmed** (local absence does not show whether Arjun has one elsewhere). |

## 2. Facebook advertising (ScrapeCreators)
Retrieved 2026-10-11 from the official OpenAPI pages (raw spec text, cross-checked with the rendered pages). Base URL `https://api.scrapecreators.com`; auth header `x-api-key`; every documented example shows `credits_charged: 1`. "Scrape Creators does not enforce API rate limits", keep under 500 concurrent requests [D: introduction]. Whether failed requests are charged is **not documented** [U]. Cache: `cache_max_age` (1d-30d) is documented only on Ad Details (cache hit 0 credits, `cached: true`) [D: caching page].

### 2.1 Endpoints and inputs [D]
| Endpoint | Method/path | Inputs (query) | Result list key |
|---|---|---|---|
| Search companies | `GET /v1/facebook/adLibrary/search/companies` | `query` (required) | `searchResults[]`: `page_id, name, category, likes, verification, entity_type, ig_username, ig_followers, page_alias, page_is_deleted, image_uri` |
| Company ads | `GET /v1/facebook/adLibrary/company/ads` (POST twin accepts the same fields as JSON) | `pageId` or `companyName`; `country` (one 2-letter code, default ALL); `status` ALL/ACTIVE/INACTIVE (default ACTIVE); `media_type` ALL/IMAGE/VIDEO/MEME/IMAGE_AND_MEME/NONE; `language` (2-letter); `sort_by` `total_impressions` (default) or `relevancy_monthly_grouped` ("Most Recent"); `start_date`, `end_date` (YYYY-MM-DD); `cursor`; `trim` | `results[]`, `cursor` |
| Search ads | `GET /v1/facebook/adLibrary/search/ads` (POST twin) | `query` (required); `search_type` keyword_unordered/keyword_exact_phrase; `ad_type` all/political_and_issue_ads; plus `country`, `language`, `status`, `media_type`, `sort_by`, `start_date`, `end_date`, `cursor`, `trim` as above | `searchResults[]`, `searchResultsCount`, `cursor` |
| Ad details | `GET /v1/facebook/adLibrary/ad` | `id` or `url` (ad library URL), `trim`, `cache_max_age` | single object, camelCase |

"Meme just means the ad has text and an image" [D]. A page size is not documented [U].

### 2.2 Response fields relevant to V2 [D, from examples; no formal schema is published]
- **Source identifiers:** list endpoints `ad_archive_id` (string), `page_id`, `page_name`; detail `adArchiveID` (number), `pageID`, `pageName`, and `url` = `https://www.facebook.com/ads/library?id=<id>` (usable as the public source link). Compare IDs as strings: 15-16 digit values exceed JavaScript's exact integer range.
- **Text/links:** `snapshot.body.text` (list) / `snapshot.body` (detail), `title`, `caption`, `link_url`, `link_description`, `cta_text`, `cta_type`.
- **Images:** `snapshot.images[]` with `original_image_url`, `resized_image_url`, `watermarked_resized_image_url`, `image_crops`; also `extra_images`. `snapshot.display_format` (examples: `MULTI_IMAGES`, `VIDEO`; enumeration not documented; detail example is lowercase `video`).
- **Variants/cards:** "For ads with multiple versions, the ad creative is found in the snapshot.cards array rather than snapshot.body" [D]. All documented examples show `cards: []`, so the **card element schema is undocumented** [U]. `collation_id` is documented as "Facebook's internal ID for related ads in a campaign" and `collation_count` as "The number of ads in the campaign"; `ad_archive_id` is "The *actual* ad id" and `is_active` "Whether the ad is currently running" [D: [ScrapeCreators Company Ads](https://docs.scrapecreators.com/v1/facebook/adLibrary/company/ads) and [Search ads](https://docs.scrapecreators.com/v1/facebook/adLibrary/search/ads) response field descriptions; the camelCase detail fields `collationID`/`collationCount` are only shown as null with no description]. This is **campaign grouping, not proof of an identical creative**: the documentation does not say that related ads in a campaign share the same image or text. Keep every distinct `ad_archive_id` as its own record; store the campaign id and count as separate grouping metadata. Whether two ads share the same creative is not answered by these fields [U]; if ever needed it must come from observed content (text, image hashes), not from `collation_id`.
- **Other:** `is_active`, `start_date`/`end_date` (epoch seconds), `publisher_platform[]`, `total_active_time`, `targeted_or_reached_countries[]`, `entity_type`, `page_like_count`.
- CDN image URLs are signed (`oh=`/`oe=` query) and on `*.fbcdn.net` [D: examples]; treat as private and download soon after retrieval (expiry [U]). The V1 allow-list (`.fbcdn.net`, no credential, redirect guard) already fits.
- **US coverage:** `country` accepts a single 2-letter code (so `US` is expressible) but no page states that US commercial image ads are returned [U]. Marketplace listings are a different source and are never ad references.

### 2.3 Reach [D unless marked]
- **ScrapeCreators:** list endpoints expose `reach_estimate`, `impressions_with_index {impressions_text, impressions_index}`, `spend`, `currency`; detail exposes `reachEstimate`, `impressionsWithIndex`, `spend`, and `aaa_info.eu_total_reach` plus `age_country_gender_reach_breakdown`. **Every documented example has `reach_estimate: null`, `impressions_text: null`, `impressions_index: -1`, `spend: null`.** The docs define none of these. Their only reach statements: political/issue `location_audience` rows include reach (fractional shares) and "regional transparency data may use absolute reach counts" (Ad Details description). `sort_by=total_impressions` is an ordering mode; no impressions value is returned to explain the order, so ordering must **not** be read as reach.
- **Meta (primary source for meaning):** Graph API `archived-ad`: `eu_total_reach` "the estimated combined ad reach for all locations inside the European Union", "available only for ads delivered to the EU"; `total_reach_by_location` supports EU, BR, UK; `age_country_gender_reach_breakdown` "available only for ads delivered to the UK & EU and POLITICAL_AND_ISSUE_ADS delivered to Brazil"; `impressions`, `spend`, `estimated_audience_size` "available only for POLITICAL_AND_ISSUE_ADS". The API page adds that other ads are available for UK/EU delivery and that political/issue ads are available worldwide. Whether Meta's reach counts people or impressions is **not stated in what I could read** [U].
- **Consequence [R]:** for US commercial image ads no reach is documented anywhere. Store `reach: {available: false, value: null, source: "not_provided"}`; never substitute impressions, likes, run duration, `total_active_time`, page likes or estimated audience. If a US ad does carry a value in a later live check, expose it with its raw field name, geography (`eu_total_reach` stays EU-only) and the statement that its definition is unverified; compare only like-for-like fields.

### 2.4 Recommended Facebook path and narrow tool contracts [R]
Backend fixes `country=US`, `media_type=IMAGE_AND_MEME`-or-`IMAGE` (operator setting), `status=ACTIVE`; the model supplies only query text and choices of IDs the backend already returned (same pattern as V1 `location_no`/`listing_id`). No URLs, page IDs from text, credentials, caps or `cache_max_age`.

| Tool | Backend call | Model inputs | Output (normalised) | Error semantics |
|---|---|---|---|---|
| `fb_ads_find_advertiser` | `search/companies` | `query` | `advertisers[]`: `advertiser_no, name, category, likes, verified` | `no_results`, `allowance_exhausted`, `provider_error`, `unknown_outcome` (never replayed) |
| `fb_ads_search` | `company/ads` (with `advertiser_no`) or `search/ads` (keyword) | `query` or `advertiser_no`; `status?`; `next_page?` (cursor held by backend) | `ads[]`: `ad_no, source_ad_id, source_url, advertiser, active, start_date, display_format, text, cta, image_count, card_count, campaign_id(from collation_id), campaign_ad_count(from collation_count), reach{...}` (one entry per distinct `ad_archive_id`; campaign fields are grouping metadata only, never a dedupe key); `has_more`; `ranking: "disabled_reach_unavailable"` | as above plus `empty` flag (change query, do not repeat) |
| `fb_ad_detail` | `ad` | `ad_no` | one ad incl. cards/images, raw reach fields with provenance | `unknown_ad`, as above |
| `fb_ad_image` | CDN download of one `images[]`/card image from the run record | `ad_no`, `image_no` | registered `image_id`, sha256, w/h, host (no signed URL) | `photo_unavailable`, `host_not_allowed`, `redirect_refused`, `not_an_image`, `allowance_exhausted` |

Backend rules reused from V1: reserve before send, count failures, serve identical successful calls from the run store, unknown outcome terminal, no redirects on API calls, TLS on, per-hop photo redirect check, no credential on downloads, ad images kept apart from Marketplace evidence.

## 3. Gemini image generation
Retrieved 2026-10-11 from `ai.google.dev` (image-generation, models, pricing, interactions-overview, image-understanding, API reference).

### 3.1 Recommended path [R, facts D]
- **Model:** `gemini-nano-banana-2.1` ("Nano Banana 2.1"), Stable, "Latest update October 2026". Inputs text/image/video/PDF, outputs image and text, input token limit 131,072. It is listed in the API reference model options. Fallback with the same API: `gemini-3.1-flash-image` ("recommended for all new projects to use Nano Banana 2.1" says the page). Do not use Imagen ("shut down") or `gemini-2.5-flash-image` (legacy).
- **API:** Interactions API, "Generally Available ... recommended for all new projects" as of June 2026; legacy `generateContent` "remains fully supported". Request: `POST https://generativelanguage.googleapis.com/v1beta/interactions`, header `x-goog-api-key`, body `{"model", "input": [{"type":"text","text":...},{"type":"image","data":<base64>,"mime_type":...}], "response_format": {"type":"image","mime_type":"image/png"|"image/jpeg","aspect_ratio":"4:5","image_size":"1K"|"2K"}, "store": false}`. The image is read from the response `steps[].content[]` image block (`data` base64, `mime_type`); `status` is one of in_progress, requires_action, completed, failed, cancelled, incomplete, queued; `usage` reports input/output/thought tokens.
- **SDK:** `google-genai` Python >= 2.3.0 exposes `client.interactions.create` (doc). **Recommend not using the SDK** (section 3.3). No install is needed or done.
- **Output size/format:** default size follows the input image else 1:1; sizes 1K/2K/4K (default 1K); for 4:5: 928x1152 (1K), 1856x2304 (2K), 3712x4608 (4K); also 1:1, 9:16, 16:9 etc. Output images carry a SynthID watermark. Docs examples use image/jpeg and image/png output.
- **Inputs:** PNG, JPEG, WEBP, HEIC, HEIF; inline base64 keeps the whole request <= 20 MB (otherwise Files API); up to 14 reference images total, "up to 10 images of objects with high-fidelity" for this model. Our registered-image path accepts JPEG/PNG/WEBP/GIF (max 8 MB each), so the usable intersection is JPEG/PNG/WEBP; cap selection at 3 photos and a conservative 12 MB raw total (base64 +33%).
- **Correction vs regeneration:** editing ("provide an image and use text prompts to add, remove, or modify elements") and multi-turn editing via `previous_interaction_id` are documented. Because `store=false` makes that id unusable, **correction [R]** = a second stateless call containing the corrections, the selected merchant photos and the first candidate's bytes as an additional input image; if the live probe shows poor fidelity, regenerate from the corrected prompt with the merchant photos only. Fidelity of either is **[U]** until the probe.
- **Data handling:** by default requests are stored (55 days paid tier, 1 day free; `store=false` opts out). Paid tier is "not used to improve our products"; free tier is. Merchant photos are sent to Google, so use `store=false` and say so in the setup note.
- **Cost (Paid, Standard) [D: pricing]:** input $1.50 / 1M tokens (text, image); output images $30 / 1M tokens = $0.0336 (1K), $0.0504 (2K); text/thinking output $7.50 / 1M. Free tier "Not available" for this model. The pricing page lists 3780 tokens for 4K while the generation page table lists 2520; do not use 4K. Input tokens and text/thinking output are charged in addition to the image-output component, and the thinking-token volume (default level medium) is not bounded by the docs [U]. **Total spend per call is unmeasured**; the image-output charge alone is $0.0504 per 2K image and $0.2016 for four.
- **Credential:** an AI Studio API key from a **billing-enabled** project (usage tier needs billing; "Rate limits are applied per project, not per API key"; image throughput is limited as images per minute, values only in AI Studio) [D]. **[B] No Gemini key exists locally; whether a billing-enabled project exists elsewhere is unconfirmed.** No Vertex/OAuth path is needed.
- **Quality settings [R]:** `aspect_ratio` 4:5, `image_size` 2K for the demonstration (text legibility matters for price/claims review; $0.0504 vs $0.0336), 1K for probes; `mime_type` image/png (text-heavy flyers); no Google Search grounding (extra charge, off by default).

### 3.2 Proposed tool contract [R]
`generate_flyer(product_id, selected_product_image_ids[1..3], prompt, reference_ad_image_ids[0..3]? , previous_candidate_id?, corrections?)`. Reference ad images are NOT sent to Gemini (spec decision 2); they only shape the prompt. Backend binds company, specialist, request, attempt number, model, aspect ratio and size. Output: `candidate_id, status, image_id, width, height, sha256, mime_type, attempts_remaining, usage`. Errors: `attempts_exhausted` (third call, any retry), `missing_inputs` (unregistered/absent photo), `bad_corrections`, `provider_blocked` (failed/incomplete, safety), `provider_error` (HTTP 4xx/5xx), `unknown_outcome` (timeout/connection lost after send: slot consumed, not replayed), `invalid_image` (does not decode, wrong type, zero or oversized dimensions, more or fewer than one final image). Every error that follows a send consumes the reserved slot.

### 3.3 Hidden retries and how to keep the two-generation bound [S + R]
- **Documentation:** `HttpRetryOptions.attempts` = "Maximum number of attempts, including the original request. If 0 or 1, it means no retries. If not specified, default to 5" (SDK `types.py`). The Gemini rate-limits page only says "wait and retry".
- **Implementation (python-genai `main`, retrieved today; pin unverified) [S]:** the Interactions client is a generated client (`google/genai/_gaos`). `_translate_retry_config` maps `attempts` to `max_retries` (retries after the first send), defaulting to `_DEFAULT_MAX_RETRIES + 1 = 3`; `interactions.create` retries status `408, 409, 429, 5XX` and transport errors, backoff 0.5 s doubling to 8 s. So with defaults one logical generation can be sent up to **4 times**, and `attempts=1` (documented as "no retries") still permits **one** retry (2 sends); only `attempts=0` yields none. A retried POST can generate and bill twice.
- **[R]** (1) Do not use the SDK for this call: send exactly one `urllib`/`httpx` POST per reserved slot with our own timeout (suggest 150 s) and no retry; V1's `api_get` pattern and reservation table apply unchanged. (2) If the SDK is later preferred, require a test with a local scripted server that counts sends under `attempts=0`, 429, 503 and a dropped connection before accepting it. (3) The provider-side behaviour on timeout (the generation may still complete and bill) is **[U]**: treat as unknown outcome, count it, never replay.

## 4. Persistent sample
**Inspected (names/provenance only; no credential files opened):** `tests/fixtures/demo_catalogue.json` + `tests/fixtures/demo_images/demo-quilt-front.png` (V1 fictional merchant; the image is a synthetic illustration, labelled so); `runtime/marketplace_check/images/*.jpg` (3 competitor Marketplace photos from the V1 diagnostic: competitor assets); research-run PNGs under `.scratch/` and `demo/` (scripted-mock output or downloaded competitor photos); the real runtime company ("Arjun Test", products "Textile", no specifications, price or photos).

**Result: blocked.** No actual merchant product photograph and no verified merchant product facts exist anywhere in the project. I did not open the unrelated personal files in `Downloads` (some `.jpg` files have no provenance); say if any of them is a product photo you want used. No synthetic illustration or competitor photo was relabelled, nothing was downloaded, the V1 sample, real company, agents, conversations and allowances were not touched.

**Missing inputs (concise):**
1. 2-3 real photographs of ONE home-textile product (JPEG/PNG/WEBP, longest edge >= 1000 px, <= 5 MB each; e.g. full view, close-up of the weave/quilting, label or packaging).
2. For each photo: who took or owns it, date, and a statement that it may be used in this prototype and sent to Google's Gemini API.
3. Verified facts: product name, size/dimensions, colour, material/fill, care, pieces, condition; the **declared price and currency**; any claims that must not be made.
4. Simple brand context: merchant name (a clearly labelled fictional name is fine, the photos must be real), tone in a few words, 2-3 style/colour words, target audience, market (default Dallas, TX).

**Proposed layout once supplied [R]:** `samples/v2-merchant/` with the photos and `manifest.json`: `{"merchant":{id,name,demo,notice,brand:{tone,style,palette},market:{location_query}}, "products":[{product_id,name,category,condition,specifications,price:{amount,currency},images:[{image_id,file,kind:"merchant_photo",provenance:{owner,captured,permission},sha256,width,height}]}]}`. Image IDs stable and unique (`<product>-front`, `-detail`, `-label`); the catalogue extension is an `images[]` list beside the existing single `image` so the V1 catalogue still works. `ECOM_CATALOGUE_FILE` and `ECOM_IMAGE_DIRS` already let it be configured without code changes; the company name must match the catalogue merchant (existing check). The validator for ticket 04 should reject `kind` of synthetic or competitor.

## 5. Proposed caps and live-test budget (for later approval; nothing authorised here)
Operator settings (backend, not model arguments):
- Per manual request: <= 8 ScrapeCreators attempts (advertiser search <= 2, ad list pages <= 3, detail <= 3), <= 4 ad-image downloads, <= 3 merchant photos sent, **2 generation slots (fixed)**, aspect 4:5, size 2K, timeout 150 s, no retries.
- Per scope: the same numbers as the live budget below; no model-visible reset.
- Model iterations: creation turn 4 (+1), flyer turn 20 (+1).

**One total live call-allowance proposal (counts, not a dollar ceiling; spent only on the stated stages, and only if approved):**
| Stage | ScrapeCreators attempts | Ad-image downloads | Gemini calls | Reasoning-model requests |
|---|---|---|---|---|
| A. ad contract probe (end of ticket 03): 1 US image `search/ads`, 1 `company/ads`, 1 `ad`, no model | 3 | 1 | 0 | 0 |
| B. Gemini probe (end of ticket 04): 1 generation with 2 merchant photos + 1 correction using the candidate | 0 | 0 | 2 | 0 |
| C. preserved demonstration (ticket 06): creation + one flyer request | 8 | 4 | 2 | 26 (4+1 creation, 20+1 flyer) |
| **Total proposed allowance** | **11** | **5** | **4** | **26** |
**Cost is unmeasured and conditional.** At the documented rate the image-output component of four 2K images is 4 x $0.0504 = $0.2016; input-token and text/thinking-token charges are additional and not bounded by the documentation, so no dollar total or ceiling is stated. The Gemini call counts above are an allowance proposal, not a guaranteed dollar limit and not authorization to spend. ScrapeCreators: at most 11 calls, i.e. 11 credits if each is charged 1 credit as in the documented examples (failed-call charging is undocumented); balance observed 7001 after the last V1 run. Stage A also records whether any US ad carries a non-null reach field; Stage B verifies input handling, edit fidelity and the retry-free single send.

## 6. Readiness for tickets 03 and 04
| Prerequisite | 03 Facebook ad research | 04 Generate/save/display flyer |
|---|---|---|
| Endpoint/model contract documented | **Ready** (section 2) | **Ready** (section 3) |
| Normalisation/limits/tool contracts | Ready (proposed) | Ready (proposed) |
| API key present | Ready (ScrapeCreators; ad endpoints not live-verified) | **Blocked: Gemini key absent locally; billing-enabled project unconfirmed** |
| Merchant sample | Not required for scripted wiring; needed for relevant live queries | **Blocked** (photos and facts); plumbing may use the labelled synthetic illustration only in scripted tests, never as merchant photography |
| US coverage / reach | **Unverified**: stage A; ranking disabled by default | n/a |
| Upstream ticket | Needs 01 (role) per the graph; backend tools can be built and scripted first | Needs 01 per the graph; scripted local Gemini stand-in supports tests |
Neither 03 nor 04 may claim a live result before its probe; missing reach and missing keys narrow only the dependent live capability.

**Recommended next ticket: V2-01 (independent social-media role).** It has no external dependency; 03 then 04 follow, and the sample/Gemini key requests below can be satisfied in parallel.

## 7. Untested assumptions and blockers
- [U] US image ads returned for `country=US`; `media_type` filter behaviour; card schema; whether ads in one campaign (`collation_id`) share a creative; page size; whether failed ad calls are charged; image URL expiry.
- [U] Any non-null `reach_estimate`/`impressions` for US commercial ads (expected null on Meta's documentation).
- [U] Gemini `store=false` accepted on `nano-banana-2.1`; edit-by-resend fidelity; latency (the 150 s timeout is a guess); safety blocks on product photos; REST response shape against the live API (documented examples only).
- [U] The SDK source facts are from `main` on the retrieval date; no installed version was inspected.
- [B] Gemini API key absent locally and billing-enabled project unconfirmed; actual merchant photos and verified product facts (section 4); Arjun's approval of any live allowance.

## Sources
- ScrapeCreators: [Ad Details](https://docs.scrapecreators.com/v1/facebook/adLibrary/ad), [Search ads](https://docs.scrapecreators.com/v1/facebook/adLibrary/search/ads), [Company ads](https://docs.scrapecreators.com/v1/facebook/adLibrary/company/ads), [Search companies](https://docs.scrapecreators.com/v1/facebook/adLibrary/search/companies), [Introduction](https://docs.scrapecreators.com/introduction), [Caching](https://docs.scrapecreators.com/caching), [index](https://docs.scrapecreators.com/llms.txt).
- Meta: [Ad Library API](https://br-fr.facebook.com/ads/library/api/) (the www host returned 403; this mirror was read), [Graph API archived-ad](https://developers.facebook.com/docs/graph-api/reference/archived-ad/), [Ad Library tools](https://transparency.meta.com/researchtools/ad-library-tools).
- Google: [Image generation](https://ai.google.dev/gemini-api/docs/image-generation), [Nano Banana 2.1 model](https://ai.google.dev/gemini-api/docs/models/gemini-nano-banana-2.1), [Pricing](https://ai.google.dev/gemini-api/docs/pricing), [Interactions overview](https://ai.google.dev/gemini-api/docs/interactions-overview), [Interactions API reference](https://ai.google.dev/api/interactions-api), [Image understanding](https://ai.google.dev/gemini-api/docs/image-understanding), [Rate limits](https://ai.google.dev/gemini-api/docs/rate-limits).
- SDK source (retry behaviour): [python-genai `_gaos/google_genai.py`, `_gaos/interactions.py`, `_gaos/utils/retries.py`, `types.py`](https://github.com/googleapis/python-genai).
