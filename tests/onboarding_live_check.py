"""LIVE smoke of onboarding -> analyst creation with the real subscription model, in an ISOLATED copy of the project (never the real
runtime). The copy needs runtime/hermes_home/auth.json + config.yaml copied from the real runtime and secrets/local.env (the launcher
does that). Refuses unless the copied login has >= 20 minutes of access-token life left, so the copy cannot trigger a token refresh
(Codex refresh tokens are single-use; a refresh in the copy would invalidate the real login). Spends subscription quota only.
Run from the copy: ONBOARDING_LIVE_I_AM_A_COPY=1 ECOM_LAYA_PY=... ECOM_HF_CACHE=... venv-python tests/onboarding_live_check.py"""
import base64, json, os, subprocess, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if os.environ.get("ONBOARDING_LIVE_I_AM_A_COPY") != "1":
    sys.exit("Refusing to run: copy of the project only (ONBOARDING_LIVE_I_AM_A_COPY=1).")
sys.path.insert(0, str(ROOT))
from app import core

PORT = 8830
results = []


def check(name, ok, detail=""):
    ok = bool(ok); results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{str(detail)[:500]}]"), flush=True)


def token_life_seconds():
    """Smallest remaining life among JWTs in the copied auth.json (values are never printed)."""
    best = None
    def walk(o):
        nonlocal best
        if isinstance(o, dict):
            for v in o.values(): walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)
        elif isinstance(o, str) and o.count(".") == 2:
            try:
                pay = json.loads(base64.urlsafe_b64decode(o.split(".")[1] + "=" * (-len(o.split(".")[1]) % 4)))
                if "exp" in pay:
                    life = pay["exp"] - time.time(); best = life if best is None else min(best, life)
            except Exception:
                pass
    walk(json.loads((core.HERMES_ROOT / "auth.json").read_text(encoding="utf-8")))
    return best


def api(path, body=None, timeout=900):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


life = token_life_seconds()
cfg, problem = core.llm_config(), core.llm_problem()
print(f"provider {cfg['provider']} model {cfg['model']} | login token life left: {None if life is None else round(life / 60)} min | problem: {problem}")
if problem or life is None or life < 20 * 60:
    sys.exit("NOT RUN: " + (problem or "login token life too short or unknown; not risking a refresh in the copy"))

env = {**os.environ, "PYTHONUTF8": "1"}
srv = subprocess.Popen([sys.executable, "-m", "app.server", str(PORT)], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(120):
        try: api("/api/status", timeout=5); break
        except Exception: time.sleep(0.5)
    check("fresh isolated runtime is blank", api("/api/company")["status"]["missing"] == ["name", "products", "customers", "goal"] and api("/api/agents") == [])
    t = time.time()
    r = api("/api/chat/main", {"message": "Hi! My company is called Acme Candles. We sell handmade soy candles and gift sets to gift buyers in the UK."})
    c = api("/api/company")
    print(f"   [{time.time() - t:.0f}s] route={r['route']['outcome']} | tools={[x['name'] for x in r['tools'] if x.get('input')]} | saved={ {k: v[:40] for k, v in c['company'].items() if v} }")
    print("   main said:", r["text"][:220].replace("\n", " "))
    check("onboarding statement routed to main; real model saved what the user stated (name at least)", r["route"]["outcome"] == "business_query" and c["company"]["name"].lower().startswith("acme"), (r["route"], c))
    check("nothing was invented: competitors/website/brand still unknown", c["company"]["competitors"] == "" and c["company"]["website"] == "" and c["company"]["brand"] == "", c["company"])
    t = time.time()
    r2 = api("/api/chat/main", {"message": "Our goal is to understand how other candle brands price their gift sets so we can price ours sensibly."})
    c = api("/api/company")
    print(f"   [{time.time() - t:.0f}s] route={r2['route']['outcome']} | complete={c['status']['complete']} | missing={c['status']['missing']}")
    print("   main said:", r2["text"][:220].replace("\n", " "))
    check("goal saved; company complete (or main still needs a detail the user did not give)", c["company"]["goal"] != "", c)
    if not c["status"]["complete"]:
        print("   (company not complete after two messages; filling the remaining details through the form API like a user would)")
        miss = {k: {"name": "Acme Candles", "products": "Handmade soy candles and gift sets", "customers": "Gift buyers in the UK"}[k] for k in c["status"]["missing"] if k in ("name", "products", "customers")}
        if miss:
            api("/api/company", {"fields": miss})
        c = api("/api/company")
    t = time.time()
    r3 = api("/api/chat/main", {"message": "Please create a competitor analyst for us."})
    agents = api("/api/agents")
    created = [json.loads(x["output"]) for x in r3["tools"] if x.get("name") == "create_agent" and x.get("output")]
    print(f"   [{time.time() - t:.0f}s] route={r3['route']['outcome']} | tools={[x['name'] for x in r3['tools'] if x.get('input')]} | created={[(o.get('ok'), o.get('code')) for o in created]}")
    print("   main said:", r3["text"][:260].replace("\n", " "))
    check("create request routed as create_market_agent; main made a real create_agent call", r3["route"]["outcome"] == "create_market_agent" and created)
    check("a persistent analyst exists with baseline + at least one custom skill", len(agents) == 1 and created and created[-1].get("ok") and len(created[-1]["skills"]) >= 2
          and created[-1]["skills"][0] == "competitor-analysis-baseline", created)
    if agents:
        aid = agents[0]["agent_id"]
        pdir = core.HERMES_ROOT / "profiles" / aid
        soul = (pdir / "SOUL.md").read_text(encoding="utf-8")
        d = api(f"/api/agents/{aid}")
        print("   analyst name:", d["name"], "| skills:", [s["name"] for s in d["skills"]], "| tools:", d["granted_tools"])
        print("   objective:", d["objective"][:240].replace("\n", " "))
        check("analyst SOUL has fixed responsibilities and Acme-specific text, and no demo labels",
              "Core responsibilities" in soul and "Acme" in soul and not any(w in soul for w in ("Northloom", "fictional")), soul[:200])
        t = time.time()
        r4 = api(f"/api/chat/{aid}", {"message": "Without browsing anything: what can you do for us, and do you have live access to competitor data right now?"})
        print(f"   [{time.time() - t:.0f}s] specialist said:", r4["text"][:420].replace("\n", " "))
        check("direct specialist chat works and is not routed", r4["ok"] and r4["route"] is None and r4["text"])
        check("specialist states it lacks live access (honesty; keyword check, read the quote above)", any(w in r4["text"].lower() for w in ("not connected", "no live", "don't have", "do not have", "can't browse", "cannot browse", "no access", "without live", "not have live", "isn't connected", "no real-time")), r4["text"][:200])
        r5 = api(f"/api/chat/{aid}", {"message": "Please save to your memory: always end my competitor reports with the sign-off 'Ferrous Heron'."})
        mem = "".join(f.read_text(encoding="utf-8") for f in (pdir / "memories").glob("*.md")) if (pdir / "memories").exists() else ""
        check("specialist saved the preference in its own memory", "Ferrous Heron" in mem, r5["text"][:200])
        check("main profile memory does not contain the specialist's preference", "Ferrous Heron" not in "".join(f.read_text(encoding="utf-8", errors="ignore") for f in (core.HERMES_ROOT / "profiles" / "main" / "memories").glob("*.md")))
    srv.terminate(); srv.wait(); time.sleep(2)
    srv = subprocess.Popen([sys.executable, "-m", "app.server", str(PORT)], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(120):
        try: api("/api/status", timeout=5); break
        except Exception: time.sleep(0.5)
    check("after restart: company, analyst and transcripts persist", api("/api/company")["status"]["complete"] and len(api("/api/agents")) == 1 and len(api(f"/api/chat/{aid}")) >= 4)
finally:
    srv.terminate()
print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if results and all(results) else 1)
