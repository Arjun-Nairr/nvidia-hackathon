"""Worker-lifecycle tests with a SCRIPTED model (tests/mock_llm.py) - wiring only, not a provider test.
DESTROYS ./runtime and rewrites secrets/local.env: run it ONLY from a copy of the project, never the real folder.
Run (from the copy): venv python tests/workers_mock.py"""
import json, os, shutil, sqlite3, subprocess, sys, threading, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if os.environ.get("WORKERS_MOCK_I_AM_A_COPY") != "1":
    sys.exit("Refusing to run: set WORKERS_MOCK_I_AM_A_COPY=1 (and run from a COPY of the project; this wipes runtime/).")
sys.path.insert(0, str(ROOT))
MOCK, APP = 8767, 8806
ENV = {**os.environ, "ECOM_TIMING": "1", "PYTHONUTF8": "1", "MOCK_SLOW_S": "25", "ECOM_CLASSIFIER": "off"}
for k in ("LLM_PROVIDER", "LLM_MODEL", "NEBIUS_API_KEY", "NEBIUS_BASE_URL", "NEBIUS_MODEL"):
    ENV.pop(k, None); os.environ.pop(k, None)
ENV_FILE = ROOT / "secrets" / "local.env"
procs, results = [], []


def conf(provider="nebius-token-factory", model="mock-model"):
    ENV_FILE.parent.mkdir(exist_ok=True)
    ENV_FILE.write_text(f"LLM_PROVIDER={provider}\nLLM_MODEL={model}\nNEBIUS_API_KEY=mock-key\nNEBIUS_BASE_URL=http://127.0.0.1:{MOCK}/v1\n", encoding="utf-8")


def check(name, ok, detail=""):
    ok = bool(ok); results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{str(detail)[:300]}]"), flush=True)


def get(path, port=APP):
    return json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=60).read())


def chat(agent, msg, timeout=300):
    req = urllib.request.Request(f"http://127.0.0.1:{APP}/api/chat/{agent}", data=json.dumps({"message": msg}).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def start_server():
    p = subprocess.Popen([sys.executable, "-m", "app.server", str(APP)], cwd=ROOT, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(p)
    for _ in range(80):
        try:
            get("/api/status"); return p
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("server did not start")


def workers():
    return {w["agent_id"]: w for w in get("/api/workers")}


def pid_alive(pid):
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True).stdout
    return str(pid) in out


def kill(pid):
    subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)


def tlog():
    f = ROOT / "runtime" / "timing.jsonl"
    return [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines()] if f.exists() else []


def stages(rec):
    return {e["stage"] for e in rec["events"]}


try:
    shutil.rmtree(ROOT / "runtime", ignore_errors=True)
    conf()
    subprocess.run([sys.executable, "scripts/setup.py"], cwd=ROOT, env=ENV, check=True, capture_output=True)
    import shutil as _sh
    (ROOT / "runtime").mkdir(exist_ok=True); _sh.copy(ROOT / "tests" / "fixtures" / "company_example.json", ROOT / "runtime" / "company.json")  # test company (production starts blank)
    procs.append(subprocess.Popen([sys.executable, "tests/mock_llm.py", str(MOCK)], cwd=ROOT, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(1)
    srv = start_server()
    check("no worker before first use (lazy start)", workers() == {})

    # ---- reuse
    r1 = chat("main", "hello one"); w1 = workers()["main"]
    r2 = chat("main", "hello two"); w2 = workers()["main"]
    check("main: same worker process reused", w1["pid"] == w2["pid"] and w2["turns"] == 2 and r2["error"] is None, (w1, w2))
    chats = [t for t in tlog() if t["kind"] == "chat"]
    check("turn 1 paid imports+agent init, turn 2 did not",
          {"import_hermes", "agent_init"} <= stages(chats[0]) and not ({"import_hermes", "agent_init", "session_db_open"} & stages(chats[1]))
          and chats[1]["worker"]["agent_created_this_turn"] is False and chats[1]["worker"]["agent_inits_total"] == 1, [stages(c) for c in chats])
    print(f"   timing: turn1 {chats[0]['total_ms']:.0f} ms, turn2 {chats[1]['total_ms']:.0f} ms")

    # ---- creation + separate workers + separate tools
    r = chat("main", "Please create a market analysis specialist for our company")
    created = [json.loads(t["output"]) for t in r["tools"] if t.get("name") == "create_agent" and t.get("output")]
    aid = created[0]["agent_id"]
    s1 = chat(aid, "hi"); s2 = chat(aid, "hi again"); ws = workers()
    check("specialist created through main's reused worker", created and created[0]["ok"], r)
    check("specialist has its own worker, reused", ws[aid]["pid"] != ws["main"]["pid"] and ws[aid]["turns"] == 2, ws)
    check("separate tool access (specialist: no create_agent; main: create_agent)",
          "create_agent" not in s2["text"] and "memory" in s2["text"] and "create_agent" in chat("main", "tools?")["text"], (s2["text"],))
    c0 = sqlite3.connect(ROOT / f"runtime/hermes_home/profiles/{aid}/state.db").execute("select count(*) from messages").fetchone()[0]
    chat(aid, "one more")
    c1 = sqlite3.connect(ROOT / f"runtime/hermes_home/profiles/{aid}/state.db").execute("select count(*) from messages").fetchone()[0]
    check("history not duplicated: one plain turn adds exactly 2 Hermes rows", c1 - c0 == 2, (c0, c1))
    seen = [int(chat(aid, "count")["text"].split("I can see ")[1].split(" messages")[0]) for _ in range(2)]
    check("model sees growing history across reused turns", seen[1] - seen[0] == 2, seen)

    # ---- preference + restart
    chat(aid, "remember: always sign reports with PURPLE-OTTER")
    mem = "".join(f.read_text(encoding="utf-8") for f in (ROOT / f"runtime/hermes_home/profiles/{aid}/memories").glob("*.md"))
    check("preference saved to specialist memory", "PURPLE-OTTER" in mem)
    pids = [w["pid"] for w in workers().values()]
    before = len(get(f"/api/chat/{aid}"))
    srv.terminate(); srv.wait(); time.sleep(3)
    check("workers exit when the server exits", not any(pid_alive(p) for p in pids), pids)
    srv = start_server()
    check("no worker until first use after restart; agents + transcript kept", workers() == {} and len(get("/api/agents")) == 1 and len(get(f"/api/chat/{aid}")) == before)
    r = chat(aid, "count")
    check("conversation continues after restart (model sees prior turns)", int(r["text"].split("I can see ")[1].split(" messages")[0]) > seen[1], r["text"])

    # ---- idle death
    old = workers()[aid]["pid"]; kill(old); time.sleep(1)
    r = chat(aid, "after idle kill")
    check("idle worker killed -> next request recovers on a new worker", r["error"] is None and workers()[aid]["pid"] != old and workers()[aid]["alive"], (r, workers()))

    # ---- mid-turn death: no replay, explicit error, then recovery
    slow0 = get("/stats", MOCK)["slow"]; box = {}
    th = threading.Thread(target=lambda: box.update(r=chat(aid, "SLOW please"))); th.start()
    time.sleep(8); victim = workers()[aid]["pid"]; kill(victim); th.join(60)
    time.sleep(1)
    check("worker killed mid-turn -> explicit error, not replayed",
          box["r"]["error"] and "NOT replayed" in box["r"]["error"] and get("/stats", MOCK)["slow"] == slow0 + 1, box)
    r = chat(aid, "after crash")
    check("next request after a crash recovers", r["error"] is None and workers()[aid]["pid"] != victim, r)
    check("agent state back to idle after failure", [a for a in get("/api/agents") if a["agent_id"] == aid][0]["state"] == "idle")

    # ---- in-process manager checks with the server stopped (no two workers on one profile)
    srv.terminate(); srv.wait(); time.sleep(3)
    from app import core, workers as wk
    r = core.run_turn(aid, "what do I like?", conv_override="fresh-check")
    check("memory preference reaches a brand-new session after restart", "PURPLE-OTTER" in r["text"], r)
    r = core.run_turn(aid, "SLOW again", timeout=4)
    time.sleep(1)
    check("timeout -> explicit error and worker stopped", r["error"] and "timed out" in r["error"] and not wk.status()[0]["alive"], (r, wk.status()))
    r = core.run_turn(aid, "after timeout", conv_override="fresh-check")
    check("next request after a timeout recovers", r["error"] is None and wk.status()[0]["alive"], r)
    wk.stop_all()
    srv = start_server()

    # ---- provider/model switching
    chat(aid, "warm"); p_model1 = workers()[aid]["pid"]
    conf(model="mock-model-2")
    chat(aid, "model changed")
    w = workers()[aid]
    check("model change restarts the worker with the new model", w["pid"] != p_model1 and w["model"] == "mock-model-2" and get("/stats", MOCK)["last_model"] == "mock-model-2", w)
    req_before = get("/stats", MOCK)["requests"]
    conf(provider="openai-codex", model="mock-model-2")
    r = chat(aid, "should not reach any model")
    check("switching to codex without login -> explicit login error, no silent fallback, no model request",
          r["error"] and "login_codex.bat" in r["error"] and get("/stats", MOCK)["requests"] == req_before, r)
    st = get("/api/status")
    check("status reports provider + problem", st["provider"] == "openai-codex" and st["problem"], st)
finally:
    for p in procs:
        p.terminate()
print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if results and all(results) else 1)
