# Proposed creative specialist: next-milestone decision

2026-10-11. Codex using research skill. Planning only; no implementation, installation, paid requests or new role authorized by this note.

## Documented facts
- [ScrapeCreators Facebook post](https://docs.scrapecreators.com/v1/facebook/post/) documents like_count, comment_count, share_count and a potentially missing view_count. Public post metrics are not evidence of paid-ad conversions or unique reach; live availability on home-textile image posts is untested.
- [ScrapeCreators ad details](https://docs.scrapecreators.com/v1/facebook/adlibrary/ad/) documents a separate ad-creative endpoint. Its inspected page contains no likes, reach or impressions fields. Absence from this documentation does not prove every response lacks them; do not promise them before a sample check.
- [Meta Ad Library API](https://br-fr.facebook.com/ads/library/api/) limits impressions and spend ranges to political/issue ads, with specific reach fields depending on region/ad type (EU, UK, Brazil). It does not establish general US commercial competitor performance access.

## Judgment and proposed next slice
Recommend a creative-generation specialist before a full UI redesign, with minimal image display/review support when needed. Use a research skill/rubric to identify available evidence before designing a performance score. Engagement, ad longevity and commercial success are distinct concepts; unknown metrics stay unknown, never zero or fabricated.

Keep existing analyst as research owner when practical; a creative specialist consumes a saved evidence package and merchant facts, selects an original design approach, calls the user-proposed Gemini image tool, checks the actual generated image against required facts/branding/product appearance/readability and returns one saved image plus rationale and check outcome. The agent should be free to reject a bad reference and revise within a bounded generation allowance. Gemini model/API/image editing feasibility has not been researched or verified here. No claim that generated product imagery preserves exact appearance yet.

Arjun proposed image-generation output as the next point for his quality feedback. Existing V1 remains technically demonstrated but not judged commercially useful. This is a proposed V2 direction, not a completed grill/spec or authorization to dispatch implementation. Publishing/account-changing actions remain deferred. Decide paid-ad creatives versus publicly engaged promotional image posts before specifying ranking and retrieval.

## User decision: reach rather than effectiveness
Arjun selected paid-ad reach as the initial reference-ranking target. Do not claim conversion/sales effectiveness. Distinguish reported reach (people/accounts reached), impressions (display count), estimated target-audience size and engagement. Rank relevant comparables using actual reported reach where available; missing metrics remain unknown, not zero or invented estimates. Region/data-source availability must be checked before promising reach-based ranking; US-only versus an initial EU/UK sample is still undecided. No new implementation or paid sample dispatched.

## V2 grilling round 1: confirmed decisions
- US-based target confirmed; no EU/UK niche switch.
- Goal: manually request one Facebook promotional flyer for a merchant product. Actual product facts/price and supplied visual assets, no publishing.
- Analyst and creative specialist must be defined together as a linked team for this capability. The creative specialist receives research from the analyst; the merchant should not manually copy evidence between them. Exact reuse/provisioning and handoff mechanics remain to be specified.
- Output: one saved flyer; multiple flyers deferred. Arjun's answer confirmed one saved flyer, but did not explicitly settle automatic regeneration count or the final check-report format.
- Arjun reports ScrapeCreators can retrieve Instagram reach. Treat this as a user-reported capability pending verification of the exact endpoint/field (reach vs views/impressions), availability and account requirements. Do not assume Facebook Marketplace exposes paid-ad reach or that reach-unavailable fallback was accepted; fallback remains an open decision.
- Next open choices: initial reference source, demo asset input versus merchant upload, and behavior when reach/checks are unavailable or fail. No production implementation/tickets dispatched.

## V2 grilling round 2: confirmed decisions
- Facebook first; Instagram deferred. If Facebook reach cannot be retrieved, gate the reach-dependent capability until Instagram is implemented. Whether the gate disables ranking only or blocks the entire flyer flow remains to be clarified; do not silently assume a relevance fallback.
- Use a prepared merchant/product sample that persists; no upload UI in this increment.
- Arjun replaces proposed agent visual review/regeneration with a deterministic backend image-validity gate. Flow: analyze reference photos -> derive features -> create Gemini prompt -> Gemini returns image -> backend checks file corruption/readability -> present image. No automatic agent quality-review or corrective-regeneration loop agreed.
- This gate confirms file integrity, not factual product identity, text correctness, design quality or advertising effectiveness. Keep these limits visible in acceptance claims.
- Exact product-photo handling and the reach gate's effect on the workflow remain open; no production code or tickets dispatched.

## V2 grilling rounds 3–4: decisions superseding open choices above
- Reach gate disables ranking only when Facebook reach is unavailable. Continue reference analysis and flyer generation; do not substitute engagement or guessed reach. Revisit reach with Instagram later.
- Gemini receives agent-written prompt/context and relevant USER-SUPPLIED photos selected by the agent. Competitor images inform the agent's analysis rather than being automatically passed to Gemini as product assets.
- Persistent prepared sample: one home-textile product, 2–3 actual product photos, verified supplied price/specifications and simple brand guidance, enough context for agent photo selection and generation. No upload interface required now; provenance/permission and Gemini input feasibility to verify during setup.
- Output minimum: one saved flyer, displayed and retrievable after restart. A brief explanation is optional if trivial; no separate explanation framework. No automatic image-quality review or regeneration. Backend validates file readability/integrity and reports invalid output explicitly.
- Grilling product choices consolidated below, awaiting Arjun's scope confirmation before to-spec. Current V1 scope remains unchanged until confirmation.

## Consolidated V2 scope for confirmation
One new semi-prebuilt creative specialist paired with the analyst. Main provisions/reuses the appropriate company team; specialist identities, company-specific instructions/skills and granted tools follow the existing backend-validated approach. Merchant manually requests one Facebook product flyer. Analyst retrieves US Facebook image-ad references (new ad source, not Marketplace data presented as ads), records provenance and reported reach when available, then automatically provides evidence to the creative specialist. Creative chooses useful visual features and supplied product photos, builds the prompt/context and calls Gemini. Backend validates the returned image, saves it with the relevant provenance and displays it through minimal replaceable UI support. Optional short explanation; no posting. Reach-based ranking is capability-gated if unavailable, without blocking generation.

Technical research before dependent implementation: verified Facebook ad retrieval/metric fields, Gemini image generation with user-selected product images, bounded call/credit settings and exact handoff/storage seams. No new roles beyond creative, Instagram integration, broad UI redesign, schedules, posting, fine-tuning or multi-business architecture. No paid test authorization inferred from grilling answers.

## Latest steering: independent social-media specialist
Arjun rejects analyst-to-creative dependency/handoff. The social-media/creative specialist should retrieve and analyze its own flyer/ad references and available reach, then generate output. It shares merchant/product facts through the existing backend, not the market analyst's conclusions. This supersedes the linked-team proposal above; do not implement cross-agent coordination for V2.

Arjun proposes adding model-based review of the generated image against criteria and a corrective Gemini request when it fails. This changes the prior corruption-only gate decision. Recommendation pending confirmation: preserve the original product facts/constraints, provide the actual generated image to a vision-capable reviewer, identify specific defects, and issue a revised generation/edit request with the relevant product images (and rejected result when the verified API supports it). Keep the deterministic integrity gate first. Bound to one corrective attempt initially; unresolved defects produce an explicitly unapproved draft or clear failure. No guarantee model self-review catches all issues. Exact review criteria/retry budget and Gemini capabilities remain to be settled before spec or code.

## Authoritative V2 scope — confirmed after final steering
Arjun confirmed one initial generation plus AT MOST one corrective attempt. This section supersedes earlier linked-team and corruption-only proposals.

- Main provisions a company-specific semi-prebuilt social-media/creative specialist using predefined role foundations and eligible tools, customizing its instructions/skills/context for the merchant. Existing analyst remains independent; no analyst-to-creative handoff or mandatory pair creation.
- Social-media specialist researches US Facebook image advertisements itself. Instagram is later. It selects relevant references and analyzes their actual images; reported reach may inform ranking only when verified available. Missing reach disables reach-based ranking, not the whole generation flow. No invented proxy reach or effectiveness claim.
- Persistent prepared sample: one home-textile product, 2–3 actual merchant-supplied product photos, verified supplied price/specifications and simple brand context. Specialist selects relevant supplied photos.
- Specialist creates a Gemini prompt/context from reference-derived visual features and merchant requirements. Gemini receives that context plus selected merchant photos; competitor imagery informs analysis rather than being treated as the merchant's product.
- Backend validates output integrity/readability first. Specialist reviews actual generated pixels against supplied product appearance, required text/price and requested layout. A failed check may cause one specific corrective generation/edit request, preserving requirements. Total generation calls per manual flyer request <=2, enforced by backend; no silent retry of uncertain generation outcomes or hidden extra generation calls.
- After the corrective attempt, report unresolved defects honestly; do not present an unchecked/failed image as approved. Model review is fallible and not certification of factual accuracy, product fidelity or ad performance. Generation/model failures are not necessarily fixed by prompt engineering alone.
- Minimum result: one saved flyer with enough provenance/review status to retrieve it after restart, displayed through minimal replaceable UI support. Short explanation only if trivial. Keep original versus corrected attempt references and failure/review evidence sufficient for later diagnosis, without a new audit framework.
- No posting, account-changing execution, schedules, extra specialist roles, Instagram implementation, full UI redesign, fine-tuning, multi-business system or publishing.

Ready for to-spec: product scope agreed; specification must mark Facebook ad/metric access, Gemini selected-photo input/edit capabilities and review-model support as verification dependencies. Exact model/config, narrow tool contracts, persistence and backend bounds belong in specification/feasibility work; do not claim these integrations already work. Grilling authorization does not authorize paid probes or implementation dispatch.
