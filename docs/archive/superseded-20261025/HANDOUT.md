# Shared project handout

Updated 2026-10-25 by Codex: project-wide scope consolidated after final review; V2 remains scripted-tested, live demo pending.
Keep below 400 lines AND about 10 KB; aim for 80-120 short lines. Archive history, do not hide it in long paragraphs.
Read this plus PROTOTYPE_SCOPE.md and the active task. Load deeper references only for a specific question.
Original handout preserved exactly at .scratch/context-history/HANDOUT-before-20261014.md (ignored; historical, not startup context).

## Current state
- Agreed product scope: PROTOTYPE_SCOPE.md (reviewed2026-10-25); glossary CONTEXT.md. Documentation approval authorizes no build, spend, runtime reset, commit or push.
- V1 technical demo accepted on the subscription development provider; product usefulness and NVIDIA compatibility remain unverified.
- V2 tickets1-5 accepted at documented scripted levels; real Gemini/model quality remains unverified. Ticket5: research/v2-ticket05-p2-verification-20261014.md.
- Ticket5 verified: image-delivery boundary, same-batch review refusal, attempt-specific cache and artifact-aware selection. Live Responses/NVIDIA unverified.
- Isolated runner accepted scripted40/40 + lint (research/v2-ticket06-corrections-verification-20261017.md). Preserve evidence; LIVE-runner/second-login plan superseded and frozen. Real Gemini demo unverified.
- Inputs: ignored demo/v2-06-inputs/ contains Northloom demo catalogue/company and three licensed Met quilt photos; USD79 is a test price. Offline checks passed2026-10-23; billing/live key validity unproven. No matching website snapshot. Separate copy prepared only, never signed in/run.
- Live path: existing project login/runtime with reviewed data preservation and explicit call bounds. Reasoning attempts are observed/iteration-bounded, not exhaustively capped. No live call from this scope review.
- Original tickets: docs/social-media-flyer-v2/INDEX.md. Latest independent corrections40/40+lint; .scratch/v206-codex-corrections-20261017.log. Earlier runner41/41 and ticket5 49/49 remain valid. Local resets/startup stalls undiagnosed.
- Local checkpoints confirmed: 98758d9 = accepted ticket5; ee16846 = ticket4; 9d9ecbe = ticket3. Later push status unverified.
- origin: https://github.com/Arjun-Nairr/nvidia-hackathon.git. Initial79d8094 push verified; later pushes/visibility unverified. Repository was public.

## Collaboration and context
- Approved2026-10-25: each roadmap ticket must fit one focused Claude context with headroom for tests/corrections, not consume the maximum window. Check sizing before dispatch; split at an independently verifiable boundary if scope grows. Compaction is a recovery tool, not justification for an oversized ticket. Load one current brief, active task and targeted code; summarize test output. Detailed acceptance criteria go in the active prompt, not every future ticket in startup context.
- Approved roadmap (Blocked by in parentheses; all pending): 00 context consolidation(none); 01 website snapshot to summary/MCQs(00); 02 answers to shared context/chat unlock(01); 03 requested specialist creation, one-per-role/optional custom skills(02); 04 persisted specialist-chat customization(03); 05 basic Neon evidence(03); 06 market analyst demonstration(04,05); 07 social specialist demonstration(04,05); 08 workspace usability(06,07); 09 activity/results presentation(08); 10 Nebius/NVIDIA verification(04,billing); 11 final evaluation/observed fixes(09,10). Live validation requires explicit call bounds. These are work slices, not build/spend authorization; 08/09/11 must be rechecked/split if their concrete scope is too large. Next prompt is00, not another build harness.
- Arjun directs product/scope/authorization. Codex researches, plans, writes inline prompts and verifies; Claude implements.
- Prompts are delivered in chat, never saved as prompt files. Do not create AGENTS.md/CLAUDE.md wrappers just for this workflow.
- Claude has Matt skills installed. Resolve its own names/files/references; do not assume Codex's curated package matches upstream.
- Load one primary execution skill; supporting skills/references only when the task needs them. User scope overrides generic skill commit/review workflows.
- Full two-axis code-review once per ticket; corrections use direct Codex inspection/focused tests, no repeat reviewer team.
- Keep Claude task context compact: read handout/current scope/active task, use /compact after completed tasks in the same chat as Arjun prefers. Do not load all research/history/scratch by default.
- Log verbose tests to ignored scratch; show summaries/failures and inspect targeted functions.
- Diagnose failures before fixes; do not broaden scope. Tests assert behavior, not implementation copies.
- Build small useful slices, then evaluate; no speculative framework, broad cleanup or exhaustive hypothetical hardening.
- Explicitly challenge weak assumptions. Distinguish documented capability, scripted wiring, live evidence and product usefulness.
- No provider/model switches, real runtime resets, publishing/deployment, external messages or paid calls unless the task authorizes them.
- Preserve unrelated edits; stage reviewed files explicitly. Credentials/runtime/dependencies/scratch/archive copies stay out of Git.

## Product scope and next direction
- Current scope is PROTOTYPE_SCOPE.md: one prepared business, Arjun only, structured website/MCQ onboarding before free chat; operator selects from two semi-prebuilt roles, one instance each; specialist-chat customization stays within validated role/tool bounds.
- Shared company.json is main-owned; each agent retains private Hermes memory. Shared facts override conflicting notes. No routine cleanup, vector store, upload system, document intake or public accounts.
- Website-snapshot reading, form state/chat gate, one-per-role enforcement, optional custom skills, persisted specialist configuration updates and basic Neon logging need implementation. Do not describe these as built.
- Social role retains US Facebook Ad Library image-ad research (not Marketplace), relevance selection when comparable reach is absent, Gemini prompt/merchant-photo input and actual-image review.
- Two dispatched generations maximum per manual request: initial plus one correction. Failed/corrupt/unknown dispatches count; no silent replay or third attempt. Final selection and review are separate from file integrity/human acceptance.
- No posting/contact/account writes, schedules, cross-specialist handoffs or additional roles. Brief live activity is later UI/QoL work. Basic Neon logs show backend execution; rationale is a model claim, not private reasoning or proof.
- Existing Met quilt photos and USD79 test offer are labelled demo inputs, not a retail product claim. Still need coherent matching website source. Agent decisions must happen live even when source retrieval is prepared.
- Broader review/evaluation remains desired; reviewer/tool TBD, no external upload or extra paid benchmark authorized. Evaluate useful actions/customization, not commercial effectiveness claims.

## Runtime and data
- Local single-company app, unauthenticated loopback: http://127.0.0.1:8800. UI is temporary; backend/API owns behavior and permissions.
- Hermes Python library AIAgent, one lazy long-lived worker per profile; no separate gateway per specialist. Cold startup remains slow; no streaming or idle shutdown.
- Laya routes main requests; it is not authorization/fine-tuning or a latency guarantee. One known tuned-table miss.
- app/core.py: company/config/registry/grants/profiles; app/worker.py + workers.py: turns/processes; hermes_plugin.py: tools/hooks; turn_state.py: trusted request state.
- app/ads.py: ad runs/evidence/allowances; app/flyer.py: generation/candidates/reviews/correction/final selection; listing.py: catalogue/legacy drafts; server.py: APIs.
- runtime/company.json = shared supplied company facts; runtime/app.db = app registry/transcripts/research/artifacts/accounting (SQLite).
- runtime/hermes_home/profiles/<agent_id> = private SOUL/skills/memory/Hermes sessions. Specialist memory is isolated; artifacts do not belong in conversational memory.
- runtime/hermes_home/auth.json = project subscription login. Never adopt/refresh external personal Codex/Hermes logins.
- Hermes system-prompt memory refreshes at a new session; mid-session preferences remain in history. Request replay cache is in memory and lost on server restart.
- Toolsets derive from stored role/grants. Only main creates agents/updates company; specialists cannot recursively spawn or grant tools.
- Existing profiles/grants/SOUL are preserved; new capabilities require explicit provisioning, not silent widening.

## Configuration and commands
- secrets/local.env ignored; secrets/local.env.template tracked placeholders. Never print keys/tokens/auth headers.
- Development reasoning: openai-codex / gpt-5.6-terra. Nebius route exists but live NVIDIA/tool/vision compatibility remains unverified; reported Nebius credit budget $25.
- LLM_PROVIDER + LLM_MODEL select reasoning provider/model; NEBIUS_API_KEY/NEBIUS_MODEL support Nebius, no fallback.
- GEMINI_API_KEY + GEMINI_MODEL configure separate image provider. Current model/API contract lives in research/v2-04-flyer-generation-result-20261013.md; reverify before a live call.
- ScrapeCreators key is configured; previously used V1 allowances/demo cannot be reset or repeated automatically.
- Launch .\run.bat (setup + app server). Login only if needed: .\login_codex.bat. Models: .\list_models.bat.
- Hermes interpreter: %LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe. Do not install dev dependencies into it or modify personal profiles.
- .\lint.bat = pinned project-local Ruff + ESLint including inline HTML scripts; .\lint.bat setup restores tooling. No autofix/startup coupling.
- Tests that wipe runtime run only on fresh isolated copies of app/scripts/tests, without secrets/runtime. Use their explicit *_I_AM_A_COPY guard.
- Run suites one at a time (fixed ports; orphaned mock servers collide). Large local chat responses are sometimes reset on this PC; flyer_review_test replays the request id.
- On this PC SSLKEYLOGFILE may need removal from a test subprocess environment; TLS verification remains enabled. core.ca_env handles Windows roots.

## Evidence pointers (conditional)
- V1 acceptance: research/v1-clean-demo-verification-20261011.md. Old original incomplete live archive was replaced by a separately authorized clean demo, not recovered.
- V2 integration docs/sample blockers: research/v2-integration-feasibility.md; research/v2-ticket02-corrections-verification-20261011.md.
- Role foundation: research/v2-ticket01-review-20261011.md.
- Ad acceptance: research/v2-ticket03-corrections-verification-20261013.md (ad80/80, analyst57/57).
- Flyer acceptance: research/v2-ticket04-corrections-verification-20261013.md (flyer44/44).
- Ticket5 evidence: research/v2-05-review-correction-result-20261013.md (+ scripted trace example); review research/v2-ticket05-review-20261014.md; P1 research/v2-05-p1-delivery-verification-20261014.md (43/43); P2 research/v2-05-p2-corrections-20261014.md (49/49).
- PROTOTYPE_SCOPE.md governs current product decisions; research/social-media-flyer-v2-spec.md and its tickets retain original V2 implementation/evidence detail. Conflicting historical sign-in/public-onboarding/extra-role proposals are superseded.
- CODEX_NOTES.md is Codex's working agreement, not mandatory Claude startup context; relevant rules are summarized here.
- Archived notes and earlier research contain superseded directions. Never revive them over current scope or claim old pending-review status is current.
