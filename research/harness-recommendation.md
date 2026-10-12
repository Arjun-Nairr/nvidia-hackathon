# Harness recommendation — 2026-10-09

Recommendation pending Arjun's acceptance and a working integration milestone: Hermes with independent profiles for persistent merchant specialists.

## Evidence

- [Hermes profiles](https://hermes-agent.nousresearch.com/docs/user-guide/profiles/): distinct configuration, memory, sessions, skills and state per profile. A separate conversation is not a separate profile. Profiles separate state, not OS-level capabilities.
- [Hermes delegation](https://hermes-agent.nousresearch.com/docs/user-guide/features/delegation/): task children have fresh conversations; current documented leaf children cannot call memory or clarify, inherit enabled toolsets, and are not resumed after process restart. Do not equate delegate_task children with persistent user-controlled product specialists.
- [Hermes FAQ](https://hermes-agent.nousresearch.com/docs/reference/faq/): supports OpenAI-compatible providers and programmatic AIAgent use. Nebius/NVIDIA integration is a plausible fit, not yet tested in this project.
- [OpenClaw multi-agent source](https://github.com/openclaw/openclaw/blob/main/docs/concepts/multi-agent.md): persistent agents with separate workspaces/configuration/session stores. Viable alternative; not rejected as incapable.
- [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness): plugin-centric harness, developer preview. Less compelling for this first increment than using a runtime Arjun already has experience with. This is a delivery judgment, not a comparative benchmark.

## Proposed first integration

Claude should configure a fresh project-specific main profile, connect an NVIDIA model via Nebius, and prove one normal message/tool round trip. Then implement create_agent as an application-owned operation that creates a blank specialist profile, writes generated role/context/skills and permitted tool configuration, starts or resumes the specialist, and exposes it to the UI. Existing personal/trading/recovery profiles should not be cloned or modified by default.

Claude Code is the implementor; Hermes runs the product agents. Claude need not keep a manually driven interactive terminal session open for each specialist. Exact hosting interface should be chosen from the installed version's supported APIs during the integration task.

No install, runtime start, or implementation performed for this recommendation.
