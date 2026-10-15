# V2-05 scripted trace example (2026-10-13)

**SCRIPTED. Not real Gemini output, not a real visual review, not a design.** Produced by `tests/flyer_review_test.py` Part B (real server, real Hermes workers, HTTP chat API)
with a Gemini stand-in that returns SOLID control colours, a rule-based specialist whose content judgement follows the pixels it receives (strongly red = "wrong price"), invented ad
data and generated placeholder merchant photographs.

- `full-trace-scripted.json`
  - `b1`: acceptable first candidate: one generation, inspect, review (passed), finalize -> `agent_review_passed`.
  - `b2`: defective first candidate: review records a numbered defect -> ONE correction -> second inspection and review -> final = the corrected candidate. Holds the exact
    Gemini requests as received (image hashes in order: the original merchant photographs, then the previous draft as the last image; the text with the original facts and
    the numbered correction), the model-pixel log (mean colours of the images that reached the scripted model) and the full flyer record (both candidates, prompts, inputs,
    reviews, selection rationale, research link with the reach-gate state, history).
  - `b3`: defective second candidate: a third attempt is refused (`correction_limit_reached`); the final draft is `unresolved_issues` (an unapproved draft) with the defect listed.
- `first-candidate-defective.jpg`, `final-candidate-one-correction.jpg`: the two candidates of `b2` (solid control colours).
