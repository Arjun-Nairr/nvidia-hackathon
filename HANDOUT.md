# Shared project handout

Updated 2026-10-14 by Codex: ticket5 accepted (scripted49/49 + lint). Current state overrides history.
Keep below 400 lines AND about 10 KB; aim for 80-120 short lines. Archive history, do not hide it in long paragraphs.
Read this plus PROTOTYPE_SCOPE.md and the active task. Load deeper references only for a specific question.
Original handout preserved exactly at .scratch/context-history/HANDOUT-before-20261014.md (ignored; historical, not startup context).

## Current state
- V1 technical demo accepted on the subscription development provider; product usefulness and NVIDIA compatibility remain unverified.
- V2 tickets1-4 accepted at their documented evidence levels. Facebook ad and Gemini-generation work is scripted-tested, not live-proven.
- Ticket5 ACCEPTED for scripted wiring/enforcement after P1 + both P2 verification. Final report: research/v2-ticket05-p2-verification-20261014.md. Real model/Gemini quality remains unverified.
- P1: supported Hermes API hooks confirm candidate/reference pixels in model input plus a response boundary; same-batch review refused. Scripted chat path verified; live Responses/NVIDIA unverified.
- Cached results describe one attempt; final-flyer state is separate. Candidate selection uses current artifact validity; no valid file => storage failure, never regeneration.
- Next: checkpoint ticket5, then ticket6 live readiness/evaluation with separately approved inputs and budget. No dispatch, commit/push or paid probe performed here.
- Ticket6/live demo not dispatched. No paid probe authorized. Real merchant photos/facts and Gemini key were last reported missing; billing unconfirmed.
- Ticket graph: docs/social-media-flyer-v2/INDEX.md. Current review: research/v2-ticket05-review-20261014.md.
- Independent latest: review49/49 + lint. Logs in .scratch/verify-v2-05-p2-20261014/. Local HTTP resets reported by Claude remain undiagnosed.
- Local checkpoint ee16846 = accepted ticket4; 9d9ecbe = accepted ticket3. Ticket5 changes remain uncommitted; inspect git status before editing.
- origin: https://github.com/Arjun-Nairr/nvidia-hackathon.git. Initial79d8094 was confirmed pushed. Repository was public; do not assume later commits pushed or visibility changed.

## Collaboration and context
- Arjun directs product/scope/authorization. Codex researches, plans, writes inline prompts and verifies; Claude implements.
- Prompts are delivered in chat, never saved as prompt files. Do not create AGENTS.md/CLAUDE.md wrappers just for this workflow.
- Claude has Matt skills installed. Resolve its own names/files/references; do not assume Codex's curated package matches upstream.
- Load one primary execution skill; supporting skills/references only when the task needs them. User scope overrides generic skill commit/review workflows.
- Full two-axis code-review once per ticket; corrections use direct Codex inspection/focused tests, no repeat reviewer team.
- New implementation/correction slices start fresh with this handout, current scope and targeted issue. Never load all research/history/scratch files by default.
- Keep normal test output concise: log to ignored scratch, show summary and failures. Inspect selected functions instead of repeatedly printing whole large files.
- Unknown failure needs diagnosis; do not guess causes or broaden the task. Tests should assert behavior, not reproduce implementation logic.
- Build small useful slices, then evaluate; no speculative framework, broad cleanup or exhaustive hypothetical hardening.
- Explicitly challenge weak assumptions. Distinguish documented capability, scripted wiring, live evidence and product usefulness.
- No provider/model switches, real runtime resets, publishing/deployment, external messages or paid calls unless the task authorizes them.
- Preserve unrelated edits; stage reviewed files explicitly. Credentials/runtime/dependencies/scratch/archive copies stay out of Git.

## Product scope and next direction
- Ecommerce company-specific team: main onboards/provisions semi-prebuilt specialists; backend owns foundations, lifecycle, tools and permissions.
- Main customizes role/identity/objective/instructions/context/priorities/eligible tools/custom skills. It cannot invent privileges.
- Supported specialists: market_analysis and social_media. User chats with each; no forced pair or analyst-to-social handoff.
- V2 social specialist independently researches US Facebook Ad Library image ads and creates one home-textile promotional flyer.
- Marketplace listings are analyst evidence, not paid ads. Instagram, video, news and other roles are outside V2.
- Missing/ambiguous/incomparable reach disables ranking, not relevance-based generation. No impressions/likes/views proxies or sales-effectiveness claims.
- Actual supplied product photographs/facts required for live work. Synthetic fixtures must be labelled and confined to isolated tests.
- Gemini gets selected merchant photos plus prompt/context; competitor images remain reasoning/provenance references.
- Generated-file integrity is separate from actual-pixel content review. At most TWO dispatched attempts per manual request: initial + one correction.
- Failed/corrupt/unknown dispatched attempts count, with no automatic replay/retries. No third attempt or second correction.
- One explicitly selected final flyer; preserve candidates, input hashes, prompts, reviews, uncertainty and decision rationale.
- Review is fallible agent review, not human approval. No actual pixel delivery means unchecked/unverified.
- Posting/sending/contact/account-changing features deferred until planned agent system and usable UI are complete.
- After V2: at most one additional useful specialist (email is a candidate, not agreed implementation), then focus on evaluation/UI/evidence/accuracy/learning.
- End V2: independent external review and broader audit, reviewer/tool TBD; no external code upload authorized by this roadmap alone.
- Evaluate useful actions and decision records, not final output alone; agent rationale is a claim checked against evidence, not private chain-of-thought.

## Runtime and data
- Local single-company app, unauthenticated loopback: http://127.0.0.1:8800. UI is temporary; backend/API owns behavior and permissions.
- Hermes Python library AIAgent, one lazy long-lived worker per profile; no separate gateway per specialist. Cold startup remains slow; no streaming or idle shutdown.
- Main-only Laya classification is routing guidance, not authorization, fine-tuning or guaranteed context/latency reduction. Small tuned table has one known miss.
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
- Ticket5 implementation/evidence: research/v2-05-review-correction-result-20261013.md; research/v2-05-scripted-trace-example-20261013/.
- Ticket5 required corrections: research/v2-ticket05-review-20261014.md. P1 result: research/v2-05-p1-delivery-verification-20261014.md (43/43 scripted). P2 result: research/v2-05-p2-corrections-20261014.md (flyer_review_test 49/49 scripted).
- Scope details: research/social-media-flyer-v2-spec.md, load the relevant decision/acceptance section only.
- CODEX_NOTES.md is Codex's working agreement, not mandatory Claude startup context; relevant rules are summarized here.
- Archived notes and earlier research contain superseded directions. Never revive them over current scope or claim old pending-review status is current.
