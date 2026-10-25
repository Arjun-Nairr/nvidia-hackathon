"""V2-06 demo runner: separately invoked phases that prepare, provision, probe, demonstrate, archive and re-read ONE isolated flyer demo.

  python scripts/v2_06_demo.py prepare   --dir D --mode scripted|live [--env-source F --catalogue C --images I --company-json J --auth-arrangement ...]
  python scripts/v2_06_demo.py provision --dir D [--live-authorized]       one main message creates one social specialist; no scraper/Gemini scope
  python scripts/v2_06_demo.py probe     --dir D [--live-authorized]       ONE request: generate -> inspect -> review; 1 Gemini dispatch, no correction, no scraper
  python scripts/v2_06_demo.py demo      --dir D --approve-demo [...]      ONE request: ad research -> generate -> inspect/review -> <=1 correction -> final
  python scripts/v2_06_demo.py archive   --dir D                           sanitized evidence + hash manifest, then removes the demo's copied key lines
  python scripts/v2_06_demo.py retrieve  --dir D                           restarts with inference credentials absent and re-reads the evidence
  python scripts/v2_06_demo.py status    --dir D

What it does NOT do (by design): read, copy, move, refresh or delete the real runtime or any auth.json; log in; reset a ledger; create a new allowance scope to get
past a failure; resubmit a turn after a timeout, dropped connection, failed turn or unknown completion; continue from one phase into the next. A phase that was
started is recorded BEFORE its request is sent and can never be started again in the same demo directory.
Scripted mode runs the project's own stand-ins (tests/mock_llm.py, mock_gemini.py, mock_fb_ads.py) with DUMMY credentials and synthetic placeholder inputs;
nothing it produces is live evidence. Live mode is implemented but refuses to start while the authentication arrangement is unresolved.
Reasoning requests are bounded only by per-turn iteration caps (+1 summary request) and, in the demo copy, agent.api_max_retries=1 / auto_recovery_cycles=0.
Uncounted paths (auxiliary Hermes requests such as context compression, any retry path outside those settings) are NOT enumerated; observed counts are recorded."""
import argparse, hashlib, http.client, json, os, re, shutil, socket, sqlite3, subprocess, sys, tempfile, time
from pathlib import Path

import psutil   # ships with the Hermes interpreter; used only to find and stop the processes THIS demo stack owns
try:
    import msvcrt   # Windows byte-range lock
except ImportError:
    msvcrt = None

ROOT = Path(__file__).resolve().parent.parent
PHASES = ("prepare", "provision", "probe", "demo", "archive", "retrieve")
# separate DURABLE scopes per phase; the backend creates a scope's row once from these values and never re-sizes it.
CAPS = {"provision": {"flyer": 0, "ads_api": 0, "ads_img": 0, "env": {"ECOM_CHAT_MAX_ITERATIONS": "6"}},
        "probe": {"flyer": 1, "ads_api": 0, "ads_img": 0, "env": {"ECOM_FLYER_MAX_ITERATIONS": "8"}},
        "demo": {"flyer": 2, "ads_api": 8, "ads_img": 4, "env": {"ECOM_FLYER_MAX_ITERATIONS": "30"}}}
SECRET_KEYS = ("GEMINI_API_KEY", "SCRAPECREATORS_API_KEY", "NEBIUS_API_KEY")
LIVE_KEYS = ("LLM_PROVIDER", "LLM_MODEL", "GEMINI_API_KEY", "GEMINI_MODEL", "GEMINI_IMAGE_SIZE", "SCRAPECREATORS_API_KEY")
DUMMY = {"LLM_PROVIDER": "nebius-token-factory", "LLM_MODEL": "mock-model", "NEBIUS_API_KEY": "mock-key", "GEMINI_API_KEY": "TEST-GEMINI-KEY-SENTINEL",
         "SCRAPECREATORS_API_KEY": "TEST-SCRAPE-KEY-SENTINEL"}   # values tests/mock_gemini.py / mock_fb_ads.py expect; not credentials
DENY_ENV = re.compile(r"(?i)(KEY|TOKEN|SECRET|PASSWORD|^ECOM_|^HERMES_|^LLM_|^NEBIUS_|^GEMINI_|^SCRAPECREATORS_|^CODEX_|^OPENAI|SSLKEYLOGFILE)")
RETRY_CFG = {"agent": {"api_max_retries": 1, "auto_recovery_cycles": 0}}
DEAD = "http://127.0.0.1:9"   # nothing listens here: a provider call from an inert server fails closed instead of reaching the internet
SCRIPTED_COMPANY = {"name": "Harbor Textiles", "products": "Wool throws (fictional test data)", "customers": "Home buyers (fictional)",
                    "goal": "Present our textiles clearly and accurately", "brand": "Calm, natural, plain-spoken"}
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")
NOTICE = "FICTIONAL TEST DATA for the scripted demo runner: the merchant and product are invented and every image is a generated placeholder, not a photograph."


class Refused(Exception):
    pass


# ---------------------------------------------------------------- small helpers
def sha(b):
    return hashlib.sha256(b).hexdigest()


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def free_ports(n):
    """n DISTINCT free ports (all sockets are held until every port is chosen; asking one at a time can hand the same number out twice)."""
    socks = [socket.socket() for _ in range(n)]
    try:
        for s in socks:
            s.bind(("127.0.0.1", 0))
        return [s.getsockname()[1] for s in socks]
    finally:
        for s in socks:
            s.close()


def load(d):
    p = Path(d) / "runner_state.json"
    if not p.is_file():
        raise Refused(f"{d} is not a prepared demo directory (no runner_state.json). Run prepare first.")
    st = json.loads(p.read_text(encoding="utf-8"))
    if st.get("mode") == "scripted":
        time.sleep(float(os.environ.get("V2_06_TEST_LOAD_DELAY") or 0))   # test seam only: widens the window between reading state and claiming a phase
    return st


class claim:
    """Exclusive, OS-held claim on one demo directory for the whole invocation (a lock file in the system temp folder, keyed by the folder; the OS drops the lock if the process dies, so it cannot go
    stale). A competing invocation is refused BEFORE it loads state, starts a server or sends anything."""

    def __init__(self, d):
        self.path = Path(tempfile.gettempdir()) / ("v2_06_demo_" + hashlib.sha1(str(Path(d).resolve()).lower().encode()).hexdigest()[:16] + ".lock")   # outside the project

    def __enter__(self):
        self.f = open(self.path, "a+b")
        try:
            if msvcrt:
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.f.close()
            raise Refused("another invocation holds this demo directory; nothing was started. Wait for it to finish; this runner never runs two operations on one demo.")
        return self

    def __exit__(self, *a):
        try:
            if msvcrt:
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            self.f.close()


def save(d, st):
    p = Path(d) / "runner_state.json"
    tmp = p.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(st, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def _req(port, method, path, body=None, timeout=60, raw=False):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        c.request(method, path, json.dumps(body) if body is not None else None, {"Content-Type": "application/json"})
        r = c.getresponse()
        data = r.read()
    finally:
        c.close()
    return r.status, (data if raw else json.loads(data))


READ_RETRIES = []   # transport faults absorbed by re-reading an idempotent GET (recorded in the evidence; a GET never costs a provider request)


def get(port, path, raw=False, tries=5):
    """Read-only GET. The app's local loopback occasionally resets a large response (undiagnosed, not fixed); a GET has no side effect, so it is simply read again.
    Only GETs are ever re-sent: a turn (POST) is never resubmitted."""
    for i in range(tries):
        try:
            return _req(port, "GET", path, raw=raw)
        except (ConnectionError, http.client.HTTPException, ValueError, OSError) as e:
            READ_RETRIES.append({"path": path.split("?")[0], "error": type(e).__name__})
            if i == tries - 1:
                raise
            time.sleep(1)


def _post(port, path, body, timeout):   # module level on purpose: tests replace it to simulate a dropped connection
    return _req(port, "POST", path, body, timeout=timeout)


def clean_env():
    return {k: v for k, v in os.environ.items() if not DENY_ENV.search(k)} | {"PYTHONUTF8": "1"}


def env_file(p):
    out = {}
    if Path(p).is_file():
        for line in Path(p).read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _token_strings(o, out):
    if isinstance(o, dict):
        for k, v in o.items():
            if isinstance(v, str) and len(v) >= 8 and re.search(r"(?i)(token|api_key|secret)", str(k)):
                out.add(v)
            else:
                _token_strings(v, out)
    elif isinstance(o, list):
        for v in o:
            _token_strings(v, out)


def secret_values(d):
    """Every non-empty credential value the demo holds - API keys in its env file AND the OAuth tokens of the demo's OWN auth files - for archive scrubbing and scans."""
    e = env_file(Path(d) / "secrets" / "local.env")
    out = {v for k, v in e.items() if k in SECRET_KEYS and v}
    for f in (Path(d) / "runtime" / "hermes_home").rglob("auth.json"):
        try:
            _token_strings(json.loads(f.read_text(encoding="utf-8")), out)
        except (OSError, ValueError):
            pass
    return sorted(out, key=len, reverse=True)


# ---------------------------------------------------------------- owned-process teardown
def _stop(proc, force=False):   # module level so a test can model a process that cannot be stopped
    try:
        proc.kill() if force else proc.terminate()
    except psutil.Error:
        pass


def owned_processes(roots, d, since=0.0):
    """Processes THIS demo stack owns: every descendant of the processes it spawned (the app server's Hermes workers and their children), plus any python process that
    started during this stack's life with its working directory inside the demo folder (a worker whose parent already died). Nothing else: not the real project, not a
    personal Hermes session, not a shell that merely sits in the folder."""
    d, seen = Path(d).resolve(), {}
    for r in roots:
        try:
            for c in [r, *r.children(recursive=True)]:
                seen[c.pid] = c
        except psutil.Error:
            pass
    for p in psutil.process_iter(["pid", "name", "create_time"]):
        try:
            if p.pid != os.getpid() and p.info["name"] and p.info["name"].lower().startswith("python") and p.info["create_time"] >= since - 1 and Path(p.cwd()).resolve().is_relative_to(d):
                seen[p.pid] = p
        except (psutil.Error, OSError, ValueError):
            pass
    return [p for p in seen.values() if p.pid != os.getpid()]


def teardown_owned(roots, d, grace=10.0, since=0.0):
    """Stop (terminate, then kill) and WAIT for every owned process; a rescan catches anything spawned while stopping. -> {confirmed, stopped, survivors}. Stopping local
    processes cannot undo a request they already dispatched; that stays an unknown completion."""
    procs = owned_processes(roots, d, since)
    for p in procs:
        _stop(p)
    _, alive = psutil.wait_procs(procs, timeout=grace)
    for p in alive:
        _stop(p, force=True)
    _, alive = psutil.wait_procs(alive, timeout=grace)
    late = [p for p in owned_processes([], d, since) if p.is_running()]
    alive = {p.pid: p for p in [*alive, *late]}
    return {"confirmed": not alive, "stopped": len(procs), "survivors": [{"pid": p.pid, "name": p.name()} for p in alive.values() if p.is_running()]}


# ---------------------------------------------------------------- servers
class Stack:
    """The demo app server (cwd = the demo copy, never the real project) and, in scripted mode, the three scripted stand-ins. All on free ports."""

    def __init__(self, d, st, phase, inert=False, opts=None, state_dir=None):
        self.d, self.st, self.phase, self.inert, self.opts = Path(d), st, phase, inert, opts or {}
        self.state_dir = Path(state_dir or d)   # where runner_state.json lives (differs from the server root for the credential-free retrieval copy)
        self.t0 = time.time()
        self.start_retries = 0
        self.procs, self.mock = [], {}
        self.port, *others = free_ports(4)
        self._mock_ports = dict(zip(("llm", "gem", "fb"), others))

    def _spawn(self, args, env):
        (self.d / "logs").mkdir(exist_ok=True)   # process output for diagnosis only (not archived); the demo server prints no credentials
        log = open(self.d / "logs" / f"{self.phase}-{Path(args[-2] if args[0] == '-m' else args[0]).stem}.log", "ab")
        p = subprocess.Popen([sys.executable, *args], cwd=self.d, env=env, stdout=log, stderr=subprocess.STDOUT)
        self.procs.append(p)
        return p

    def _wait(self, port, path, tries=120):
        """Readiness probe with a hard wall-clock bound (short per-request timeout, fresh connection each time): a stalled local connection can delay it, never hang it."""
        deadline = time.time() + max(30.0, tries * 0.75)
        while time.time() < deadline:
            try:
                if _req(port, "GET", path, timeout=5)[0] == 200:
                    return
            except Exception:
                pass
            time.sleep(0.5)
        raise RuntimeError(f"service on port {port} did not start within the bound")

    def env(self):
        st, ph = self.st, self.phase
        e = clean_env()
        e.update({"ECOM_TIMING": "1", "ECOM_CATALOGUE_FILE": st["inputs"]["catalogue"], "ECOM_IMAGE_DIRS": st["inputs"]["images"]})
        caps = CAPS.get(ph)
        if caps:
            e.update({"ECOM_FLYER_SCOPE": st["scopes"][ph]["flyer"], "ECOM_FLYER_MAX_ATTEMPTS": str(caps["flyer"]),
                      "ECOM_ADS_SCOPE": st["scopes"][ph]["ads"], "ECOM_ADS_API_MAX": str(caps["ads_api"]), "ECOM_ADS_IMAGE_MAX": str(caps["ads_img"]),
                      "ECOM_ADS_RUN_API_MAX": str(caps["ads_api"]), "ECOM_ADS_RUN_IMAGE_MAX": str(caps["ads_img"]), **caps["env"]})
        else:   # archive / retrieve: no phase scope is configured and no provider is reachable
            e.update({"ECOM_FLYER_SCOPE": "v2-06-readonly", "ECOM_FLYER_MAX_ATTEMPTS": "0", "ECOM_ADS_SCOPE": "v2-06-readonly", "ECOM_ADS_API_MAX": "0",
                      "ECOM_ADS_IMAGE_MAX": "0"})
        if st["mode"] == "scripted":
            e.update({"ECOM_CLASSIFIER": "off", "ECOM_VISION_MODELS": "" if self.opts.get("vision") is False else "nebius-token-factory:mock-model", "ECOM_FLYER_ALLOW_SYNTHETIC": "1", "ECOM_PHOTO_HOSTS": "127.0.0.1",
                      "NEBIUS_BASE_URL": f"http://127.0.0.1:{self.mock['llm']}/v1", "ECOM_GEMINI_URL": f"http://127.0.0.1:{self.mock['gem']}",
                      "ECOM_SCRAPECREATORS_URL": f"http://127.0.0.1:{self.mock['fb']}"})
        elif self.inert:
            e.update({"ECOM_GEMINI_URL": DEAD, "ECOM_SCRAPECREATORS_URL": DEAD})
        else:   # live: main's requests are classified by the real local Laya (read-only use of its environment and model cache)
            laya, hf = ROOT / ".venv-laya" / "Scripts" / "python.exe", ROOT / "runtime" / "hf_cache"
            if not (laya.is_file() and hf.is_dir()):
                raise Refused("the local Laya classifier (.venv-laya, runtime/hf_cache) is not available; main-agent routing cannot run")
            e.update({"ECOM_LAYA_PY": str(laya), "ECOM_HF_CACHE": str(hf)})
        return e

    def __enter__(self):
        try:
            try:
                return self._enter()
            except RuntimeError as e:
                if "did not start" not in str(e):
                    raise
                # a local start-up stall (seen on this PC: a stand-in accepts connections but never answers). Nothing has been sent to any provider yet, so stop what this
                # stack started and start ONCE more on fresh ports; the retry is recorded.
                self.start_retries = 1
                teardown_owned([psutil.Process(p.pid) for p in self.procs if p.poll() is None], self.d, since=self.t0)
                self.procs, self.mock = [], {}
                self.port, *others = free_ports(4)
                self._mock_ports = dict(zip(("llm", "gem", "fb"), others))
                return self._enter()
        except BaseException:
            self.__exit__()
            raise

    def _enter(self):
        if self.st["mode"] == "scripted":
            for name, script in (("llm", "mock_llm.py"), ("gem", "mock_gemini.py"), ("fb", "mock_fb_ads.py")):
                self.mock[name] = self._mock_ports[name]
                self._spawn([f"tests/{script}", str(self.mock[name])], clean_env())
            self._wait(self.mock["llm"], "/stats", tries=60)
            self._wait(self.mock["gem"], "/stats", tries=60)
            self._wait(self.mock["fb"], "/stats", tries=60)
            o = self.opts
            _req(self.mock["gem"], "POST", "/control", {"reset": True, "mode": o.get("gem_mode", "ok"), **({"colors": o["colors"]} if o.get("colors") else {})})
            _req(self.mock["fb"], "POST", "/control", {"reset": True, **o.get("fb", {"first": "relevant", "reach": "absent"})})
        self.server_env = self.env()
        self._spawn(["-m", "app.server", str(self.port)], self.server_env)
        self._wait(self.port, "/api/status", tries=160)
        return self

    def __exit__(self, *a):
        roots = []
        for p in self.procs:
            try:
                roots.append(psutil.Process(p.pid))
            except psutil.Error:
                pass
        res = teardown_owned(roots, self.d, since=self.t0)
        for p in self.procs:
            p.poll()
        self.teardown = {**res, "start_retries": self.start_retries, "at": now()}
        self.st.setdefault("teardown", {})[self.phase] = self.teardown
        if not res["confirmed"]:
            self.st["unstable_teardown"] = True   # archive and retrieval must not claim a stable snapshot
        if (self.state_dir / "runner_state.json").is_file():
            save(self.state_dir, self.st)
        time.sleep(1)

    def provider_counts(self):
        """Requests the scripted stand-ins actually received during this stack's life (scripted mode); None in live mode (no independent counter)."""
        if self.st["mode"] != "scripted":
            return None
        return {"reasoning_requests": get(self.mock["llm"], "/stats")[1]["requests"], "gemini_requests": get(self.mock["gem"], "/stats")[1]["total"],
                "scraper_and_cdn_requests": get(self.mock["fb"], "/stats")[1]["total"]}


# ---------------------------------------------------------------- phase bookkeeping
READ_ONLY_PHASES = ("archive", "retrieve")   # they send no model, scraper or Gemini request, so an attempt that crashed or failed may be repeated; paid phases never


def begin(d, st, phase, live_ok=False, approve_demo=False):
    prior = st["phases"].get(phase)
    if prior and not (phase in READ_ONLY_PHASES and prior.get("status") in ("started", "failed", "crashed")):
        raise Refused(f"phase {phase} was already attempted here (status {st['phases'][phase].get('status')}). This runner never re-runs a phase, resets a ledger or "
                      "creates a new allowance scope to get past a failure; a new attempt needs a new prepared directory and a new approval.")
    need = {"provision": "prepare", "probe": "provision", "demo": "probe", "retrieve": "archive"}.get(phase)
    if need and st["phases"].get(need, {}).get("status") != "completed":
        raise Refused(f"{phase} needs a completed {need} phase (found {st['phases'].get(need, {}).get('status')}).")
    if phase == "demo" and not approve_demo:
        raise Refused("the demonstration needs --approve-demo, given only after the probe report was read. It never follows the probe automatically.")
    if st["mode"] == "live" and phase in ("provision", "probe", "demo"):
        if not live_ok:
            raise Refused(f"{phase} in live mode spends real provider allowance: pass --live-authorized (explicit, per phase).")
        if st["auth_arrangement"] == "unresolved":
            raise Refused("authentication arrangement is UNRESOLVED. Same-account demo sign-in may invalidate the existing login; Arjun must choose "
                          "(shared canonical refresh owner, or accept the re-login trade-off) and prepare with --auth-arrangement demo-own-signin-accepted.")
        if not (Path(d) / "runtime" / "hermes_home" / "auth.json").is_file():
            raise Refused("the demo copy holds no sign-in of its own (runtime/hermes_home/auth.json); the real login is never copied.")
    st["phases"][phase] = {"status": "started", "started": now(), **({"earlier_attempts": [*(prior.get("earlier_attempts") or []), {k: prior.get(k) for k in ("status", "started", "error")}]} if prior else {})}
    save(d, st)
    return st["phases"][phase]


def timing_api_calls(d, since):
    p = Path(d) / "runtime" / "timing.jsonl"
    n, turns = 0, 0
    if p.is_file():
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("kind") == "chat" and r.get("ts", 0) >= since:
                n += int(r.get("api_calls") or 0)
                turns += 1
    return {"api_end_events": n, "chat_turns": turns}


def busy(port, agent):
    try:
        return agent in get(port, "/api/state")[1]
    except Exception:
        return False


def send_turn(d, st, rec, stack, agent, message, request_id, timeout, settle):
    """ONE POST. Any transport failure, timeout or unreadable answer is 'unknown completion': read-only polling, evidence, stop. Never a second POST."""
    rec.update(request_id=request_id, agent=agent, posts=1, message_chars=len(message))
    save(d, st)   # recorded BEFORE the request leaves
    try:
        code, r = _post(stack.port, f"/api/chat/{agent}", {"message": message, "request_id": request_id}, timeout)
    except Exception as e:
        deadline = time.time() + settle
        while busy(stack.port, agent) and time.time() < deadline:
            time.sleep(1)
        still = busy(stack.port, agent)
        row = None
        if not still:   # read-only: did the backend store this turn's outcome? (the app saves the agent/error row itself, whatever happened to the HTTP answer)
            try:
                rows = get(stack.port, f"/api/chat/{agent}", tries=3)[1]
                if len(rows) >= 2 and rows[-2]["who"] == "user" and rows[-2]["content"].strip() == message.strip() and rows[-1]["who"] in ("agent", "error"):
                    row = rows[-1]
            except Exception:
                row = None
        if row is not None:   # the answer was lost in transit but the backend's own transcript confirms the finished turn: use THAT, still never resend
            rec.update(status="completed" if row["who"] == "agent" else "failed", answer_lost_in_transit=True, confirmed_from_transcript=True,
                       transport_error=type(e).__name__, reply=str(row.get("content") or "")[:1500],
                       activity=[{"tool": a.get("tool"), "status": a.get("status")} for a in row.get("activity") or []],
                       note="The HTTP answer was lost; the outcome was read from the backend transcript. Nothing was resubmitted.")
            return {"ok": row["who"] == "agent", "text": row.get("content")}
        rec.update(status="unknown_completion", transport_error=type(e).__name__, still_running_after_settle=still,
                   note="The answer was lost and the transcript does not confirm a finished turn. Nothing was resubmitted. Read the transcript and ledgers.")
        return None
    if code != 200 or not isinstance(r, dict) or not r.get("ok"):
        rec.update(status="failed", http_status=code, error=str((r or {}).get("error") if isinstance(r, dict) else r)[:400])
    else:
        rec.update(status="completed", http_status=code)
    rec.update(reply=str((r or {}).get("text") or "")[:1500] if isinstance(r, dict) else "",
               activity=[{"tool": a.get("tool"), "status": a.get("status")} for a in (r.get("activity") or [])] if isinstance(r, dict) else [])
    return r


def rows(d, sql, *a):
    c = sqlite3.connect(f"file:{(Path(d) / 'runtime' / 'app.db').as_posix()}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in c.execute(sql, a).fetchall()]
    finally:
        c.close()


def review_binding(d, st, rid, cand, problems, label):
    """The candidate's review row must belong to THIS agent and request, have been delivery-verified, and rest on an inspection of exactly this candidate's pixels."""
    rv = rows(d, "SELECT request_id, agent_id, verified, verdict, inspection_id, sha256 FROM flyer_reviews WHERE candidate_id=?", cand["candidate_id"])
    if not rv:
        problems.append(f"{label}: no review is recorded for candidate {cand['candidate_id']}")
        return None
    r = rv[0]
    if r["request_id"] != rid or r["agent_id"] != st["specialist"]["agent_id"]:
        problems.append(f"{label}: the review is bound to a different agent/request")
    if not r["verified"]:
        problems.append(f"{label}: the review is not delivery-verified (the candidate's pixels were not confirmed delivered to the reviewing model)")
    ins = rows(d, "SELECT kind, sha256 FROM image_inspections WHERE id=?", r["inspection_id"]) if r["inspection_id"] else []
    out_sha = (cand.get("output") or {}).get("sha256")
    if not ins or ins[0]["kind"] != "flyer_candidate" or not (ins[0]["sha256"] == r["sha256"] == out_sha):
        problems.append(f"{label}: no actual-image inspection of exactly this candidate is recorded")
    return r


def phase_outcome(d, st, phase, rec, port):
    """Technical outcome of a probe/demonstration from the backend's own records (flyer run, candidates, inspection, review, research package), never from the chat reply.
    A verified review that reports content defects is a valid result; it is recorded, not required to be favourable."""
    rid, ag, problems = rec.get("request_id"), st["specialist"]["agent_id"], []
    out = {"request_id": rid, "agent_id": ag, "technical_ok": False, "problems": problems}
    runs = rows(d, "SELECT run_id, scope FROM flyer_runs WHERE agent_id=? AND request_id=?", ag, rid)
    if not runs:
        problems.append("no flyer run exists for this agent and request: nothing was generated")
        return out
    out.update(flyer_id=runs[0]["run_id"], scope=runs[0]["scope"])
    if runs[0]["scope"] != st["scopes"][phase]["flyer"]:
        problems.append(f"the flyer run used scope {runs[0]['scope']!r}, not this phase's scope")
    det = get(port, f"/api/flyers/{runs[0]['run_id']}")[1]
    cands = det.get("candidates") or []
    good = [c for c in cands if c.get("outcome") == "ok" and (c.get("integrity") or {}).get("state") == "valid"]
    out.update(flyer_status=det.get("status"), attempts_used=(det.get("attempts") or {}).get("used"), final_selected=bool((det.get("final") or {}).get("selected")),
               candidates=[{"candidate_id": c["candidate_id"], "outcome": c.get("outcome"), "integrity": (c.get("integrity") or {}).get("state")} for c in cands])
    if not good:
        problems.append("no valid generated candidate exists (generation failed, outcome unknown, or the stored file is damaged)")
        return out
    target = good[0]
    if phase == "demo":
        fin = det.get("final") or {}
        pk = rows(d, "SELECT package_id, status FROM ad_packages WHERE agent_id=? AND request_id=?", ag, rid)
        out["ad_package_id"] = pk[0]["package_id"] if pk else None
        if not pk:
            problems.append("no ad-research package exists for this request: the flyer rests on no research evidence")
        elif pk[0]["status"] == "blocked":
            problems.append("the ad-research package is blocked (no usable references)")
        elif (det.get("research") or {}).get("ad_package_id") != pk[0]["package_id"]:
            problems.append("the flyer does not cite this request's ad-research package")
        if not fin.get("selected") or not fin.get("candidate_id"):
            problems.append("no explicit final selection was recorded")
        else:
            target = next((c for c in good if c["candidate_id"] == fin["candidate_id"]), None)
            if target is None:
                problems.append("the selected final candidate is not a valid generated candidate")
            elif not str(fin.get("rationale") or "").strip():
                problems.append("the final selection has no rationale")
    if target is not None:
        out["candidate_id"] = target["candidate_id"]
        r = review_binding(d, st, rid, target, problems, "final candidate" if phase == "demo" else "candidate")
        if r:
            out.update(review_verified=bool(r["verified"]), review_verdict=r["verdict"])
    out["technical_ok"] = not problems
    return out


def ledgers(port):
    return {"flyer_allowance": get(port, "/api/flyers/allowance")[1], "ads_allowance": get(port, "/api/ads/allowance")[1]}


def finish_phase(d, st, rec, stack, since):
    rec["ended"] = now()
    rec["observed"] = {"timing_log": timing_api_calls(d, since), "provider_stand_ins": None}
    pc = stack.provider_counts()
    if pc:
        rec["observed"]["provider_stand_ins"] = {"reasoning_requests": pc["reasoning_requests"], "gemini_requests": pc["gemini_requests"],
                                                 "scraper_and_cdn_requests": pc["scraper_and_cdn_requests"]}
    rec["ledgers_after"] = ledgers(stack.port)
    rec["flyers"] = [{"flyer_id": f["flyer_id"], "status": f.get("status")} for f in get(stack.port, "/api/flyers")[1]]
    save(d, st)
    (Path(d) / f"phase-{rec['name']}.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- instructions (the text the agents actually receive)
SPECIALIST_OBJECTIVE = ("Research US Facebook image ads for the merchant's product category, generate ONE accurate promotional flyer from the merchant's own supplied "
                        "photographs, review the candidate's actual pixels, correct it at most once, and select one final candidate with a rationale.")
SPECIALIST_INSTRUCTIONS = (
    "You work for {company}. Use only the supplied catalogue facts, the declared price and the merchant's own photographs; never invent a fact. "
    "Competitor ad images are references for layout ideas only; they are never sent to the image generator and never copied. "
    "Order of work: read the catalogue; research US Facebook image ads within your backend allowance; inspect the merchant photographs you rely on; call generate_flyer "
    "once; inspect_flyer on the candidate; then review_flyer in a LATER step (never in the same step as inspect_flyer). If review_flyer records defects you may correct "
    "ONCE with generate_flyer using previous_candidate_id; there is no second correction and no third generation. Finish with finalize_flyer naming one candidate and why. "
    "If a tool answers allowance_exhausted, blocked, unknown or failed, stop that line of work and say so plainly; never retry the same call, never work around a limit. "
    "A review is a fallible agent review: report it as 'agent review passed' or 'unresolved issues', never as approved. If the image was not actually delivered to you, "
    "say the flyer is unchecked.")
SKILL = {"name": "flyer-routine", "content": "# Flyer routine\n1. Read the catalogue and the supplied facts.\n2. Research ads, inspect the photographs you rely on.\n"
         "3. Generate one flyer, inspect its pixels, review it in a later step.\n4. Correct once only for a recorded defect; select one final candidate."}
PROVISION_PROSE = (
    "Please create exactly one specialist agent for {company}: a social_media specialist named \"{name}\". Give it exactly these tools and no others: {tools}. "
    "Objective: {objective} Instructions for it: {instructions} Do not create any other agent, do not change the company profile and do not ask me to confirm; "
    "report the agent id and its granted tools.")
PROBE_PROSE = (
    "PROBE (contract check, one request). Do not research competitors. Read the catalogue, choose ONE product photograph, and call generate_flyer exactly once for "
    "the product with a short factual prompt (product name and the declared price). Then call inspect_flyer on that candidate, and in a later step review_flyer on it. "
    "Do not correct, do not generate again and do not select a final candidate. Report the flyer id, the candidate id and the review status as they are.")
DEMO_PROSE = (
    "DEMONSTRATION (one request). Research US Facebook image ads for the product category within your allowance and choose the references yourself; inspect the "
    "merchant photographs you rely on; generate one flyer; inspect its actual pixels and review it in a later step; correct at most once, only for a defect the review "
    "recorded; then finalize exactly one candidate with a short rationale. Report what each step returned, including any limit you hit. Do not call the result approved.")


def specialist_spec(st):
    return {"role": "social_media", "name": f"{st['company']} Social Media Specialist", "company_context_refs": [], "skills": [SKILL],
            "objective": SPECIALIST_OBJECTIVE, "instructions": SPECIALIST_INSTRUCTIONS.format(company=st["company"]), "requested_tools": st["specialist_tools"]}


def scripted_markers(opts, base):
    return " ".join([*base, *opts.get("markers", [])])


# ---------------------------------------------------------------- phases
def catalogue_image_ids(cat):
    ids = []
    for p in cat.get("products") or []:
        if isinstance(p, dict):
            for it in (p.get("images") if isinstance(p.get("images"), list) and p["images"] else [p.get("image")]):
                iid = it.get("image_id") if isinstance(it, dict) else it
                if isinstance(iid, str) and iid not in ids:
                    ids.append(iid)
    return ids


def find_image(folder, iid):
    return next((q for e in IMAGE_EXTS for q in [Path(folder) / f"{iid}{e}"] if q.is_file()), None)


def cmd_prepare(a):
    d = Path(a.dir).resolve()
    if d.exists() and any(d.iterdir()):
        raise Refused(f"{d} already exists and is not empty; prepare only creates new directories.")
    try:
        inside = d.is_relative_to(ROOT)
    except AttributeError:
        inside = str(d).startswith(str(ROOT))
    if inside and subprocess.run(["git", "check-ignore", "-q", str(d / "x")], cwd=ROOT).returncode != 0:
        raise Refused(f"{d} is inside the project but not git-ignored; use a folder under demo/ (ignored) or outside the project.")
    if a.mode == "live":
        for f, flag in ((a.env_source, "--env-source"), (a.catalogue, "--catalogue"), (a.images, "--images")):
            if not f:
                raise Refused(f"live mode needs {flag}.")
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "v2_06_readiness.py"), "--catalogue", a.catalogue, "--images", a.images, "--env", a.env_source],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise Refused("inputs are not READY (scripts/v2_06_readiness.py):\n" + r.stdout[-1500:])
    d.mkdir(parents=True, exist_ok=True)
    for sub in ("app",):
        shutil.copytree(ROOT / sub, d / sub, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (d / "scripts").mkdir()
    for f in ("setup.py", "marketplace_check.py"):   # setup, and the code app/research.py imports for its pure helpers (no ledger or data is copied)
        shutil.copy2(ROOT / "scripts" / f, d / "scripts" / f)
    if a.mode == "scripted":
        (d / "tests").mkdir()
        for f in ("mock_llm.py", "mock_gemini.py", "mock_fb_ads.py"):
            shutil.copy2(ROOT / "tests" / f, d / "tests" / f)
    # explicit allow-list was copied above; nothing from runtime/, secrets/ or any auth file may exist in the copy
    leaked = [str(p.relative_to(d)) for p in d.rglob("*") if p.name in ("auth.json", "app.db", "local.env") or "runtime" in p.relative_to(d).parts[:1]]
    if leaked:
        raise Refused(f"the copy would contain private files: {leaked}")
    (d / "secrets").mkdir()
    if a.mode == "scripted":
        lines = [f"{k}={v}" for k, v in DUMMY.items()]
    else:
        src = env_file(a.env_source)
        lines = [f"{k}={src[k]}" for k in LIVE_KEYS if src.get(k)]
    (d / "secrets" / "local.env").write_text("\n".join(lines) + "\n", encoding="ascii")
    inp = d / "inputs"
    if a.mode == "scripted" and not a.catalogue:
        from PIL import Image, ImageDraw
        (inp / "images").mkdir(parents=True)
        for name, color, fmt, ext in (("hw-front", (200, 120, 60), "PNG", "png"), ("hw-detail", (60, 130, 190), "JPEG", "jpg")):
            im = Image.new("RGB", (600, 800), color)
            ImageDraw.Draw(im).ellipse([150, 200, 450, 600], fill=(255, 255, 255))
            im.save(inp / "images" / f"{name}.{ext}", fmt)
        cat = {"schema": 1, "demo": False, "notice": NOTICE, "merchant": {"merchant_id": "harbor-textiles", "name": "Harbor Textiles"},
               "products": [{"product_id": "harbor-wool-throw", "name": "Heritage Wool Throw", "category": "throws", "condition": "new",
                             "specifications": {"size": "130 x 180 cm", "material": "100% wool", "care": "Dry clean"}, "price": {"amount": 64.5, "currency": "EUR"},
                             "images": [{"image_id": "hw-front", "kind": "test placeholder image (synthetic)"}, {"image_id": "hw-detail", "kind": "test placeholder image (synthetic)"}]}]}
        (inp / "catalogue.json").write_text(json.dumps(cat), encoding="utf-8")
        cat_path, img_dir = inp / "catalogue.json", inp / "images"
        company = dict(SCRIPTED_COMPANY)
    else:   # supplied from OUTSIDE (live, or scripted with --catalogue): COPIED into the demo, which then reads only its own copy (so later changes outside cannot alter it)
        src_cat, src_img = Path(a.catalogue).resolve(), Path(a.images).resolve()
        (inp / "images").mkdir(parents=True)
        shutil.copy2(src_cat, inp / "catalogue.json")
        for iid in catalogue_image_ids(json.loads(src_cat.read_text(encoding="utf-8"))):
            f = find_image(src_img, iid)
            if f is None:
                raise Refused(f"the catalogue registers image {iid!r} but the supplied photo folder has no such file; nothing further was prepared.")
            shutil.copy2(f, inp / "images" / f.name)
        cat_path, img_dir = inp / "catalogue.json", inp / "images"
        mer = json.loads(cat_path.read_text(encoding="utf-8")).get("merchant") or {}
        company = json.loads(Path(a.company_json).read_text(encoding="utf-8")) if a.company_json else (dict(SCRIPTED_COMPANY) if a.mode == "scripted" else {})
        company.setdefault("name", mer.get("name") or mer.get("company_name") or "")
    snapshot = {"catalogue": {"sha256": sha(cat_path.read_bytes())}, "images": {}}
    for iid in catalogue_image_ids(json.loads(cat_path.read_text(encoding="utf-8"))):
        f = find_image(img_dir, iid)
        if f is not None:
            snapshot["images"][iid] = {"file": f.name, "sha256": sha(f.read_bytes()), "bytes": f.stat().st_size}
    env = clean_env() | {"HERMES_HOME": str(d / "runtime" / "hermes_home")}
    r = subprocess.run([sys.executable, "scripts/setup.py"], cwd=d, env=env, capture_output=True, text=True)
    if r.returncode != 0:
        raise Refused("setup.py failed in the demo copy: " + r.stderr[-400:])
    names = subprocess.run([sys.executable, "-c", "import json; from app import core; print(json.dumps({'tools': sorted(set(core.FLYER_TOOLS)|set(core.AD_TOOLS)|"
                           "{'inspect_image','read_catalogue'})}))"], cwd=d, env=env, capture_output=True, text=True)
    tools = json.loads(names.stdout.strip().splitlines()[-1])["tools"]
    patch_config(d / "runtime" / "hermes_home" / "config.yaml")
    patch_config(d / "runtime" / "hermes_home" / "profiles" / "main" / "config.yaml")
    st = {"schema": 1, "mode": a.mode, "created": now(), "dir": str(d), "company": company["name"], "company_fields": company, "specialist_tools": tools,
          "inputs": {"catalogue": str(cat_path), "images": str(img_dir), "catalogue_sha256": snapshot["catalogue"]["sha256"], "synthetic": a.mode == "scripted",
                     "snapshot": snapshot, "supplied_from": str(Path(a.catalogue).resolve()) if a.catalogue else "generated synthetic fixtures"},
          "auth_arrangement": "scripted-dummy" if a.mode == "scripted" else a.auth_arrangement,
          "scopes": {p: {"flyer": f"v2-06-{p}-flyer", "ads": f"v2-06-{p}-ads"} for p in CAPS}, "caps": {p: {k: v for k, v in c.items()} for p, c in CAPS.items()},
          "phases": {"prepare": {"status": "completed", "started": now(), "ended": now()}}, "specialist": None}
    save(d, st)
    print(f"prepared {d} ({a.mode}); auth arrangement: {st['auth_arrangement']}")
    return 0


def patch_config(path):
    """Merge the demo-only retry/recovery settings into one config.yaml (other keys kept). Never touches a real profile: callers pass demo paths only."""
    import yaml
    p = Path(path)
    cur = yaml.safe_load(p.read_text(encoding="utf-8")) if p.is_file() else {}
    cur = cur if isinstance(cur, dict) else {}
    new = {**cur, "agent": {**(cur.get("agent") if isinstance(cur.get("agent"), dict) else {}), **RETRY_CFG["agent"]}}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(new), encoding="utf-8")


def cmd_provision(a):
    d = Path(a.dir).resolve()
    st = load(d)
    opts = scripted_opts(a, st)
    rec = begin(d, st, "provision", a.live_authorized)
    rec["name"] = "provision"
    since = time.time()
    with Stack(d, st, "provision", opts=opts) as s:
        code, _ = _req(s.port, "POST", "/api/company", {"fields": st["company_fields"]})
        if code != 200:
            rec.update(status="failed", error="company save failed", http_status=code)
        else:
            spec = specialist_spec(st)
            msg = PROVISION_PROSE.format(company=st["company"], name=spec["name"], tools=", ".join(spec["requested_tools"]), objective=spec["objective"],
                                         instructions=spec["instructions"])
            if st["mode"] == "scripted":   # the scripted main executes exactly this tool call; the real create_agent tool runs in Hermes either way
                msg += "\nCALL_TOOL:" + json.dumps({"name": "create_agent", "args": spec})
            before = {x["agent_id"] for x in get(s.port, "/api/agents")[1]}
            send_turn(d, st, rec, s, "main", msg, f"v2-06-provision-{int(time.time())}", a.turn_timeout, a.settle)
            new = [x for x in get(s.port, "/api/agents")[1] if x["agent_id"] not in before]
            if rec["status"] == "completed":
                if len(new) == 1 and new[0]["role"] == "social_media" and set(spec["requested_tools"]) <= set(new[0]["granted_tools"]):
                    ag = new[0]["agent_id"]
                    started = [w for w in get(s.port, "/api/workers")[1] if w["agent_id"] == ag]
                    patch_config(d / "runtime" / "hermes_home" / "profiles" / ag / "config.yaml")   # BEFORE the specialist's first worker exists
                    st["specialist"] = {"agent_id": ag, "granted_tools": new[0]["granted_tools"], "worker_existed_before_config_patch": bool(started)}
                else:
                    rec.update(status="incomplete", note=f"expected exactly one new social_media agent with the requested tools; found {[(x['role']) for x in new]}. "
                                                         "Nothing further was sent (main may have asked a question).")
        finish_phase(d, st, rec, s, since)
        rec["provider_counts_checked"] = {"scraper_and_cdn_requests": (rec["observed"]["provider_stand_ins"] or {}).get("scraper_and_cdn_requests"),
                                          "gemini_requests": (rec["observed"]["provider_stand_ins"] or {}).get("gemini_requests")}
        save(d, st)
    print(f"provision: {rec['status']}")
    return 0 if rec["status"] == "completed" else 3


def scripted_opts(a, st):
    if not a.scripted_opts:
        return {}
    if st["mode"] != "scripted":
        raise Refused("--scripted-opts is only valid in scripted mode.")
    t = a.scripted_opts
    return json.loads(Path(t[1:]).read_text(encoding="utf-8") if t.startswith("@") else t)


def run_request(a, phase, prose, base_markers):
    d = Path(a.dir).resolve()
    st = load(d)
    opts = scripted_opts(a, st)
    rec = begin(d, st, phase, a.live_authorized, getattr(a, "approve_demo", False))
    rec["name"] = phase
    since = time.time()
    if not st.get("specialist"):
        rec.update(status="failed", error="no provisioned specialist")
        save(d, st)
        return 3
    with Stack(d, st, phase, opts=opts) as s:
        msg = opts["message"] if opts.get("message") else prose   # scripted test seam: an arbitrary request text (for example one that makes no tool call)
        if st["mode"] == "scripted" and not opts.get("message"):
            first = json.loads(Path(st["inputs"]["catalogue"]).read_text(encoding="utf-8"))["products"][0]["images"][0]["image_id"]
            mk = [m for m in base_markers if not (opts.get("correct") and m == "NO_CORRECT")]
            if phase == "probe" and opts.get("ads"):
                mk = [m for m in mk if m != "SKIP_ADS"]
            msg += "\n" + scripted_markers(opts, [*mk] + ([f"IMAGES:{first}"] if phase == "probe" else []))
        send_turn(d, st, rec, s, st["specialist"]["agent_id"], msg, f"v2-06-{phase}-{int(time.time())}", a.turn_timeout, a.settle)
        chat_status = rec["status"]
        rec["chat_status"] = chat_status
        rec["outcome"] = phase_outcome(d, st, phase, rec, s.port)   # also for lost/failed turns: whatever the backend recorded is partial evidence
        if chat_status == "completed" and not rec["outcome"]["technical_ok"]:
            rec["status"] = "incomplete"   # an agent reply is not a result: the required artifact/inspection/review/selection records are missing
        finish_phase(d, st, rec, s, since)
        run_ids = [f["flyer_id"] for f in get(s.port, "/api/flyers")[1]]
        det = [get(s.port, f"/api/flyers/{r}")[1] for r in run_ids]
        mine = [x for x in det if x.get("identity", {}).get("request_id") == rec.get("request_id")]
        rec["flyer_for_this_request"] = [{"flyer_id": x["identity"]["run_id"], "scope": x["identity"]["scope"], "status": x.get("status"),
                                          "attempts_used": x["attempts"]["used"], "final": (x.get("final") or {}).get("candidate_id"),
                                          "reviews_verified": [bool((c.get("review") or {}).get("verified")) for c in x.get("candidates") or []]} for x in mine]
        save(d, st)
    print(f"{phase}: {rec['status']}" + (f" - {'; '.join(rec['outcome']['problems'])}" if rec["status"] == "incomplete" else ""))
    return 0 if rec["status"] == "completed" else 3


def cmd_probe(a):
    return run_request(a, "probe", PROBE_PROSE, ["REVIEW_AGENT", "SKIP_ADS", "NO_CORRECT", "NO_FINALIZE"])


def cmd_demo(a):
    return run_request(a, "demo", DEMO_PROSE, ["REVIEW_AGENT"])


# ---------------------------------------------------------------- evidence
def judge(path, expected):
    """State of one input file against the hashes the generation records (or, with no generation, the prepare-time snapshot) say it must have."""
    path = Path(path) if path else None
    if path is None or not path.is_file():
        return {"state": "missing", "recorded_sha256": sorted(expected), "current_sha256": None}, None
    raw = path.read_bytes()
    cur = sha(raw)
    state = "match" if expected and cur in expected else ("mismatch" if expected else "unverified")
    return {"state": state, "recorded_sha256": sorted(expected), "current_sha256": cur}, (raw if state == "match" else None)


def check_inputs(d, st):
    """Preserve the merchant inputs the demo actually used - the full catalogue (with provenance) and the photos - and validate each against what the flyer attempts
    recorded. Only a file whose current hash EQUALS the recorded one is archived; a changed or missing file is disclosed, never archived as the original."""
    snap = st["inputs"].get("snapshot") or {}
    rec_cat, rec_img = set(), {}
    attempts = rows(d, "SELECT inputs_json, product_json FROM flyer_attempts")
    for r in attempts:
        c = json.loads(r["product_json"] or "{}").get("catalogue_sha256")
        if c:
            rec_cat.add(c)
        for i in json.loads(r["inputs_json"] or "[]"):
            rec_img.setdefault(i["image_id"], set()).add(i["sha256"])
    out, blobs = {"generation_records": len(attempts), "images": {}}, {}
    out["catalogue"], raw = judge(st["inputs"]["catalogue"], rec_cat or ({snap["catalogue"]["sha256"]} if snap.get("catalogue") else set()))
    if raw is not None:
        blobs["inputs/catalogue.json"] = raw
    for iid in sorted(rec_img or snap.get("images") or {}):
        f = find_image(st["inputs"]["images"], iid)
        out["images"][iid], raw = judge(f, rec_img.get(iid) or ({snap["images"][iid]["sha256"]} if iid in (snap.get("images") or {}) else set()))
        if raw is not None:
            blobs[f"inputs/images/{f.name}"] = raw
    out["complete"] = out["catalogue"]["state"] == "match" and all(v["state"] == "match" for v in out["images"].values())
    return out, blobs


def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, default=str), encoding="utf-8")


def scrub(text, secrets):
    for s in secrets:
        text = text.replace(s, "***")
    return text


def cmd_archive(a):
    d = Path(a.dir).resolve()
    st = load(d)
    rec = begin(d, st, "archive")
    rec["name"] = "archive"
    secrets = secret_values(d)
    dest = d / "archive" / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    dest.mkdir(parents=True)
    with Stack(d, st, "archive", inert=True) as s:
        p = s.port
        files = {}

        def put_json(rel, obj):
            files[rel] = scrub(json.dumps(obj, indent=1, default=str), secrets)
        put_json("state.json", st)
        put_json("ledgers.json", ledgers(p))
        put_json("company.json", get(p, "/api/company")[1])
        agents = get(p, "/api/agents")[1]
        put_json("agents.json", agents)
        for ag in [x["agent_id"] for x in agents] + ["main"]:
            put_json(f"transcripts/{ag}.json", get(p, f"/api/chat/{ag}")[1])
        blobs = {}
        flyers = get(p, "/api/flyers")[1]
        put_json("flyers.json", flyers)
        for f in flyers:
            det = get(p, f"/api/flyers/{f['flyer_id']}")[1]
            put_json(f"flyers/{f['flyer_id']}.json", det)
            for c in det.get("candidates") or []:
                code, raw = get(p, f"/api/flyers/images/{c['candidate_id']}", raw=True)
                if code == 200:
                    blobs[f"flyers/{f['flyer_id']}/{c['candidate_id']}.img"] = raw
            code, raw = get(p, f"/api/flyers/images/{f['flyer_id']}", raw=True)
            if code == 200:   # the managed image endpoint also serves the ONLY valid candidate when nothing was selected: label it honestly
                blobs[f"flyers/{f['flyer_id']}/{'final' if (det.get('final') or {}).get('selected') else 'unselected-only-valid-candidate'}.img"] = raw
        runs = get(p, "/api/ads/runs")[1]
        put_json("ads/runs.json", runs)
        put_json("ads/packages.json", get(p, "/api/ads/packages")[1])
        for r in runs:
            rv = get(p, f"/api/ads/runs/{r['run_id']}")[1]
            put_json(f"ads/run-{r['run_id']}.json", rv)
            for iid in sorted(set(re.findall(r'"image_id": "([\w-]+)"', json.dumps(rv)))):
                code, raw = get(p, f"/api/ads/images/{r['run_id']}/{iid}", raw=True)
                if code == 200:
                    blobs[f"ads/{r['run_id']}/{iid}.img"] = raw
        for pk in get(p, "/api/ads/packages")[1]:
            put_json(f"ads/package-{pk['package_id']}.json", get(p, f"/api/ads/packages/{pk['package_id']}")[1])
        pc = s.provider_counts()
    chk, input_blobs = check_inputs(d, st)
    blobs.update(input_blobs)
    put_json("inputs_check.json", chk)
    put_json("inputs.json", {"prepare_time_snapshot": st["inputs"].get("snapshot"), "synthetic": st["inputs"]["synthetic"], "supplied_from": st["inputs"].get("supplied_from")})
    tl = d / "runtime" / "timing.jsonl"
    if tl.is_file():
        files["timing.jsonl"] = scrub(tl.read_text(encoding="utf-8"), secrets)
    put_json("observed.json", {n: st["phases"].get(n, {}).get("observed") for n in ("provision", "probe", "demo")} | {
        "note": "Reasoning requests are bounded only by iteration caps and the demo-only retry settings; auxiliary or other uncounted paths are not enumerated."})
    unstable = bool(st.get("unstable_teardown"))
    manifest = {"created": now(), "mode": st["mode"], "synthetic_inputs": st["inputs"]["synthetic"], "stable_snapshot": not unstable, "inputs_verified": chk["complete"], "files": {}}
    for rel, text in files.items():
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        (dest / rel).write_text(text, encoding="utf-8")
    for rel, raw in blobs.items():
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        (dest / rel).write_bytes(raw)
    for f in sorted(dest.rglob("*")):
        if f.is_file():
            manifest["files"][str(f.relative_to(dest)).replace("\\", "/")] = {"sha256": sha(f.read_bytes()), "bytes": f.stat().st_size}
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    bad = [r for r, m in manifest["files"].items() if sha((dest / r).read_bytes()) != m["sha256"]]
    leaked = [str(f.relative_to(dest)) for f in dest.rglob("*") if f.is_file() and any(s.encode() in f.read_bytes() for s in secrets)]
    quiet = not pc or not any(pc.values())
    ok = not bad and not leaked and quiet
    status = "failed" if not ok else "unstable_snapshot" if unstable else "inputs_mismatch" if not chk["complete"] else "completed"
    rec.update(status=status, stable_snapshot=not unstable, inputs_verified=chk["complete"], archive=str(dest), manifest_files=len(manifest["files"]), hash_mismatch=bad, secret_hits=leaked,
               provider_requests_during_archive=pc)
    if ok:   # the dummy/copied key lines are removed only AFTER the archive verified; the file keeps the provider/model lines
        keep = [l for l in (d / "secrets" / "local.env").read_text(encoding="utf-8").splitlines() if l.split("=", 1)[0].strip() in ("LLM_PROVIDER", "LLM_MODEL")]
        (d / "secrets" / "local.env").write_text("\n".join(keep) + "\n", encoding="ascii")
        rec["credentials_removed_from_demo_env"] = list(SECRET_KEYS)
    rec["ended"] = now()
    rec["read_retries"] = list(READ_RETRIES)
    st["archive_dir"] = str(dest)
    save(d, st)
    print(f"archive: {rec['status']} ({len(manifest['files'])} files) {dest}")
    return 0 if rec["status"] == "completed" else 3


def retrieval_copy(d, st):
    """An isolated, credential-free copy of what the app reads to answer GETs: its code, runtime database and managed files. The demo's Hermes home (its OAuth login, profiles,
    sessions), certificate bundle and every auth file are NOT copied; the env file keeps only the provider/model names. The original demo and the real project are untouched."""
    root = Path(d) / "retrieval" / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    root.mkdir(parents=True)
    shutil.copytree(Path(d) / "app", root / "app", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (root / "scripts").mkdir()
    shutil.copy2(Path(d) / "scripts" / "marketplace_check.py", root / "scripts" / "marketplace_check.py")
    if st["mode"] == "scripted":
        (root / "tests").mkdir()
        for f in ("mock_llm.py", "mock_gemini.py", "mock_fb_ads.py"):
            shutil.copy2(Path(d) / "tests" / f, root / "tests" / f)
    shutil.copytree(Path(d) / "runtime", root / "runtime", ignore=shutil.ignore_patterns("hermes_home", "auth.json", "auth.lock", "*.pem", "timing.jsonl"))
    (root / "secrets").mkdir()
    keep = [l for l in (Path(d) / "secrets" / "local.env").read_text(encoding="utf-8").splitlines() if l.split("=", 1)[0].strip() in ("LLM_PROVIDER", "LLM_MODEL")]
    (root / "secrets" / "local.env").write_text("\n".join(keep) + "\n", encoding="ascii")
    return root


def cmd_retrieve(a):
    d = Path(a.dir).resolve()
    st = load(d)
    rec = begin(d, st, "retrieve")
    rec["name"] = "retrieve"
    dest = Path(st["archive_dir"])
    man = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))
    before_db = db_signature(d)
    problems = []
    root = retrieval_copy(d, st)
    before_copy = db_signature(root)
    images_ok = 0
    with Stack(root, st, "retrieve", inert=True, state_dir=d) as s:
        p = s.port
        status = get(p, "/api/status")[1]
        env_creds = [k for k in s.server_env if re.search(r"(?i)(KEY|TOKEN|SECRET|PASSWORD)", k)]
        if not status.get("problem"):
            problems.append("the application's own provider-readiness check says inference is USABLE in the retrieval process")
        if env_creds:
            problems.append(f"credential-like variables reached the retrieval process: {env_creds}")
        if ledgers(p) != json.loads((dest / "ledgers.json").read_text(encoding="utf-8")):
            problems.append("allowance ledgers differ from the archive")
        for rel in man["files"]:
            m = re.fullmatch(r"flyers/(fly-[0-9a-f]{10})\.json", rel)
            if not m:
                continue
            arch = json.loads((dest / rel).read_text(encoding="utf-8"))
            now_ = get(p, f"/api/flyers/{m.group(1)}")[1]
            for k in ("status", "candidate_id"):
                if now_.get(k) != arch.get(k):
                    problems.append(f"{m.group(1)} {k} changed")
            if (now_.get("final") or {}).get("candidate_id") != (arch.get("final") or {}).get("candidate_id"):
                problems.append(f"{m.group(1)} final selection changed")
            for fin in (f"flyers/{m.group(1)}/final.img", f"flyers/{m.group(1)}/unselected-only-valid-candidate.img"):
                if fin in man["files"]:
                    code, raw = get(p, f"/api/flyers/images/{m.group(1)}", raw=True)
                    if code != 200 or sha(raw) != man["files"][fin]["sha256"]:
                        problems.append(f"{m.group(1)} managed image hash differs or is not served")
                    else:
                        images_ok += 1
            for c in arch.get("candidates") or []:
                rel_c = f"flyers/{m.group(1)}/{c['candidate_id']}.img"
                if rel_c in man["files"]:
                    code, raw = get(p, f"/api/flyers/images/{c['candidate_id']}", raw=True)
                    if code != 200 or sha(raw) != man["files"][rel_c]["sha256"]:
                        problems.append(f"candidate {c['candidate_id']} hash differs or is not served")
                    else:
                        images_ok += 1
        pc = s.provider_counts()
    if not st["teardown"]["retrieve"]["confirmed"]:
        problems.append("the retrieval server's shutdown could not be confirmed")
    auth_files = [str(f.relative_to(root)) for f in root.rglob("*") if f.is_file() and (f.name == "auth.json" or f.suffix == ".pem")]
    secrets_now = secret_values(d)
    data_files = [f for sub in ("runtime", "secrets") for f in (root / sub).rglob("*") if f.is_file()]   # the data the app serves; the copied stand-in SCRIPTS legitimately contain their dummy key constant
    hits = [str(f.relative_to(root)) for f in data_files if any(x.encode() in f.read_bytes() for x in secrets_now)]
    if auth_files or hits:
        problems.append(f"credential material is accessible inside the retrieval copy: {auth_files + hits}")
    if pc and (pc["reasoning_requests"] or pc["gemini_requests"] or pc["scraper_and_cdn_requests"]):
        problems.append(f"provider requests during retrieval: {pc}")
    after_db = db_signature(d)
    if before_db != after_db or before_copy != db_signature(root):
        problems.append("dispatch tables changed during retrieval")
    rec.update(status="completed" if not problems else "failed", problems=problems, provider_requests_during_retrieval=pc, dispatch_signature=after_db,
               retrieval={"root": str(root), "provider_problem": status.get("problem"), "provider_unusable": bool(status.get("problem")), "env_has_inference_credentials": bool(env_creds),
                          "credential_inventory": {"auth_files": auth_files, "secret_value_hits": hits}, "images_verified": images_ok},
               read_retries=list(READ_RETRIES), ended=now())
    save(d, st)
    dump(dest.parent / (dest.name + "-retrieval.json"), rec)
    print(f"retrieve: {rec['status']} {problems or ''}")
    return 0 if not problems else 3


def db_signature(d):
    """Row counts of every table that records a provider dispatch or an allowance use (read-only open)."""
    p = Path(d) / "runtime" / "app.db"
    c = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
    try:
        out = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("flyer_attempts", "flyer_reviews", "ad_calls", "ad_images", "research_calls", "messages")}
        out["flyer_used"] = c.execute("SELECT COALESCE(SUM(attempts_used),0) FROM flyer_allowance").fetchone()[0]
        return out
    finally:
        c.close()


def cmd_status(a):
    st = load(Path(a.dir).resolve())
    print(json.dumps({"mode": st["mode"], "auth_arrangement": st["auth_arrangement"], "scopes": st["scopes"], "specialist": st.get("specialist"),
                      "phases": {k: v.get("status") for k, v in st["phases"].items()}}, indent=1))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("phase", choices=PHASES[0:1] + PHASES[1:] + ("status",))
    ap.add_argument("--dir", required=True)
    ap.add_argument("--mode", choices=("scripted", "live"), default="scripted")
    ap.add_argument("--env-source")
    ap.add_argument("--catalogue")
    ap.add_argument("--images")
    ap.add_argument("--company-json")
    ap.add_argument("--auth-arrangement", choices=("unresolved", "demo-own-signin-accepted"), default="unresolved")
    ap.add_argument("--live-authorized", action="store_true")
    ap.add_argument("--approve-demo", action="store_true")
    ap.add_argument("--turn-timeout", type=float, default=1500.0)
    ap.add_argument("--settle", type=float, default=120.0, help="seconds of READ-ONLY polling after a lost answer before evidence is taken")
    ap.add_argument("--scripted-opts", help="JSON or @file: colors, gem_mode, fb, markers, ads, correct (scripted mode only)")
    a = ap.parse_args(argv)
    cmds = {"prepare": cmd_prepare, "provision": cmd_provision, "probe": cmd_probe, "demo": cmd_demo, "archive": cmd_archive, "retrieve": cmd_retrieve, "status": cmd_status}
    try:
        if a.phase == "status":
            return cmds["status"](a)
        with claim(Path(a.dir).resolve()):   # BEFORE any state is read: one invocation per demo directory at a time
            return cmds[a.phase](a)
    except Refused as e:
        print("REFUSED:", e)
        return 2
    except Exception as e:   # an unexpected crash is recorded (never silently left as 'started') and is NEVER retried by the runner
        try:
            st = load(Path(a.dir).resolve())
            rec = st["phases"].get(a.phase)
            if rec and rec.get("status") == "started":
                rec.update(status="crashed", error=f"{type(e).__name__}: {str(e)[:300]}", ended=now())
                save(Path(a.dir).resolve(), st)
        except Exception:
            pass
        print(f"CRASHED in {a.phase}: {type(e).__name__}: {str(e)[:300]}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
