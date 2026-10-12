"""LIVE check of main-chat routing on the REAL runtime with the selected provider (spends subscription quota; no Nebius spend unless
LLM_PROVIDER is nebius). Starts its own server (port 8818, Laya prewarm). Steps, each once, no retries:
  1. an out-of-scope message (handled locally; must make zero Hermes model calls),
  2. a creation request naming a clearly marked test agent ('ROUTETEST Diagnostic Analyst') -> main creates a persistent specialist,
  3. direct chat with that new specialist and with the existing first specialist (unchanged by routing).
Run: venv python tests/routing_live_check.py   (adds turns to the main conversation; creates ONE test agent; nothing is deleted)"""
import json, os, subprocess, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import core
PORT, SPEC = 8818, os.environ.get("DIAG_SPECIALIST", "northloom-competitor-analyst")
results = []


def check(name, ok, detail=""):
    ok = bool(ok); results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{str(detail)[:400]}]"), flush=True)


def api(path, body=None, timeout=600):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


cfg, problem = core.llm_config(), core.llm_problem()
print("provider:", cfg["provider"], "| model:", cfg["model"])
if problem:
    sys.exit("NOT RUN: " + problem)
srv = subprocess.Popen([sys.executable, "-m", "app.server", str(PORT)], cwd=ROOT, env={**os.environ, "PYTHONUTF8": "1", "ECOM_TIMING": "1"},
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(120):
        try: api("/api/status", timeout=5); break
        except Exception: time.sleep(0.5)
    before = {a["agent_id"] for a in api("/api/agents")}
    workers_before = {w["agent_id"] for w in api("/api/workers")}
    t = time.time(); r = api("/api/chat/main", {"message": "What's the capital of France?"}); cold = time.time() - t
    check("out-of-scope handled locally, no Hermes worker was started for it", r["route"]["outcome"] == "out_of_scope" and r["route"]["handled_locally"] and not api("/api/workers"), (r["route"], api("/api/workers")))
    print(f"   cold request (waited for Laya load) {cold:.1f}s; classifier {r['route']['classifier'].get('round_trip_ms')} ms round trip, model {r['route']['classifier'].get('model_ms')} ms")
    t = time.time(); r = api("/api/chat/main", {"message": "Create a market analysis specialist named 'ROUTETEST Diagnostic Analyst' for this company. Keep its objective, instructions and one skill short."})
    wall = time.time() - t
    calls = [x for x in r["tools"] if x.get("name") == "create_agent" and x.get("input")]
    outs = [json.loads(x["output"]) for x in r["tools"] if x.get("name") == "create_agent" and x.get("output")]
    check("create request routed as create_market_agent and main made a real create_agent call", r["route"]["outcome"] == "create_market_agent" and len(calls) >= 1, (r["route"], r["tools"]))
    check("a persistent specialist was created", any(o.get("ok") for o in outs) and any(a["agent_id"] not in before for a in api("/api/agents")), outs)
    print(f"   creation turn {wall:.1f}s (classification {r['route']['classifier'].get('round_trip_ms')} ms of it)")
    new = [a["agent_id"] for a in api("/api/agents") if a["agent_id"] not in before]
    for aid in (new[:1] + [SPEC]):
        r = api(f"/api/chat/{aid}", {"message": "[routingtest] Reply with just the word PONG."})
        check(f"direct specialist chat works unchanged ({aid})", r["ok"] and r["route"] is None and "PONG" in r["text"].upper(), r)
finally:
    srv.terminate()
print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if results and all(results) else 1)
