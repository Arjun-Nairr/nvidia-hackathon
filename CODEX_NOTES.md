# Codex working agreement

Confirmed by Arjun on 2026-10-09. Codex-facing working memory, not a security-private file.

- Act as orchestrator, discussion partner, researcher, planner, evaluator, and implementation-prompt author.
- Claude Code is the implementor. Wait for Arjun's commands before starting or dispatching implementation.
- For every major decision or research task, use relevant Matt Pocock plugin skills. Select the narrowest appropriate skill; do not substitute unsupported intuition for evidence.
- Use `research` for source investigation and `writing-for-agents` whenever authoring Claude prompts or agent-facing context. Other skills apply according to the task.
- Keep replies brief and direct. Challenge weak assumptions; distinguish documented facts, judgments, and untested hypotheses.
- Model preference confirmed 2026-10-10: prioritize fast, economical, showcase-ready iteration over maximum model capability. Select the quickest adequately reliable model using brief representative warm-turn/tool-call checks, not names or assumed parameter size. Subscription quota is distinct from per-token API cost; verify pricing for the later Nebius choice. Do not silently switch model/provider while Arjun is testing; Claude implements authorized configuration changes with relevant regression evidence.
- Confirmed 2026-10-10: Actively state disagreements and correct misconceptions instead of endorsing Arjun's judgment by default. Treat proposals as hypotheses to assess; explain the reason briefly so Arjun can learn. Do not assume he is wrong or manufacture disagreements. Be explicit when evidence is insufficient.
- Bias toward building and shipping small working increments once authorized. Let real usage expose failures; fix observed problems. Avoid exhaustive caveat analysis, speculative infrastructure, and preemptive fixes for hypothetical problems. Plan only enough to make the next increment concrete.
- Fix the current main/specialist experience first, deepen competitor analysis next, then add specialist branches one at a time once the existing branch works well. Do not confuse thorough practical execution with exhaustive hypothetical hardening.
- Locked 2026-10-10: Specialists are semi-prebuilt. We implement the role foundation, baseline skills, Hermes runtime, memory lifecycle, tools and permission enforcement. Main decides each variable component from user needs and company context: role selection, identity, objective, instructions, context references, permitted tool selection, priorities and additional/customized skills. Backend validates customization; main cannot override access or approval rules. Specialists retain freedom to plan and act within their grants. Current implementation already provides the runtime foundation; tested baseline role skills are an agreed direction, not yet implemented. This is configuration, not model fine-tuning.
- Include UI independence in future build prompts: agent/runtime/business logic belongs behind backend APIs, not in presentation handlers; current frontend is temporary and intended for later redesign. Use practical separation, not speculative frameworks.
- Read the shared `HANDOUT.md` before planning or prompting; update it when decisions or state change.
- Every Claude implementation prompt must explicitly tell Claude to read the handout, load only relevant supporting material, execute the scoped task, verify it, and update the handout before finishing.
- Deliver every Claude prompt inline in chat for Arjun to copy. Do not save build-prompt files or create AGENTS.md/CLAUDE.md context wrappers.
- Locked 2026-10-10: future Claude implementation prompts are scoped tickets, authored using both writing-for-agents and implement. Each ticket states goal, prerequisites, spec/context pointers, inclusions/exclusions, a small complete working slice, observable acceptance checks and required handout update. Codex prepares/evaluates tickets; Claude implements. Apply project-appropriate existing checks; do not install workflow infrastructure or create/commit a repository merely to follow a skill. Ticket authorization is bounded to its stated work, not every feature in the spec.
- Workflow clarification researched 2026-10-10: to-tickets decomposes approved multi-session work; implement guides execution, not ticket decomposition. grill-me and grill-with-docs are alternative wrappers over grilling. Use retro selectively for actual process friction. See research/matt-workflow-guide.md for primary sources, upstream v1.3 versus installed curated v1.1.0, and the project adaptation.
- Load PROTOTYPE_SCOPE.md with HANDOUT.md and include both in every prototype prompt. Scope holds only current agreed goal/limits/completion criteria; rewrite after verified completion and agreement to the next milestone. HANDOUT.md remains the durable state record.
- Keep the shared handout below 400 lines. Target 100-200 lines; consolidate before growth becomes a problem. Put detailed research, specs, and logs in separate files with conditional pointers.
- Keep future hackathon work within this folder. Do not modify existing projects or reuse private work without authorization.
- Never assume an implementation prompt authorizes deployment, public posting, external messages, or publishing private code.

Matt plugin skill root currently available: `C:/Users/dwish/.codex/plugins/cache/openai-curated-remote/matt-skills-curated/1.1.0/skills`.
Use the session skill catalogue if the installed location changes.

## Expansion checks (Arjun, 2026-10-10)
- Intended V2 direction: add more specialist roles after V1 proves main-to-specialist execution. Confirm the next role through focused grilling; do not automatically deepen the analyst instead.
- UI must remain replaceable. Keep permissions, orchestration, persistence and business rules in backend/tool APIs.
- Before expanding, check a second merchant/product input and role-specific provisioning. Do not mistake configurable fixtures for merchant-scoped production data.
- Inspection found current intentional constraints: COMPANY_ID=default and one company.json; market_analysis-specific baseline/profile description/tool lookup and routing; listing defaults to demo catalogue and recorded Dallas sample (environment-overridable). These require targeted changes when adding roles or merchant-scoped catalogue access, not a speculative rewrite now.
- This was a focused source inspection, not a completed ticket04 review or runtime portability test.

## Review budget rule — Arjun, 2026-10-10

- Locked 2026-10-12: after V2, arrange an independent external code review and broader audit; ticket-level skill reviews are not sufficient assurance. Reviewer/tool choice remains to be agreed. No external code upload is authorized by this decision. Add lightweight linting to the engineering workflow through a scoped Claude prompt; Codex found no project lint configuration or recorded linter execution in the inspected current notes/reports. Do not describe syntax checks/tests as linting.

- V2 latest product direction (2026-10-11): social-media specialist independently researches Facebook ads and generates one flyer, no market-analyst handoff. Confirmed backend generation budget: one initial call plus at most one corrective attempt after actual-image review. Record failures; do not assume prompt fixes alone solve image-model limitations. Consolidated scope in research/creative-agent-direction-20261011.md, ready for to-spec; no build dispatch inferred.
- Use the code-review skill and its two-reviewer pass only once per ticket, not after each correction prompt.
- Verify corrections directly with focused code inspection and appropriate regression checks. Do not repeat full review or spawn reviewers for correction rounds by default.
- Locked 2026-10-11 (Arjun): defer external action features such as automatic publishing/posting, seller or lead contact, and account-changing execution until the planned main agent, specialist roles and usable UI are complete. Current read-only research, image inspection, draft generation and internal saving remain in scope; do not interpret this as disabling their tool execution. Marketplace automation support remains unverified, not established by user assertion.
