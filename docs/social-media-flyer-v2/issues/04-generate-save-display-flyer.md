# V2-04 — Selected merchant photos produce one saved flyer

Status: BLOCKED.
Blocked by: V2-01; V2-02 Gemini contract and usable sample findings. V2-03 is not required for this slice: use explicitly labelled recorded ad references, never call them live. Real Gemini call needs separate authorization.
Parent: `research/social-media-flyer-v2-spec.md`, decisions2,5,7–8.

## Outcome
The social specialist selects product photos, writes a feature-informed prompt, invokes the configured Gemini tool and returns one valid saved/displayed flyer. Content status is UNCHECKED until05, not approved.

## Scope
- Backward-compatible multi-photo catalogue and registered asset selection, matching merchant/product facts. No arbitrary image paths/URLs or competitor-as-product substitution.
- Dedicated narrow Gemini tool with backend-bound company/agent/request/product/candidate IDs, stored prompt/context/input hashes, explicit configured model/auth and no hidden SDK generation retries.
- Add durable run/attempt/candidate/final-artifact persistence before dispatch. Initial-generation path only in this slice: second attempt rejected until05 introduces the reviewed correction path. Backend enforces the final two-attempt maximum and handles duplicate/concurrent/restart/unknown outcomes safely from the outset.
- File type/size/full decode/dimensions/hash gate; unreadable bytes never displayed as success. Registered managed output image and flyer list/detail/image read APIs; keys/signed URLs private, no traversal.
- Minimal chat/result card for saved image, unchecked status and errors; renderer consumes backend records. Retrieve with credentials unavailable and without inference.

## Acceptance
- Through specialist chat with scripted Gemini/local responses, chosen supplied image IDs and exact stored context reach the tool; one persisted candidate/flyer displays and retrieves unchanged after restart.
- Recorded references labelled; unknown/mismatched merchant assets rejected. Configured alternate product/merchant works without role-code changes; V1 single-image catalogue still works.
- Concurrent/duplicate/failed/unknown first generation reserves and consumes allowance durably; no automatic replay or silent second generation. Provider absence/refusal/corrupt file/storage failure explicit.
- Image/read API serves only managed registered files; UI never interprets model text as approval or hides unchecked status.
- If an authorized real generation is run, retain actual image/source/model/usage evidence; fake-model checks are not real Gemini proof. No agent content-review loop, posting or UI redesign yet.

## Completion evidence
Return one sample saved flyer or explicit blocker, selected input images, prompt snapshot, candidate status/hash, call accounting and read-after-restart results. Update ticket/index/HANDOUT. Preserve generated/evidence artifacts before any isolated-copy cleanup.
