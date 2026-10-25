# Project handout (single project context)

Updated 2026-10-25 by the Ticket 00 consolidation. Load this + the active prompt + targeted implementation files; open history only for a specific question.
Superseded briefs (old scope, glossary, handout, Codex notes) are archived at docs/archive/superseded-20261025/ (see its README).

## Purpose and scope
- Hackathon ecommerce multi-agent prototype on Hermes Agent: a main agent understands one business, then creates bounded, business-customized specialists that do useful work. The claim is real execution, meaningful customization, honest outcomes and basic usability, not advertising quality or commercial effectiveness.
- Sole operator: Arjun. One prepared home-textile business, "Northloom Demo Studio": a labelled demonstration built on one Met public-domain quilt (three licensed museum photos). USD 79 is an arbitrary test price, not a retail offer; claim no ownership, inventory, condition, care or museum endorsement.
- Out of scope: extra roles, customer accounts, multi-business hosting, document/PDF/OCR intake, live website discovery, cross-specialist handoffs, posting/contact/account writes, schedules, fine-tuning.

## Agreed workflow (target)
1. Operator enters a website link. A prepared website snapshot (never claimed as fetched live) identifies the business; the normal composer stays blocked.
2. Main reads the snapshot and shows a brief business summary, about 5-10 MCQs (each with a write-in option) and an optional correction box.
3. Operator answers. Main merges source facts and operator input into shared business context, keeping them distinguishable, then unlocks chat and explains which roles fit. The operator chooses; submitting the form authorizes no specialist.
4. On request, main configures one semi-prebuilt specialist: objective, style, business instructions, context, minimal eligible tools, optional skills. The backend validates and creates the Hermes profile.
5. Operator inspects the specialist and chats with it directly. Requested changes are validated and persisted on the SAME specialist. Direct tasks run autonomously within configured limits; no per-tool permission prompts.

## Roles, customization, memory, logging
- Exactly two roles, at most ONE instance each: market analyst (competitor products/prices/listings; today only narrower Marketplace research and listing drafts) and social-media specialist (US Facebook Ad Library image-ad research, Gemini flyer, actual-image review). Operator activates; never auto-create both.
- Semi-prebuilt: we provide role foundations, baseline skills, potential tools, memory lifecycle and enforced permissions. Main customizes within them and cannot invent tools or privileges. Extra custom skills are optional (reusable procedures only); necessary tool dependencies stay usable. This is configuration, not fine-tuning.
- Shared business context is runtime/company.json; only main writes it. Each agent keeps separate private Hermes memory; specialists suggest shared corrections through main. Current shared facts override conflicting private notes. No vector store or memory-cleanup framework.
- Flyer rules: reach ranking only when documented reach exists; one initial Gemini generation plus at most one correction after actual-image review; failed or unknown dispatches count; no silent replay.
- Basic Neon execution logging is REQUIRED for the finished demo: backend-observed steps (source/profile/questionnaire, requested/validated/applied configuration, tool calls and results, generation/review/final/error) with identities, timestamps and any available timing/usage. Rationale is a model claim, not hidden reasoning or proof. No secrets or raw image payloads. Local SQLite/traces suffice for early tests.

## Terms
Demo operator = Arjun. Demo business = the prepared example. Website snapshot = saved source copy, distinct from the company profile main derives and the operator clarifies (shared business context, main-owned). Role foundation = predefined purpose, boundaries and potential tools. Specialist = business-customized agent on a foundation. Specialist memory = one agent's private notes. Website, catalogue, configuration, memory and execution logs are different records; a website does not establish goals, price, material or size.

## Status (evidence level matters)
- V1 accepted 2026-10-11 live on the subscription provider: main plus analyst, Marketplace research, image inspection, listing drafts (research/v1-clean-demo-verification-20261011.md). Product usefulness and NVIDIA compatibility unverified.
- V2 tickets 1-5 accepted at SCRIPTED level only: independent social role, integration feasibility, Facebook ad research with reach gating, flyer generation, actual-image review with one correction (delivery-bound review). Local checkpoints: 9d9ecbe (ticket 3), ee16846 (4), 98758d9 (5).
- Ticket 6 offline demo runner and five corrections: accepted scripted (41/41, 40/40, lint). It is evidence only; its isolated live-runner/second-login route is superseded.
- Unbuilt (agreed future work, not features): website-snapshot reading, MCQ/form state, onboarding chat gate, one-per-role enforcement (today only names are unique), optional skills (creation still requires them), source-aware main intake, specialist-chat persisted configuration/grant updates, Neon, the analyst's broader responsibilities, UI redesign.
- Not established: any live V2 Gemini flyer or actual-image review quality, live Responses delivery, Nebius/NVIDIA tool/vision compatibility (reported $25 credit; provider switch deferred by Arjun, not dropped), a coherent website snapshot. Key presence does not prove validity or billing. Local response resets and startup stalls are undiagnosed.

## Immediate sequence
- The original unfinished task is the first real flyer probe / full social-specialist test. It uses the existing project authentication and runtime with a scoped preservation/setup plan. The isolated live-runner/second-login route is superseded.
- Offline readiness passed with ignored demo/v2-06-inputs/ (catalogue.json, company.json, three hash-verified quilt photos). The ignored copy demo/v2-06-live-20261023 was prepared but never signed in or run; it holds copied API keys, so delete it once unneeded.
- Website/MCQ onboarding, configuration updates and Neon are NOT prerequisites for testing the existing flyer capability. Existing local evidence supports the first test; Neon is needed for the finished demo.
- Next: a small Claude task preparing the existing app and sample for a separately authorized probe. Then the probe (own go-ahead, explicit call bounds). Then the unbuilt items above, an evaluation that changes requirements and checks persisted behavior on the same specialist, UI/QoL, Nebius/NVIDIA verification, and independent external review (tool TBD; no upload authorized).

## Architecture and files
- Local single-company app at http://127.0.0.1:8800, unauthenticated loopback; the UI is temporary and the backend/API owns behavior and permissions. Hermes AIAgent library, one lazy long-lived worker per profile; no gateway per specialist.
- app/core.py company/config/registry/grants/profiles; worker.py + workers.py turns; hermes_plugin.py tools/hooks; turn_state.py trusted request state; ads.py ad research/allowances; flyer.py generation, review, correction, selection; listing.py catalogue/drafts; server.py APIs. Only main creates agents or edits company facts; specialists cannot spawn or grant tools.
- runtime/ (ignored): company.json shared facts; app.db registry/transcripts/research/artifacts/accounting; hermes_home/profiles/<agent_id> private SOUL, skills, memory and sessions; hermes_home/auth.json is the project login. Never adopt or refresh personal Codex/Hermes logins. Existing profiles and grants are preserved; new capability needs explicit provisioning.
- Config: secrets/local.env (ignored; template tracked). Reasoning is openai-codex / gpt-5.6-terra via LLM_PROVIDER + LLM_MODEL; Nebius via NEBIUS_API_KEY/NEBIUS_MODEL with no fallback; Gemini image via GEMINI_API_KEY + GEMINI_MODEL (verified contract in research/v2-04-flyer-generation-result-20261013.md; recheck before a live call). V1 ScrapeCreators allowances are spent and cannot be reset automatically.

## Commands
- .\run.bat starts setup and the app. .\login_codex.bat only if login is needed. .\list_models.bat lists models. .\lint.bat runs pinned Ruff and ESLint (.\lint.bat setup restores tooling).
- Hermes Python: %LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe (no dev dependencies in it).
- Tests that wipe runtime run only on fresh isolated copies of app/scripts/tests without secrets/runtime, behind the *_I_AM_A_COPY guard. Run suites one at a time (fixed ports). Remove SSLKEYLOGFILE from test subprocesses if needed; TLS verification stays on.

## Collaboration rules
- Arjun directs scope and authorization. Codex plans, writes inline prompts and verifies; Claude implements. Prompts live in chat, never in prompt files; no AGENTS.md/CLAUDE.md wrappers. CODEX_NOTES.md holds Codex-only preferences and is not startup context.
- Each Claude task: read this handout, load only task-relevant material, execute the bounded slice, verify, update this handout, then stop. One primary execution skill; /compact after completed tasks.
- Code review once per ticket; corrections get direct inspection and focused tests. Log verbose output to ignored .scratch and show summaries and failures.
- Diagnose before fixing; build small useful slices; challenge weak assumptions; separate documented capability, scripted wiring, live evidence and product usefulness.
- No provider/model switch, runtime reset, deployment, external message, paid call, commit or push unless the task authorizes it. Stage explicit paths; credentials, runtime, dependencies and scratch stay out of Git.
- Origin https://github.com/Arjun-Nairr/nvidia-hackathon.git (initial 79d8094 pushed; later push status and visibility unverified; repository was public).
- Historical evidence is under research/ and docs/social-media-flyer-v2/ (index there lists per-ticket reports).
