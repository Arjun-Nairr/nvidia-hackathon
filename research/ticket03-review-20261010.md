# Ticket03 review, 2026-10-10

Two fresh isolated code-review agents evaluated Standards and Spec separately. Current-file review; no Git baseline. Codex independently verified the scripted image-path suite in a disposable project copy. No live inference, scraping, credentials or existing profile changes during this review.

## Standards

No substantive blocking finding. Image inspection is optional backend role eligibility, excluded from main and ungranted specialists; built-in arbitrary-path vision_analyze remains ineligible. Input accepts constrained IDs, bounds input bytes/transmitted dimensions, fully decodes and returns structured failures or a cohesive multimodal result. Current profile-creation guard rejects missing/outside-project HERMES_HOME. UI remains unchanged.

## Spec

Functional pass. Recorded live controls used neutral references without answer-bearing prompts and a fresh session after the pixel swap; outputs followed the new shapes/text. The existing Marketplace photo was reported under its source ID with uncertainty, and missing/corrupt IDs were not invented. Exact provider/model and development-only proof are recorded. No new implementation defect found.

Preservation caveat: Claude's test incident created a stray profile in the personal Hermes home, violating the isolation requirement historically. Claude reports deregistering it with Hermes profile deletion, which affected its reported gateway entry; an empty/default residual folder with locked state.db files remained. The current guard addresses the reproduced cause and passed the independent negative regression. Reviewers/Codex did not inspect personal state, delete the folder or stop any personal gateway. Do not describe this ticket as having had no outside-project effects. This incident remains disclosed follow-up, not an unresolved functional image-path defect.

## Independent verification

Codex ran the complete unchanged tests/image_path_test.py in .scratch/review-ticket03-57bd234c with synthetic credentials, localhost scripted model and private test profiles:31/31, exit0. Confirmed decoding, swaps, rejection paths, main/ungranted specialist exclusion, exact transmitted image bytes and honest fallback without vision declaration. The initial sandbox run passed18 pure checks but could not launch the existing Hermes CLI trampoline; approved execution with explicit installation/private-home paths completed successfully. No real login copied or model calls made.

Claude's live proof is one recorded run,6 model requests on openai-codex/gpt-5.6-terra,88.2s total. Codex inspected the harness and recorded outputs; did not rerun live inference. The initial8/10 harness result was rescored offline after correcting tool/hero-ID assertions; image observations themselves already matched controls. Other regression totals remain Claude-reported. Nebius/NVIDIA capability and general photo accuracy are not certified.

## Disposition

Ticket03 accepted for the development provider, with the disclosed isolation incident retained. Ticket04 can be scoped next: one saved listing draft from recorded evidence. Pixels are not retained in conversation history; ticket04 must persist observations with image/source ID and hash. No ticket04 implementation dispatched.

## Reviewed SHA256

- app/core.py:615EF2AF9C502E8F6760D67BB7B05D2997D83CBDE4E2CE985AEEAD48264F47E6
- app/hermes_plugin.py:8122AE2FD085958A5270ACC66A77E37F4FE1D9D18DA69C10DA7F4A2A815A92D5
- app/worker.py:8A244BE655626092A503062275DECDE15FA2960ED07480FD665569DFA2214F8E
- tests/image_path_test.py:E54AEFBBA47FBF0F4DFB0A76E98CAF51DAE4D74802B4B47501778007D60C2B2C
- research/image-inspection-live-result-20261010.json:8CA42D23D330A0F14F6FC722F0BC820B68F5727C0B68B9EE3F70456E8984F304
