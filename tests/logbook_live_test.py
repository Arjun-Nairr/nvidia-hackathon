"""Ticket 05 LIVE DATABASE check: ONE scripted application request whose execution events go to the REAL Postgres (Supabase) named by LOGBOOK_LIVE_URL, then read back by request id.
The model is the scripted test double tests/mock_llm.py (NOT a model); the backend, HTTP API, SQLite registry, Hermes worker and hooks are real. Company data is synthetic. No ChatGPT, NVIDIA/Nebius,
Gemini or scraper call. The URL is passed ONLY to the server process (as LOGBOOK_DATABASE_URL) and is never printed. Wipes the copy's runtime/ - run ONLY from a COPY of the project:
  LOGBOOK_LIVE_I_AM_A_COPY=1 LOGBOOK_LIVE_URL=<postgres uri> venv-python tests/logbook_live_test.py"""
import json, os, shutil, subprocess, sys, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if os.environ.get("LOGBOOK_LIVE_I_AM_A_COPY") != "1":
    sys.exit("Refusing to run: set LOGBOOK_LIVE_I_AM_A_COPY=1 and run from a COPY of the project.")
if (ROOT / "secrets" / "local.env").exists():
    sys.exit("Refusing to run: this copy holds secrets/local.env. Only the database URL is passed in, through LOGBOOK_LIVE_URL.")
URL = os.environ.get("LOGBOOK_LIVE_URL", "")
if not URL.startswith(("postgresql://", "postgres://")):
    sys.exit("Refusing to run: LOGBOOK_LIVE_URL must be a postgresql:// URI.")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / "hermes-agent"))
MOCK, APP, KEY = 8789, 8839, "SECRETKEY-for-test-123456"
ENV = {**os.environ, "PYTHONUTF8": "1", "ECOM_CLASSIFIER": "off", "ECOM_ASSUME_EXISTING_RUNTIME": "1", "ECOM_CHAT_MAX_ITERATIONS": "6"}
for k in ("LLM_PROVIDER", "LLM_MODEL", "NEBIUS_API_KEY", "NEBIUS_BASE_URL", "NEBIUS_MODEL", "ECOM_APP_ROOT", "HERMES_HOME", "ECOM_LOGBOOK", "LOGBOOK_LIVE_URL", "LOGBOOK_DATABASE_URL", "NEON_DATABASE_URL"):
    ENV.pop(k, None)
procs, results = [], []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{str(detail)[:600]}]"), flush=True)


def call(path, body=None, port=APP, timeout=300):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
    r = urllib.request.urlopen(req, timeout=timeout)
    return json.loads(r.read())


def spawn(args, env):
    p = subprocess.Popen([sys.executable, *args], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(p)
    return p


rid = "live-supabase-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
try:
    shutil.rmtree(ROOT / "runtime", ignore_errors=True)
    (ROOT / "secrets").mkdir(exist_ok=True)
    cfg_env = ROOT / "secrets" / "local.env"
    cfg_env.write_text(f"LLM_PROVIDER=nebius-token-factory\nLLM_MODEL=mock-model\nNEBIUS_API_KEY={KEY}\nNEBIUS_BASE_URL=http://127.0.0.1:{MOCK}/v1\n", encoding="utf-8")
    subprocess.run([sys.executable, "scripts/setup.py"], cwd=ROOT, env=ENV, check=True, capture_output=True)
    spawn(["tests/mock_llm.py", str(MOCK)], ENV)
    time.sleep(1)
    spawn(["-m", "app.server", str(APP)], {**ENV, "LOGBOOK_DATABASE_URL": URL})
    for _ in range(80):
        try:
            call("/api/status", timeout=5)
            break
        except Exception:
            time.sleep(0.5)
    call("/api/company", {"fields": {"name": "Harbor Loom Co (synthetic)", "products": "Printed home textiles (synthetic)", "customers": "US shoppers (synthetic)", "goal": "Present our products clearly"}})
    d0 = call("/api/logbook")
    check("L-1 the server enabled the logbook for the live database (driver present, connection string not exposed)", d0["enabled"] and d0["configured"] and d0["driver"] == "psycopg" and "postgres" not in json.dumps(d0), d0)
    r = call("/api/chat/main", {"message": "CALL_TOOL:" + json.dumps({"name": "read_company_context", "args": {}}), "request_id": rid})
    d = {}
    for _ in range(60):   # wait for the single background writer
        d = call("/api/logbook")
        if d["queued"] == 0 and d["written"] + d["lost_write_failed"] + d["dropped_queue_full"] >= d["accepted"] > 0:
            break
        time.sleep(0.5)
    check("L-2 the scripted request finished and the background writer reports every accepted row written, none failed, lost or dropped",
          r.get("ok") and d["accepted"] == d["written"] > 0 and d["batches_failed"] == 0 and d["lost_write_failed"] == 0 and d["dropped_queue_full"] == 0 and d["last_error"] is None, d)

    import psycopg
    with psycopg.connect(URL, connect_timeout=10) as c:
        rows = c.execute("SELECT event_type, agent_id, request_id, outcome, tool_name, provider, model, prompt_tokens, inputs, result FROM ecom_execution_events WHERE request_id = %s ORDER BY ts, event_id", (rid,)).fetchall()
        ssl = c.pgconn.ssl_in_use
    ev = [dict(zip(("event_type", "agent_id", "request_id", "outcome", "tool_name", "provider", "model", "prompt_tokens", "inputs", "result"), x)) for x in rows]
    kinds = [e["event_type"] for e in ev]
    starts, calls = [e for e in ev if e["event_type"] == "model.start"], [e for e in ev if e["event_type"] == "model.call"]
    tools = [e for e in ev if e["event_type"] == "tool.call"]
    link = lambda e: (e["inputs"] or {}).get("api_request_id")
    check("L-3 the connection used TLS", ssl is True, ssl)
    check("L-4 request.start, 2 model.start, 2 model.call, tool.call and request.end are queryable from the live database under ONE request id and the main agent id",
          kinds.count("request.start") == 1 and kinds.count("request.end") == 1 and len(starts) == 2 and len(calls) == 2 and len(tools) == 1 and {e["request_id"] for e in ev} == {rid} and {e["agent_id"] for e in ev} == {"main"}, kinds)
    check("L-5 each model.start is linked by api_request_id to a successful model.call that carries the usage the (scripted) provider reported; the starts are not counted as calls",
          sorted(map(link, starts)) == sorted(map(link, calls)) and all(e["outcome"] == "unknown" for e in starts) and all(e["outcome"] == "success" and e["prompt_tokens"] == 10 for e in calls), [(e["event_type"], link(e), e["outcome"]) for e in ev])
    check("L-6 the actual tool result is stored: read_company_context succeeded and its observed result is present",
          tools and tools[0]["tool_name"] == "read_company_context" and tools[0]["outcome"] == "success" and tools[0]["result"]["observed_result"]["ok"] is True, tools)
    check("L-7 the request.end row records success and the configured test key and connection URI appear nowhere in the stored rows", ev[-1]["event_type"] == "request.end" and ev[-1]["outcome"] == "success" and KEY not in json.dumps(ev, default=str) and URL not in json.dumps(ev, default=str), ev[-1])
    print(f"SAFE REQUEST ID: {rid}", flush=True)
except Exception as e:
    check("live run completed without an exception", False, type(e).__name__)   # never print the exception text: a driver error could name the host
finally:
    for p in procs:
        if p.poll() is None:
            p.terminate()
print(f"{sum(results)}/{len(results)} passed", flush=True)
sys.exit(0 if results and all(results) else 1)
