"""LIVE check against the selected provider in secrets/local.env (spends subscription/credits). Uses the real runtime/.
Creates ONE specialist (left in place). Steps: create via natural language -> chat -> save preference -> restart app -> verify.
Run: venv python tests\\live_check.py   (it refuses to run if llm_problem() reports a problem)"""
import json, subprocess, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import core

PORT = 8802
cfg, problem = core.llm_config(), core.llm_problem()
print("provider:", cfg["provider"], "| model:", cfg["model"])
if problem:
    sys.exit("NOT RUN: " + problem)
SIGNOFF = "Ferrous Heron"
procs, results = [], []


def check(name, ok, detail=""):
    results.append(bool(ok)); print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{str(detail)[:400]}]"), flush=True)


def api(path, body=None):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=600).read())


def start():
    p = subprocess.Popen([sys.executable, "-m", "app.server", str(PORT)], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(p)
    for _ in range(60):
        try:
            api("/api/status"); return p
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("server did not start")


try:
    srv = start()
    before = {a["agent_id"] for a in api("/api/agents")}
    r = api("/api/chat/main", {"message": "Please create a market analysis specialist for our company, focused on watching our competitors."})
    print("main agent said:", r["text"][:300].replace("\n", " "))
    calls = [t for t in r["tools"] if t.get("name") == "create_agent" and t.get("input")]
    outs = [json.loads(t["output"]) for t in r["tools"] if t.get("name") == "create_agent" and t.get("output")]
    check("main agent made a real create_agent tool call", len(calls) >= 1, r)
    ok = [o for o in outs if o.get("ok")]
    check("create_agent succeeded (state idle, conversation id, granted tools)", ok and ok[-1]["state"] == "idle" and ok[-1]["conversation_id"], outs)
    new = [a for a in api("/api/agents") if a["agent_id"] not in before]
    check("specialist appears in the registry", len(new) == 1, new)
    aid = new[0]["agent_id"]
    d = api(f"/api/agents/{aid}")
    check("generated instructions + skill present", len(d["instructions"]) > 80 and len(d["skills"]) >= 1)
    r = api(f"/api/chat/{aid}", {"message": "Introduce yourself in two sentences and name one competitor you would watch first."})
    check("specialist accepts a direct message", r["text"] and not r["error"], r)
    r = api(f"/api/chat/{aid}", {"message": f"Please save this to your memory: I want every report to end with the sign-off '{SIGNOFF}'."})
    pdir = core.HERMES_ROOT / "profiles" / aid / "memories"
    mem = "".join(f.read_text(encoding="utf-8") for f in pdir.glob("*.md")) if pdir.exists() else ""
    check("preference saved in specialist's own memory files", SIGNOFF in mem, r)
    n = len(api(f"/api/chat/{aid}"))
    srv.terminate(); srv.wait(); start()
    check("agent identity survives restart", any(a["agent_id"] == aid for a in api("/api/agents")))
    check("app transcript survives restart", len(api(f"/api/chat/{aid}")) == n and n >= 4)
    r = api(f"/api/chat/{aid}", {"message": "Which earlier question of mine did you answer first? One short sentence."})
    check("same Hermes conversation resumes after restart", r["text"] and not r["error"], r)
    r = core.run_turn(aid, "What sign-off do I want at the end of every report?", conv_override="fresh-session-check")
    check("new session after restart answers from memory", SIGNOFF.lower() in r["text"].lower(), r)
finally:
    for p in procs:
        p.terminate()
print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if results and all(results) else 1)
