"""Small local backend + static UI. Run: python -m app.server  (http://127.0.0.1:8800)"""
import json, sys, threading, time, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from app import ads, core, demo_reset, flyer, listing, logbook, onboarding, research, results, routing, timing, workers

STATIC = Path(__file__).parent / "static"
locks = {}  # one turn at a time per agent
inflight = {}  # agent_id -> {"request_id", "since"}  (what the UI shows as "working")
done = {}      # request_id -> (agent_id, result): lets an intentional retry of a COMPLETED request be answered without re-running it
MAX_MESSAGE = 8000
ACTIVITY_LABELS = {"create_agent": "Creating specialist", "read_company_context": "Reading company context", "memory": "Saving to memory",
                   "skill_manage": "Updating a skill", "skill_view": "Reading a skill", "skills_list": "Listing skills",
                   "inspect_image": "Looking at an image", "read_catalogue": "Reading the catalogue", "read_recorded_evidence": "Reading recorded Marketplace evidence",
                   "save_listing_draft": "Saving a listing draft", "marketplace_locate": "Looking up a Marketplace location",
                   "marketplace_search": "Searching Facebook Marketplace", "marketplace_item": "Reading a Marketplace listing",
                   "marketplace_photo": "Fetching a listing photo", "fb_ads_find_advertiser": "Finding Facebook advertisers", "fb_ads_search": "Searching Facebook image ads",
                   "fb_ad_detail": "Reading a Facebook ad", "fb_ad_image": "Fetching an ad image", "save_ad_research": "Saving ad research",
                   "read_ad_research": "Reading saved ad research", "generate_flyer": "Generating a flyer", "read_flyer": "Reading saved flyers", "inspect_flyer": "Looking at a flyer candidate", "review_flyer": "Saving a flyer review", "finalize_flyer": "Selecting the final flyer"}


def fail(code, message, status, retryable=False, **extra):
    """Structured API error. 'error' stays a plain string like tool errors; 'code' is what clients branch on."""
    return status, {"ok": False, "code": code, "error": message, "retryable": retryable, **extra}


def activity(tools):
    """Readable activity list from raw tool calls/results (labels and ok/error status decided here, not in the UI)."""
    calls = [t for t in tools or [] if "input" in t]
    results = [t for t in tools or [] if "output" in t]
    by_id = {t.get("id"): t for t in results if t.get("id")}
    out = []
    for i, c in enumerate(calls):
        r = by_id.get(c.get("id")) or (results[i] if i < len(results) and not c.get("id") else None)
        status = "no result"
        if r is not None:
            status = "ok"
            try:
                o = json.loads(r.get("output") or "")
                if isinstance(o, dict) and (o.get("ok") is False or (o.get("error") and "ok" not in o)):
                    status = "error"
            except ValueError:
                status = "error" if r.get("is_error") else "ok"
        name = c.get("name") or "tool"
        out.append({"tool": name, "label": ACTIVITY_LABELS.get(name, name.replace("_", " ").capitalize()), "status": status,
                    "input": c.get("input"), "output": r.get("output") if r else None})
    return out


def agent_row(r, full=False):
    d = {"agent_id": r["agent_id"], "name": r["name"], "role": r["role"], "state": r["state"],
         "conversation_id": r["conversation_id"], "granted_tools": json.loads(r["granted_tools"])}
    if full:
        d.update(objective=r["objective"], instructions=r["instructions"], context_refs=json.loads(r["context_refs"]),
                 skills=json.loads(r["skills"]), approval_requirements=json.loads(r["approvals"]), company_id=r["company_id"],
                 customizations=core.customization_log(r["agent_id"]))
    return d


def history(agent_id):
    with core.db() as d:
        rows = d.execute("SELECT id, who, content, tools, meta, ts FROM messages WHERE agent_id=? ORDER BY id", (agent_id,)).fetchall()
    out = []
    for r in rows:
        tools = json.loads(r["tools"] or "[]")
        out.append({"id": r["id"], "who": r["who"], "content": r["content"], "tools": tools, "activity": activity(tools), "ts": r["ts"],
                    "route": json.loads(r["meta"]) if r["meta"] else None})
    return out


def recent_turns(agent_id, n=4):
    """Bounded recent conversation for routing (oldest first). Error rows are skipped."""
    with core.db() as d:
        rows = d.execute("SELECT who, content FROM messages WHERE agent_id=? AND who IN ('user','agent') ORDER BY id DESC LIMIT ?", (agent_id, n)).fetchall()
    return [{"speaker": "user" if r["who"] == "user" else "assistant", "text": r["content"]} for r in reversed(rows)]


def public_route(rt):
    """Routing metadata that is stored and shown (no prompt text): outcome, rule, Laya's own probabilities, timing."""
    return {k: rt.get(k) for k in ("outcome", "domain", "role", "agent_id", "decision_rule", "probabilities", "classifier", "handled_locally", "allow_create_agent")}


admit = threading.Lock()   # makes "is chat open?" + "accept this turn" one step, and "start onboarding" + "no turn running on main" one step: whichever comes first wins, the other is refused
resetting, busy_ops = False, 0   # a demo restart is running; onboarding steps / company saves running (both only read or changed while holding `admit`)


def _closed():
    """A refusal while the demo restarts (or an earlier restart is unfinished), else None. Call while holding `admit`."""
    if resetting:
        return fail("demo_restarting", "The demo is restarting. Wait a moment, then reload the page.", 409, retryable=True)
    p = demo_reset.pending()
    if p:
        return fail("demo_restart_incomplete", demo_reset.guard_message(p), 409)
    return None


def guarded(op):
    """Onboarding steps and company saves: refused while the demo restarts, and counted while they run so a restart cannot begin underneath them."""
    global busy_ops
    with admit:
        closed = _closed()
        if closed:
            return closed
        busy_ops += 1
    try:
        return op()
    finally:
        with admit:
            busy_ops -= 1


def onboarding_op(step, body):
    if step == "start":
        return start_onboarding()
    return guarded(lambda: onboarding.submit_source(body.get("url")) if step == "source" else onboarding.submit_answers(body))


def save_company(body):   # same validation/storage as main's update_company tool
    def op():
        r = core.update_company(body.get("fields", body), source="form")
        if not r["ok"]:
            return 503 if r["code"] == "company_storage_error" else 400, r
        return 200, {**r, "status": core.company_status()}
    return guarded(op)


def reset_demo(body):
    """The operator's Restart demo (also used by fresh_demo.bat when the app is running): refused while anything runs; while it runs, every new operation is refused."""
    global resetting
    if not isinstance(body, dict) or body.get("confirm") is not True:
        return fail("confirmation_required", "Restarting the demo clears the current onboarding, company details, specialists and chats (they are archived first). Confirm to proceed.", 400)
    with admit:
        if resetting:
            return fail("demo_restarting", "The demo is already restarting.", 409, retryable=True)
        if inflight or busy_ops:
            who = sorted(inflight)
            return fail("demo_busy", f"Something is still running ({', '.join(who) if who else 'an onboarding step or a company save'}). Wait for it to finish, then restart the demo.",
                        409, retryable=True, running=who)
        resetting = True
    try:
        r = demo_reset.reset(stop_workers=workers.stop_all)
        if r["ok"] or r["code"] == "reset_incomplete":
            done.clear()   # no finished request of the old demo can be replayed into the new one
        return (200 if r["ok"] else 503 if r["code"] == "archive_failed" else 500), r
    finally:
        with admit:
            resetting = False


def start_onboarding():
    """Onboarding's own model turns switch main's Hermes conversation (the worker restarts), so it may only begin when no accepted turn is running on main."""
    with admit:
        closed = _closed()
        if closed:
            return closed
        if "main" in inflight:
            return fail("main_busy", "The main agent is still answering an accepted request. Wait for it to finish, then start onboarding again.", 409, retryable=True)
        return onboarding.start()


def chat(agent_id, text, request_id, customize=False):
    """One accepted turn per agent at a time. Rejections (busy / duplicate / invalid) happen BEFORE anything is saved."""
    with admit:
        closed = _closed()
    if closed:   # checked before the replay cache too: nothing of the old demo is answered while it is being restarted
        return closed
    prev = done.get(request_id)
    if prev and prev[0] == agent_id:   # intentional retry of a request that already finished: return its result, run nothing
        logbook.emit("request.duplicate", "success", request_id=request_id, agent_id=agent_id, result={"reason": "completed_request_replayed", "executed_again": False, "original_ok": prev[1].get("ok")})
        return 200, {**prev[1], "replayed": True}
    lock = locks.setdefault(agent_id, threading.Lock())
    with admit:
        closed = _closed()
        if closed:
            return closed
        if onboarding.chat_blocked():
            return fail("onboarding_incomplete", "Onboarding is not complete yet, so chat and manual company edits are locked. Finish the onboarding form first.", 409)
        if not lock.acquire(blocking=False):
            same = inflight.get(agent_id, {}).get("request_id") == request_id
            if same:
                logbook.emit("request.duplicate", "failure", request_id=request_id, agent_id=agent_id, result={"reason": "already_running", "executed_again": False})
            return fail("duplicate_in_flight" if same else "agent_busy",
                        "This request is already running." if same else "This agent is already working on another request. Wait for it to finish, then send again.",
                        409, retryable=True)
        inflight[agent_id] = {"request_id": request_id, "since": time.time()}
    stage, ended, agent_ok = "setup", False, None   # where an unexpected exception happened, for the one terminal failure event (the logbook never causes or repeats agent work)
    try:
        t0 = time.perf_counter()
        logbook.emit("request.start", "unknown", request_id=request_id, agent_id=agent_id, inputs={"message_chars": len(text), "message_preview": logbook.preview(text), "customize": bool(customize)})
        recent = recent_turns(agent_id) if agent_id == "main" else []   # BEFORE this request is saved, so it is never its own context
        stage = "initial_transcript_write"
        with core.db() as d:
            d.execute("INSERT INTO messages(agent_id,who,content,tools,ts) VALUES(?,?,?,?,?)", (agent_id, "user", text, "[]", time.time()))
            d.execute("UPDATE agents SET state='running' WHERE agent_id=?", (agent_id,))
        t1 = time.perf_counter()
        stage, rt = "run", None
        try:
            if agent_id == "main":   # Laya runs BEFORE the main Hermes agent; specialists are unchanged in this increment
                with core.db() as d:
                    agents = [dict(x) for x in d.execute("SELECT agent_id, name, role FROM agents ORDER BY created_at")]
                try:
                    rt = routing.route(text, recent, agents, core.load_company())
                except routing.ClassifierError as e:
                    r = {"text": "", "tools": [], "error": f"Request routing failed, so nothing was sent to the agent: {e}"}
                else:
                    r = ({"text": rt["reply"], "tools": [], "error": None} if rt["handled_locally"]
                         else core.run_turn(agent_id, text, route=rt, request_id=request_id))
            else:
                r = core.run_turn(agent_id, text, request_id=request_id, **({"customize": True} if customize else {}))   # the operator's Customize mode for THIS turn
        except Exception as e:  # never leave the agent "running" or the transcript without an outcome
            r = {"text": "", "tools": [], "error": f"Backend error while running the turn: {type(e).__name__}: {e}"}
        t2 = time.perf_counter()
        stage, agent_ok = "final_transcript_write", not r["error"]
        with core.db() as d:
            body = r["text"] or (f"[error] {r['error']}" if r["error"] else "")
            d.execute("INSERT INTO messages(agent_id,who,content,tools,ts,meta) VALUES(?,?,?,?,?,?)",
                      (agent_id, "agent" if not r["error"] else "error", body, json.dumps(r["tools"]), time.time(), json.dumps(public_route(rt)) if rt else None))
            d.execute("UPDATE agents SET state='idle' WHERE agent_id=?", (agent_id,))
        tw, wk = r.pop("timing", None), r.pop("worker", None)
        if tw:
            ev = tw["events"]
            timing.log({"kind": "chat", "agent": agent_id, "db_pre_ms": round((t1 - t0) * 1000, 1), "run_turn_ms": round((t2 - t1) * 1000, 1),
                        "db_post_ms": round((time.perf_counter() - t2) * 1000, 1), "total_ms": round((time.perf_counter() - t0) * 1000, 1),
                        "api_calls": sum(e["stage"] == "api_end" for e in ev), "tool_calls": sum(e["stage"] == "tool" for e in ev),
                        "parent": tw.get("parent"), "worker": wk, "pre_run_ms": tw["pre_run_ms"], "turn_ms": tw["turn_ms"], "events": ev})
        r = {"ok": not r["error"], **r, "activity": activity(r["tools"]), "request_id": request_id, "route": public_route(rt) if rt else None}
        logbook.emit("request.end", "success" if r["ok"] else "failure", request_id=request_id, agent_id=agent_id, duration_ms=(time.perf_counter() - t0) * 1000,
                     result={"route_outcome": (rt or {}).get("outcome"), "handled_locally": bool((rt or {}).get("handled_locally")), "tool_calls": [a["tool"] for a in r["activity"]],
                             "error": r.get("error"), "model_provided_final_answer_preview": logbook.preview(r.get("text"))})
        ended = True
        if r["ok"]:  # failed turns are never replayed: an intentional retry must actually run again
            done[request_id] = (agent_id, r)
            while len(done) > 200:
                done.pop(next(iter(done)))
        return 200, r
    except BaseException as e:   # the transcript (SQLite) failed outside the guarded agent run: one terminal failure event, then the error propagates exactly as before
        if not ended:
            logbook.emit("request.end", "failure", request_id=request_id, agent_id=agent_id, result={"stage": stage, "exception": type(e).__name__, "error": str(e), "agent_run_ok": agent_ok})
        raise
    finally:
        inflight.pop(agent_id, None)
        with core.db() as d:  # also covers an exception after the 'running' update
            d.execute("UPDATE agents SET state='idle' WHERE agent_id=? AND state='running'", (agent_id,))
        lock.release()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def send(self, code, obj, ctype="application/json"):
        raw = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        for i in range(0, len(raw), 16384):   # Windows loopback stalls ~19 s and then resets on one multi-MB write (the 3 MB flyer image never arrived): write in slices
            self.wfile.write(raw[i:i + 16384])

    def do_GET(self):
        t0 = time.perf_counter()
        try:
            self._get()
        finally:
            if timing.ENABLED:
                timing.log({"kind": "http", "method": "GET", "path": self.path.split("?")[0].split("/api/")[-1].split("/")[0] or "page",
                            "ms": round((time.perf_counter() - t0) * 1000, 1)})

    def _get(self):
        p = self.path.split("?")[0]
        if p == "/":
            return self.send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
        if p == "/api/status":
            c = core.llm_config()
            return self.send(200, {"provider": c["provider"], "model": c["model"], "problem": core.llm_problem(), "classifier": routing.status(), "company": core.company_status(),
                                   "secrets_file": "secrets/local.env", "live_research_connected": bool(research.diag().get_key()), "image_generation_configured": flyer.connected(),
                                   "timing": timing.ENABLED})
        if p == "/api/state":   # who is working right now (main included); the UI polls this for status pills
            return self.send(200, {a: {"busy": True, "since": v["since"]} for a, v in list(inflight.items())})
        if p == "/api/workers":
            return self.send(200, workers.status())
        if p == "/api/logbook":   # concise local diagnostic of the best-effort execution logbook (never contains the connection string)
            return self.send(200, logbook.diagnostics())
        if p == "/api/onboarding":   # persisted onboarding state (backend-owned; the page only displays it)
            return self.send(200, onboarding.status())
        if p == "/api/company":   # the single saved company + what is still missing (same data main reads with read_company_context)
            c = core.load_company()
            return self.send(200, {"company": {k: c[k] for k in core.COMPANY_FIELDS}, "updated_at": c["updated_at"], "updated_by": c["updated_by"],
                                   "status": core.company_status(c)})
        if p == "/api/results":     # saved results as chat cards, tied to the producing message by backend-owned identity (app/results.py); ?agent_id= is required. Reads SQLite only.
            q = urllib.parse.parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
            aid = (q.get("agent_id") or [""])[0]
            if not aid:
                return self.send(*fail("agent_required", "agent_id is required.", 400))
            return self.send(200, results.cards(aid))
        if p == "/api/roles":
            return self.send(200, core.ROLES)
        if p == "/api/drafts":      # saved listing drafts (summaries); ?agent_id= filters. Reads SQLite only.
            q = urllib.parse.parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
            return self.send(200, listing.list_drafts((q.get("agent_id") or [None])[0]))
        if p == "/api/research/runs":      # live research runs (calls, outcomes, credits, photos, allowance); ?agent_id= filters. SQLite only.
            q = urllib.parse.parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
            return self.send(200, research.list_runs((q.get("agent_id") or [None])[0]))
        if p == "/api/research/allowance":
            return self.send(200, research.allowances())
        if p == "/api/ads/runs":            # Facebook ad-research runs (calls, outcomes, accounting, allowance); ?agent_id= filters. SQLite only.
            q = urllib.parse.parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
            return self.send(200, ads.list_runs((q.get("agent_id") or [None])[0]))
        if p == "/api/ads/packages":        # saved ad-research packages (summaries); ?agent_id= filters. SQLite only.
            q = urllib.parse.parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
            return self.send(200, ads.list_packages((q.get("agent_id") or [None])[0]))
        if p == "/api/ads/allowance":
            return self.send(200, ads.allowances())
        if p == "/api/flyers":              # saved flyers per manual request (status, error, image url); ?agent_id= filters. SQLite only: no provider, no credentials.
            q = urllib.parse.parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
            return self.send(200, flyer.list_flyers((q.get("agent_id") or [None])[0]))
        if p == "/api/flyers/allowance":
            return self.send(200, flyer.allowances())
        if p == "/api/agents":
            with core.db() as d:
                return self.send(200, [agent_row(r) for r in d.execute("SELECT * FROM agents ORDER BY created_at")])
        parts = p.strip("/").split("/")
        if len(parts) == 3 and parts[:2] == ["api", "agents"]:
            with core.db() as d:
                r = d.execute("SELECT * FROM agents WHERE agent_id=?", (parts[2],)).fetchone()
            return self.send(200, agent_row(r, True)) if r else self.send(404, {"error": "unknown agent"})
        if len(parts) == 3 and parts[:2] == ["api", "drafts"]:   # one draft with its product/listing/image evidence snapshots
            dr = listing.get_draft(parts[2])
            return self.send(200, dr) if dr else self.send(404, {"ok": False, "code": "unknown_draft", "error": f"No saved draft {parts[2]!r}."})
        if len(parts) == 4 and parts[:3] == ["api", "flyers", "images"]:   # the managed output image; the id is validated and resolved through the database
            s, a, b = flyer.image_state(parts[3])
            if s == "ok":
                return self.send(200, a, b)
            if s == "unselected":   # two valid candidates and no explicit final selection: no default image (each candidate id still serves its own file)
                return self.send(409, {"ok": False, "code": "final_not_selected", "error": "This flyer has two candidates and none was selected as final; request a candidate image by id."})
            if s == "integrity":   # the flyer exists but its stored file failed validation: an explicit failure, never a file
                return self.send(409, {"ok": False, "code": "artifact_integrity_failed", "error": f"The saved flyer image failed its integrity check: {a}."})
            return self.send(404, {"ok": False, "code": "unknown_image", "error": "No such managed flyer image."})
        if len(parts) == 3 and parts[:2] == ["api", "flyers"]:
            f = flyer.get_flyer(parts[2])
            return self.send(200, f) if f else self.send(404, {"ok": False, "code": "unknown_flyer", "error": "No such saved flyer."})
        if len(parts) == 4 and parts[:3] == ["api", "ads", "packages"]:
            pk = ads.get_package(parts[3])
            return self.send(200, pk) if pk else self.send(404, {"ok": False, "code": "unknown_package", "error": f"No saved ad-research package {parts[3]!r}."})
        if len(parts) == 4 and parts[:3] == ["api", "ads", "runs"]:
            rv = ads.run_view(parts[3])
            return self.send(200, rv) if rv else self.send(404, {"ok": False, "code": "unknown_run", "error": f"No ad-research run {parts[3]!r}."})
        if len(parts) == 5 and parts[:3] == ["api", "ads", "images"]:   # one managed ad image; both ids are validated and resolved through the database
            im = ads.image_file(parts[3], parts[4])
            return self.send(200, im[0], im[1]) if im else self.send(404, {"ok": False, "code": "unknown_image", "error": "No such managed ad image."})
        if len(parts) == 4 and parts[:3] == ["api", "research", "runs"]:
            rv = research.run_view(parts[3])
            return self.send(200, rv) if rv else self.send(404, {"ok": False, "code": "unknown_run", "error": f"No research run {parts[3]!r}."})
        if len(parts) == 3 and parts[:2] == ["api", "chat"]:
            return self.send(200, history(parts[2]))
        self.send(404, {"error": "not found"})

    def do_POST(self):
        parts = self.path.strip("/").split("/")
        if timing.ENABLED and parts == ["api", "timing"]:  # browser-side render timings (numbers only)
            b = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            timing.log({"kind": "client", **{k: v for k, v in b.items() if isinstance(v, (int, float))}})
            return self.send(200, {})
        if (parts == ["api", "company"] or (len(parts) == 3 and parts[:2] == ["api", "chat"])) and onboarding.chat_blocked():   # backend gate: no chat and no manual company save until onboarding is complete
            self.rfile.read(min(int(self.headers.get("Content-Length", 0) or 0), 1_000_000))   # drain the unread request body: closing with unread data can reset the connection on Windows and the client would never see this 409
            return self.send(*fail("onboarding_incomplete", "Onboarding is not complete yet, so chat and manual company edits are locked. Finish the onboarding form first.", 409))
        if len(parts) == 3 and parts[:2] == ["api", "onboarding"] and parts[2] in ("start", "source", "answers"):   # explicit onboarding operations (structured form, not chat)
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("body must be a JSON object")
            except (ValueError, TypeError) as e:
                return self.send(*fail("invalid_request", f"Request body is not valid JSON: {e}", 400))
            return self.send(*onboarding_op(parts[2], body))
        if parts in (["api", "company"], ["api", "demo", "reset"]):
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("body must be a JSON object")
            except (ValueError, TypeError) as e:
                return self.send(*fail("invalid_request", f"Request body is not valid JSON: {e}", 400))
            return self.send(*(save_company(body) if parts[1] == "company" else reset_demo(body)))
        if len(parts) == 3 and parts[:2] == ["api", "chat"]:
            aid = parts[2]
            try:
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("body must be a JSON object")
            except (ValueError, TypeError) as e:
                return self.send(*fail("invalid_request", f"Request body is not valid JSON: {e}", 400))
            if aid != "main":
                with core.db() as d:
                    if not d.execute("SELECT 1 FROM agents WHERE agent_id=?", (aid,)).fetchone():
                        return self.send(*fail("unknown_agent", f"Unknown agent {aid!r}.", 404))
            customize = body.get("customize", False)
            if not isinstance(customize, bool) or (customize and aid == "main"):   # Customize mode is the operator's explicit control and exists only for a specialist's own chat
                return self.send(*fail("customize_not_available", "customize must be true or false, and only a specialist's own chat has Customize mode.", 400))
            msg = str(body.get("message") or "").strip()
            if not msg:
                return self.send(*fail("empty_message", "The message is empty.", 400))
            if len(msg) > MAX_MESSAGE:
                return self.send(*fail("message_too_long", f"The message is {len(msg)} characters; the limit is {MAX_MESSAGE}.", 413))
            rid = str(body.get("request_id") or "")[:64] or f"srv-{time.time_ns()}"
            try:
                code, r = chat(aid, msg, rid, customize)
            except Exception as e:   # unexpected backend failure: say so, do not pretend the message is safe to resend blindly
                return self.send(*fail("internal_error", f"Backend error: {type(e).__name__}: {e}. The message may or may not have been recorded; check the transcript before resending.", 500))
            return self.send(code, r)
        self.send(404, {"error": "not found"})


def main(port=8800):
    demo_reset.refuse_if_pending()   # never serve a half-cleared demo; the message says how to finish the restart
    with core.db() as d:
        d.execute("UPDATE agents SET state='idle' WHERE state='running'")  # crash recovery
    core.sync_profiles()
    c = core.llm_config()
    print("Logbook:", logbook.start()["reason"], flush=True)
    if not routing.explicit_off():
        threading.Thread(target=routing.prewarm, daemon=True).start()   # load Laya once, in the background; first message waits only if it is still loading
    print(f"Provider {c['provider']!r} model {c['model']!r} | problem: {core.llm_problem()} | UI: http://127.0.0.1:{port}", flush=True)
    try:
        ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
    finally:
        workers.stop_all()
        routing.client.stop()


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 8800)
