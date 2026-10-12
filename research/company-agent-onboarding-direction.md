# Direction under discussion: creating company-specific agents

2026-10-09. Discovery only; no project selected or implementation authorized.

Arjun now proposes an interface that identifies user requirements, hands work to one or more agents, and creates appropriate skills/context/memory. He asks whether to build our own general version or a twist. Preserve prior desire for substantial agent discretion; do not default to a classifier and fixed tool chain.

## Verified recent reference points

Dots documentation describes persistent agents, background agents, context and ongoing work. It does not establish that each chat automatically creates a new specialist agent or separate memory system. [Official documentation](https://learn.chatgpt.com/docs/dots).

Grok Bot's September 11 guide describes chat-configured bot instructions, persistent computers, specialist chains, and a case of turning an existing application into skills/plugins/MCP components from within the bot. It describes user-created specialists; do not universalize this into automatic agent creation per request. [Grok guide](https://x.ai/bot/guides/grok-bot-101).

Meta's September 8 engineering account explicitly describes subagents, building tools and editing itself. It also says Meta engineers authored connector skills. This supports the broad adaptation direction but not the exact proposed pipeline. [Muse engineering](https://research.meta.ai/blog/security-and-safety-for-ai-agents-our-approach-with-muse).

## Judgment

A general Dots/Muse/Grok competitor is likely an excessive scope for this student hackathon and has weak differentiation if it only generates configuration files. A stronger hypothesis is company-specific onboarding that produces a persistent, executable specialist: understand responsibility, inspect authorized company context, establish appropriate access and memory, perform real work, capture reusable procedures where beneficial and adapt over subsequent tasks.

The interface should decide whether to reuse an existing agent, delegate a temporary task, or create a lasting role. Do not create a new persistent agent, skill file or memory subsystem for every chat by default. Generated skill files are proposed instructions; usefulness must be established through task execution. No auto-granted privileges, credentials, or ability to certify its own expanded authority.

Potential twist: company owns and can inspect/export its role configuration, domain context and learned procedures rather than relying solely on a vendor-managed personal identity. This is a design hypothesis, not verified novelty. Portability alone may be an engineering feature rather than a sufficient user problem.

Potential product demonstration: company provides an ongoing commercial responsibility, its documents and connected test systems; system configures a specialist, performs the first work, then handles a changed request using relevant context and revised procedures. Success is less owner setup/re-explanation and actual work delivered relative to a basic agent with a static company prompt. Avoid making completion-claim verification the product; evaluation supports the application.

Conceptual overlap with Second Me should be acknowledged, but no implementation status, reuse, licence change or publication permission is inferred. Industry selection and first demonstration responsibility remain open.
