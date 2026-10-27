# Nebius model fit — 2026-10-27

Follow-up: authenticated catalogue discovery and broader research found `nvidia/Nemotron-3.5-Super-VL`, a newer vision-language candidate. See [current recommendation](nebius-catalog-models-20261027.md). The text-only limitation below concerns **3 Super**, not **3.5 Super VL**.

## Verified facts
- Local secrets/local.env selects openai-codex / gpt-5.6-terra. NEBIUS_MODEL is nvidia/nemotron-3-super-120b-a12b; it is not the active provider. Read only these non-secret configuration fields.
- [Nebius announcement](https://nebius.com/blog/posts/nemotron3-super-now-available) explicitly describes Super as text-in/text-out, designed for tool calling and agent workflows. It cannot be assumed to consume our ad/flyer images directly.
- [Nebius cookbook](https://github.com/nebius/token-factory-cookbook/blob/main/models/nemotron/nemotron3-super-120B.md) documents the exact model ID, function calling and structured output. This is documentation evidence, not a Hermes integration test.
- [Current Nebius family page](https://nebius.com/services/token-factory/nemotron) also lists Nano Omni; account availability, exact serving ID, pricing and suitability were not established in this bounded check.

## Judgment and next action
Super is a plausible text orchestrator, not an established single-model replacement for our image-consuming agents. Earlier plans to test image input on this exact model were too broad: documented modality already exposes the mismatch. Before paid testing, check the current serving catalogue and official prices for a suitable vision-capable option, or deliberately select separate reasoning and vision models. No final model choice or budget estimate is justified yet. Keep the subscription active; no paid calls or configuration changes made.
