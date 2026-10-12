# Workflow check: grilling to specification

Checked 2026-10-10. This note verifies workflow guidance; it is not the Marketplace implementation spec.

## Documented facts
- Matt Pocock's current [to-spec](https://github.com/mattpocock/skills/blob/main/skills/engineering/to-spec/SKILL.md) synthesizes conversation plus inspected codebase state into problem/solution, user stories, implementation decisions, testing decisions and exclusions. It favors existing high-level test interfaces over new internal seams.
- Anthropic's [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents), originally December 2024 and now linking to current Managed Agents guidance, recommends starting simple, measuring outcomes and increasing complexity when useful. Treat it as longstanding guidance, not a recent release.
- Anthropic's April 2026 [Managed Agents architecture](https://www.anthropic.com/engineering/managed-agents) separates durable sessions, model/harness execution and tools behind replaceable interfaces. This supports distinguishing these responsibilities in a spec, not copying their infrastructure into our prototype.

## Codex judgment for this project
Use one compact specification for the next useful outcome, with sections for merchant/catalogue input, main customization, specialist decision loop, Marketplace tools, actual image inspection, evidence/output persistence, API/UI contract and acceptance. Do not commission separate broad specs for hypothetical future roles or deployment.

Draft known decisions now and label unresolved live Marketplace inventory and runtime/model image support explicitly. Validate those with a small spike before locking the dependent technical decisions. Finish/review the existing onboarding increment separately.

Then implement one vertical slice via a scoped inline Claude prompt: manual request through agent-led research to one sourced listing concept, evaluated by Arjun. Add draft count, monitoring or other capabilities only after that slice works. Formal tickets are optional if the task exceeds one bounded prompt. There is no source proving a universally smartest workflow; this is a reasoned fit to our constraints.
