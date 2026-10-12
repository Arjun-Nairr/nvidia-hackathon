# V2-01 result: main/Laya can create an independent social-media specialist (2026-10-11)

Author: Claude Code. Ticket: `docs/social-media-flyer-v2/issues/01-independent-social-role.md`. Status: **implementation complete, awaiting Codex review; not independently accepted.** All reasoning-model behaviour below is a SCRIPTED stand-in (`tests/mock_llm.py`): it proves wiring, grants, isolation and enforcement, not live model quality. No subscription-model, scraper, Gemini or Nebius call was made; no real credential was copied into a test; no personal Hermes profile, runtime, company, sample or allowance was touched.

## What changed
- **Role registry (`app/core.py`, `app/roles.py`):** `ROLES["social_media"]` beside `market_analysis`, with its own fixed responsibilities and baseline skill `social-media-flyer-baseline` (supplied facts vs creative choices, responsible use of references, use of the merchant's product photos, brief checklist, output format; no analyst text). Mandatory tools `read_company_context`, `memory`, `skills`; optional eligible tools only those that are implemented and relevant: `inspect_image`, `read_catalogue`. Not connected (listed as such): `facebook_ad_research`, `image_generation`, `social_posting`, `instagram`, `email`, `web_search`, `web_scraping`, `scheduling`. `roles.FOUNDATIONS` gives each role its baseline name/text, responsibilities and start line.
- **One-role assumptions removed in touched paths:** validation (per-role baseline duplicate rule, corrected "no other roles" hint), `build_soul` (role label, responsibilities, honest limits, baseline start line; a dict without a role is still an analyst), profile description and baseline file written, create_agent response `skills`, and `run_turn` (toolsets come from the agent's OWN stored role, so analyst and social grants resolve correctly after restart).
- **Plugin (`app/hermes_plugin.py`, `app/turn_state.py`):** the create_agent description and `role` parameter cover both roles with their own guidance; the pre-tool hook and the tool body both refuse a role other than the one the backend classified (`create_allowed(role)`); the classifier-off test seam carries no role and so does not restrict.
- **Routing (`app/routing.py`):** new outcome `create_social_agent` (`CREATE_OUTCOMES` maps each supported role to its outcome). The analyst path is unchanged. Social creation requires `social_media >= 0.55` AND a margin of `>= 0.30` over the next role (`T_SOCIAL`, `T_SOCIAL_MARGIN`; tuned on the small table, not calibrated); a close call yields `clarification`, email/other stay `unsupported_role`. `allow_create_agent` is true only for the two creation outcomes. Context and replies name both roles, list existing specialists WITH their roles and say to point to an existing specialist of that role unless the user explicitly asks for another.
- **Main (`scripts/setup.py`):** SOUL rewritten: two roles; main's own capabilities (company context, creating specialists, no research/image/posting tools) separated from specialists'; research is stated per role (Marketplace only for an analyst granted the marketplace tools; Facebook ad research and flyer generation not connected; nothing can be posted); reuse of existing specialists; no forced pairing, dependency or deletion. Role-neutral goal wording: `COMPANY_LABELS["goal"]` is "business goal" and two UI strings changed (goal label; the blanket "Live market research: not connected" line is now "Research tools: granted per specialist ..."). No layout change.
- **Tests:** new `tests/social_role_test.py` (38 checks); `tests/mock_llm.py` (social creation stand-in), `tests/routing_e2e_mock.py` (social creation through real Laya, email still unsupported), `tests/route_table.py` (6 new social cases, 3 changed expectations).

## One actual scripted creation response (social_media, through main's create_agent tool)
```json
{"ok": true, "agent_id": "acme-social-media-specialist", "conversation_id": "conv-acme-social-media-specialist",
 "granted_tools": ["inspect_image", "memory", "read_catalogue", "read_company_context", "skills"],
 "approval_requirements": [
  {"action": "read company context / read the catalogue / inspect registered images / use own memory and skills", "requirement": "none"},
  {"action": "publish, post, send messages or change anything externally", "requirement": "user confirmation required; no such tool is granted"},
  {"action": "Facebook ad research, image or flyer generation", "requirement": "not connected in this increment"}],
 "state": "idle", "context_refs": ["customers", "goal", "products", "profile"],
 "skills": ["social-media-flyer-baseline", "feed-flyer-checklist"]}
```

## Role foundations and grants (as created in the isolated test)
| | market_analysis (`acme-competitor-analyst`) | social_media (`acme-social-media-specialist`) |
|---|---|---|
| Baseline skill (backend) | `competitor-analysis-baseline` | `social-media-flyer-baseline` |
| Custom skill (main) | `price-tier-review` | `feed-flyer-checklist` |
| Granted tools | the seven requested (`marketplace_locate/search/item/photo`, `inspect_image`, `read_catalogue`, `save_listing_draft`) + `read_company_context`, `memory`, `skills` | `inspect_image`, `read_catalogue` + `read_company_context`, `memory`, `skills` |
| Tools visible to the model (direct chat) | marketplace_*, save_listing_draft, inspect_image, read_catalogue, company/memory/skills | company/memory/skills, catalogue, image inspection only |
| SOUL | market-analysis, Marketplace research paragraph | social-media; "Facebook ad research and image or flyer generation are NOT connected yet ... cannot produce or publish" |

## Isolation, memory and restart evidence (scripted; real server, real Hermes workers)
- Each profile contains only its own baseline and custom skill files; neither profile text contains the other's name, skills or memory.
- Each specialist saved its own preference (`PURPLE-OTTER` / `TEAL-HERON`) to its own memory; the other specialist and main never held it.
- Specialists have no `create_agent` / `update_company` tool (the model is told the tool is not available); registry, grants and company are unchanged afterwards. Main alone created agents and updated the company; the company edit did not rewrite specialists' saved SOUL.
- After an app restart: both agents, roles, grants and transcripts persist, both chat, memory files are unchanged and still separate, each worker still resolves its toolsets from its own role, and the social SOUL file is byte-identical. Duplicate name is refused (`name_taken`).
- Honesty is enforced by what is granted and stated in the SOUL; whether a live model reports it faithfully is NOT established.

## Failing-before / passing-after
| Behaviour | Unmodified snapshot | Now |
|---|---|---|
| validate `social_media` | refused `unsupported_role` | validates; tools = requested + foundation |
| `ROLES` keys | `['market_analysis']` | `['market_analysis', 'social_media']` |
| clear social request routes to | `unsupported_role`, `allow_create_agent` false | `create_social_agent`, allowed |
| create_agent description / role parameter | "Currently only: market_analysis" | both roles |
| creation guard | not role-aware | refuses a role other than the routed one |
| baseline per role | single analyst baseline | `FOUNDATIONS` per role |
Real Laya on the same table: the old "unsupported role (social)" cases became creation outcomes by design; the one pre-existing miss (`yes please` after an Instagram detour, role 0.38 vs 0.31) is unchanged.

## Checks (fresh isolated copies; scripted model; real Laya/Hermes where noted)
Baseline (unmodified): ticket01 28/28, onboarding 26/26, workers 22/22, e2e 24/24, chat API 18/18, routing_e2e (real Laya) 21/21, route_table (real Laya) 48/49.
After the first full pass: social_role_test 38/38 (A1-A11, B1-B19), ticket01 28/28, workers 22/22, e2e 24/24, chat API 18/18, research_test 79/79, listing 57/57, research_archive 15/15. That pass exposed two things (see Audit), so the affected suites were re-run on the FINAL code: social_role_test 38/38, image_path 31/31 (was a KeyError), onboarding 26/26, routing_e2e (real Laya) 23/23, route_table (real Laya) 54/55 (49 baseline cases + 6 new social cases; the single miss is the pre-existing `yes please` after the Instagram detour, identical probabilities to the baseline's 48/49). ticket01, workers, e2e, chat API, research, listing and archive were NOT re-run after the last two small changes (role-less `build_soul` default; social margin), which they do not exercise.

## Audit (touched paths)
- **Fixed:** `build_soul` indexed `c["role"]` and broke a legacy-shaped call in `image_path_test` (found by the run): now a dict without a role is an analyst.
- **Fixed:** the first routing rule (margin 0.10) let "Create an agent for social media competitor analysis" create the social role (0.50 vs 0.30); social now needs 0.55 and a 0.30 margin, so that request is a clarification or the analyst path.
- **Fixed:** UI blanket "Live market research: not connected" (false once the analyst holds Marketplace tools) and the analyst-specific goal label.
- **Checked, no change:** `read_company_context`/context refs are role-neutral; plugin tool registration is by agent id and exposure is by granted toolset; `listing.save_draft`/`research.*` take identity from the worker environment, not the role; profile config and plugin shim are role-independent; stored analyst profiles are never rewritten.

## Limitations and remaining blockers
- Scripted model only: no evidence of live main/specialist behaviour for the social role, of Laya accuracy beyond the 55-case table (thresholds tuned on it), or of Nebius/NVIDIA.
- "Create a social media agent to post on Instagram" now creates a social specialist (posting not connected; the SOUL and main's instructions say so). Whether that is the desired product reply is a judgment call.
- Facebook ad retrieval, Gemini generation and the merchant sample are NOT part of this ticket (V2-03/04, blocked as recorded); the specialist has no tool that could produce an image or a post.
- Analyst-only hold-over strings remain intentionally: the analyst's own SOUL limits sentence and `competitor-analysis-baseline`.
