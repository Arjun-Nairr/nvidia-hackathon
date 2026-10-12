# Matt Pocock workflow: verified guide and project adaptation

Checked 2026-10-10 against upstream primary sources. No plugin updates or workflow infrastructure installed.

## Version distinction
Matt's official [skills hub](https://www.aihero.dev/skills) lists upstream v1.3 on October 5, 2026. His [v1.3 guide](https://www.aihero.dev/skills/skills-changelog-v13-implement-spec-pr-retro-and-glossary-md) describes the release changes and notes the full changeset is v1.3.1. Our installed matt-skills-curated package is v1.1.0, maintained by Mamdouh Aboammar and adapted from an upstream snapshot. Package version and upstream version are different namespaces; installed files must not be represented as unmodified upstream v1.3.

## Documented roles
- Idea discussion/research is problem discovery: decide whose work matters and whether the needed capabilities/data are real. Use research for unresolved technical facts, not a mandatory ritual for every edit.
- [grill-me](https://github.com/mattpocock/skills/blob/main/skills/productivity/grill-me/SKILL.md) delegates to grilling. It aligns on an idea without requiring domain-document writing.
- [grilling](https://github.com/mattpocock/skills/blob/main/skills/productivity/grilling/SKILL.md) is the shared interview discipline, not a separate mandatory phase after grill-me.
- [grill-with-docs](https://github.com/mattpocock/skills/blob/main/docs/engineering/grill-with-docs.md) combines grilling and domain-modeling for codebase decisions: resolved terms go to GLOSSARY.md; qualifying hard-to-reverse, surprising tradeoffs go to ADRs. It does not automatically persist every answer; the spec/handout remains necessary for requirements.
- [to-spec](https://github.com/mattpocock/skills/blob/main/docs/engineering/to-spec.md) records agreed decisions for work spanning sessions. Small clear changes can go directly to implement. The spec should not silently invent user decisions.
- [to-tickets](https://github.com/mattpocock/skills/blob/main/skills/engineering/to-tickets/SKILL.md) decomposes into bounded complete working slices with blocking relationships. This is the ticket-authoring step, not implement.
- [implement](https://github.com/mattpocock/skills/blob/main/skills/engineering/implement/SKILL.md) executes scoped work, uses TDD where appropriate, verifies and reviews. Upstream includes committing; project instructions govern whether Git/commits are authorized and available.
- [writing-for-agents](https://github.com/mattpocock/skills/blob/main/skills/productivity/writing-for-agents/SKILL.md) shapes clear agent-facing prompts/context; it supports handoffs rather than adding a serial project phase.
- [code-review](https://github.com/mattpocock/skills/blob/main/skills/engineering/code-review/SKILL.md) uses separate parallel standards and spec reviewers against a pinned diff. Baseline code smells are labeled judgments, distinct from breaches of documented rules. No Git here means any current review must explicitly disclose file/snapshot scope rather than pretend it is a pinned diff review.
- [retro](https://github.com/mattpocock/skills/blob/main/skills/engineering/retro/SKILL.md) studies actual sessions and suggests improvements to checks, navigation, instructions and information access. The v1.3 guide says it is human-in-the-loop and warns against automatic changes. It is not another feature-review pass.
- v1.3 adds implement-spec for autonomous whole-spec execution, pr for reviewable PR bodies and retro. implement-spec is optional, not necessary for the manual Codex/Claude collaboration.

## Codex judgment for Arjun's project
Use problem discovery -> one appropriate grilling mode -> compact spec for the multi-session milestone -> to-tickets -> inline handoff using writing-for-agents plus implement -> Claude implements/verifies -> independent two-axis review -> fix material findings -> evaluate a concrete output. Use retro selectively after milestones or recurring friction, with Arjun choosing proposed environment changes.

Codex researches, plans, prepares tickets/prompts and reviews; Arjun chooses scope and evaluates usefulness; Claude implements. Manual dispatch remains agreed. No requirement to adopt unattended implement-spec, cloud trackers, broad ADR generation or elaborate infrastructure.

Benefits are a reasoned fit: explicit decisions, bounded contexts, checkable results and independent review can reduce misunderstandings. Sources describe intended practice, not a controlled proof of productivity or correctness. Failures can still arise from vague requirements, missing facts, bad checks and AI review errors. Do not turn the full chain into a ceremony for tiny fixes.

Current project status: Marketplace grilling and compact spec exist; onboarding implementation completion remains unconfirmed. Next is review onboarding evidence, validate Marketplace/vision access and use to-tickets for the actionable slices. Saved research/spec files remain references; implementation prompts are delivered inline.

## Split Codex/Claude roles: additional check, 2026-10-10
The skills are not inherently single-agent-only. Upstream [handoff](https://github.com/mattpocock/skills/blob/main/skills/productivity/handoff/SKILL.md) explicitly transfers context to another agent; [implement-spec](https://github.com/mattpocock/skills/blob/main/skills/engineering/implement-spec/SKILL.md) coordinates implementer/merger subagents; code-review already uses independent reviewers. Upstream [ask-matt](https://github.com/mattpocock/skills/blob/main/skills/engineering/ask-matt/SKILL.md) describes fresh implementation sessions working from tickets and two-way handoffs for experiments. These support split responsibilities without a special Codex-to-Claude product integration.

Relevant additions/clarifications:
- Handoff is the missing explicit discipline: concise next task, pointers to spec/ticket/state, prerequisites, evidence and suggested skills. Our user-requested persistent HANDOUT plus ticket/prompt largely performs this job. Preserve the requested project-local handout; do not create redundant temp handoffs for every ticket solely to copy upstream packaging.
- Claude should actually load implement/TDD where installed, not merely be told that Codex consulted them while writing a prompt. Codex's writing-for-agents governs handoff quality; implementation discipline must apply where code is executed.
- After each meaningful completed ticket, Codex reads updated state and inspects actual changes/test evidence. Use code-review for material code changes and recheck fixes; do not defer all independent review until the complete version. Small docs-only changes do not require two reviewers by default.
- implement-spec is optional autonomous ticket dispatch, not a way to automatically communicate with a separate Claude Code app/session. It would change our manual dispatch arrangement and require Git/worktrees; it is not recommended for this small sequential milestone.
- Retro should inspect Claude's actual session/log evidence for implementation process problems; a completion summary alone misses failures and repeated attempts. Teach follows reviewed working behavior. Architecture review is optional when a concrete structural problem appears, not another mandatory end-of-ticket ritual.

State update: onboarding has since completed according to Claude; Codex independent review found two material defects and issued corrective ticket01. The five local tickets exist under .scratch/marketplace-listing. Earlier state paragraph above records the situation at the initial guide check, not current implementation progress.
