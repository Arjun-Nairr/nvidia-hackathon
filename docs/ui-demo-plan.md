# Demo workspace UI — confirmed plan

Confirmed by Arjun 2026-10-28 after grilling. Covers roadmap 08+09; implementation has not started. This approved plan is sufficient input to to-tickets; no separate speculative architecture spec needed.

## Outcome
Make the existing single-operator prepared demo simple to use and show. Main creates business-customized specialists; the operator chats directly with each. Preserve existing backend boundaries, task/accounting safeguards, persistence and Supabase logging.

## Confirmed interaction
- Professional light workspace: warm white, charcoal, muted emerald. Visual reference: https://variant.com/shared/363db375-32a3-4858-91df-9a9859340e01?t=1793185462076 . Recreate appearance against existing APIs; no Variant source export required. Do not copy fictional logistics, account, inventory, PDF/export/editing controls or invented metrics from the reference.
- Small agent sidebar, one central conversation, no permanent right inspector. Only created specialists appear; main is always available. No uncreated role placeholders.
- Website entry, business summary and questionnaire stay in the same chat-style screen, using focused answer cards; preserve backend chat gate until onboarding completes. The prepared snapshot is not a live website fetch.
- Newly created specialist has a short introduction showing its business-specific goal, relevant business context and capabilities in plain language. Never automatically create both roles.
- Research, listing drafts and flyers appear within their originating chat. Click a flyer to enlarge. No separate editor.
- Replies are short and result-first. Internal IDs, raw tool payloads, skill contents, configuration dumps and repetitive disclaimers do not appear by default. Retain diagnostics in existing local/Supabase records.
- Relevant results may have one clean, collapsed Sources & details section with source links and concise review information. Do not replace unsupported claims with invented explanations or statistics.
- Label image output Generated flyer; automated review is not human approval. Show known issues; do not claim no defects merely because a review passed.
- Keep useful partial results after failures with a short truthful explanation. Do not invent a partial result or automatically replay paid actions.
- Block messages to the selected busy agent; retain switching to other agents. Preserve duplicate-send protection, per-agent drafts, reconnect/unknown-completion handling and persisted working state. No interrupt, queue or invented percentage/step progress.
- Existing Customize capability stays behind the specialist menu using its current explicit one-turn authorization. No new form or automatic natural-language settings-persistence system. Ordinary chat does not gain config-changing authority.
- Existing business details/settings can be revealed on demand; no new account system. Meaningful failures/required actions remain visible.

## Exclusions and separate follow-up
- No in-app reset, agent deletion, new-conversation backend, flyer redesign loop, additional roles, provider switch, paid test run, tracing platform, framework migration or broad cleanup/refactor in this UI slice.
- Arjun needs a convenient clean launch for repeat personal testing. Assess a separate bounded setup task; no existing safe reset API or runtime selector. Preserve OAuth credentials and consumed research/ad/flyer budgets/evidence; never repurpose scripts/reset_demo.py, renew scopes or wipe app.db. Do not claim fresh launch solved by UI changes.
- No guaranteed agent output quality or repeatability is implied by the UI.

## Implementation seams and checks
- Current UI is app/static/index.html (inline CSS/JS); server.py supplies existing APIs. core.py and roles.py supply generated instructions/role foundations. Inspect worker behavior only if instruction refresh is needed.
- No preparatory architecture refactor identified as necessary. Small asset extraction is optional only when it reduces this implementation's complexity.
- Verify onboarding through unlock, creation through sidebar introduction, existing specialist customization, busy/duplicate/switch/reconnect states, and saved result rendering after reload with isolated scripted fixtures. Reuse saved licensed flyer for visual inspection; no new paid calls.
- Source links and model text must be rendered safely. Associate results with a trusted request/message identity, not merely newest artifact or text-parsed IDs. A small additive API change is allowed if required; preserve legacy transcript readability without guessing associations.
- Inspect desktop and narrow viewport, keyboard focus, contrast, scroll/composer placement and image loading. Run appropriate existing regressions plus lint once per completed code batch.

## Approved decomposition — local tickets published
1. Workspace + onboarding + creation + existing Customize controls. Blocked by: none.
2. Inline result cards + concise agent output + sources/partial failure presentation. Blocked by: 1.

Arjun approved the two-slice breakdown 2026-10-28. Local ticket index: .scratch/ui-demo/INDEX.md (ignored/uncommitted); atomic issues: .scratch/ui-demo/issues/01-workspace-and-agent-flow.md and 02-inline-results-and-replies.md. UI-01 is ready-for-agent; UI-02 is blocked by UI-01 acceptance. No GitHub issues or implementation created. Each slice delivers working visible behavior with necessary API/instruction changes and focused checks, not separate CSS/backend/test tickets. Execute in separate fresh/compacted contexts. Fresh-testing setup is tracked separately, not silently included.
