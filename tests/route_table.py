"""Table-driven REAL Laya predictions for main-chat routing (no Hermes, no model spend). Loads Laya once (first run downloads the
checkpoint into runtime/hf_cache). Run: python tests/route_table.py [-v]   (any Python 3; Laya itself runs under .venv-laya)"""
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import core, routing

AGENTS = [{"agent_id": "northloom-competitor-analyst", "name": "Northloom Competitor Analyst", "role": "market_analysis"},
          {"agent_id": "my-market-scout", "name": "My Market Scout", "role": "market_analysis"}]
H_OFFER = [{"speaker": "user", "text": "I want to keep an eye on our competitors."},
           {"speaker": "assistant", "text": "Would you like me to create a market-analysis specialist to monitor your competitors' pricing and launches?"}]
H_OFFER2 = [{"speaker": "assistant", "text": "I can create a market-analysis specialist for competitor pricing. Want me to?"}]
H_DONE = [{"speaker": "user", "text": "Create a market analysis specialist for our company."},
          {"speaker": "assistant", "text": "Created Northloom Competitor Analyst (market_analysis). You can chat with it directly from the list."}]
H_SOCIAL = [{"speaker": "user", "text": "Can you make me an Instagram agent?"},
            {"speaker": "assistant", "text": "A social media agent isn't available yet. Right now I can create a market-analysis specialist. Would you like one?"}]
H_Q_PRODUCTS = [{"speaker": "assistant", "text": "Happy to help. What kinds of products do you sell?"}]
H_Q_CUSTOMERS = [{"speaker": "assistant", "text": "Thanks. Who are your target customers?"}]
H_Q_GOAL = [{"speaker": "assistant", "text": "And what is your main goal for the competitor analysis?"}]
H_OOS = [{"speaker": "user", "text": "What's the capital of France?"},
         {"speaker": "assistant", "text": "That looks outside what I can help with here. I'm set up for Northloom Apparel: products, pricing, competitors, brand, and creating or using specialist agents. Ask me something along those lines."}]
C, X, E, B, U, CL = ("create_market_agent", "existing_agent_task", "existing_agent_task", "business_query", "out_of_scope", "clarification")
UR = "unsupported_role"
CS = "create_social_agent"   # V2-01: social_media is a supported role (a clear margin over the other roles is required)
H_SOCIAL_OFFER = [{"speaker": "user", "text": "We want nicer promotional flyers for our bedding."},
                  {"speaker": "assistant", "text": "Would you like me to create a social-media specialist to draft promotional creative for your products?"}]
# (group, message, history, acceptable outcomes)
TABLE = [
    ("create", "Create a market analysis specialist for our company.", [], {C}),
    ("create", "Please set up an agent to watch our competitors' pricing.", [], {C}),
    ("create", "I need a competitor analyst on my team. Can you make one?", [], {C}),
    ("create", "Can you spin up someone to track what Harbor & Pine is charging?", [], {C}),
    ("create", "Add a pricing and market research agent.", [], {C}),
    ("contextual yes", "yes, create it", H_OFFER, {C}),
    ("contextual yes", "ok go ahead", H_OFFER, {C}),
    ("contextual yes", "sure", H_OFFER2, {C}),
    ("contextual yes", "yes please", H_SOCIAL, {C}),   # offered market analysis after refusing social
    ("old instruction", "thanks! what can it do?", H_DONE, {B, X, CL}),   # "it" is ambiguous; any non-creating outcome is acceptable
    ("old instruction", "great, now what is our cheapest product?", H_DONE, {B}),
    ("existing agent", "Ask the Northloom Competitor Analyst to compare our hoodie price with Harbor & Pine.", [], {X}),
    ("existing agent", "Have My Market Scout look at Kinfolk Row's new jackets.", [], {X}),
    ("existing agent", "Can the competitor analyst tell me which competitor discounts the most?", [], {X}),
    ("business", "How should I price the Waxed Overshirt for autumn?", [], {B}),
    ("business", "What are our best sellers?", [], {B}),
    ("business", "What can the agents in this system do?", [], {B}),
    ("business", "Who are our main competitors and how do they position themselves?", [], {B}),
    ("business", "Should I run a discount on the Field Jacket?", [], {B}),
    ("social", "Create a social media specialist who writes promotional flyers for our bedding.", [], {CS}),
    ("social", "Set up a social media specialist for us.", [], {CS}),
    ("social", "I need someone to handle our social media creative.", [], {CS}),
    ("social", "Please create a social media agent for our company.", [], {CS}),
    ("contextual yes", "yes please, create it", H_SOCIAL_OFFER, {CS}),
    ("role ambiguity", "Create an agent for social media competitor analysis.", [], {C, CL}),   # both roles apply: never the social role on a close call
    ("social/email", "Create a social media agent to post on Instagram for us.", [], {CS, CL, UR}),   # posting is not connected; the specialist says so
    ("social/email", "I want an email marketing agent that writes our newsletters.", [], {UR}),
    ("social/email", "Make me an agent that handles customer support tickets.", [], {UR}),
    ("social/email", "Set up an agent to generate ad images.", [], {CS, CL, UR}),   # image generation is not connected; any non-analyst outcome is honest
    ("unrelated", "What's the capital of France?", [], {U}),
    ("unrelated", "Write me a poem about the ocean.", [], {U}),
    ("unrelated", "Help me debug my Python script.", [], {U}),
    ("unrelated", "Who won the football match last night?", [], {U}),
    ("after an out-of-scope reply", "Write me a poem about the ocean.", H_OOS, {U}),
    ("after an out-of-scope reply", "Who won the football match last night?", H_DONE, {U}),
    ("after an out-of-scope reply", "Do it.", H_OOS, {CL}),
    ("ambiguous", "Do it.", [], {CL}),
    ("ambiguous", "Create an agent.", [], {CL}),
    ("ambiguous", "Can you help me?", [], {CL}),
    ("onboarding", "We sell handmade candles to gift buyers.", [], {B}, "blank"),
    ("onboarding", "My company is called Acme Candles.", [], {B}, "blank"),
    ("onboarding", "I want to keep an eye on what other candle shops charge.", [], {B, C}, "blank"),
    ("onboarding", "My website is acme-candles.example.com", [], {B}, "blank"),
    ("onboarding", "Create a competitor analyst for us.", [], {C}, "blank"),
    ("onboarding answer", "Mostly scented soy candles and gift sets.", H_Q_PRODUCTS, {B}, "blank"),
    ("onboarding answer", "Women aged 25-40 in the UK.", H_Q_CUSTOMERS, {B}, "blank"),
    ("onboarding answer", "Find out if we are priced too high.", H_Q_GOAL, {B}, "blank"),
    ("onboarding answer", "Mostly students and young parents.", H_Q_CUSTOMERS, {B}, "partial"),
    ("onboarding unrelated", "What's the capital of France?", H_Q_CUSTOMERS, {U}, "blank"),
    ("onboarding unrelated", "Write me a poem about the ocean.", H_Q_CUSTOMERS, {U}, "blank"),
    ("onboarding unrelated", "Help me debug my Python script.", H_Q_GOAL, {U}, "blank"),
    ("onboarding social", "Create a social media agent for Instagram.", [], {CS, CL, UR}, "blank"),
    ("mixed", "Create a market analysis agent and also write me a poem about dogs.", [], {CL}),
    ("mixed", "Make one for Instagram and also compare our prices to competitors.", [], {CL}),
    ("mixed", "Create a market agent, or maybe just tell me about competitors, I'm not sure.", [], {CL, C}),
]


def main(verbose):
    company, rows = json.loads((Path(__file__).parent / "fixtures" / "company_example.json").read_text(encoding="utf-8")), []
    t0 = time.perf_counter(); routing.client.warm(); load_s = time.perf_counter() - t0
    print(f"Laya ready: load/wait {load_s:.1f}s  ({routing.client.ready})")
    states = {"complete": company, "blank": {k: "" for k in company}, "partial": {**{k: "" for k in company}, "name": "Acme Candles", "products": "Handmade candles"}}
    for group, msg, hist, ok, *st in TABLE:
        r = routing.route(msg, hist, AGENTS, states[st[0] if st else "complete"])
        rows.append((group, msg, ok, r))
        good = r["outcome"] in ok
        print(f"{'PASS' if good else 'FAIL'} [{group}] {msg[:62]!r}\n      expected {sorted(ok)} got {r['outcome']} | {r['decision_rule']} | role={r['role']} agent={r['agent_id']} | {r['classifier']['model_ms']}ms/{r['classifier']['calls']} call(s)"
              + (f"\n      probs {r['probabilities']}" if verbose or not good else ""), flush=True)
    n = sum(r["outcome"] in ok for _, _, ok, r in rows)
    ms = sorted(r["classifier"]["model_ms"] for *_, r in rows)
    print(f"\n{n}/{len(rows)} as expected. model_ms median {ms[len(ms)//2]} min {ms[0]} max {ms[-1]}; round_trip median "
          f"{sorted(r['classifier']['round_trip_ms'] for *_, r in rows)[len(rows)//2]}ms")
    json.dump([{"group": g, "message": m, "expected": sorted(ok), "outcome": r["outcome"], "rule": r["decision_rule"], "probs": r["probabilities"],
                "model_ms": r["classifier"]["model_ms"]} for g, m, ok, r in rows], open(core.RUNTIME / "route_table_last.json", "w"), indent=1)
    routing.client.stop()
    return 0 if n == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main("-v" in sys.argv))
