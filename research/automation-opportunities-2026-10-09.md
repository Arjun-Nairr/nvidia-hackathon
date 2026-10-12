# Automation opportunity shortlist

Researched: 2026-10-09 (Asia/Dubai). Stage: discovery only; no project selected, repository created, tools installed, or implementation authorized.

## Decision

Provisional ranking: (1) shared-lab disruption recovery, (2) electronics build recovery after supplier cancellation, (3) recall-response operations for secondhand sellers. Ranking is engineering judgment based on demonstrable actions, likely user access, and a bounded hackathon slice. None has a verified market gap or proven demand. Product descriptions below are first-party documented claims, not independently tested performance.

Used Matt skills Research as the primary workflow; Engineering Workflow Guide for scope and Workflow Designer for trigger/input/action/verification boundaries. Research skill requires background reading and a durable note. No implementation specifications or prompts were produced.

## Verified hackathon fit

Official rules specify a submission deadline of October 30, 2026, 10am Pacific Time, corresponding to 9pm Dubai. A runtime call to Token Factory inference qualifies as running on Nebius; at least one NVIDIA open-source model is required. A public repository with an open-source licence and setup instructions is required. The rules ask for a public demonstration video under three minutes and a working demo/test build, with a Physical AI demo exception. These proposals provisionally fit Best Apps and Agents. [Official rules, sections 1 and 4](https://nebiusglobalaihackathon.devpost.com/rules), [tracks and judging](https://nebiusglobalaihackathon.devpost.com/).

Nebius documents model-selected function calls and an iterative backend execution loop: the model proposes tools; application code executes them. Its official cookbook lists NVIDIA Nemotron models available on Token Factory. We have not tested credentials, availability in Arjun's account, latency, cost, or task accuracy. [Function calling](https://docs.tokenfactory.nebius.com/ai-models-inference/function-calling), [Nemotron catalogue](https://github.com/nebius/token-factory-cookbook/blob/main/models/nemotron/README.md).

Recommended model contribution: interpret unstructured changes, choose investigations, compare feasible recovery options, react to fresh tool results, and decide when evidence is insufficient. Deterministic tools enforce quantities, time windows, permissions, budgets, and approved substitutions. Compare against a rules-only baseline; if a fixed workflow performs as well, the agentic claim is weak.

Hermes documents toolsets, web retrieval, persistent memory, scheduled tasks and MCP/plugin integrations. Its possible contribution is an existing tool/action runtime and reusable procedures, not a domain solution. Compatibility with the selected Nebius model and strict action controls remains untested. Use only if it reduces implementation work relative to a small direct controller. [Hermes tools](https://hermes-agent.nousresearch.com/docs/user-guide/features/tools/).

## 1. Shared-lab disruption recovery

### Proposed work

A shared instrument fails after experiments have been scheduled. The operator needs to recover dependent work under timing, training and equipment constraints, not merely open a repair ticket. Example: identify experiments affected by a breakdown, examine pre-approved equivalent instruments and valid time windows, reserve replacements, update incident records, verify bookings, then replan when the repair ETA changes. Scientific substitutions require prior expert approval; the agent cannot invent protocol equivalence.

Hackathon slice: one lab, six instruments, ten bookings, an approved-equivalence table, two changing incident reports and a separate test booking system. Output: actual revised bookings and incident records, plus a short explanation of affected experiments and unresolved conflicts. No physical hardware control is needed for this slice.

### Documented alternatives and access

Calira already advertises AI multi-instrument workflow reservations, training-based scheduling rules and maintenance tracking. A generic AI lab scheduler is therefore poor differentiation. [Calira features](https://calira.co/).

eLabFTW documents resource bookings, links from bookings to experiments, booking permissions and cancellation. It documents read/write API access and an API surface for booking events. A future private test instance is a plausible integration route; no instance was created or tested. [Scheduler](https://doc.elabftw.net/docs/usage/user-guide/scheduler/), [API access](https://doc.elabftw.net/docs/usage/api/), [API reference](https://doc.elabftw.net/api/v2/).

### Judgment and hypotheses

The proposed distinguishing scope is disruption recovery across experimental dependencies, bookings and repair information. We have not established that competitors lack this. University proximity may make user interviews easier, but Arjun's access is unknown. Without validated lab constraints, this becomes a synthetic calendar demo.

Next evidence: ask a lab manager for one recent equipment failure and an anonymized recovery timeline. Reject if recovery is rare, handled adequately by existing scheduling tools, or relies on scientific judgment that cannot be encoded as approved rules.

Evaluation: work recovered within valid windows; invalid or conflicting bookings blocked; correct escalation; human decisions required. Baselines: manual recovery and earliest-available approved-resource scheduling.

## 2. Electronics build recovery after supplier cancellation

### Proposed work

A supplier cancels a component needed by several committed builds. The agent reads the cancellation, traces affected jobs, inspects stock and approved alternatives, checks distributor offers, considers split purchases or inventory reallocation, and prepares bounded procurement changes. It rechecks stock before applying a plan and adapts when the offer disappears.

Hackathon slice: one public 20-30-line bill of materials, three build jobs, a small inventory ledger and an explicit approved-substitution list. Execute reservations/job updates in a test ledger and, if access works, create and read back a distributor MyLists list. A shopping list does not reserve stock or guarantee delivery. Purchasing money or approving a new electrical substitute requires a human decision.

### Documented alternatives and access

Altium ActiveBOM already provides supply data and alternatives. PartsBox explicitly combines multiple build BOMs, subtracts inventory and supports approved substitutes through purchasing and builds. Z2Data advertises alternate-part and supply-chain recovery capabilities. Basic cheapest-BOM or replacement-part search is already well served. [ActiveBOM](https://www.altium.com/altium-designer/features/bom-management), [PartsBox purchase lists](https://partsbox.com/purchase-lists.html), [PartsBox substitutes](https://partsbox.com/handle-part-shortages-with-substitutes.html), [Z2Data lifecycle management](https://www.z2data.com/solutions/lcm/).

DigiKey documents product search and MyLists create/read/add-parts operations. CreateList requires three-legged OAuth. Its sandbox returns representative structures whose data may not match a request, so sandbox stock cannot support a claim of live sourcing. Credentials and production access have not been tested. [Product search](https://developer.digikey.com/products/product-information-v4/productsearch/keywordsearch), [CreateList and related methods](https://developer.digikey.com/products/mylists/mylists/createlist), [Sandbox constraints](https://developer.digikey.com/tutorials-and-resources/developer-and-sandbox).

### Judgment and hypotheses

Potential scope: cancellation-to-recovered-build handling across supplier notices, stock, deadlines and job priorities. This is not a demonstrated market gap. A robotics club or small hardware team could supply a real case, but access is unknown. Engineering qualification and accurate shipping promises are the largest limits.

Next evidence: get one recent cancelled order from a hardware team and compare its resolution against PartsBox/ActiveBOM. Reject if the work is already solved by their inventory software or if distributor access consumes the available time.

Evaluation: build quantities recovered before deadline; cost within cap; no unapproved substitutions; fresh stock rechecked; no duplicate changes. Baseline: existing BOM sourcing output plus manual procurement.

## 3. Recall-response operations for secondhand sellers

### Proposed work

A recall affects some units of an item already listed for sale. The agent identifies candidates in imperfect inventory records, fetches official scope and remedy instructions, asks for missing serial-number evidence, and distinguishes confirmed affected units from unresolved ones. Under a seller-approved policy, it places holds, withdraws applicable test listings, records the physical inspection tasks and prepares remedy evidence. It reads back listing state to verify containment. Physical quarantine or successful refund cannot be inferred from a database write.

Hackathon slice: US consumer-product recalls, a synthetic seller inventory, test listings, one serial-specific recall and a later inventory update. Demonstrate an affected unit, a same-model unit outside the specified serial scope, and a unit with missing identification. Missing evidence remains unresolved; no general safety clearance is issued. No real customer messages, refund submissions or physical disposal actions are authorized.

### Documented problem, alternatives and access

CPSC gives resale businesses guidance on screening inventory and checking recalls. It publishes recall information through a JSON/XML API. [Resale guidance](https://www.cpsc.gov/FAQ/ResaleThrift-Stores), [Recall API](https://www.cpsc.gov/Recalls/CPSC-Recalls-Application-Program-Interface-API-Information?language=en).

A concrete public case is INIU BI-B41: the notice includes only specified serial numbers, illustrating why brand/model similarity is insufficient. Follow the official notice for handling and remedy, not an agent's invented advice. [INIU recall](https://www.cpsc.gov/Recalls/2026/INIU-Recalls-Power-Banks-Due-to-Fire-and-Burn-Hazards-Sold-on-Amazon).

Recall InfoLink advertises notifications, response verification and documentation; DeepRecall advertises AI catalogue matching and enforcement decisions (its site also announces a pivot); Palletry AI advertises recall checks on liquidation manifests. Detection, matching, and audit evidence alone are not new. [Recall InfoLink](https://www.recallinfolink.com/), [DeepRecall](https://www.deeprecall.io/), [Palletry AI](https://palletry.ai/).

eBay documents offer withdrawal without deleting the offer object, and a separate sandbox for fictional users and listings. Inventory API access applies to supported/migrated inventory listings, not every seller listing automatically. A developer account, keys, seller authorization and functioning test setup are prerequisites; none were tested. [Listing management](https://developer.ebay.com/develop/guides/sell/listing-management), [Sandbox](https://www.developer.ebay.com/api-docs/static/gs_understand-the-sandbox-and.html), [Getting started](https://www.developer.ebay.com/develop/guides/sell/get-started-with-ebay-apis).

### Judgment and hypotheses

Potential scope: unit-specific operational containment and remedy preparation for small resale businesses, across online listings and physical inventory. Competitor overlap is strongest here. Seller demand, recall frequency, willingness to delegate holds and access to serial data are unverified. This is ranked third; accessible public data alone does not establish product value.

Next evidence: examine a reseller's actual inventory identification and recall process. Reject if serial data is absent for most items, existing platform enforcement suffices, or a basic database join handles the actual task.

Evaluation: affected-unit recall identification; unresolved units handled correctly; confirmed test listings actually withdrawn; no automatic re-release from missing evidence; physical actions remain pending until acknowledged. Baseline: identifier matching plus a checklist.

## Context and boundaries

Arjun is a university student seeking useful agents and a portfolio outcome. University remains a priority. Codex handles research, architecture, orchestration and evaluation; Claude Code handles implementation only when authorized. The rejected directions are completion-claim verification, contradiction-finding research and stale project-handoff reconciliation. These proposals are separate applications, not renamed versions of those ideas.

No reuse of Second Me or other private implementations is assumed. The submission's public open-source obligation is a material trade-off: choose a fresh project and synthetic/anonymized fixtures unless Arjun explicitly authorizes reuse and publication. Publicly accessible data or datasheets do not automatically permit bundling them in an open-source repository; review source licensing before selecting demo assets.
