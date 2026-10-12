"""LIVE diagnostic for long-lived workers (current provider; spends subscription quota, ~12 short requests, once each, no retries).
Adds turns to the main conversation and the existing specialist, and creates ONE agent named 'WORKERTEST Diagnostic Analyst'.
Starts its own server (port 8807, ECOM_TIMING=1), restarts it once, kills one idle worker. Prints a compact table.
Run: venv python tests/worker_live_diag.py   (uses the REAL runtime; no destructive steps)"""
import json, os, subprocess, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import core
PORT, SPEC = 8807, os.environ.get("DIAG_SPECIALIST", "northloom-competitor-analyst")
ENV = {**os.environ, "ECOM_TIMING": "1", "PYTHONUTF8": "1"}
LOG = ROOT / "runtime" / "timing.jsonl"
rows = []


def api(path, body=None, timeout=600):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def start():
    p = subprocess.Popen([sys.executable, "-m", "app.server", str(PORT)], cwd=ROOT, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(80):
        try:
            api("/api/status", timeout=5); return p
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("server did not start")


def ask(label, agent, msg):
    n0 = LOG.read_text(encoding="utf-8").count("\n") if LOG.exists() else 0
    t = time.perf_counter()
    r = api(f"/api/chat/{agent}", {"message": msg})
    wall = time.perf_counter() - t
    recs = [json.loads(l) for l in LOG.read_text(encoding="utf-8").splitlines()[n0:]]
    c = next((x for x in recs if x["kind"] == "chat"), None)
    ev = {e["stage"]: e for e in (c["events"] if c else [])}
    api_ms = sum(e["ms"] for e in (c["events"] if c else []) if e["stage"] == "api_end")
    tool_ms = sum((e["ms"] or 0) for e in (c["events"] if c else []) if e["stage"] == "tool")
    row = {"label": label, "agent": agent, "wall_s": round(wall, 1), "error": r.get("error"),
           "total_ms": c and c["total_ms"], "auth_ms": c and c["parent"]["auth_check_ms"], "spawned": c and c["parent"]["worker_spawned_this_turn"],
           "pid": c and c["worker"]["pid"], "turn_index": c and c["worker"]["turn_index"], "agent_inits": c and c["worker"]["agent_inits_total"],
           "import_ms": ev.get("import_hermes", {}).get("ms"), "agent_init_ms": ev.get("agent_init", {}).get("ms"),
           "pre_run_ms": c and c["pre_run_ms"], "run_conv_ms": ev.get("run_conversation", {}).get("ms"), "model_ms": round(api_ms) if c else None,
           "tool_ms": round(tool_ms) if c else None, "api_calls": c and c["api_calls"], "tool_calls": c and c["tool_calls"],
           "text": (r.get("text") or "")[:90].replace("\n", " ")}
    rows.append(row); print(json.dumps(row), flush=True)
    return r


srv = start()
try:
    ask("main cold", "main", "[workertest] Reply with just the word PONG.")
    ask("main #2", "main", "[workertest] Reply with just the word PING.")
    ask("main #3", "main", "[workertest] Reply with just the word PONG.")
    ask("specialist cold", SPEC, "[workertest] Reply with just the word PONG.")
    ask("specialist #2", SPEC, "[workertest] Reply with just the word PING.")
    ask("specialist continuity", SPEC, "[workertest] What sign-off do I want at the end of every report? Answer in a few words.")
    ask("specialist tools", SPEC, "[workertest] List the exact names of the tools you can call, comma separated, nothing else.")
    ask("main tools", "main", "[workertest] List the exact names of the tools you can call, comma separated, nothing else.")
    r = ask("create test agent (main, reused worker)", "main", "[workertest] Create a market analysis specialist named 'WORKERTEST Diagnostic Analyst' for this company. Keep its objective, instructions and one skill short.")
    snap = {"agents": sorted(a["agent_id"] for a in api("/api/agents")), "rows": {a: len(api(f"/api/chat/{a}")) for a in ["main", SPEC]}}
    memfiles = {f.name: f.stat().st_size for f in (core.HERMES_ROOT / "profiles" / SPEC / "memories").glob("*.md")}
    srv.terminate(); srv.wait(); time.sleep(3)
    srv = start()
    after = {"agents": sorted(a["agent_id"] for a in api("/api/agents")), "rows": {a: len(api(f"/api/chat/{a}")) for a in ["main", SPEC]},
             "workers_before_use": api("/api/workers")}
    print("restart:", json.dumps({"agents_kept": snap["agents"] == after["agents"], "rows_kept": snap["rows"] == after["rows"],
                                   "memory_files_kept": memfiles == {f.name: f.stat().st_size for f in (core.HERMES_ROOT / "profiles" / SPEC / "memories").glob("*.md")},
                                   "workers_running_before_first_use": after["workers_before_use"]}))
    ask("specialist after restart (cold worker)", SPEC, "[workertest] What sign-off do I want at the end of every report? Answer in a few words.")
    pid = api("/api/workers")[0]["pid"]
    subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True); time.sleep(1)
    ask("specialist after idle worker killed", SPEC, "[workertest] Reply with just the word PONG.")
finally:
    srv.terminate()
json.dump(rows, open(ROOT / "runtime" / "worker_live_diag_last.json", "w"))
