"""Ticket 05 tests: the minimal execution logbook (app/logbook.py). SCRIPTED model (tests/mock_llm.py, a test double, NOT a model) and the REAL backend, HTTP API, SQLite registry, Hermes
workers and hooks. The database is a SQLite file reached through the logbook's TEST-ONLY url scheme 'ecom-test-sqlite:<path>', so the exact INSERT/DDL statements run for real, but a live Postgres
connection is NOT exercised here (the live Supabase check is a separate step, see the ticket report). No credential, scraper, Gemini or Nebius call. Wipes the copy's runtime/ - run ONLY from a COPY of the project:
  LOGBOOK_I_AM_A_COPY=1 venv-python tests/logbook_test.py"""
import json, os, queue, shutil, sqlite3, subprocess, sys, tempfile, threading, time, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if os.environ.get("LOGBOOK_I_AM_A_COPY") != "1":
    sys.exit("Refusing to run: set LOGBOOK_I_AM_A_COPY=1 and run from a COPY of the project.")
if (ROOT / "secrets" / "local.env").exists():
    sys.exit("Refusing to run: this copy holds secrets/local.env. Real credentials must never be loaded by a test copy.")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / "hermes-agent"))
MOCK, APP = 8788, 8838
TMP = Path(tempfile.mkdtemp(prefix="logbook-test-"))
EVDB, IMGS = TMP / "events.db", TMP / "imgs"
IMGS.mkdir()
KEY = "SECRETKEY-for-test-123456"
ENV = {**os.environ, "PYTHONUTF8": "1", "ECOM_CLASSIFIER": "off", "ECOM_ASSUME_EXISTING_RUNTIME": "1", "ECOM_CHAT_MAX_ITERATIONS": "6", "MOCK_SLOW_S": "4", "ECOM_IMAGE_DIRS": str(IMGS)}
DB_VARS = ("LOGBOOK_DATABASE_URL", "NEON_DATABASE_URL")   # the current and the retired name: an offline run must NEVER inherit a live database connection from the shell
for k in ("LLM_PROVIDER", "LLM_MODEL", "NEBIUS_API_KEY", "NEBIUS_BASE_URL", "NEBIUS_MODEL", "ECOM_APP_ROOT", "HERMES_HOME", "ECOM_LOGBOOK", *DB_VARS):
    ENV.pop(k, None)
for k in DB_VARS:
    os.environ.pop(k, None)
os.environ["ECOM_ASSUME_EXISTING_RUNTIME"] = "1"   # the in-process sections below call the backend directly, like the subprocess servers do
procs, results = [], []
import atexit
atexit.register(lambda: [p.terminate() for p in procs if p.poll() is None])


def check(name, ok, detail=""):
    ok = bool(ok)
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{str(detail)[:900]}]"), flush=True)


def call(path, body=None, port=APP, timeout=600):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def spawn(args, env=None):
    p = subprocess.Popen([sys.executable, *args], cwd=ROOT, env=env or ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(p)
    return p


def start_server(url=None):
    p = spawn(["-m", "app.server", str(APP)], {**ENV, **({"LOGBOOK_DATABASE_URL": url} if url else {})})
    for _ in range(80):
        try:
            call("/api/status", timeout=5)
            return p
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("server did not start")


def stop(p):
    p.terminate()
    p.wait()
    time.sleep(2)


def chat(agent, message, rid, **extra):
    return call(f"/api/chat/{agent}", {"message": message, "request_id": rid, **extra})[1]


def tool_msg(name, args):
    return "CALL_TOOL:" + json.dumps({"name": name, "args": args})


def mock_n():
    return call("/stats", port=MOCK)[1]["requests"]


def drain(timeout=20):
    """Wait until the server's writer has handled everything it accepted."""
    end = time.time() + timeout
    d = {}
    while time.time() < end:
        d = call("/api/logbook")[1]
        if d.get("queued") == 0 and d.get("written", 0) + d.get("lost_write_failed", 0) + d.get("dropped_queue_full", 0) >= d.get("accepted", 0):
            return d
        time.sleep(0.2)
    return d


def events(where="1=1", params=(), db=EVDB):
    if not Path(db).exists():
        return []
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    out = []
    for r in c.execute(f"SELECT * FROM ecom_execution_events WHERE {where} ORDER BY ts, rowid", params):
        d = dict(r)
        for k in ("inputs", "result"):
            d[k] = json.loads(d[k]) if d[k] else None
        out.append(d)
    c.close()
    return out


def of(rid):
    drain()
    return events("request_id = ?", (rid,))


def kinds(rows):
    return [r["event_type"] for r in rows]


try:
    shutil.rmtree(ROOT / "runtime", ignore_errors=True)
    (ROOT / "secrets").mkdir(exist_ok=True)
    (ROOT / "secrets" / "local.env").write_text(f"LLM_PROVIDER=nebius-token-factory\nLLM_MODEL=mock-model\nNEBIUS_API_KEY={KEY}\nNEBIUS_BASE_URL=http://127.0.0.1:{MOCK}/v1\n", encoding="utf-8")
    subprocess.run([sys.executable, "scripts/setup.py"], cwd=ROOT, env=ENV, check=True, capture_output=True)
    import yaml
    cfg_f = ROOT / "runtime" / "hermes_home" / "profiles" / "main" / "config.yaml"
    cfg = yaml.safe_load(cfg_f.read_text(encoding="utf-8")) or {}
    cfg.setdefault("agent", {}).update(api_max_retries=1, auto_recovery_cycles=0)
    cfg_f.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    from PIL import Image
    Image.new("RGB", (64, 48), (200, 30, 30)).save(IMGS / "img-test.png")
    spawn(["tests/mock_llm.py", str(MOCK)])
    time.sleep(1)

    print("UNIT: redaction, bounds, never-raise, full queue", flush=True)
    from app import logbook as lb
    secret_in = {"api_key": "sk-live-AAAAAAAAAAAA", "Authorization": "Bearer abcdef0123456789abcdef", "nested": {"password": "pw1234567", "ok": "fine", "prompt_tokens": 42},
                 "url": "postgresql://neon_user:p4ssw0rd@ep-cool-123.neon.tech/db", "text": "call me with token=zzzz1234 and api_key = sk-test-BBBBBBBBBB please",
                 "img": "data:image/png;base64," + "QUJD" * 500, "blob": "A1b2" * 80, "big": ["x"] * 100, "deep": {"a": {"b": {"c": {"d": {"e": {"f": 1}}}}}}, "bytes": b"\x00\x01\x02"}
    clean = lb.sanitize(secret_in)
    dump = json.dumps(clean)
    check("LB-1 sanitize redacts secret-named keys and secret-looking text (keys, bearer values, URLs with passwords, key=value pairs), removes image/base64 payloads, keeps harmless fields and token COUNTS",
          all(x not in dump for x in ("sk-live-AAAA", "abcdef0123456789abcdef", "pw1234567", "p4ssw0rd", "zzzz1234", "sk-test-BBBB", "QUJDQUJD", "A1b2A1b2A1b2")) and clean["nested"]["ok"] == "fine"
          and clean["nested"]["prompt_tokens"] == 42 and clean["api_key"] == "<redacted>" and clean["Authorization"] == "<redacted>", dump[:600])
    check("LB-2 sanitize bounds lists (20 + a count), depth, bytes and the serialized size", len(clean["big"]) == 21 and clean["big"][-1] == {"_more_items": 80} and clean["bytes"] == "<3 bytes>"
          and "<depth limit>" in dump and len(json.dumps(lb.bounded({"k%d" % i: "v" * 500 for i in range(30)}))) < lb.PAYLOAD_MAX + 200, dump[-300:])
    check("LB-3 tool_result_summary keeps only allowed fields and every *_id (never raw content); tool_outcome follows the ACTUAL result (ok:false / error / status) rather than the call",
          lb.tool_result_summary(json.dumps({"ok": True, "draft_id": "d1", "content": "SECRET BODY", "image_ids": ["a"]})) == {"ok": True, "draft_id": "d1", "image_ids": ["a"], "_omitted_keys": ["content"]}
          and lb.tool_outcome("ok", json.dumps({"ok": False, "code": "x"})) == "failure" and lb.tool_outcome("ok", json.dumps({"ok": True})) == "success"
          and lb.tool_outcome("error", "plain text") == "failure" and lb.tool_outcome("ok", json.dumps({"error": "boom"})) == "failure" and lb.tool_outcome(None, "plain text") == "unknown")
    lb.S.update(role="server", enabled=True, url="ecom-test-fail:connect", writer=None)
    lb._q = queue.Queue(2)
    t0 = time.perf_counter()
    for i in range(6):
        lb.emit("tool.call", "success", request_id="q", tool_name=f"t{i}", inputs={"x": object()}, result={"y": {1, 2}})
    lb.emit("model.call", "success", request_id="q", usage={"prompt_tokens": "ten"}, duration_ms="slow", ts="never")
    el = time.perf_counter() - t0
    check("LB-4 a full queue never blocks or raises: the oldest 2 are kept, the rest are counted as dropped; odd inputs and non-numeric usage are tolerated (missing numbers stay NULL)",
          el < 0.5 and lb.stats["accepted"] == 2 and lb.stats["dropped_queue_full"] == 5, (el, lb.stats))
    row = lb._q.get_nowait()
    check("LB-5 an event row has a unique id, the request/agent/tool fields, outcome in the allowed set and ONLY numeric token values", len(row["event_id"]) == 32 and row["request_id"] == "q"
          and row["tool_name"] == "t0" and row["outcome"] == "success" and row["prompt_tokens"] is None and row["inputs"] is not None, row)
    lb.S.update(role=None, enabled=False, url="")
    n_before = lb._q.qsize()
    lb.emit("tool.call", "success", tool_name="x")
    check("LB-6 with the logbook disabled emit() does nothing at all", lb._q.qsize() == n_before, lb._q.qsize())
    lb.S["role"] = "server"
    lb.S["enabled"] = True
    lb._q = queue.Queue(10)
    lb.accept([{"event_id": "e" * 32, "event_type": "tool.call", "outcome": "bogus", "ts": "x", "inputs": {"api_key": "sk-zzzzzzzzzz", "t": "y" * 100000}, "result": None}, {"nope": 1}, "str"])
    got = lb._q.get_nowait()
    check("LB-7 rows a worker sends are shape-checked and re-bounded by the server: bad outcome -> unknown, secrets redacted, size capped, malformed rows ignored",
          got["outcome"] == "unknown" and "sk-zzzz" not in json.dumps(got) and len(json.dumps(got["inputs"])) < lb.PAYLOAD_MAX + 200 and lb._q.qsize() == 0 and isinstance(got["ts"], float), got)
    lb.S.update(role=None, enabled=False, url="")
    lb.stats.update(accepted=0, dropped_queue_full=0)
    lb._q = queue.Queue(lb.QUEUE_MAX)

    print("CORRECTIONS (review findings 1-5), in-process", flush=True)
    CORR = TMP / "corr.db"
    os.environ["LOGBOOK_DATABASE_URL"] = f"ecom-test-sqlite:{CORR}"
    lb.S.update(role=None, enabled=False, url="", writer=None)
    lb._q = queue.Queue(lb.QUEUE_MAX)
    lb.start()
    from app import server
    real = (server.routing.route, server.core.run_turn, server.core.db)
    runs = []

    def arm(text):
        server.routing.route = lambda *a, **k: {"outcome": "business_query", "handled_locally": False, "allow_create_agent": False}
        server.core.run_turn = lambda *a, **k: runs.append(k.get("request_id")) or {"text": text, "tools": [], "error": None}

    def disarm():
        server.routing.route, server.core.run_turn, server.core.db = real

    def stored(rid=None):
        lb.flush()
        return events("1=1" if rid is None else "request_id = ?", () if rid is None else (rid,), db=CORR)

    # ---- finding 1: every persisted text column is protected, and a transformed identifier still correlates backend and worker rows
    rid1, rid2 = "rq-" + KEY, "rq-" + KEY + "-other"
    lb.emit("request.start", request_id=rid1, agent_id="main", tool_name="t-" + KEY, provider="p " + KEY, model="m-" + KEY, inputs={"mark": "emit-1"})
    lb.emit("request.start", request_id=rid1, agent_id="main", inputs={"mark": "emit-2"})
    lb.accept([{"event_id": "b" * 32, "event_type": "tool.call", "request_id": rid1, "agent_id": "main", "tool_name": "x" + KEY, "provider": KEY, "model": KEY, "ts": time.time(),
                "outcome": "success", "inputs": {"mark": "worker"}, "result": None}])
    lb.emit("request.start", request_id=rid2, agent_id="main", inputs={"mark": "other"})
    lb.emit("request.start", request_id="rq-safe-1", agent_id="main", inputs={"mark": "safe-emit"})
    lb.accept([{"event_id": "c" * 32, "event_type": "tool.call", "request_id": "rq-safe-1", "agent_id": "main", "ts": time.time(), "outcome": "success", "inputs": {"mark": "safe-worker"}, "result": None}])
    allrows = stored()
    by = {(x["inputs"] or {}).get("mark"): x for x in allrows}
    check("LB-24 a configured secret used as a request id, tool name, provider or model never reaches ANY stored column (emit and worker-row acceptance), while a transformed id is deterministic: the backend row, a "
          "second backend row and the worker row for the same id carry the SAME stored id, a different id gets a different one, and a safe id is stored unchanged",
          KEY not in json.dumps(allrows) and by["emit-1"]["request_id"] == by["emit-2"]["request_id"] == by["worker"]["request_id"] and by["other"]["request_id"] != by["emit-1"]["request_id"]
          and by["safe-emit"]["request_id"] == by["safe-worker"]["request_id"] == "rq-safe-1", [(k, v["request_id"], v["tool_name"], v["provider"], v["model"]) for k, v in by.items()])

    # ---- finding 2: previews are taken from the scrubbed text; a secret straddling the 300-character boundary does not survive in part
    pad = "word " * 55 + " "   # 276 characters: the secret starts at 276 and its last character lies beyond the 300-character preview
    arm(pad + KEY + " end")
    runs.clear()
    code, rp = server.chat("main", pad + KEY + " tail", "rq-preview-1")
    prev = stored("rq-preview-1")
    ps = [x for x in prev if x["event_type"] == "request.start"][0]["inputs"]["message_preview"]
    pe = [x for x in prev if x["event_type"] == "request.end"][0]["result"]["model_provided_final_answer_preview"]
    check("LB-25 a secret that crosses the preview boundary leaves neither the full secret nor a substantial prefix in the operator-message preview or the final-answer preview (both are cut from scrubbed text)",
          code == 200 and rp["ok"] and len(runs) == 1 and all(KEY[:8] not in x and KEY not in x for x in (ps, pe)) and len(ps) <= 310 and len(pe) <= 310 and "<redacted>" in ps, (ps[-60:], pe[-60:]))

    # ---- finding 4: an accepted request whose local transcript write raises still gets exactly one terminal failure event, and no agent work is replayed to get it
    class DbProxy:
        def __init__(self, conn, pattern):
            self.c, self.pat = conn, pattern

        def __enter__(self):
            self.c.__enter__()
            return self

        def __exit__(self, *a):
            return self.c.__exit__(*a)

        def execute(self, sql, *a):
            if self.pat in " ".join(sql.split()):
                raise sqlite3.OperationalError("injected transcript write failure")
            return self.c.execute(sql, *a)

        def __getattr__(self, n):
            return getattr(self.c, n)

    def fail_db(pattern):
        server.core.db = lambda: DbProxy(real[2](), pattern)

    def run_chat(text, rid):
        try:
            return server.chat("main", text, rid), None
        except Exception as e:
            return None, e
    arm("fine")
    runs.clear()
    fail_db("INSERT INTO messages(agent_id,who,content,tools,ts) VALUES")
    ri_, ei = run_chat("hello initial", "rq-tw-init")
    server.core.db = real[2]
    ki = stored("rq-tw-init")
    n_init = len(runs)
    runs.clear()
    fail_db("INSERT INTO messages(agent_id,who,content,tools,ts,meta) VALUES")
    rf_, ef = run_chat("hello final", "rq-tw-final")
    server.core.db = real[2]
    kf = stored("rq-tw-final")
    n_final = len(runs)
    runs.clear()
    rok, eok = run_chat("hello fine", "rq-tw-ok")
    ko = stored("rq-tw-ok")
    check("LB-26 a failing INITIAL transcript write records one request.end failure (stage named) and the agent never ran; a failing FINAL write records one failure after exactly ONE agent run (no replay); the exception "
          "still propagates as before; a normal request still has exactly one terminal event",
          ei and ef and not eok and kinds(ki) == ["request.start", "request.end"] and ki[1]["outcome"] == "failure" and ki[1]["result"].get("stage") == "initial_transcript_write" and n_init == 0
          and kinds(kf) == ["request.start", "request.end"] and kf[1]["outcome"] == "failure" and kf[1]["result"].get("stage") == "final_transcript_write" and n_final == 1
          and kinds(ko) == ["request.start", "request.end"] and ko[1]["outcome"] == "success" and rok[0] == 200, (kinds(ki), kinds(kf), kinds(ko), n_init, n_final, ei, ef))
    disarm()

    # ---- finding 5: a reconnect is attempted when its deadline passes even though events keep arriving more often than the backoff
    now = {"t": 0.0}
    attempts = []
    rec_db = TMP / "recover.db"

    def connector(url):
        attempts.append(now["t"])
        if now["t"] < 25:
            raise ConnectionError("database still down")
        return lb._SqliteTestConn(str(rec_db))

    def mk(i):
        return {"event_id": f"{i:032d}", "request_id": "rq-rec", "agent_id": "main", "event_type": "tool.call", "ts": time.time(), "duration_ms": None, "provider": None, "model": None, "tool_name": None,
                "outcome": "success", "prompt_tokens": None, "completion_tokens": None, "total_tokens": None, "inputs": None, "result": None}
    real_connect, real_url = lb.connect, lb.S["url"]
    lb.connect, lb.S["url"] = connector, "scripted"
    stt = {"conn": None, "next_try": 0.0}
    lb.stats["schema_ready"] = False
    w0 = lb.stats["written"]
    for t in (0, 10, 20, 30, 40, 50):   # an event every 10 s, the backoff is 15 s, the database comes back at t=25
        now["t"] = t
        lb._flush_batch([mk(t)], stt, lambda: now["t"])
    lb.connect, lb.S["url"] = real_connect, real_url
    got = sqlite3.connect(rec_db).execute("SELECT count(*) FROM ecom_execution_events").fetchone()[0] if rec_db.exists() else 0
    check("LB-27 events arriving every 10 s (backoff 15 s) do not push the reconnect deadline forward: attempts happen at t=0, 20 and 40, the database recovers at 25, and the events at t=40 and t=50 are written "
          "without any idle period", attempts == [0, 20, 40] and got == 2 and lb.stats["written"] - w0 == 2, (attempts, got))

    # ---- finding 3: a model request start is its own observer event, linked to its completion/error by the Hermes api_request_id, and is not a second attempt
    hooks, sent = {}, []

    class Ctx:
        def register_hook(self, name, fn):
            hooks[name] = fn
    old_state = (lb.S["role"], lb._sink)
    os.environ["ECOM_LOGBOOK"] = "1"
    lb.S["role"], lb._sink = "worker", lambda rows: sent.extend(rows)
    lb.register_hooks(Ctx())
    if "pre_api_request" in hooks:
        hooks["pre_api_request"](api_request_id="api-1", api_call_count=1, provider="p", model="m", message_count=3, tool_count=2, approx_input_tokens=100, started_at=time.time(), request_messages=[{"role": "user", "content": "SECRET " + KEY}])
        hooks["pre_api_request"](api_request_id="api-2", api_call_count=2, provider="p", model="m", message_count=3, tool_count=2, started_at=time.time())
        hooks["pre_api_request"](api_request_id="api-3", api_call_count=3, provider="p", model="m", message_count=3, tool_count=2, started_at=time.time())
    hooks["post_api_request"](api_request_id="api-1", usage={"prompt_tokens": 5, "output_tokens": 2, "total_tokens": 7}, provider="p", model="m", api_duration=0.5, finish_reason="stop", api_call_count=1)
    hooks["api_request_error"](api_request_id="api-2", provider="p", model="m", api_duration=0.2, error={"type": "ServerError", "message": "boom"}, status_code=500, api_call_count=2)
    lb.S["role"], lb._sink = old_state
    os.environ.pop("ECOM_LOGBOOK", None)
    st_ = [x for x in sent if x["event_type"] == "model.start"]
    ca = [x for x in sent if x["event_type"] == "model.call"]
    link = lambda x: (x["inputs"] or {}).get("api_request_id")
    check("LB-28 pre_api_request is observed: one model.start per request (outcome unknown, no usage, no prompt text), linked by api_request_id to its model.call success or failure; a start with no observed "
          "outcome (api-3) stays 'unknown' and only the model.call rows count as executed attempts",
          len(st_) == 3 and all(x["outcome"] == "unknown" and x["prompt_tokens"] is None and "SECRET" not in json.dumps(x) for x in st_) and sorted(link(x) for x in st_) == ["api-1", "api-2", "api-3"]
          and sorted((link(x), x["outcome"]) for x in ca) == [("api-1", "success"), ("api-2", "failure")] and {link(x) for x in ca} <= {link(x) for x in st_}
          and not [x for x in sent if link(x) == "api-3" and x["event_type"] == "model.call"], [(x["event_type"], link(x), x["outcome"]) for x in sent])
    lb.flush()
    lb._q.put(lb._STOP)   # stop this section's writer so the later in-process section starts its own
    lb.S["writer"].join(5)
    lb.S.update(role=None, enabled=False, url="", writer=None)
    lb._q = queue.Queue(lb.QUEUE_MAX)
    os.environ.pop("LOGBOOK_DATABASE_URL", None)

    print("CONFIGURATION (neutral LOGBOOK_DATABASE_URL), in-process", flush=True)
    from app import core
    check("LB-32 offline isolation: neither the current nor the retired database variable is in this test's environment or in the environment it gives its servers",
          not [k for k in DB_VARS if k in os.environ or k in ENV], [k for k in DB_VARS if k in os.environ or k in ENV])
    lb.S.update(role=None, enabled=False, url="", writer=None)
    os.environ["NEON_DATABASE_URL"] = "ecom-test-sqlite:" + str(TMP / "retired.db")
    d_old = lb.start()
    os.environ.pop("NEON_DATABASE_URL")
    os.environ["LOGBOOK_DATABASE_URL"] = "ecom-test-sqlite:" + str(TMP / "neutral.db")
    url_env = lb._url()
    os.environ.pop("LOGBOOK_DATABASE_URL")
    real_secrets = core.load_secrets
    SUPA_PW, SUPA = "Pa%24sw0rd-9876", "postgresql://postgres.abcdefgh:Pa%24sw0rd-9876@aws-0-eu-west-1.pooler.supabase.com:5432/postgres?sslmode=require"
    core.load_secrets = lambda: {"LOGBOOK_DATABASE_URL": SUPA}
    try:
        url_file = lb._url()
        lb._secret_values["at"] = 0.0
        txt = f"conn {SUPA} / pw {SUPA_PW} / decoded Pa$sw0rd-9876 / FATAL password authentication failed (Pa$sw0rd-9876)"
        scrubbed = lb.scrub(txt)
    finally:
        core.load_secrets = real_secrets
        lb._secret_values["at"] = 0.0
    check("LB-33 the logger reads LOGBOOK_DATABASE_URL (environment or secrets file) and ignores the retired NEON_DATABASE_URL, whose absence is explained by the new name; the configured URI AND its password (raw and decoded) are redacted from any text",
          url_env == "ecom-test-sqlite:" + str(TMP / "neutral.db") and url_file == SUPA and d_old["enabled"] is False and "LOGBOOK_DATABASE_URL" in d_old["reason"]
          and "Pa$sw0rd" not in scrubbed and "Pa%24sw0rd" not in scrubbed and "pooler.supabase.com" not in scrubbed and scrubbed.count("<redacted>") >= 3, (url_env, d_old, scrubbed))
    seen, fake = [], type(sys)("psycopg")
    fake.connect = lambda url, **kw: seen.append((url, kw)) or "conn"
    real_pg = sys.modules.get("psycopg")
    sys.modules["psycopg"] = fake
    try:
        lb._default_connect("postgresql://u:p@h:5432/d")
        lb._default_connect("postgresql://u:p@h:5432/d?sslmode=verify-full")
    finally:
        sys.modules.pop("psycopg")
        if real_pg is not None:
            sys.modules["psycopg"] = real_pg
    check("LB-34 a URI without sslmode is connected with sslmode=require (never the plaintext-tolerant libpq default); an explicit sslmode in the URI (for example verify-full) is not overridden; bounded connect/statement timeouts stay",
          seen[0][1].get("sslmode") == "require" and "sslmode" not in seen[1][1] and seen[1][0].endswith("sslmode=verify-full") and seen[0][1]["connect_timeout"] == 5 and "statement_timeout" in seen[0][1]["options"], seen)
    os.environ["LOGBOOK_DATABASE_URL"] = "ecom-test-sqlite:" + str(TMP / "neutral.db")
    captured = {}
    from app import workers as wk
    real_run = wk.run
    wk.run = lambda agent_id, sig, env, req, timeout: captured.update(env=env) or ({"text": "ok", "tools": [], "error": None}, False)
    try:
        core.run_turn("main", "hello", request_id="lb-env")
    finally:
        wk.run = real_run
        os.environ.pop("LOGBOOK_DATABASE_URL")
    check("LB-35 the database URI is never handed to a Hermes worker (the server's single writer is the only holder), even when it is configured through the process environment",
          "env" in captured and not [k for k in captured["env"] if k in DB_VARS] and "ecom-test-sqlite" not in json.dumps(captured["env"]), sorted(k for k in captured.get("env", {}) if "DATA" in k or "LOGBOOK" in k))
    if os.environ.get("LOGBOOK_FAST") == "1":
        print("LOGBOOK_FAST=1: stopping after the in-process correction checks (the full suite runs the end-to-end ones too)", flush=True)
        raise SystemExit(0 if all(results) else 1)

    print("END TO END (real server, workers, hooks; scripted model; SQLite stands in for Postgres)", flush=True)
    srv = start_server(f"ecom-test-sqlite:{EVDB}")
    st, co = call("/api/company", {"fields": {"name": "Harbor Loom Co (synthetic)", "products": "Printed home textiles (synthetic)", "customers": "US shoppers (synthetic)", "goal": "Present our products clearly"}})
    assert st == 200, co
    call("/api/company", {"fields": {"bogus": "x"}})
    diag0 = call("/api/logbook")[1]
    check("LB-8 the local diagnostic reports enabled/configured, the driver and counters, and never the connection string", diag0["enabled"] and diag0["configured"] and "queued" in diag0 and "best effort" in diag0["delivery"]
          and str(EVDB) not in json.dumps(diag0) and "ecom-test-sqlite" not in json.dumps(diag0), diag0)

    n0 = mock_n()
    r1 = chat("main", tool_msg("read_company_context", {}), "lb-main-tool")
    n1 = mock_n() - n0
    rows = of("lb-main-tool")
    models = [x for x in rows if x["event_type"] == "model.call"]
    tl = [x for x in rows if x["event_type"] == "tool.call"]
    check("LB-9 one request's backend, model and tool events share its request id and agent (main routing path included): request.start, model.call x2, tool.call, request.end; the model-call count equals what the provider really received",
          r1["ok"] and kinds(rows)[0] == "request.start" and kinds(rows)[-1] == "request.end" and len(models) == 2 == n1 and len(tl) == 1 and {x["agent_id"] for x in rows} == {"main"}
          and len({x["request_id"] for x in rows}) == 1, (kinds(rows), n1))
    check("LB-10 model.call rows carry provider, model, duration and the usage the provider reported; tool.call carries the tool name, duration, the observed result and the model's arguments labelled as arguments",
          all(m["provider"] == "nebius-token-factory" and m["model"] == "mock-model" and m["duration_ms"] is not None and m["total_tokens"] == 15 and m["prompt_tokens"] == 10 and m["completion_tokens"] == 5
              and m["outcome"] == "success" for m in models) and tl[0]["tool_name"] == "read_company_context" and tl[0]["outcome"] == "success" and tl[0]["duration_ms"] is not None
          and tl[0]["result"]["observed_result"]["ok"] is True and "model_arguments" in tl[0]["inputs"], (models[:1], tl))
    end = rows[-1]
    check("LB-11 request.end records the outcome, duration, route outcome and the tool names; the model's final text is stored only as a labelled model-provided preview",
          end["outcome"] == "success" and end["duration_ms"] > 0 and end["result"]["route_outcome"] == "classifier_off_test_only" and end["result"]["tool_calls"] == ["read_company_context"]
          and end["result"]["model_provided_final_answer_preview"].startswith("[MOCK LLM]") and rows[0]["inputs"]["message_chars"] > 10, end)

    ra = chat("main", tool_msg("update_company", {"website": "harborloom.example.com"}), "lb-upd-ok")
    rb = chat("main", tool_msg("update_company", {"bogus": "x"}), "lb-upd-bad")
    oa, ob = [x for x in of("lb-upd-ok") if x["event_type"] == "tool.call"], [x for x in of("lb-upd-bad") if x["event_type"] == "tool.call"]
    ctx = events("event_type = 'context.save'")
    check("LB-12 a successful and a failed tool are distinguished by their ACTUAL result (the agent still finishes both requests); main's own save appears once, as its tool call, not also as a context.save",
          ra["ok"] and rb["ok"] and oa[0]["outcome"] == "success" and oa[0]["result"]["observed_result"].get("changed") and ob[0]["outcome"] == "failure" and ob[0]["result"]["observed_result"]["code"] == "unknown_field"
          and not [c for c in ctx if c["request_id"] in ("lb-upd-ok", "lb-upd-bad")], (oa, ob))
    check("LB-13 a company save that did not come through main's tool (the web form) is recorded as context.save, success and failure, attributed to the operator with the sanitized fields",
          sorted(c["outcome"] for c in ctx if c["inputs"]["source"] == "form") == ["failure", "success"] and all(c["agent_id"] == "operator" for c in ctx if c["inputs"]["source"] == "form")
          and any(c["result"].get("code") == "unknown_field" for c in ctx), ctx)

    rc = chat("main", "please create_social_agent", "lb-create")
    cr = [x for x in of("lb-create") if x["event_type"] == "tool.call"]
    rc2 = chat("main", "please create_social_agent", "lb-create2")
    cr2 = [x for x in of("lb-create2") if x["event_type"] == "tool.call"]
    sid = "acme-social-media-specialist"
    check("LB-14 specialist creation is recorded from the backend's real result: the first create_agent succeeds with the new agent id and tools, a second one for the same role fails with role_exists",
          rc["ok"] and cr[0]["tool_name"] == "create_agent" and cr[0]["outcome"] == "success" and cr[0]["result"]["observed_result"]["agent_id"] == sid and "inspect_image" in cr[0]["result"]["observed_result"]["granted_tools"]
          and rc2["ok"] and cr2[0]["outcome"] == "failure" and cr2[0]["result"]["observed_result"]["code"] == "role_exists", (cr, cr2))
    rz = chat(sid, tool_msg("customize_specialist", {"objective": "Describe Acme Linens bedding photos precisely for promotional copy; nothing is posted."}), "lb-cust", customize=True)
    rcat = chat(sid, tool_msg("read_catalogue", {}), "lb-cat")   # no catalogue is configured in this copy: a real, backend-produced failure
    cz, czn = of("lb-cust"), of("lb-cat")
    ct = [x for x in cz if x["event_type"] == "tool.call"][0]
    ctf = [x for x in czn if x["event_type"] == "tool.call"]
    check("LB-15 customization is recorded under the SPECIALIST's identity with its own request id (applied fields on success); a specialist tool whose real result is an error (read_catalogue without a catalogue) is a recorded failure with its code",
          rz["ok"] and ct["agent_id"] == sid and ct["outcome"] == "success" and "objective" in json.dumps(ct["result"]["observed_result"]["applied"]) and {x["agent_id"] for x in cz} == {sid}
          and rcat["ok"] and ctf and ctf[0]["tool_name"] == "read_catalogue" and ctf[0]["outcome"] == "failure" and ctf[0]["result"]["observed_result"]["ok"] is False and ctf[0]["result"]["observed_result"]["code"],
          ([x["event_type"] for x in cz], czn))

    n_a = mock_n()
    d1 = chat("main", "hello once", "lb-dup")
    n_b = mock_n()
    d2 = chat("main", "hello once", "lb-dup")
    rows = of("lb-dup")
    check("LB-16 a duplicate submit of a COMPLETED request returns the stored result, runs nothing again (no new model or tool call) and is recorded as ONE request.duplicate, not as another run",
          d1["ok"] and d2.get("replayed") and mock_n() == n_b and n_b - n_a == 1 and kinds(rows).count("request.start") == 1 and kinds(rows).count("request.end") == 1 and kinds(rows).count("request.duplicate") == 1
          and kinds(rows).count("model.call") == 1 and [x for x in rows if x["event_type"] == "request.duplicate"][0]["result"]["executed_again"] is False, (kinds(rows), n_b - n_a))
    n_c = mock_n()
    box = {}
    th = threading.Thread(target=lambda: box.update(r=chat("main", "SLOW please", "lb-inflight")))
    th.start()
    time.sleep(1.2)
    dup = call("/api/chat/main", {"message": "SLOW please", "request_id": "lb-inflight"})
    th.join()
    rows = of("lb-inflight")
    check("LB-17 a duplicate of a request that is STILL RUNNING is refused (409), runs nothing, and is recorded once as a failed request.duplicate while the original keeps exactly its own model call",
          dup[0] == 409 and dup[1]["code"] == "duplicate_in_flight" and box["r"]["ok"] and mock_n() - n_c == 1 and kinds(rows).count("model.call") == 1 and kinds(rows).count("request.duplicate") == 1
          and [x for x in rows if x["event_type"] == "request.duplicate"][0]["outcome"] == "failure", (dup, kinds(rows)))

    hostile = f"my key is {KEY} and api_key=sk-LIVE-abcdef1234567890 and postgresql://neon_user:p4ssw0rd@ep-cool.neon.tech/db and Authorization: Bearer abcdef123456789012345 " + "lorem ipsum " * 600
    rh = chat("main", hostile, "lb-hostile")
    ri = chat(sid, tool_msg("inspect_image", {"image_id": "img-test"}), "lb-image")
    rows = of("lb-hostile") + of("lb-image")
    alltext = json.dumps(events())
    big = max(len(json.dumps(x["inputs"])) + len(json.dumps(x["result"])) for x in events())
    img = [x for x in of("lb-image") if x["event_type"] == "tool.call"]
    check("LB-18 secrets and payloads never reach the table: a hostile message (this project's own key, api_key=, a URL with a password, a bearer header) is stored redacted and truncated; an inspected image appears as ids only, "
          "no base64/data URL; every stored payload is within the size bound",
          rh["ok"] and ri["ok"] and all(x not in alltext for x in (KEY, "sk-LIVE-abcdef", "p4ssw0rd", "abcdef123456789012345", "base64", "data:image")) and img and img[0]["tool_name"] == "inspect_image"
          and big < 2 * lb.PAYLOAD_MAX + 400 and len([x for x in of("lb-hostile") if x["event_type"] == "request.start"][0]["inputs"]["message_preview"]) <= lb.TEXT_MAX, (big, img[:1]))

    print("ONBOARDING AND ITS IDENTITY", flush=True)
    stt, _ = call("/api/onboarding/start", {})
    ss, sr = call("/api/onboarding/source", {"url": "https://northloom-demo.example.com"})
    ans = {"answers": {"q1": {"choice": 0}, "q2": {"choice": 1}, "q3": {"write_in": "Make clear promotional flyers and understand competitor prices"}, "q4": {"choice": 0}, "q5": {"choice": 1}}, "correction": ""}
    sa, ar = call("/api/onboarding/answers", ans)
    drain()
    ob = events("event_type LIKE 'onboarding.%'")
    src = [x for x in ob if x["event_type"] == "onboarding.source"]
    anw = [x for x in ob if x["event_type"] == "onboarding.answers"]
    same = events("request_id = ?", (src[0]["request_id"],)) if src else []
    same2 = events("request_id = ?", (anw[0]["request_id"],)) if anw else []
    check("LB-19 onboarding steps are recorded with a request id that its own model turns and the shared-context save carry: onboarding.source with a main model.call; onboarding.answers with a model.call and a context.save (source onboarding)",
          stt == 200 and ss == 200 and sa == 200 and len(src) == 1 == len(anw) and src[0]["outcome"] == "success" and anw[0]["outcome"] == "success" and anw[0]["result"]["state"] == "ready"
          and any(x["event_type"] == "model.call" for x in same) and any(x["event_type"] == "model.call" for x in same2)
          and any(x["event_type"] == "context.save" and x["inputs"]["source"] == "onboarding" and x["outcome"] == "success" for x in same2), (kinds(same), kinds(same2)))
    # ---- corrections, end to end
    n_slow = mock_n()
    th = threading.Thread(target=lambda: box.update(slow=chat("main", "SLOW start probe", "lb-start-slow")))
    th.start()
    for _ in range(300):   # wait until the provider has RECEIVED the request (it sleeps 4 s before answering), whatever the worker's start-up time
        if mock_n() > n_slow:
            break
        time.sleep(0.1)
    time.sleep(0.8)
    drain(3)   # the request is IN FLIGHT now
    mid = events("request_id = ?", ("lb-start-slow",))
    th.join()
    after = of("lb-start-slow")
    s_mid = [x for x in mid if x["event_type"] == "model.start"]
    c_after = [x for x in after if x["event_type"] == "model.call"]
    s_after = [x for x in after if x["event_type"] == "model.start"]
    check("LB-29 end to end, a model request that is still being answered is already visible as a model.start (outcome unknown, no model.call yet); when it completes the model.call carries the same api_request_id, "
          "and there is exactly one start and one completed call for the one provider request",
          len(s_mid) == 1 and s_mid[0]["outcome"] == "unknown" and not [x for x in mid if x["event_type"] == "model.call"] and len(c_after) == 1 == len(s_after)
          and (s_mid[0]["inputs"] or {}).get("api_request_id") and s_mid[0]["inputs"]["api_request_id"] == c_after[0]["inputs"]["api_request_id"] and s_after[0]["ts"] <= c_after[0]["ts"]
          and kinds(after)[-1] == "request.end", (kinds(mid), kinds(after)))
    f0 = call("/stats", port=MOCK)[1].get("failed_500", 0)
    r5 = chat("main", "LLM_500 please fail", "lb-500")
    f1 = call("/stats", port=MOCK)[1].get("failed_500", 0) - f0
    r5rows = of("lb-500")
    s5, c5 = [x for x in r5rows if x["event_type"] == "model.start"], [x for x in r5rows if x["event_type"] == "model.call"]
    check("LB-30 a provider failure is recorded as model.start + model.call(failure) with the same api_request_id for every real attempt the provider saw, and the request ends as a failure",
          not r5["ok"] and f1 >= 1 and len(s5) == len(c5) == f1 and all(x["outcome"] == "failure" for x in c5) and {x["inputs"]["api_request_id"] for x in s5} == {x["inputs"]["api_request_id"] for x in c5}
          and [x for x in r5rows if x["event_type"] == "request.end"][0]["outcome"] == "failure", (f1, kinds(r5rows)))
    sec_rid = "rq-" + KEY
    rs = chat("main", tool_msg("read_company_context", {}), sec_rid)
    ident = getattr(lb, "ident", lambda x: x)
    srows = of(ident(sec_rid))
    check("LB-31 end to end, a request whose client-chosen id contains this project's secret is stored under a safe deterministic id that BOTH the backend and the worker events carry (request.start, model.start, "
          "model.call, tool.call, request.end), and the secret appears nowhere in the table",
          rs["ok"] and KEY not in json.dumps(events()) and {"request.start", "model.start", "model.call", "tool.call", "request.end"} <= set(kinds(srows)) and len({x["request_id"] for x in srows}) == 1, (kinds(srows),))
    stop(srv)

    print("LOGGING UNAVAILABLE OR BROKEN: the agent's result must not change", flush=True)
    base_tools = [t["tool"] for t in r1["activity"]]

    def same_result(r):
        return r["ok"] and not r.get("error") and r["text"].startswith("[MOCK LLM]") and [t["tool"] for t in r["activity"]] == base_tools and all(t["status"] == "ok" for t in r["activity"])
    ev_before = len(events())
    srv = start_server()   # no connection string at all
    n0 = mock_n()
    rd = chat("main", tool_msg("read_company_context", {}), "lb-off-1")
    dd = call("/api/logbook")[1]
    check("LB-20 logging disabled (no LOGBOOK_DATABASE_URL): the agent behaves exactly as before (same tool path, 2 provider requests), nothing is accepted or written, and the diagnostic says why",
          same_result(rd) and mock_n() - n0 == 2 and dd["enabled"] is False and "LOGBOOK_DATABASE_URL" in dd["reason"] and dd["accepted"] == 0 and dd["written"] == 0 and len(events()) == ev_before, dd)
    stop(srv)
    for label, url, expect in (("unreachable database (connect fails, the error text carries a password)", "ecom-test-fail:connect", "connection"),
                               ("writer failure after connecting (the insert fails)", "ecom-test-fail:insert", "insert failure"),
                               ("a real postgres URL whose host is unreachable/driver absent", "postgresql://logbook_user:s3cretpw@127.0.0.1:9/db?sslmode=disable", "")):
        srv = start_server(url)
        n0 = mock_n()
        rf = chat("main", tool_msg("read_company_context", {}), f"lb-fail-{expect[:4]}")
        df = drain()
        blob = json.dumps(df) + json.dumps(rf)
        check(f"LB-21 {label}: the agent's result is unchanged (same tools/status, 2 provider requests), the diagnostic admits the loss (written 0, lost > 0, a redacted last_error) and no credential or URL appears anywhere",
              same_result(rf) and mock_n() - n0 == 2 and df["enabled"] and df["written"] == 0 and df["lost_write_failed"] > 0 and df["last_error"] and "hunter2secret" not in blob and "s3cretpw" not in blob
              and "ecom-test-fail" not in blob and "logbook_user" not in blob, df)
        stop(srv)
    check("LB-22 the separate event database stayed untouched by the broken-logging runs", len(events()) == ev_before, (len(events()), ev_before))

    print("IN-PROCESS: a request answered locally by routing (no model, no worker)", flush=True)
    lb.S.update(role=None, enabled=False, url="")
    lb._q = queue.Queue(lb.QUEUE_MAX)
    for k in list(lb.stats):
        lb.stats[k] = 0 if isinstance(lb.stats[k], int) else None
    os.environ["LOGBOOK_DATABASE_URL"] = f"ecom-test-sqlite:{TMP / 'local.db'}"
    lb.start()
    from app import server
    calls = []
    server.routing.route = lambda *a, **k: {"outcome": "out_of_scope", "handled_locally": True, "reply": "That is outside what this workspace does.", "allow_create_agent": False}
    server.core.run_turn = lambda *a, **k: calls.append(a) or {"text": "SHOULD NOT RUN", "tools": [], "error": None}
    code, rl = server.chat("main", "What is the weather today?", "lb-local")
    lb.flush()
    lr = events("request_id = ?", ("lb-local",), db=TMP / "local.db")
    check("LB-23 a request answered locally by routing is recorded as request.start + request.end(handled_locally, route outcome) and nothing else: no worker was used, no model or tool event exists",
          code == 200 and rl["text"].startswith("That is outside") and not calls and kinds(lr) == ["request.start", "request.end"] and lr[1]["result"]["handled_locally"] is True
          and lr[1]["result"]["route_outcome"] == "out_of_scope" and lr[1]["outcome"] == "success", (kinds(lr), calls))
except Exception:
    import traceback
    traceback.print_exc()
    check("HARNESS: unexpected exception (see traceback above)", False, "")
finally:
    for p in procs:
        if p.poll() is None:
            p.terminate()
    print(f"\nLOGBOOK TESTS {sum(results)}/{len(results)}")
    sys.exit(0 if results and all(results) else 1)
