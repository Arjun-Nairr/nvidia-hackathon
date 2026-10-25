# Ecommerce agent demo

Language for the hackathon demonstration. Scope and implementation decisions live in the existing scope and specification documents.

## Language

**Demo operator**:
Arjun, the sole person who directly uses the hackathon application and demonstrates it. There are no external people onboarding themselves for this demo.
_Avoid_: Customer account, tenant

**Demo business**:
The single prepared ecommerce business example used to demonstrate company-specific agents.
_Avoid_: Tenant, production merchant

**Specialist**:
A business-customized agent built on an approved role foundation, with its own responsibilities and permitted tools. The demo has two specialist roles: market analyst and social-media specialist.
_Avoid_: Unrestricted agent, entirely prewritten agent

**Role foundation**:
The predefined purpose, boundaries and potential tools available to a specialist role. Customization chooses within this foundation rather than inventing unrestricted capabilities.

**Main agent**:
The agent that onboards the demo business and creates/configures its specialists. The demo operator then gives ongoing tasks directly to the specialists.

**Website snapshot**:
A saved copy of the demo operator's supplied business website, used as company source material. It is distinct from the company profile the main agent derives from it.

**Company profile**:
The business context extracted from the website snapshot and clarified with the demo operator. The operator's intended goals are supplied through conversation, not assumed from the website.

**Market analyst**:
The specialist responsible for competitor products, prices and listings, and recommendations about the demo business's products/offers.

**Social-media specialist**:
The specialist responsible for competitor image-ad research and promotional creative, including flyer generation and review.

**Onboarding conversation**:
The short exchange in which main checks its understanding of the supplied business website and clarifies what the demo operator wants its specialists to accomplish.

**Shared business context**:
The team's common business facts and goals, maintained by main. Specialists use it but keep their own task-specific notes and learning separate.

**Specialist memory**:
The private notes and preferences belonging to one specialist. They are not shared business facts or another specialist's memory.

Shared business facts take precedence over conflicting private notes; a specialist's local learning does not redefine the business for the team.
