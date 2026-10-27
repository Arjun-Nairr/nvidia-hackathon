# Nebius model decision for Hermes ecommerce — 2026-10-27

## Recommendation (engineering judgment)

First evaluate **`nvidia/Nemotron-3.5-Super-VL` as the one main model**. It offers the required NVIDIA contribution through planning/tool selection and image understanding, while Gemini continues generating flyers. This is the smallest architecture to validate before October 30. The existing app shares one provider/model across profiles; a split route would add implementation and verification work. Public documentation supports this choice, but does **not** establish successful Hermes execution.

Fallback: **`nvidia/Nemotron-3_5-Lightning` for text orchestration plus Super VL as an explicit image-inspection tool**. Use only if a measured issue justifies the extra route. Passing extracted visual evidence back to Lightning avoids depending on Lightning accepting images. This is a proposed architecture, not a current app capability.

## Verified public facts

Rates below are USD per **million** input/output tokens. Exact ID spelling and capitalization matter.

| Candidate serving ID | Documented role / compatibility | Official input / output rate | Decision |
|---|---|---|---|
| `nvidia/Nemotron-3.5-Super-VL` | Nebius explicitly describes visual understanding, reasoning and tool use; official sample uses this exact ID | **$0.30 / $0.90** | First candidate; [Nebius October 16 release](https://nebius.com/blog/posts/three-new-open-weight-models-from-us-companies-give-builders-more-choice) |
| `nvidia/Nemotron-3_5-Lightning` | Agentic reasoning and tool use; public endpoint; no image-understanding claim established here | **$0.06 / $0.24** | Text fallback; [Nebius Nemotron model page](https://nebius.com/services/token-factory/models/nvidia-nemotron-models-inference) |
| `nvidia/Nemotron-3-Ultra-550b-a55b` | Public reasoning/tool-use candidate; no image-understanding claim established here | **$1.00 / $3.00** | More expensive; unnecessary without evidence; [Nebius Nemotron model page](https://nebius.com/services/token-factory/models/nvidia-nemotron-models-inference) |
| `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | Scheduled serverless retirement November 9 | Not independently verified in this research | Avoid new adoption; [official deprecation notice](https://docs.tokenfactory.nebius.com/model-deprecations-november-2026) |
| `nvidia/nemotron-3-super-120b-a12b` | Text tool-use candidate; scheduled serverless retirement November 9 | Not independently verified in this research | Prefer its recommended Super VL replacement; [official deprecation notice](https://docs.tokenfactory.nebius.com/model-deprecations-november-2026) |

NVIDIA's [Super VL BF16 model card](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-BF16#input) documents text/images/video input and text output. Its [API examples](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-BF16#api-client) include `image_url` data URLs and an inventory function-call cycle. The model is released under OpenMDW 1.1. These establish model capability, not the Nebius endpoint's precise serving configuration or Hermes compatibility. NVIDIA's weight repository name is **not** the Nebius serving ID.

Use Nebius's documented global base URL **`https://api.tokenfactory.nebius.com/v1/`** from its [quickstart](https://docs.tokenfactory.nebius.com/quickstart). Public endpoints can change processing region; a region-specific URL can stop working, per [public-endpoint documentation](https://docs.tokenfactory.nebius.com/public-serverless).

Nebius describes OpenAI-style tool schemas and `tool_choice="auto"` / explicit function selection. Applications execute requested functions and return their results; the model does not execute them itself. This generic interface description does not prove every model/parser supports every Hermes message shape. [Function-calling documentation](https://docs.tokenfactory.nebius.com/ai-models-inference/function-calling).

Do not substitute historical catalog entries: **Nano Omni** and **Qwen2.5-VL-72B** left serverless August 31; there is no automatic rerouting. [August notice](https://docs.tokenfactory.nebius.com/august-2026-deprecation-notice). **Qwen3.5-397B-A17B** retires November 9, with Qwen3.8-27B recommended instead; replacement listing alone is not verification of its modality/tool compatibility. [November notice](https://docs.tokenfactory.nebius.com/model-deprecations-november-2026).

## Local evidence and remaining compatibility gate

The coordinating agent reports authenticated model discovery returned all five NVIDIA IDs above, plus Qwen3.8-27B, Qwen3.5-397B-A17B and Gemma3-27B. Discovery proves listing for the account, **not successful inference, image/tool behavior, credits, or billing**. This research agent made no inference requests, accessed no keys, and changed no configuration.

Local source independently confirms that [model selection](<C:/Users/dwish/Documents/Codex/Nebius NVIDIA Global AI Hackathon 2026/app/core.py:1076>) reads `LLM_MODEL`; it can override `NEBIUS_MODEL`. An isolated Nebius test therefore needs an explicit correct `LLM_MODEL`. Preserve the subscription configuration.

The app's [vision allowlist](<C:/Users/dwish/Documents/Codex/Nebius NVIDIA Global AI Hackathon 2026/app/core.py:543>) and [worker vision check](<C:/Users/dwish/Documents/Codex/Nebius NVIDIA Global AI Hackathon 2026/app/worker.py:15>) require attention. The coordinating agent additionally inspected Hermes v0.21.4's image-preparation gates: native model vision alone does not prove it accepts list-type image content returned in a tool message. A diagnostic allowlist override should not be presented as a verified integration.

Minimum acceptance gate before changing the normal run: one harmless text request; one actual product image inspection; then a real Hermes read-only tool cycle whose image observation reaches the model and whose final answer correctly uses visible evidence. Record exact model, returned usage, full cost estimate, tool selection, image handling and errors. Also check an ordinary ecommerce specialist tool call. No claim of completed integration is justified until these pass.

## Budget arithmetic and limits

At the published Super VL rates, **100,000 billable input tokens + 10,000 billable output tokens = $0.039**. The equivalent Lightning text workload is **$0.0084**. These are arithmetic examples, not measured run costs. A split route costs both its text calls and its visual calls; sending every request through both models can eliminate the apparent saving.

The reported $25 is Nebius credit; Gemini generation and scraper charges are separate and cannot be assumed covered by it. Reserve most Nebius credit until small tests establish token use and retries. Output budgets must allow reasoning as well as the final response; NVIDIA's card says both share `max_tokens`. Do not advertise an enforced aggregate spending cap without shared usage accounting and a verified stop mechanism.

Unverified: image-to-token conversion and image billing details; endpoint context/image count limits; accepted thinking controls; streaming/tool parser behavior; account balances/credit restrictions; actual latency/quality and cost per completed ecommerce task. The public pricing dashboard rendered no readable data through this research interface, so the table uses directly attributable Nebius release/model pages rather than third-party price aggregators. Recheck the account's live rate display before billable testing.
