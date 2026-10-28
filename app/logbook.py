"""Minimal execution logbook (ticket 05): ONE append-only Postgres (Supabase) table of backend-observed events, written best-effort by a small bounded background writer.
SQLite stays authoritative for application state, permissions, artifacts and attempt limits; this log is evidence only and never decides anything.
Events come from the backend (request start/end/duplicate, onboarding steps, shared-context saves) and from Hermes' own observer hooks in the worker (model call, tool call): a model
call and a tool call are recorded when they COMPLETED (one row each, with their result), never merely because the model asked. Workers do not hold the database credential: they
send their rows to the server over the existing worker protocol and the server's single writer stores them.
Optional by design: no LOGBOOK_DATABASE_URL, a missing driver, an unreachable database, a failing write or a full queue never change an agent's result; emit() never raises and never
blocks. Delivery is best effort: there is no durable queue or replay, so events can be lost (queue full, database down, abrupt shutdown); diagnostics() says how many.
No hidden reasoning, prompts, replies, API keys, authentication headers, database URLs or image payloads are stored: see sanitize() and the allowed fields at each call site."""
import atexit, datetime, functools, hashlib, json, os, queue, re, threading, time, uuid
from urllib.parse import unquote, urlsplit
from contextlib import contextmanager

TABLE = "ecom_execution_events"
QUEUE_MAX, BATCH_MAX, RECONNECT_S, FLUSH_S = 1000, 50, 15.0, 3.0
TEXT_MAX, ITEMS_MAX, KEYS_MAX, DEPTH_MAX, PAYLOAD_MAX, ID_MAX, LABEL_MAX = 600, 20, 30, 5, 6000, 80, 120
OUTCOMES = ("success", "failure", "unknown")
DB_ENV_VARS = ("LOGBOOK_DATABASE_URL", "NEON_DATABASE_URL")   # the setting and its retired name; the server alone reads the first, nothing else may carry either
DDL = (f"CREATE TABLE IF NOT EXISTS {TABLE}(event_id TEXT PRIMARY KEY, request_id TEXT, agent_id TEXT, event_type TEXT NOT NULL, ts TIMESTAMPTZ NOT NULL, duration_ms DOUBLE PRECISION, "
       "provider TEXT, model TEXT, tool_name TEXT, outcome TEXT NOT NULL CHECK (outcome IN ('success','failure','unknown')), "
       "prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER, inputs JSONB, result JSONB)",
       f"CREATE INDEX IF NOT EXISTS {TABLE}_request_idx ON {TABLE}(request_id, ts)")
INSERT = (f"INSERT INTO {TABLE}(event_id, request_id, agent_id, event_type, ts, duration_ms, provider, model, tool_name, outcome, prompt_tokens, completion_tokens, total_tokens, inputs, result) "
          "VALUES (%s,%s,%s,%s,to_timestamp(%s),%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb) ON CONFLICT (event_id) DO NOTHING")
COLS = ("event_id", "request_id", "agent_id", "event_type", "ts", "duration_ms", "provider", "model", "tool_name", "outcome", "prompt_tokens", "completion_tokens", "total_tokens", "inputs", "result")
INSPECT_ONE_REQUEST = f"SELECT ts, event_type, agent_id, tool_name, model, outcome, duration_ms, prompt_tokens, completion_tokens, result FROM {TABLE} WHERE request_id = %s ORDER BY ts, event_id"

_q = queue.Queue(QUEUE_MAX)
_STOP = object()
_lock = threading.Lock()
_tl = threading.local()
_sink = None   # in a worker: callable(list of rows) that forwards them to the server
S = {"role": None, "enabled": False, "reason": "logbook not started", "url": "", "writer": None}
stats = {"accepted": 0, "written": 0, "dropped_queue_full": 0, "lost_write_failed": 0, "batches_failed": 0, "last_error": None, "last_ok_ts": None, "schema_ready": False}
connect = None   # test seam: replaced by a callable(url) -> connection; default below


# ------------------------------------------------------------------ redaction and bounds
_SECRET_KEY = re.compile(r"(?:.*_)?(?:api_?key|secret|password|passwd|authorization|cookie|dsn|credentials?|private_key|database_url|connection_string|token|bearer)", re.I)
_URL_CRED = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s/@:]+(?::[^\s/@]*)?@[^\s\"']+", re.I)
_BEARER = re.compile(r"\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}", re.I)
_DATA_URL = re.compile(r"data:[a-z]+/[a-z0-9.+-]+;base64,[A-Za-z0-9+/=_-]*", re.I)
_LONG_B64 = re.compile(r"[A-Za-z0-9+/=_-]{200,}")
_KV_SECRET = re.compile(r"(?i)\b((?:[a-z0-9_]*_)?(?:api_?key|secret|password|passwd|token|authorization))\b\s*[=:]\s*[\"']?[^\s\"',;&]{4,}")
_secret_values = {"at": 0.0, "vals": ()}


def _known_secrets():
    """Values of this project's own configured secrets (cached 60 s); any text containing one is scrubbed."""
    if time.time() - _secret_values["at"] > 60:
        vals = []
        try:
            from app import core
            for k, v in core.load_secrets().items():
                if _SECRET_KEY.fullmatch(k) and len(v) >= 8:
                    vals.append(v)
        except Exception:
            pass
        u = os.environ.get("LOGBOOK_DATABASE_URL") or S["url"]
        if u:
            vals.append(u)
        for v in list(vals):   # the password inside a configured connection URI is a secret on its own (it can appear in a driver message without the rest of the URI)
            try:
                pw = urlsplit(v).password
            except ValueError:
                pw = None
            if pw and len(pw) >= 8:
                vals += [pw, unquote(pw)]
        _secret_values.update(at=time.time(), vals=tuple(sorted(set(vals), key=len, reverse=True)))
    return _secret_values["vals"]


def scrub(s, limit=TEXT_MAX):
    """One string with credentials, URLs with passwords, bearer values, key=value secrets and image/base64 payloads removed, then truncated (limit=None: not truncated)."""
    for v in _known_secrets():
        s = s.replace(v, "<redacted>")
    s = _URL_CRED.sub("<redacted-url>", s)
    s = _BEARER.sub("<redacted>", s)
    s = _DATA_URL.sub("<image data omitted>", s)
    s = _KV_SECRET.sub(lambda m: m.group(1) + "=<redacted>", s)
    s = _LONG_B64.sub("<long encoded data omitted>", s)
    return s if limit is None or len(s) <= limit else s[:limit] + f"...[+{len(s) - limit} chars]"


def preview(text, n=300):
    """The first n characters of the SCRUBBED text (never slice before scrubbing: a secret cut at the boundary would no longer match). None when the logbook is off."""
    return scrub(str(text or ""), limit=None)[:n] if _on() else None


def ident(v):
    """A stored identifier (request or agent id): unchanged when it is safe, otherwise a deterministic digest, so a backend row and a worker row for the same id still correlate and the
    secret-bearing text itself is never stored."""
    if v is None:
        return None
    t = str(v)
    return t if len(t) <= ID_MAX and scrub(t) == t else "id-" + hashlib.sha256(t.encode("utf-8", "replace")).hexdigest()[:20]


def label(v, n=LABEL_MAX):
    """A short stored text column (event type, provider, model, tool name): scrubbed, then cut."""
    return None if v is None else scrub(str(v), limit=None)[:n]


def sanitize(v, depth=0):
    """JSON-able, bounded copy of v: secret-named keys redacted, strings scrubbed and truncated, lists/dicts/depth capped, bytes and unknown objects reduced to a label."""
    if v is None or isinstance(v, (bool, int, float)):
        return v
    if isinstance(v, str):
        return scrub(v)
    if isinstance(v, (bytes, bytearray)):
        return f"<{len(v)} bytes>"
    if depth >= DEPTH_MAX:
        return "<depth limit>"
    if isinstance(v, dict):
        out = {}
        for i, (k, x) in enumerate(v.items()):
            if i >= KEYS_MAX:
                out["_more_keys"] = len(v) - KEYS_MAX
                break
            k = scrub(str(k))[:80]
            out[k] = "<redacted>" if _SECRET_KEY.fullmatch(k.lower()) else sanitize(x, depth + 1)
        return out
    if isinstance(v, (list, tuple, set)):
        seq = list(v)
        out = [sanitize(x, depth + 1) for x in seq[:ITEMS_MAX]]
        return out + [{"_more_items": len(seq) - ITEMS_MAX}] if len(seq) > ITEMS_MAX else out
    return scrub(str(v))


def bounded(v):
    """sanitize() and a final cap on the serialized size."""
    v = sanitize(v)
    if v is None:
        return None
    raw = json.dumps(v, ensure_ascii=False, default=str)
    return v if len(raw) <= PAYLOAD_MAX else {"_truncated": True, "preview": raw[:PAYLOAD_MAX // 2]}


_KEEP = {"ok", "code", "error", "status", "hint", "verdict", "state", "count", "total", "applied", "kept", "granted_tools", "custom_skills", "missing", "allowance", "cached", "replayed",
         "delivery", "changed", "complete", "meta", "attempt_no", "note"}


def tool_result_summary(raw):
    """What the BACKEND observed a tool return, reduced to an allowed set of fields: outcome flags, error code/message, counts and every *_id (artifact identifiers). Never raw content."""
    obj = raw
    if isinstance(raw, str):
        try:
            obj = json.loads(raw)
        except ValueError:
            return {"text": raw}
    if isinstance(obj, dict):
        out = {k: v for k, v in obj.items() if k in _KEEP or k.endswith("_id") or k.endswith("_ids")}
        rest = sorted(k for k in obj if k not in out)
        return {**out, **({"_omitted_keys": rest[:20]} if rest else {})}
    return {"type": type(obj).__name__}


def tool_outcome(status, raw):
    """success / failure / unknown from the tool's ACTUAL result (and Hermes' status), never from the fact that the model asked for it."""
    obj = raw
    if isinstance(raw, str):
        try:
            obj = json.loads(raw)
        except ValueError:
            obj = None
    if isinstance(obj, dict) and (obj.get("ok") is False or (obj.get("error") and obj.get("ok") is not True)):
        return "failure"
    if status in ("error", "cancelled", "blocked", "timeout"):
        return "failure"
    if status == "ok" or isinstance(obj, (dict, list)):
        return "success"
    return "unknown"


# ------------------------------------------------------------------ context and emit
@contextmanager
def bind(request_id=None, agent_id=None):
    """Server side: events emitted in this thread inside the block carry this request and agent (worker events carry the turn's own)."""
    old = (getattr(_tl, "request_id", None), getattr(_tl, "agent_id", None))
    _tl.request_id, _tl.agent_id = request_id, agent_id
    try:
        yield
    finally:
        _tl.request_id, _tl.agent_id = old


def current_request():
    rid = getattr(_tl, "request_id", None)
    if rid:
        return rid
    try:
        from app import turn_state
        return turn_state.request_id
    except Exception:
        return None


def _on():
    return bool(_sink) if S["role"] == "worker" else S["enabled"]


def enabled():
    return S["enabled"]


def _num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else None   # missing usage/duration stays unknown (NULL), never 0


def emit(event_type, outcome="unknown", *, request_id=None, agent_id=None, duration_ms=None, provider=None, model=None, tool_name=None, usage=None, inputs=None, result=None, ts=None):
    """Record one event. NEVER raises and never waits: no configuration -> nothing; full queue -> counted and dropped."""
    try:
        if not _on():
            return
        usage = usage if isinstance(usage, dict) else {}
        row = {"event_id": uuid.uuid4().hex, "request_id": ident(request_id or current_request()), "agent_id": ident(agent_id or getattr(_tl, "agent_id", None) or os.environ.get("ECOM_AGENT_ID")),
               "event_type": label(event_type, 60), "ts": ts if isinstance(ts, (int, float)) and not isinstance(ts, bool) else time.time(), "duration_ms": _num(duration_ms),
               "provider": label(provider), "model": label(model), "tool_name": label(tool_name),
               "outcome": outcome if outcome in OUTCOMES else "unknown", "prompt_tokens": _num(usage.get("prompt_tokens")), "completion_tokens": _num(usage.get("completion_tokens")),
               "total_tokens": _num(usage.get("total_tokens")), "inputs": bounded(inputs), "result": bounded(result)}
        if _sink:
            _sink([row])
        else:
            _enqueue(row)
    except Exception:
        pass


def _enqueue(row):
    try:
        _q.put_nowait(row)
        stats["accepted"] += 1
    except queue.Full:
        stats["dropped_queue_full"] += 1


def accept(rows):
    """Server: rows a worker sent over the protocol. Shape-checked and re-bounded here; anything odd is ignored."""
    try:
        if not S["enabled"] or not isinstance(rows, list):
            return
        for r in rows[:BATCH_MAX]:
            if isinstance(r, dict) and r.get("event_id") and r.get("event_type"):
                row = {c: r.get(c) for c in COLS}
                row["inputs"], row["result"] = bounded(row["inputs"]), bounded(row["result"])
                row["event_id"] = row["event_id"] if isinstance(row["event_id"], str) and re.fullmatch(r"[0-9a-f]{32}", row["event_id"]) else uuid.uuid4().hex
                row["request_id"], row["agent_id"] = ident(row["request_id"]), ident(row["agent_id"])
                for c in ("event_type", "provider", "model", "tool_name"):
                    row[c] = label(row[c], 60 if c == "event_type" else LABEL_MAX)
                for c in ("duration_ms", "prompt_tokens", "completion_tokens", "total_tokens"):
                    row[c] = _num(row[c])
                row["outcome"] = row["outcome"] if row["outcome"] in OUTCOMES else "unknown"
                row["ts"] = row["ts"] if isinstance(row["ts"], (int, float)) and not isinstance(row["ts"], bool) else time.time()
                _enqueue(row)
    except Exception:
        pass


def step(event_type):
    """Decorator for a backend step that returns (http_status, body): binds a fresh request id for its model turns and saves, then emits ONE event with the step's outcome."""
    def deco(fn):
        @functools.wraps(fn)
        def run(*a, **k):
            rid, t = f"{event_type.split('.')[0]}-{time.time_ns()}", time.perf_counter()
            with bind(rid, "main"):
                try:
                    out = fn(*a, **k)
                except BaseException as e:
                    emit(event_type, "failure", duration_ms=(time.perf_counter() - t) * 1000, result={"exception": type(e).__name__})
                    raise
                try:
                    st, body = out
                    ok = isinstance(body, dict) and body.get("ok") is not False and st < 400
                    emit(event_type, "success" if ok else "failure", duration_ms=(time.perf_counter() - t) * 1000,
                         result={"http_status": st, "state": body.get("state") if isinstance(body, dict) else None, "code": body.get("code") if isinstance(body, dict) else None,
                                 "error": body.get("error") if isinstance(body, dict) else None, "replayed": body.get("replayed") if isinstance(body, dict) else None})
                except Exception:
                    pass
                return out
        return run
    return deco


# ------------------------------------------------------------------ Hermes observer hooks (worker process)
def _tool_call_name(t):
    f = t.get("function") if isinstance(t, dict) else getattr(t, "function", None)
    return f.get("name") if isinstance(f, dict) else getattr(f, "name", None)


def _ms(seconds):
    return seconds * 1000 if isinstance(seconds, (int, float)) else None


def register_hooks(ctx):
    """Observer hooks only (their return values are ignored): one model.start row when a provider request is sent (outcome unknown, so a start never implies success), and one model.call row
    per COMPLETED or FAILED provider attempt, linked by the Hermes api_request_id; plus one tool.call row per executed tool. Executed/billable attempts are the model.call rows, never the starts."""
    if os.environ.get("ECOM_LOGBOOK") != "1":
        return

    def model_start(**kw):
        emit("model.start", "unknown", provider=kw.get("provider"), model=kw.get("model"), ts=kw.get("started_at"),
             inputs={"api_request_id": kw.get("api_request_id"), "api_call_count": kw.get("api_call_count"), "retry_count": kw.get("retry_count"), "message_count": kw.get("message_count"),
                     "tool_count": kw.get("tool_count"), "approx_input_tokens": kw.get("approx_input_tokens")})

    def model_ok(**kw):
        u = kw.get("usage") if isinstance(kw.get("usage"), dict) else {}
        names = [_tool_call_name(t) for t in (getattr(kw.get("assistant_message"), "tool_calls", None) or [])]
        first, start = kw.get("first_chunk_at"), kw.get("started_at")
        emit("model.call", "success", duration_ms=_ms(kw.get("api_duration")), provider=kw.get("provider"), model=kw.get("model"),
             usage={"prompt_tokens": u.get("prompt_tokens"), "completion_tokens": u.get("output_tokens"), "total_tokens": u.get("total_tokens")} if u else None,
             inputs={"api_request_id": kw.get("api_request_id"), "api_call_count": kw.get("api_call_count"), "message_count": kw.get("message_count")},
             result={"finish_reason": kw.get("finish_reason"), "response_model": kw.get("response_model"), "tool_call_names": [n for n in names if n],
                     "assistant_content_chars": kw.get("assistant_content_chars"), "ttfb_ms": round((first - start) * 1000, 1) if first and start else None,
                     "reasoning_tokens": u.get("reasoning_tokens"), "cache_read_tokens": u.get("cache_read_tokens")})

    def model_err(**kw):
        e = kw.get("error") if isinstance(kw.get("error"), dict) else {}
        emit("model.call", "failure", duration_ms=_ms(kw.get("api_duration")), provider=kw.get("provider"), model=kw.get("model"),
             inputs={"api_request_id": kw.get("api_request_id"), "api_call_count": kw.get("api_call_count")},
             result={"error_type": e.get("type"), "error_message": e.get("message"), "status_code": kw.get("status_code"), "retry_count": kw.get("retry_count"),
                     "max_retries": kw.get("max_retries"), "retryable": kw.get("retryable"), "reason": kw.get("reason")})

    def tool_done(**kw):
        raw = kw.get("result")
        emit("tool.call", tool_outcome(kw.get("status"), raw), duration_ms=kw.get("duration_ms"), tool_name=kw.get("tool_name"),
             inputs={"tool_call_id": kw.get("tool_call_id"), "api_request_id": kw.get("api_request_id"), "model_arguments": kw.get("args")},
             result={"observed_result": tool_result_summary(raw), "hermes_status": kw.get("status"), "error_type": kw.get("error_type"), "error_message": kw.get("error_message")})

    for name, fn in (("pre_api_request", model_start), ("post_api_request", model_ok), ("api_request_error", model_err), ("post_tool_call", tool_done)):
        ctx.register_hook(name, fn)


# ------------------------------------------------------------------ server: the single bounded writer
class _SqliteTestConn:
    """TEST ONLY (url 'ecom-test-sqlite:<path>' or 'ecom-test-fail:<connect|insert>'): runs the exact SQL above on SQLite so tests exercise the real statements without a Postgres server."""
    def __init__(self, path, fail_insert=False):
        import sqlite3
        self.c, self.fail_insert = sqlite3.connect(path, check_same_thread=False, timeout=5), fail_insert
        self.c.create_function("to_timestamp", 1, lambda s: datetime.datetime.fromtimestamp(s, datetime.timezone.utc).isoformat())

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=()):
        return self.c.execute(sql.replace("::jsonb", "").replace("%s", "?"), params)

    def executemany(self, sql, rows):
        if self.fail_insert:
            raise RuntimeError("scripted insert failure while writing (user=neon password=hunter2secret)")
        return self.c.executemany(sql.replace("::jsonb", "").replace("%s", "?"), rows)

    def commit(self):
        self.c.commit()

    def close(self):
        self.c.close()


def _default_connect(url):
    if url.startswith("ecom-test-sqlite:"):
        return _SqliteTestConn(url.split(":", 1)[1])
    if url.startswith("ecom-test-fail:"):
        if url.endswith("connect"):
            raise ConnectionError(f"scripted connection failure to {url} (password=hunter2secret)")
        return _SqliteTestConn(":memory:", fail_insert=True)
    try:
        import psycopg
    except ImportError:
        raise RuntimeError("the Postgres driver is not installed in this Python (install it with: <Hermes python> -m pip install -r requirements-logbook.txt)")
    extra = {} if "sslmode=" in url else {"sslmode": "require"}   # never fall back to libpq's default 'prefer', which silently accepts a plaintext connection
    return psycopg.connect(url, connect_timeout=5, options="-c statement_timeout=5000", **extra)


def _url():
    u = os.environ.get("LOGBOOK_DATABASE_URL")
    if u:
        return u.strip()
    try:
        from app import core
        return core.load_secrets().get("LOGBOOK_DATABASE_URL", "").strip()
    except Exception:
        return ""


def _fail(msg):
    s = scrub(str(msg))
    stats["last_error"] = s[:200]


def start():
    """Server only. Reads this project's configuration and starts the writer; returns the diagnostic. Safe to call without configuration."""
    S["role"] = "server"
    if os.environ.get("ECOM_LOGBOOK") == "off":
        S.update(enabled=False, reason="disabled by ECOM_LOGBOOK=off")
    elif not (u := _url()):
        S.update(enabled=False, reason="LOGBOOK_DATABASE_URL is not set in secrets/local.env, so nothing is logged")
    else:
        S.update(enabled=True, reason="configured (best effort)", url=u)
        if not S["writer"] or not S["writer"].is_alive():
            S["writer"] = threading.Thread(target=_writer, daemon=True, name="logbook-writer")
            S["writer"].start()
            atexit.register(stop)
    return diagnostics()


def attach_worker(send):
    """Worker only: forward rows to the server instead of writing them. Active only when the server enabled the logbook (ECOM_LOGBOOK=1 in the worker's environment)."""
    global _sink
    S["role"] = "worker"
    if os.environ.get("ECOM_LOGBOOK") == "1":
        guard = threading.Lock()

        def sink(rows):
            with guard:
                send({"event": "log", "rows": rows})
        _sink = sink


def _flush_batch(batch, st, clock=time.time):
    """Write one batch with the writer's connection state st = {"conn", "next_try"}; clock is injectable so the reconnect timing can be tested. A failure loses the batch (best effort)."""
    if st["conn"] is None and clock() < st["next_try"]:   # still backing off after a real failure: this batch is lost, but its arrival must NOT move the deadline
        stats["lost_write_failed"] += len(batch)
        return
    try:
        if st["conn"] is None:
            st["conn"] = (connect or _default_connect)(S["url"])
            stats["schema_ready"] = False
        conn = st["conn"]
        if not stats["schema_ready"]:
            for stmt in DDL:
                conn.execute(stmt)
            conn.commit()
            stats["schema_ready"] = True
        with conn.cursor() as cur:
            cur.executemany(INSERT, [tuple(r[c] if c not in ("inputs", "result") else (None if r[c] is None else json.dumps(r[c], ensure_ascii=False, default=str)) for c in COLS) for r in batch])
        conn.commit()
        stats["written"] += len(batch)
        stats["last_ok_ts"] = clock()
    except Exception as e:
        _fail(e)
        stats["lost_write_failed"] += len(batch)
        stats["batches_failed"] += 1
        st["next_try"] = clock() + RECONNECT_S
        try:
            st["conn"] and st["conn"].close()
        except Exception:
            pass
        st["conn"] = None


def _writer():
    st = {"conn": None, "next_try": 0.0}
    while True:
        first = _q.get()
        taken, batch, stop_after = 1, ([] if first is _STOP else [first]), first is _STOP
        try:
            while len(batch) < BATCH_MAX and not stop_after:
                x = _q.get_nowait()
                taken += 1
                if x is _STOP:
                    stop_after = True
                else:
                    batch.append(x)
        except queue.Empty:
            pass
        if batch:
            _flush_batch(batch, st)
        for _ in range(taken):
            _q.task_done()
        if stop_after:
            return


def flush(timeout=FLUSH_S):
    """Wait (bounded) until the queue is written or given up on. Used at shutdown and by tests."""
    end = time.time() + timeout
    while _q.unfinished_tasks and time.time() < end:
        time.sleep(0.02)
    return not _q.unfinished_tasks


def stop():
    if S["writer"] and S["writer"].is_alive():
        flush()


def diagnostics():
    """Concise local status; never contains the connection string. 'written' counts rows the database accepted; everything else says why rows were not."""
    drv = "test" if S["url"].startswith("ecom-test-") else None
    if drv is None:
        try:
            import importlib.util
            drv = "psycopg" if importlib.util.find_spec("psycopg") else "missing (pip install -r requirements-logbook.txt into the Hermes Python)"
        except Exception:
            drv = "unknown"
    return {"enabled": S["enabled"], "reason": S["reason"], "configured": bool(S["url"]), "driver": drv, "queued": _q.qsize(), **stats,
            "delivery": "best effort: rows can be lost if the queue is full, the database is down or the server stops abruptly; SQLite remains the source of truth"}


def check():
    """Small schema/insert/read check with a synthetic event, using the configured connection. Returns (ok, message); prints nothing sensitive."""
    url = _url()
    if not url:
        return False, "LOGBOOK_DATABASE_URL is not set: live check pending"
    S["url"] = url
    rid = f"synthetic-check-{time.time_ns()}"
    try:
        conn = (connect or _default_connect)(url)
        for stmt in DDL:
            conn.execute(stmt)
        conn.commit()
        row = {"event_id": uuid.uuid4().hex, "request_id": rid, "agent_id": "logbook-check", "event_type": "logbook.check", "ts": time.time(), "duration_ms": 1.0, "provider": None,
               "model": None, "tool_name": None, "outcome": "success", "prompt_tokens": None, "completion_tokens": None, "total_tokens": None, "inputs": {"synthetic": True}, "result": {"ok": True}}
        with conn.cursor() as cur:
            cur.executemany(INSERT, [tuple(row[c] if c not in ("inputs", "result") else json.dumps(row[c]) for c in COLS)])
            conn.commit()
            n = len(cur.execute(INSPECT_ONE_REQUEST, (rid,)).fetchall())
        conn.close()
        return n == 1, f"inserted and read back {n} synthetic event(s) for request {rid}"
    except Exception as e:
        return False, scrub(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    ok, msg = check()
    print(("PASS " if ok else "FAIL ") + msg)
    raise SystemExit(0 if ok else 1)
