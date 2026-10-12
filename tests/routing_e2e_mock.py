"""Main-chat routing end to end: REAL Laya (separate process) + scripted model (tests/mock_llm.py) + real Hermes workers.
Proves wiring and enforcement, not model quality. Run ONLY from a COPY of the project (wipes the copy's runtime/):
  ROUTING_E2E_I_AM_A_COPY=1 ECOM_LAYA_PY=<real project>\\.venv-laya\\Scripts\\python.exe ECOM_HF_CACHE=<real project>\\runtime\\hf_cache  venv-python tests/routing_e2e_mock.py"""
import json, os, shutil, subprocess, sys, threading, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if os.environ.get("ROUTING_E2E_I_AM_A_COPY") != "1" or not os.environ.get("ECOM_LAYA_PY") or not os.environ.get("ECOM_HF_CACHE"):
    sys.exit("Refusing to run: needs ROUTING_E2E_I_AM_A_COPY=1, ECOM_LAYA_PY and ECOM_HF_CACHE (run from a COPY of the project).")
sys.path.insert(0, str(ROOT))
MOCK, APP, APP2 = 8769, 8815, 8816
BASE = {**os.environ, "PYTHONUTF8": "1"}
for k in ("ECOM_CLASSIFIER", "LLM_PROVIDER", "LLM_MODEL", "NEBIUS_API_KEY", "NEBIUS_BASE_URL", "NEBIUS_MODEL"):
    BASE.pop(k, None)
(ROOT / "secrets").mkdir(exist_ok=True)
(ROOT / "secrets" / "local.env").write_text(f"LLM_PROVIDER=nebius-token-factory\nLLM_MODEL=mock-model\nNEBIUS_API_KEY=mock-key\nNEBIUS_BASE_URL=http://127.0.0.1:{MOCK}/v1\n", encoding="utf-8")
procs, results = [], []


def check(name, ok, detail=""):
    ok = bool(ok); results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{str(detail)[:400]}]"), flush=True)


def call(path, body=None, port=APP):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=600); return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def stats(): return call("/stats", port=MOCK)[1]
def chat(msg, agent="main", port=APP): return call(f"/api/chat/{agent}", {"message": msg}, port)[1]


def start_server(port, env):
    p = subprocess.Popen([sys.executable, "-m", "app.server", str(port)], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(p)
    for _ in range(120):
        try: call("/api/status", port=port); return p
        except Exception: time.sleep(0.5)
    raise RuntimeError("server did not start")


try:
    shutil.rmtree(ROOT / "runtime", ignore_errors=True)
    subprocess.run([sys.executable, "scripts/setup.py"], cwd=ROOT, env=BASE, check=True, capture_output=True)
    procs.append(subprocess.Popen([sys.executable, "tests/mock_llm.py", str(MOCK)], cwd=ROOT, env=BASE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(1)
    t_start = time.time()
    start_server(APP, BASE)
    st0 = call("/api/status")[1]["classifier"]
    # ---- cold: first message arrives while Laya is still loading -> it waits, is still handled locally
    s0 = stats()["requests"]
    t = time.time(); r = chat("What's the capital of France?"); cold_s = time.time() - t
    rt = r.get("route") or {}
    check("cold first message waits for Laya, is classified out_of_scope and handled locally with zero model calls",
          rt.get("outcome") == "out_of_scope" and rt.get("handled_locally") and stats()["requests"] == s0 and r["ok"], (r, stats()))
    print(f"   status at start: {st0}; first message total {cold_s:.1f}s; classifier meta {rt.get('classifier')}")
    check("classifier status becomes ready", call("/api/status")[1]["classifier"]["state"] == "ready")
    t = time.time(); r = chat("Write me a poem about the ocean."); warm_s = time.time() - t
    cm = (r.get('route') or {}).get('classifier', {})
    print(f"   warm out_of_scope: http {warm_s:.2f}s, laya round_trip_ms {cm.get('round_trip_ms')}, model_ms {cm.get('model_ms')}, wait_for_load_ms {cm.get('wait_for_load_ms')}")
    check("warm message not marked first_call_after_start", not (r["route"]["classifier"].get("first_call_after_start")), r["route"])

    # ---- onboarding on a BLANK company (no fixture anywhere): routing must let onboarding talk reach main without weakening enforcement
    import sqlite3
    check("company starts blank", call("/api/company")[1]["status"]["missing"] == ["name", "products", "customers", "goal"])
    s0 = stats()["requests"]
    r = chat("My company is called Acme Candles.")
    c = call("/api/company")[1]
    check("onboarding statement is routed to main and main saved the stated name with update_company",
          r["route"]["outcome"] == "business_query" and stats()["requests"] > s0 and c["company"]["name"] == "Acme Candles" and c["updated_by"] == "main", (r.get("route"), c))
    r = chat("Create a market analysis specialist for us.")
    outs = [json.loads(t["output"]) for t in r["tools"] if t.get("name") == "create_agent" and t.get("output")]
    check("creation request with an incomplete company reaches main; the backend refuses with company_incomplete; nothing created",
          r["route"]["outcome"] == "create_market_agent" and outs and outs[0].get("code") == "company_incomplete" and call("/api/agents")[1] == [], (r.get("route"), outs))
    sq = sqlite3.connect(ROOT / "runtime" / "app.db")
    sq.execute("INSERT INTO messages(agent_id,who,content,tools,ts) VALUES('main','agent','Who are your target customers?','[]',?)", (time.time(),)); sq.commit(); sq.close()
    s0 = stats()["requests"]
    r = chat("Write me a poem about the ocean.")
    check("an unrelated request right after main's question is still out_of_scope, handled locally",
          r["route"]["outcome"] == "out_of_scope" and r["route"]["handled_locally"] and stats()["requests"] == s0, r.get("route"))
    s0 = stats()["requests"]
    r = chat("Women aged 25-40 in the UK.")
    c = call("/api/company")[1]
    check("an answer to main's question reaches main (business_query) and the stated customers are saved",
          r["route"]["outcome"] == "business_query" and "reply to main's question" in r["route"]["decision_rule"] and stats()["requests"] > s0
          and c["company"]["customers"].startswith("Women aged 25-40"), (r.get("route"), c))
    r = chat("We sell handmade candles to gift buyers. Our goal is to see what rivals charge.")
    c = call("/api/company")[1]
    check("statement with products/customers/goal is saved; company becomes complete", c["status"]["complete"] and c["company"]["goal"].startswith("see what rivals"), (r.get("route"), c))

    # ---- handled outcomes: zero model calls ("Do it." first: after an unsupported-role reply that OFFERS market analysis, "Do it." correctly means yes)
    for label, msg, want in [("clarification", "Do it.", "clarification"),
                             ("unsupported role (email)", "I want an email marketing agent that writes our newsletters.", "unsupported_role")]:
        s0 = stats()["requests"]; r = chat(msg)
        check(f"{label}: {want}, handled locally, zero model calls, no agent created",
              r["route"]["outcome"] == want and stats()["requests"] == s0 and call("/api/agents")[1] == [], (r.get("route"), stats()))

    # ---- supported creation reaches main with the ORIGINAL message and trusted context
    ctx0, s0 = stats()["routing_ctx_seen"], stats()["requests"]
    r = chat("Create a market analysis specialist for our company.")
    created = [json.loads(t["output"]) for t in r["tools"] if t.get("name") == "create_agent" and t.get("output")]
    agents = call("/api/agents")[1]
    check("create_market_agent -> main called create_agent and a persistent specialist exists", r["route"]["outcome"] == "create_market_agent" and created and created[0].get("ok") and len(agents) == 1, (r.get("route"), r["tools"]))
    check("main received the trusted routing context (original message kept)", stats()["routing_ctx_seen"] > ctx0 and stats()["requests"] > s0)
    aid = agents[0]["agent_id"]

    # ---- existing agent task: recommend, do not create, zero model calls
    s0 = stats()["requests"]
    r = chat("Ask the Market Analyst to compare our hoodie price with Harbor & Pine.")
    check("existing-agent task is recommended locally, no duplicate agent, zero model calls",
          r["route"]["outcome"] == "existing_agent_task" and r["route"]["agent_id"] == aid and "Market Analyst" in r["text"] and len(call("/api/agents")[1]) == 1 and stats()["requests"] == s0, (r.get("route"), r["text"]))

    # ---- non-creation route cannot create: the scripted model tries create_agent anyway (its text contains 'market')
    n0, s0 = len(call("/api/agents")[1]), stats()["requests"]
    r = chat("How should I price our candle gift sets for the market this Christmas?")
    outs = [t.get("output", "") for t in r["tools"] if t.get("name") == "create_agent" and t.get("output")]
    check("business_query reaches main, the model's create_agent attempt is BLOCKED, no agent created",
          r["route"]["outcome"] == "business_query" and stats()["requests"] > s0 and outs and "not permitted" in outs[0] and len(call("/api/agents")[1]) == n0, (r.get("route"), outs, r["text"]))
    from app import turn_state
    check("default routing state is fail-closed (no route -> create_agent not allowed)", turn_state.create_allowed() is False)

    # ---- V2-01: a social-media specialist is a supported role. Real Laya routes the natural-language request; the scripted model then calls create_agent
    n0, s0 = len(call("/api/agents")[1]), stats()["requests"]
    r = chat("Create a social media specialist who writes promotional flyers for our bedding.")
    created = [json.loads(t["output"]) for t in r["tools"] if t.get("name") == "create_agent" and t.get("output")]
    agents = call("/api/agents")[1]
    check("create_social_agent: main called create_agent for role social_media; a persistent social specialist exists beside the analyst; the analyst is untouched",
          r["route"]["outcome"] == "create_social_agent" and r["route"]["role"] == "social_media" and created and created[0].get("ok")
          and created[0]["skills"][0] == "social-media-flyer-baseline" and len(agents) == n0 + 1
          and sorted(a["role"] for a in agents) == ["market_analysis", "social_media"] and stats()["requests"] > s0, (r.get("route"), r["tools"]))
    aid_social = [a["agent_id"] for a in agents if a["role"] == "social_media"][0]
    s0 = stats()["requests"]
    r = chat("I want an email marketing agent that writes our newsletters.")
    check("an email agent is still unsupported after the social role exists: handled locally, zero model calls, offers both supported roles",
          r["route"]["outcome"] == "unsupported_role" and stats()["requests"] == s0 and "social-media specialist" in r["text"] and "market-analysis specialist" in r["text"], (r.get("route"), r["text"]))
    r = chat("hello social specialist", aid_social)
    check("the social specialist chats directly (unrouted) and has no Marketplace or create_agent tool", r["ok"] and r["route"] is None
          and "marketplace_search" not in r["text"] and "create_agent" not in r["text"] and "inspect_image" in r["text"], r["text"][:200])

    # ---- specialist chat unchanged
    r = chat("hello specialist", aid)
    check("direct specialist chat unchanged (no routing, normal reply)", r["ok"] and r["route"] is None and r["text"].startswith("[MOCK LLM]"), r)

    # ---- persistence of routing metadata
    rows = call("/api/chat/main")[1]
    check("routing metadata + Laya probabilities stored with the replies", any(x.get("route") and x["route"].get("probabilities") for x in rows))

    # ---- duplicate protection still holds with classification in front
    s0 = stats()["requests"]; res = [None, None]
    def go(i): res[i] = call("/api/chat/main", {"message": "How should I price our candle gift sets for the market this Christmas?", "request_id": "dup-1"})
    ts = [threading.Thread(target=go, args=(i,)) for i in range(2)]; [t.start() for t in ts]; [t.join() for t in ts]
    check("two simultaneous identical requests: one runs, the other is rejected", sorted(r[0] for r in res) in ([200, 409], [200, 200]) and any(r[0] == 409 for r in res) or res[0][1].get("replayed") or res[1][1].get("replayed"), res)

    # ---- classifier failure is explicit and does not reach Hermes
    env2 = {**BASE, "ECOM_LAYA_PY": str(ROOT / "nonexistent" / "python.exe")}
    start_server(APP2, env2)
    s0, n0 = stats()["requests"], len(call("/api/agents", port=APP2)[1])
    r = chat("Create a market analysis specialist for our company.", port=APP2)
    check("classifier failure: explicit error, nothing sent to Hermes, nothing created",
          r["ok"] is False and "routing failed" in r["error"] and "Laya" in r["error"] and stats()["requests"] == s0 and len(call("/api/agents", port=APP2)[1]) == n0, r)
finally:
    for p in procs:
        p.terminate()
print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if results and all(results) else 1)
