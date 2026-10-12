# V2-01 — Main creates an independent social-media specialist

Status: ACCEPTED 2026-10-11 by Codex after two-axis code review and independent isolated social-role checks 38/38. Scripted-model evidence only; no live model, scraper, Gemini or Nebius call. Review: research/v2-ticket01-review-20261011.md. Implementation: research/v2-01-social-role-result-20261011.md.
Blocked by: none.
Parent: `research/social-media-flyer-v2-spec.md`, existing seams and decision1.

## Outcome
A merchant asks main for a social-media specialist, Laya recognizes the supported role, backend provisions its role-specific foundation and company customization, and the specialist chats with isolated memory. Existing analyst stays independent and works unchanged.

## Scope
- Targeted preparatory expansion of role definitions, creation validation/guidance, SOUL/baseline selection, profile description, worker toolset selection, routing creation authorization and main setup instructions. Expand the new path beside the old one, preserve/migrate relevant analyst assumptions only, then remove obsolete one-role assumptions in touched paths.
- Mandatory read_company_context/memory/skills foundation; role-specific baseline plus main's complementary custom skills. No inherited analyst instructions, conclusions or memory. No mandatory paired creation or recreation.
- Eligible new capabilities are advertised only when implemented/registered; until03/04, clearly state Facebook ad/Gemini tools are not yet connected. Do not install fake working tools or silently enable arbitrary Hermes tools.
- Role-neutral company-goal wording; main recognizes existing specialists and directs reuse when appropriate, without prohibiting explicit new-agent requests.

## Acceptance
- Natural-language social-role creation passes the real main/Laya/backend path in an isolated high-level test; scripted reasoning is labelled. Analyst creation still passes, unknown/email roles remain unsupported, ambiguous input does not grant creation rights by itself.
- Both roles get the correct baseline/custom skills and toolsets; main alone can create/update; specialists cannot recursively create agents or grant themselves capabilities.
- Direct chats and separate memory/history survive app restart; no existing company/profile reset or migration into the new role.
- Main's obsolete global research-not-connected claim is corrected to describe its own versus specialist capabilities honestly.
- Relevant creation/routing/worker regression checks pass; no broad architecture rewrite, live scraping/Gemini/Nebius calls, installs or UI redesign.

## Completion evidence
Record the actual creation response, role foundations/grants, isolation/restart result, failing-before/passing-after relevant checks, touched assumptions and remaining unavailable capabilities. Update ticket/index and HANDOUT.

## Result (Claude, 2026-10-11)
Note `research/v2-01-social-role-result-20261011.md` (files changed, one actual scripted creation response, role foundations/grants, isolation/restart evidence, checks, audit, limitations).
- `social_media` added beside `market_analysis`: own responsibilities, baseline `social-media-flyer-baseline`, mandatory read_company_context/memory/skills, optional implemented `inspect_image` and `read_catalogue` only; ad research and image generation advertised as NOT connected.
- One-role assumptions removed in validation, plugin description/schema, profile description, SOUL/baseline selection and run_turn toolsets (from the agent's own role). Analyst behaviour and stored profiles unchanged.
- Routing: `create_social_agent` needs social >= 0.55 and a 0.30 margin; analyst path unchanged; email/other unsupported; a creation route allows only its classified role (hook and tool body). Main's SOUL rewritten (own vs specialist capabilities, reuse existing specialists, no pairing/deletion); role-neutral goal wording and two UI strings.
- Checks (scripted model, fresh isolated copies, real Laya where noted): social_role_test 38/38, ticket01 28, onboarding 26, workers 22, e2e 24, chat API 18, routing_e2e 23 (real Laya), research 79, listing 57, image path 31, archive 15, route_table 54/55 (real Laya; one pre-existing miss; baseline 48/49).
- Not covered: live model behaviour, Laya accuracy beyond the small tuned table, Nebius/NVIDIA. No ad retrieval, Gemini or sample work (tickets 03/04).

