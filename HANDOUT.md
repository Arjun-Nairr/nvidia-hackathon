# Project handout (single project context)

Updated 2026-10-25 (Ticket 00; probe preparation). Load this + the active prompt + targeted implementation files; open history only for a specific question.
Superseded briefs are archived at docs/archive/superseded-20261025/ (see its README).

## Purpose and scope
- Hackathon ecommerce multi-agent prototype on Hermes Agent: a main agent understands one business, then creates bounded, business-customized specialists that do useful work. The claim is real execution, meaningful customization, honest outcomes and basic usability, not advertising quality or commercial effectiveness.
- Sole operator: Arjun. One prepared home-textile business, "Northloom Demo Studio": a labelled demonstration built on one Met public-domain quilt (three licensed museum photos). USD 79 is an arbitrary test price, not a retail offer; claim no ownership, inventory, condition, care or museum endorsement.
- Out of scope: extra roles, customer accounts, multi-business hosting, document intake, live website discovery, cross-specialist handoffs, posting/contact/account writes, schedules, fine-tuning.

## Agreed workflow (target)
1. Operator enters a website link. A prepared website snapshot (never claimed as fetched live) identifies the business; the normal composer stays blocked.
2. Main reads the snapshot and shows a brief business summary, about 5-10 MCQs (each with a write-in option) and an optional correction box.
3. Operator answers. Main merges source facts and operator input into shared business context, keeping them distinguishable, then unlocks chat and explains which roles fit. The operator chooses; submitting the form authorizes no specialist.
4. On request, main configures one semi-prebuilt specialist: objective, style, business instructions, context, minimal eligible tools, optional skills. The backend validates and creates the Hermes profile.
5. Operator inspects the specialist and chats with it directly. Requested changes are validated and persisted on the SAME specialist. Direct tasks run autonomously within configured limits.

## Roles, customization, memory, logging
- Exactly two roles, ONE instance each at most: market analyst (competitor products/prices/listings; today only narrower Marketplace research and listing drafts) and social-media specialist (US Facebook Ad Library image-ad research, Gemini flyer, actual-image review). Operator activates; never auto-create both.
- Semi-prebuilt: we provide role foundations, baseline skills, potential tools, memory lifecycle and enforced permissions. Main customizes within them and cannot invent tools or privileges. Extra custom skills are optional (reusable procedures only); needed tool dependencies stay usable. Configuration, not fine-tuning.
- Arjun clarified: workflow steps/prerequisites and permissions must be enforced by code, not only prompts. Instructions guide decisions within those boundaries. Current tool/budget/review guards exist; the agreed onboarding step sequence is still unbuilt. No LangGraph migration has been selected.
- Shared business context is runtime/company.json; only main writes it. Each agent keeps separate private Hermes memory; specialists suggest shared corrections through main. Current shared facts override conflicting private notes. No vector store or memory-cleanup framework.
- Flyer rules: reach ranking requires documented comparable metric meaning, geography and measurement period, not merely an available number; one initial Gemini generation plus at most one correction after actual-image review; failed or unknown dispatches count; no silent replay.
- Basic Neon execution logging is REQUIRED for the finished demo: backend-observed steps (source/profile/questionnaire, requested/validated/applied configuration, tool calls and results, generation/review/final/error) with identities, timestamps and any available timing/usage. Rationale is a model claim, not hidden reasoning or proof. No secrets or raw image payloads. Local SQLite/traces suffice for early tests.

## Terms
Website snapshot = saved source copy, distinct from the company profile main derives and the operator clarifies (shared business context, main-owned). Role foundation = predefined purpose, boundaries and potential tools; specialist memory = one agent's private notes. Website, catalogue, configuration, memory and execution logs are different records; website-derived facts may be used with provenance, missing facts are never guessed, and goals and demonstration prices come only from explicit operator input.

## Status (evidence level matters)
- V1 accepted 2026-10-11 live on the subscription provider: main plus analyst, Marketplace research, image inspection, listing drafts (research/v1-clean-demo-verification-20261011.md). Product usefulness and NVIDIA compatibility unverified.
- V2 tickets 1-5 accepted at SCRIPTED level only: social role, integration feasibility, Facebook ad research with reach gating, flyer generation, actual-image review with one correction. Checkpoints: 9d9ecbe (3), ee16846 (4), 98758d9 (5), 8743f60 (Ticket 00).
- Ticket 6 offline demo runner and five corrections: accepted scripted (41/41, 40/40, lint). It is evidence only; its isolated live-runner/second-login route is superseded.
- Unbuilt (agreed future work, not features): website-snapshot reading, MCQ/form state, onboarding chat gate, one-per-role enforcement (today only names are unique), optional skills (creation still requires them), source-aware main intake, specialist-chat persisted configuration/grant updates, Neon, the analyst's broader responsibilities, UI redesign.
- Not established: product-usefulness of the flyer (Arjun's judgment pending), repeatability (one live sample each), Nebius/NVIDIA tool/vision compatibility (reported $25 credit; switch deferred, not dropped), a coherent website snapshot. Key presence proves neither validity nor billing. Local response resets/startup stalls undiagnosed.

## Immediate sequence
- The original unfinished task is the first real flyer probe / full social-specialist test. It uses the existing project authentication and runtime with a scoped preservation/setup plan. The isolated live-runner/second-login route is superseded.
- SOCIAL END-TO-END RUN 2026-10-25 executed successfully (request social-e2e-20261025-1, 148 s; 11 model requests, 18 tool calls, retries invisible: unknown): real US Facebook Ad Library research (4 of 8 scraper calls, 2 of 3 downloads; package adpkg-6fc899d84e, relevance-only: no ad carried reach), ONE Gemini dispatch of 2 (27 s, 5826 tokens) from our photos only, flyer fly-05fba9a82e / cand-15eb5139e0 (runtime/flyers/fly-05fba9a82e/cand-15eb5139e0.jpg), hook-confirmed inspection, verified review rev-aef14b6703 (passed, no correction), finalized agent_review_passed. Not V2 acceptance or human approval; Arjun's judgment pending. My look: the inset close-up overlaps the quilt's lower-right corner (grey band) and the review missed it. Gaps: the final flyer stores its package link (flyer_runs.research_json: adpkg-6fc899d84e + reference ids) but generation-level references_json is empty (no reference_ad_image_ids supplied: weaker provenance); competitor/catalogue inspections lack hook-confirmed delivery. Details: research/v2-06-probe-plan-20261025.md.
- Earlier probes 2026-10-25: attempt 1 failed at Gemini (HTTP 400, response_format.delivery) and was fixed offline (flyer 45/45, review 49/49, runner 40/40 + 41/41, lint); retry 1 produced cand-0de3bc4839 with verified review rev-b8f09f93c8. All flyer scopes are spent; evidence kept.
- Provisioning 2026-10-25: attempt 1 failed (main's saved Hermes session kept its OLD system prompt until its title was retired via SessionDB; history kept); attempt 2 created social_media specialist northloom-social-specialist (requested tools only, no create_agent/update_company, skill flyer-routine, retries 1 / recovery 0). Never reuse request ids.
- Backups under backups/ are point-in-time copies: do NOT restore them now that live turns have run. ECOM_* paths/caps come from the server's process environment (caps read at start), not secrets/local.env. Unused demo/v2-06-live-20261023 holds copied API keys.
- Website/MCQ onboarding, configuration updates and Neon are NOT prerequisites for testing the existing flyer capability. Existing local evidence supports the first test; Neon is needed for the finished demo.
- Next: Arjun judges the final flyer (fly-05fba9a82e). Then decide: supply reference ids at generation, make the review check overlap/occlusion, evaluate customization changes on the same specialist, or stop. No further live run is authorized. Remaining roadmap: the unbuilt items, UI/QoL, Nebius/NVIDIA verification, independent external review (tool TBD; no upload authorized).

## Architecture and files
- Local single-company app at http://127.0.0.1:8800 (unauthenticated loopback); the UI is temporary, the backend/API owns behavior and permissions. Hermes AIAgent library, one lazy long-lived worker per profile.
- app/core.py company/config/registry/grants/profiles; worker.py + workers.py turns; hermes_plugin.py tools/hooks; turn_state.py trusted request state; ads.py ad research/allowances; flyer.py generation, review, correction, selection; listing.py catalogue/drafts; server.py APIs. Only main creates agents or edits company facts; specialists cannot spawn or grant tools.
- runtime/ (ignored): company.json shared facts; app.db registry/transcripts/research/artifacts/accounting; hermes_home/profiles/<agent_id> private SOUL, skills, memory and sessions; hermes_home/auth.json is the project login. Never adopt or refresh personal Codex/Hermes logins. Preserve existing profiles and grants; new capability needs explicit provisioning.
- Config: secrets/local.env (ignored; template tracked). Reasoning is openai-codex / gpt-5.6-terra via LLM_PROVIDER + LLM_MODEL; Nebius via NEBIUS_API_KEY/NEBIUS_MODEL with no fallback; Gemini image via GEMINI_API_KEY + GEMINI_MODEL (verified contract in research/v2-04-flyer-generation-result-20261013.md; recheck before a live call). V1 ScrapeCreators allowances are spent and cannot be reset automatically.

## Commands
- .\run.bat starts setup and the app. .\login_codex.bat only if login is needed. .\list_models.bat lists models. .\lint.bat runs pinned Ruff and ESLint (.\lint.bat setup restores tooling).
- Hermes Python: %LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe (no dev dependencies in it).
- Tests that wipe runtime run only on isolated copies without secrets/runtime (*_I_AM_A_COPY guard); run suites one at a time (fixed ports). Remove SSLKEYLOGFILE from subprocess environments if needed; TLS verification stays on.

## Collaboration rules
- Arjun directs scope and authorization. Codex plans, writes inline prompts and verifies; Claude implements. Prompts live in chat, never in prompt files; no AGENTS.md/CLAUDE.md wrappers. CODEX_NOTES.md holds Codex-only preferences and is not startup context.
- STRICT: Codex/ChatGPT sees only this HANDOUT, git status/diff and changed files, never Claude's chat replies. Record every finding, caveat, judgment and next step in HANDOUT or a changed report file before finishing; ignored paths (runtime/, backups/, .scratch/, demo/) need a visible note.
- Each Claude task: read this handout, load only task-relevant material, execute the bounded slice, verify, update this handout, then stop. /compact after completed tasks.
- Code review once per ticket; corrections get direct inspection and focused tests. Verbose logs go to ignored .scratch. Diagnose before fixing; build small slices; challenge weak assumptions; separate documented capability, scripted wiring, live evidence and product usefulness.
- No provider/model switch, runtime reset, deployment, external message, paid call, commit or push unless the task authorizes it. Stage explicit paths; credentials, runtime, dependencies and scratch stay out of Git.
- Origin github.com/Arjun-Nairr/nvidia-hackathon (79d8094 pushed; later pushes/visibility unverified; was public).
- History: research/ and docs/social-media-flyer-v2/INDEX.md.
