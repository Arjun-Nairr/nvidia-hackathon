# Hackathon demo scope

Updated 2026-10-25 after project-wide grill-with-docs and final consistency review.
This consolidates Arjun's confirmed decisions. It is a product scope, not an implementation specification or permission to run paid services.

## Purpose and audience
- Primary showcase: main understands a business and creates meaningfully customized, bounded specialists that perform useful tasks.
- One prepared home-textile business example; Arjun is the sole demo operator. No external-user onboarding, customer accounts, multi-business hosting or production-authentication work.
- High advertising quality/commercial-effectiveness metrics are not the central claim. Real execution, meaningful customization, honest outcomes and basic usability still matter.
- Exactly two available roles, with at most ONE instance of each: market analyst and social-media specialist. Operator may activate either or both; never auto-create both just because they are available.

## End-to-end workflow
1. Start with structured website-link entry. Free-form chats remain unavailable during onboarding; main still runs internally to process the onboarding steps.
2. The supplied URL identifies the prepared website snapshot. Main reads basic business source information using suitable predefined tools/research fundamentals, scoped to this business. No live website fetching or independent company discovery is required during presentation; do not claim the saved source was fetched live.
3. Main derives a brief business understanding and a batch of about5-10 scoped MCQs from that source. Every question has a write-in alternative. Include an optional correction box for wrong/missing information in the summary. Do not preload the derived profile, answers or agent decisions and present them as live inference.
4. Present summary/questions in the main panel with the normal composer blocked. Operator answers the form. Main combines website information with explicit corrections/goals into structured shared business context; preserve the distinction between source-derived facts and operator input.
5. Complete onboarding when that context is ready, unlock main chat, and explain relevant available specialist roles and why they fit. Operator chooses/requests a specialist; questionnaire submission alone is not authorization to create every recommendation.
6. Main configures the requested semi-prebuilt specialist: objective, response style, business-specific instructions, relevant context, minimal eligible tools and any useful additional skills. Backend validates and creates the Hermes profile, role foundation/baseline skills, permitted tool grants and private memory.
7. Operator inspects the created setup and chats directly with the specialist for tasks and customization. A request for an existing role reuses/customizes that agent, not another instance. Main does not coordinate ongoing specialist tasks or require analyst-to-social handoffs.
8. Direct task requests authorize mostly autonomous execution within configured limits. Do not ask permission at each ordinary tool step; unrelated actions, posting and limit changes remain outside scope.
9. Show honest outputs/status and retain execution evidence. Brief live activity and its presentation belong to later UI/QoL work, not speculative orchestration infrastructure.

## Customization and role boundaries
- Predefined: role purposes/foundations, potential tools, baseline skills, memory lifecycle and enforced permissions/action limits.
- Main customizes within that foundation; it cannot invent executable tools, unrestricted agents or privileges.
- Additional custom skills are OPTIONAL: create them for reusable business-specific procedures. Objectives/tone belong in instructions when sufficient; do not manufacture files to satisfy a skill count.
- From its own chat, each specialist can accept requested changes to objective, response style, business-specific instructions, custom skills and eligible-tool selection. Backend validates/applies persisted configuration changes. Editing memory alone is not a persisted grant/objective update.
- Fixed role/tool boundaries and shared business facts cannot be changed by specialist customization. Necessary tool dependencies must remain usable; minimal means sufficient, not an arbitrary minimum tool count.
- Market analyst: competitor products/prices/listings, differences and recommendations about products/offers. Current evidence is narrower Marketplace research/listing drafts; do not claim broad intelligence already exists.
- Social-media specialist: competitor image-ad research and promotional creative. Retain the established US Facebook Ad Library image-ad/flyer scope, distinct from Marketplace; Instagram, video and news remain excluded.
- Retain honest reach gating: no comparable documented reach means no reach ranking, not a fabricated proxy. Retain one initial Gemini generation plus at most one correction after actual-image review, two dispatched attempts total; failures/unknown dispatches count and are not silently replayed.

## Context and memory
- One shared business-context store; reuse existing company.json rather than duplicate it in another Markdown profile. Main and each specialist retain their existing separate Hermes memory files.
- Among agents, only main may change shared business context. Specialists keep local preferences/task learning private and suggest shared corrections through main.
- Current shared business facts take precedence over conflicting private notes. Specialists may correct their own conflicting notes, never silently redefine shared company facts.
- No routine main-led memory cleanup, shared private memories, vector database or new memory-management framework.
- Source website material, catalogue assets, configuration, agent memory and execution logs are different records. A website does not establish operator goals or unsupplied product facts such as price/material/size.

## Demo inputs and runtime
- Prepare slow inputs: saved website source, catalogue and product photographs. Main still interprets the website and asks requirements during onboarding.
- Already prepared: ignored demo/v2-06-inputs/ has three licensed Met quilt photos, provenance, catalogue.json and company.json for Northloom Demo Studio; USD79 is explicitly an arbitrary test price, not a retail offer/valuation. Do not infer ownership, inventory, new condition or museum endorsement.
- Still missing: a website snapshot aligned with the prepared business/catalogue. Existing catalogue/price preparation is not evidence of website-driven onboarding. Prepare a coherent, honestly labelled example before presenting that flow.
- Use the existing project login/runtime for the hackathon path, preserving existing data. No second demo login or authentication redesign is required. Detailed safe setup/backup steps need a scoped implementation plan.
- Keep the isolated regression tests and their evidence; the elaborate isolated LIVE runner is not a required demo route. Do not expand, delete or repurpose it without a specific task.
- Development reasoning remains the configured ChatGPT subscription provider. Gemini makes images. Nebius/NVIDIA compatibility is still required verification for the intended submission; billing/provider switch deferred by Arjun, not silently dropped.

## Execution evidence and evaluation
- Basic Neon logs are REQUIRED for the finished proof of concept; use existing local traces for initial tests. Neon stores execution evidence, not business/agent memory.
- Capture backend-observed meaningful steps: source/profile/questionnaire, requested/validated/applied configuration, actual tool calls/results, generation/review/final/error. Link run/agent identities and timestamps; record available timing/usage without inventing missing metrics.
- Concise decision rationale is a model claim, not hidden chain-of-thought or proof a tool executed. Do not log secrets or raw image payloads; use artifact references/hashes.
- Minimal evaluation design is delegated to Codex: inspect initial customization against the answers, then change requirements and verify meaningful persisted configuration/behavior changes on the SAME specialist. No duplicate agents or commercial-effectiveness study required.
- Representative tasks must really execute; scripted plumbing is not live inference proof. Real output must be judged by Arjun. This scope authorizes no paid tests by itself.
- Broader external review remains an agreed later goal; reviewer/tool and external uploads are not authorized here.

## Built versus still to implement
- Existing: company context, main-only creation, role foundations, eligible-tool validation, private Hermes profiles/memory, persistent workers, local SQLite transcripts/artifacts and scripted analyst/social generation/review flows.
- Unbuilt: website-snapshot reading, generated MCQ/form state, onboarding-wide backend chat gate, specialist-chat persisted configuration/grant updates, Neon integration.
- Needs change: creation validation currently requires custom skills; instance uniqueness currently checks name, not one-per-role. Main's prompt currently collects user-stated company facts; website-derived context needs an explicit source-aware intake path.
- Desired analyst responsibility is broader than its current tools/evidence. Assess the smallest useful extension; do not rebuild the specialist or call that extension done.
- UI has not been redesigned; actual Gemini/Responses image-review quality and Nebius/NVIDIA behavior remain unverified.

## Boundaries and next step
- No extra roles, customer accounts, document/PDF/OCR ingestion, live website discovery, cross-specialist task coordination, posting/contact/account writes, schedules, training/fine-tuning, or speculative infrastructure.
- Operator may freeze nonessential aspects while stabilizing the base. This does not authorize unrelated expansion or disposal of evidence.
- Next: reconcile these gaps into a compact updated specification/implementation plan when Arjun asks, then scoped Claude prompts. Do not automatically dispatch a build, switch providers, change runtime data, commit or push.
- This scope governs new project-wide decisions. Earlier research/social-media-flyer-v2-spec.md and docs/social-media-flyer-v2/ remain useful V2 implementation/evidence references; conflicting historical demo-login, public-onboarding and extra-role proposals are superseded. Do not delete or silently rewrite their historical evidence.
- Shared context: HANDOUT.md = current implementation state; this file = agreed product scope; CONTEXT.md = glossary. Interview history is preserved at .scratch/context-history/PROTOTYPE_SCOPE-before-project-lock-20261025.md, not default startup context.
