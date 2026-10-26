"""Batch A tests (roadmap tickets 01 + 02): prepared-demo-source onboarding, answers -> shared company context, chat unlock. SCRIPTED stand-in only: tests/mock_llm.py answers
the two onboarding turns by rule from the snapshot/answer text it is handed (a test double, NOT a model and never evidence of model quality). The backend, the real Hermes worker,
the persisted state machine, the HTTP routes and the company storage are the real ones. No credential, scraper, Gemini or Nebius call. Wipes the copy's runtime/: COPY ONLY:
  ONBOARDING_I_AM_A_COPY=1 venv-python tests/onboarding_test.py"""
import json, os, shutil, sqlite3, subprocess, sys, tempfile, time, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if os.environ.get("ONBOARDING_I_AM_A_COPY") != "1":
    sys.exit("Refusing to run: set ONBOARDING_I_AM_A_COPY=1 and run from a COPY of the project.")
if (ROOT / "secrets" / "local.env").exists():
    sys.exit("Refusing to run: this copy holds secrets/local.env. Real credentials must never be loaded by a test copy.")
MOCK, APP = 8783, 8833
TMP = Path(tempfile.mkdtemp(prefix="onboarding_"))
SNAP = TMP / "snapshot.txt"
REAL_SNAP = (ROOT / "app" / "demo_snapshots" / "northloom-demo.example.com.txt").read_text(encoding="utf-8")
ENV = {**os.environ, "PYTHONUTF8": "1", "ECOM_CLASSIFIER": "off", "ECOM_ONBOARDING_SNAPSHOT": str(SNAP), "ECOM_CHAT_MAX_ITERATIONS": "6", "MOCK_SLOW_S": "3"}
for k in ("LLM_PROVIDER", "LLM_MODEL", "NEBIUS_API_KEY", "NEBIUS_BASE_URL", "NEBIUS_MODEL", "ECOM_APP_ROOT", "HERMES_HOME", "ECOM_ASSUME_EXISTING_RUNTIME"):   # the last one would hide the fresh-install gate
    ENV.pop(k, None)
os.environ.pop("ECOM_APP_ROOT", None)
os.environ.pop("HERMES_HOME", None)
results, procs = [], []
import atexit
atexit.register(lambda: [p.terminate() for p in procs if p.poll() is None])


def check(name, ok, detail=""):
    ok = bool(ok)
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{str(detail)[:700]}]"), flush=True)


def http(port, path, body=None, timeout=300):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        data = e.read()
        try:
            return e.code, json.loads(data)
        except ValueError:
            return e.code, data


def model_n():
    return http(MOCK, "/stats")[1]["requests"]


def spawn(args, env=None):
    p = subprocess.Popen([sys.executable, *args], cwd=ROOT, env=env or ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(p)
    return p


def wait_up(port, path="/api/status"):
    for _ in range(80):
        try:
            http(port, path, timeout=5)
            return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"port {port} did not come up")


def start_server():
    p = spawn(["-m", "app.server", str(APP)])
    wait_up(APP)
    return p


def stop(p):
    p.terminate()
    p.wait()
    time.sleep(2)


def db():
    c = sqlite3.connect(ROOT / "runtime" / "app.db")
    c.row_factory = sqlite3.Row
    return c


def chat_try(agent, text):
    return http(APP, f"/api/chat/{agent}", {"message": text, "request_id": f"try-{time.time_ns()}"})


def company_name():
    return http(APP, "/api/company")[1]["company"]["name"]


def chat_blocked_probe():
    return http(APP, '/api/chat/main', {'message': 'probe', 'request_id': f'probe-{time.time_ns()}'})[0] == 409


def set_snapshot(text):
    SNAP.write_text(text, encoding="utf-8")


def reset_onboarding_row():   # test harness only (the product has no reset): lets one run exercise several source variants
    with db() as c:
        c.execute("DELETE FROM onboarding")


def new_onboarding(snapshot_text):
    set_snapshot(snapshot_text)
    reset_onboarding_row()
    return http(APP, "/api/onboarding/start", {})


SRC = lambda u="https://northloom-demo.example.com": http(APP, "/api/onboarding/source", {"url": u})
try:
    shutil.rmtree(ROOT / "runtime", ignore_errors=True)
    (ROOT / "secrets").mkdir(exist_ok=True)
    (ROOT / "secrets" / "local.env").write_text(f"LLM_PROVIDER=nebius-token-factory\nLLM_MODEL=mock-model\nNEBIUS_API_KEY=mock-key\nNEBIUS_BASE_URL=http://127.0.0.1:{MOCK}/v1\n", encoding="utf-8")
    subprocess.run([sys.executable, "scripts/setup.py"], cwd=ROOT, env=ENV, check=True, capture_output=True)
    import yaml
    for prof in (ROOT / "runtime" / "hermes_home" / "profiles" / "main" / "config.yaml",):   # one request per failing turn (Hermes would otherwise retry a failing provider many times)
        cfg = yaml.safe_load(prof.read_text(encoding="utf-8")) or {}
        cfg.setdefault("agent", {}).update(api_max_retries=1, auto_recovery_cycles=0)
        prof.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    set_snapshot(REAL_SNAP)
    spawn(["tests/mock_llm.py", str(MOCK)])
    wait_up(MOCK, "/stats")
    srv = start_server()

    print("TICKET 01: link -> source-derived summary and five questions", flush=True)
    # ---- before onboarding is started the app behaves exactly as before
    st0, s0 = http(APP, "/api/onboarding")
    n0 = model_n()
    f_chat, f_any = chat_try("main", "hello fresh"), chat_try("anyone", "hi")
    f_comp = http(APP, "/api/company", {"fields": {"name": "Sneaky Edit", "products": "x", "customers": "y", "goal": "z goal here"}})
    check("T01-1 a FRESH runtime (start-up files, profiles and empty tables only) reports not_started with chat locked and onboarding required, the registered demo URL and the 'prepared demo material' "
          "notice; direct chat (main or any agent id) and the manual company save are refused 409 onboarding_incomplete in the backend: no model call, nothing saved",
          st0 == 200 and s0["state"] == "not_started" and s0["chat_unlocked"] is False and s0["required"] is True and s0["registered_url"] == "https://northloom-demo.example.com"
          and "No real website is fetched" in s0["notice"] and f_chat[0] == 409 and f_chat[1]["code"] == "onboarding_incomplete" and f_any[0] == 409 and f_comp[0] == 409
          and model_n() == n0 and company_name() == "", (s0, f_chat, f_any, f_comp))
    stop(srv)
    srv = start_server()
    s0b = http(APP, "/api/onboarding")[1]
    check("T01-1b a restart of a fresh runtime keeps chat locked; a company file with only blank fields does not make it an existing business", s0b["chat_unlocked"] is False and chat_try("main", "x")[0] == 409, s0b)
    (ROOT / "runtime" / "company.json").write_text(json.dumps({"name": "", "products": "", "customers": ""}), encoding="utf-8")
    blank_company = http(APP, "/api/onboarding")[1]
    (ROOT / "runtime" / "company.json").write_text(json.dumps({"name": "Existing Demo Co", "products": "mugs", "customers": "locals", "goal": "sell more mugs"}), encoding="utf-8")
    saved_company = http(APP, "/api/onboarding")[1]
    saved_chat = chat_try("anyone", "hi")
    (ROOT / "runtime" / "company.json").unlink()
    with db() as c:
        c.execute("INSERT INTO messages(agent_id,who,content,tools,ts) VALUES('main','user','an old message','[]',1)")
    old_history = http(APP, "/api/onboarding")[1]
    with db() as c:
        c.execute("DELETE FROM messages")
    check("T01-1c an EXISTING runtime stays usable until onboarding is started: a saved company (or old chat history) unlocks it, a blank company file does not; the chat gate lets the request through (404 for an unknown agent)",
          blank_company["chat_unlocked"] is False and saved_company["chat_unlocked"] is True and saved_company["state"] == "not_started" and saved_chat[0] == 404 and old_history["chat_unlocked"] is True
          and http(APP, "/api/onboarding")[1]["chat_unlocked"] is False, (blank_company, saved_company, saved_chat, old_history))
    n0 = model_n()
    st_s, r_s = SRC()
    check("T01-2 submitting a source before onboarding was started is refused (not_started) and calls no model", st_s == 409 and r_s["code"] == "not_started" and model_n() == n0, (st_s, r_s))
    st_a, r_a = http(APP, "/api/onboarding/start", {})
    check("T01-3 start creates the persisted awaiting_source state (chat stays open until ticket 02's gate)", st_a == 200 and r_a["state"] == "awaiting_source", r_a)

    # ---- unknown / malformed source URLs: clear response, no model call, nothing fetched
    n0 = model_n()
    bad = [SRC(u) for u in ("https://www.example.org", "http://127.0.0.1:8800/secret", "file:///c:/windows/win.ini", "northloom-demo.example.com.evil.net", "", 5)]
    check("T01-4 any URL other than the one registered demo URL gets a clear unknown_source answer naming the registered URL; no model call, no fetch, state unchanged",
          all(s == 404 and r["code"] == "unknown_source" and r["registered_url"] == "https://northloom-demo.example.com" for s, r in bad) and model_n() == n0
          and http(APP, "/api/onboarding")[1]["state"] == "awaiting_source", bad[:2])

    # ---- the happy path: summary and questions come from the snapshot through main's real Hermes worker
    n0 = model_n()
    t0 = time.time()
    st_h, r_h = SRC("Northloom-Demo.example.com/")
    qs = r_h.get("questions") or []
    opts = [o for q in qs for o in q["options"]]
    check("T01-5 the demo link (any case, optional scheme/slash) yields main's summary and exactly five questions with ids q1..q5, 2-4 options each, at least one goal question; "
          "ONE model request; state awaiting_answers",
          st_h == 200 and r_h["state"] == "awaiting_answers" and len(qs) == 5 and [q["id"] for q in qs] == [f"q{i}" for i in range(1, 6)]
          and all(2 <= len(q["options"]) <= 4 for q in qs) and any(q["topic"] == "goal" for q in qs) and model_n() - n0 == 1 and r_h["summary"].startswith("From the prepared demo snapshot"),
          (st_h, r_h.get("code"), r_h.get("error"), model_n() - n0))
    check("T01-6 the summary and options are SOURCE-DERIVED: they carry the snapshot's own wording (business name, featured piece, readers, voice), and the response states it is "
          "prepared demo material",
          "Northloom Demo Studio" in r_h["summary"] and "Chintz Applique Quilt" in opts and any("heritage patterns" in o.lower() for o in opts) and "calm, factual" in " ".join(opts).lower()
          and "No real website is fetched" in r_h["notice"], r_h)
    with db() as c:
        row = dict(c.execute("SELECT * FROM onboarding").fetchone())
    check("T01-7 the generated summary/questions are persisted with the snapshot id and hash; ordinary main chat history and the agent registry are untouched (no specialist, no transcript rows)",
          row["state"] == "awaiting_answers" and row["snapshot_id"] == "northloom-demo-2026-10" and len(row["snapshot_sha256"]) == 64 and json.loads(row["questions_json"]) == qs
          and http(APP, "/api/chat/main")[1] == [] and http(APP, "/api/agents")[1] == [], row)

    # ---- repeated submit, reload, restart: stored result, no second model call
    n1 = model_n()
    st_r, r_r = SRC()
    st_r2, r_r2 = SRC("https://other.example.org")
    stop(srv)
    srv = start_server()
    st_g, r_g = http(APP, "/api/onboarding")
    check("T01-8 a repeated submit, a reload and a server restart all return the SAME stored summary/questions and call the model zero further times; a different URL for the same onboarding is refused",
          st_r == 200 and r_r.get("replayed") is True and r_r["questions"] == qs and st_r2 == 409 and r_r2["code"] == "source_already_set"
          and st_g == 200 and r_g["state"] == "awaiting_answers" and r_g["summary"] == r_h["summary"] and r_g["questions"] == qs and model_n() == n1, (st_r, st_r2, model_n() - n1))

    # ---- a different source text gives different questions: nothing is prewritten
    VARIANT = REAL_SNAP.replace("Chintz Applique Quilt", "Linen Table Runner").replace("people who love heritage patterns, collectors of traditional textiles and anyone choosing a thoughtful gift for a home",
                                                                                         "cafe owners, hotel buyers and wedding planners").replace("calm, factual and plain-spoken", "bright, chatty and playful")
    new_onboarding(VARIANT)
    n0 = model_n()
    st_v, r_v = SRC()
    opts_v = [o for q in r_v.get("questions", []) for o in q["options"]]
    check("T01-9 with a different snapshot text the SAME code produces different, source-derived options (new featured piece, new readers, new voice): no prewritten profile or questions",
          st_v == 200 and "Linen Table Runner" in opts_v and "Chintz Applique Quilt" not in opts_v and any("hotel buyers" in o for o in opts_v) and "bright, chatty" in " ".join(opts_v)
          and model_n() - n0 == 1, (st_v, opts_v))

    # ---- malformed / unusable model output: recoverable error, nothing saved, NO automatic retry
    for label, marker in (("prose without JSON", "malformed"), ("three questions", "fewq"), ("no goal question", "nogoal")):
        new_onboarding(REAL_SNAP + f"\nMOCK_ONBOARDING={marker}\n")
        n0 = model_n()
        st_m, r_m = SRC()
        stt = http(APP, "/api/onboarding")[1]
        check(f"T01-10 unusable model output ({label}): 502 invalid_model_output, retryable, the state stays awaiting_source with the reason stored, no summary saved and exactly ONE model "
              "request (no automatic retry loop)",
              st_m == 502 and r_m["code"] == "invalid_model_output" and r_m["retryable"] is True and stt["state"] == "awaiting_source" and stt["error"] and "summary" not in stt
              and model_n() - n0 == 1, (st_m, r_m, stt, model_n() - n0))
    set_snapshot(REAL_SNAP)   # the operator resubmits explicitly after the source text no longer carries the failure marker
    n0 = model_n()
    st_ok, r_ok = SRC()
    check("T01-11 an explicit resubmission after a failure succeeds (recoverable), and the stored error is cleared", st_ok == 200 and r_ok["state"] == "awaiting_answers" and not r_ok.get("error") and model_n() - n0 == 1, (st_ok, r_ok.get("code"), r_ok.get("error")))
    new_onboarding(REAL_SNAP + "\nMOCK_ONBOARDING=fenced\n")
    st_f, r_f = SRC()
    check("T01-12 valid JSON inside a markdown code fence is accepted (the reply is parsed, not trusted blindly)", st_f == 200 and r_f["state"] == "awaiting_answers" and len(r_f["questions"]) == 5, (st_f, r_f.get("code")))

    # ---- the model path itself failing
    new_onboarding(REAL_SNAP + "\nLLM_500\n")
    n0 = model_n()
    st_e, r_e = SRC()
    stt = http(APP, "/api/onboarding")[1]
    check("T01-13 a failing model request (HTTP 500 from the provider) is reported as generation_failed (retryable), saves nothing, and sends exactly one provider request (retries 1/0)",
          st_e == 502 and r_e["code"] == "generation_failed" and r_e["retryable"] is True and stt["state"] == "awaiting_source" and "summary" not in stt and model_n() - n0 == 1, (st_e, r_e, model_n() - n0))
    check("T01-14 none of this created an agent or wrote ordinary main-chat history", http(APP, "/api/agents")[1] == [] and http(APP, "/api/chat/main")[1] == [])
    page = urllib.request.urlopen(f"http://127.0.0.1:{APP}/", timeout=30).read().decode("utf-8")
    check("T01-15 the page ships the plain onboarding form hooks (state panel, source form, question form, kept-answers draft)", all(k in page for k in ('id="onboard"', "onb-start", "submitSource", "Read the site", "onbDraft", "restoreDraft")), page[:200])

    print("TICKET 02: answers -> shared company context -> chat unlock", flush=True)
    import threading

    def ready_for_answers(snapshot_text=REAL_SNAP):
        new_onboarding(snapshot_text)
        st_, r_ = SRC()
        assert st_ == 200 and r_["state"] == "awaiting_answers", (st_, r_)
        return r_["questions"]

    def good_answers(correction="", goal_text="Make clear promotional flyers for the quilt and understand competitor prices"):
        return {"answers": {"q1": {"choice": 0}, "q2": {"choice": 1}, "q3": {"write_in": goal_text}, "q4": {"choice": 0}, "q5": {"choice": 1}}, "correction": correction}

    ANS = lambda body: http(APP, "/api/onboarding/answers", body)
    chat_main = lambda text="Hello main": http(APP, "/api/chat/main", {"message": text, "request_id": f"t02-{time.time_ns()}"})
    company = lambda: http(APP, "/api/company")[1]

    # ---- the gate: in-progress onboarding blocks ordinary chat and manual company saves in the BACKEND
    ready_for_answers()
    n0 = model_n()
    g_chat = chat_main()
    g_spec = http(APP, "/api/chat/anyone", {"message": "hi"})
    g_comp = http(APP, "/api/company", {"fields": {"name": "Sneaky Edit", "products": "x", "customers": "y", "goal": "z goal here"}})
    check("T02-1 while onboarding is in progress, direct API chat (main or any agent id) and the manual company-save route are refused 409 onboarding_incomplete; no model call, nothing saved; "
          "reading state stays allowed",
          g_chat[0] == 409 and g_chat[1]["code"] == "onboarding_incomplete" and g_spec[0] == 409 and g_comp[0] == 409 and g_comp[1]["code"] == "onboarding_incomplete"
          and model_n() == n0 and company()["company"]["name"] == "" and http(APP, "/api/onboarding")[1]["state"] == "awaiting_answers" and http(APP, "/api/chat/main")[0] == 200, (g_chat, g_comp))

    # ---- invalid answers
    qs = http(APP, "/api/onboarding")[1]["questions"]
    base = good_answers()
    bads = {"missing question": {**base, "answers": {k: v for k, v in base["answers"].items() if k != "q5"}},
            "unknown id": {**base, "answers": {**base["answers"], "q9": {"choice": 0}}},
            "choice out of range": {**base, "answers": {**base["answers"], "q1": {"choice": 7}}},
            "boolean choice": {**base, "answers": {**base["answers"], "q1": {"choice": True}}},
            "both keys": {**base, "answers": {**base["answers"], "q1": {"choice": 0, "write_in": "also text"}}},
            "empty write-in": {**base, "answers": {**base["answers"], "q3": {"write_in": "  "}}},
            "placeholder write-in": {**base, "answers": {**base["answers"], "q3": {"write_in": "n/a"}}},
            "long correction": {**base, "correction": "x" * 601}, "wrong type": {"answers": ["q1"]}, "not an object": [1, 2]}
    res = {k: ANS(v) for k, v in bads.items()}
    check("T02-2 invalid answers (missing, unknown id, bad/boolean choice, both keys, empty or placeholder write-in, over-long correction, wrong shapes) get 400 invalid_answers: no model call, "
          "no company saved, state and lock unchanged",
          all(s_ == 400 and r_["code"] in ("invalid_answers", "invalid_request") for s_, r_ in res.values()) and model_n() == n0 and company()["company"]["name"] == ""
          and http(APP, "/api/onboarding")[1]["state"] == "awaiting_answers" and chat_main()[0] == 409, {k: (v[0], v[1].get("code")) for k, v in res.items()})

    # ---- failed generation / unusable output / failed save never unlock chat, and each attempt sends exactly ONE request
    for label, snap, corr in (("unusable model reply", REAL_SNAP + "\nMOCK_ONBOARDING=malformed_context\n", ""), ("model reply with an empty required field", REAL_SNAP + "\nMOCK_ONBOARDING=empty_products\n", ""),
                              ("provider failure (HTTP 500)", REAL_SNAP, "LLM_500")):
        ready_for_answers(snap)
        n1 = model_n()
        st_f, r_f = ANS(good_answers(corr))
        stt = http(APP, "/api/onboarding")[1]
        check(f"T02-3 {label}: 502, retryable, nothing saved, state stays awaiting_answers, chat stays locked, exactly ONE model request (no automatic retry)",
              st_f == 502 and r_f["retryable"] is True and r_f["code"] in ("invalid_model_output", "generation_failed") and stt["state"] == "awaiting_answers" and stt["chat_unlocked"] is False
              and stt["error"] and company()["company"]["name"] == "" and chat_main()[0] == 409 and model_n() - n1 == 1, (st_f, r_f, model_n() - n1))
    # a failed SAVE (the company file cannot be written): the model answered fine, but nothing unlocks
    ready_for_answers()
    blocker = ROOT / "runtime" / "company.json"
    blocker.mkdir()
    st_d, r_d = ANS(good_answers())
    stt = http(APP, "/api/onboarding")[1]
    check("T02-4 a failed company save (storage error) answers 503 context_not_saved (retryable), keeps awaiting_answers and the chat lock, and records no ready state",
          st_d == 503 and r_d["code"] == "context_not_saved" and r_d["retryable"] is True and stt["state"] == "awaiting_answers" and stt["chat_unlocked"] is False and chat_main()[0] == 409, (st_d, r_d, stt))
    blocker.rmdir()

    # ---- a model that tries to write the goal itself cannot: the saved goal is the operator's answer
    ready_for_answers(REAL_SNAP + "\nMOCK_ONBOARDING=goal_injection\n")
    st_gi, r_gi = ANS(good_answers(goal_text="Help us explain the quilt's patterns to gift buyers"))
    check("T02-4b a model reply that includes its own 'goal' is ignored: the saved goal is exactly the operator's answer, never the model's text",
          st_gi == 200 and company()["company"]["goal"] == "Help us explain the quilt's patterns to gift buyers" and "Maximise" not in json.dumps(company()), (st_gi, company()["company"].get("goal")))

    # ---- the happy path
    ready_for_answers()
    n1 = model_n()
    st_ok, r_ok = ANS(good_answers("The studio also publishes short pattern guides."))
    c_ok = company()
    st_cs, cstat = http(APP, "/api/status")
    check("T02-5 valid answers + a correction: ONE main turn combines snapshot and operator input; the backend validates and saves the EXISTING shared company context (complete, updated_by "
          "onboarding, demo link as website); onboarding is ready and chat is unlocked",
          st_ok == 200 and r_ok["state"] == "ready" and r_ok["chat_unlocked"] is True and model_n() - n1 == 1 and c_ok["company"]["name"] == "Northloom Demo Studio"
          and c_ok["company"]["website"] == "https://northloom-demo.example.com" and c_ok["status"]["complete"] is True and c_ok["updated_by"] == "onboarding"
          and "operator note: The studio also publishes short pattern guides." in c_ok["company"]["products"], (st_ok, r_ok.get("code"), r_ok.get("error"), c_ok))
    check("T02-6 GOALS COME FROM THE OPERATOR: the saved goal is exactly the operator's own goal answer; the provenance block separates source facts from operator input and records the correction",
          c_ok["company"]["goal"] == "Make clear promotional flyers for the quilt and understand competitor prices" and r_ok["context"]["goal"] == c_ok["company"]["goal"]
          and r_ok["provenance"]["goal"].startswith("your own answer") and "summary_correction" in r_ok["provenance"] and r_ok["correction"] == "The studio also publishes short pattern guides." and r_ok["answers"][2]["kind"] == "write_in", r_ok.get("provenance"))
    check("T02-7 saving answers created NO specialist and wrote no chat history; the response explains the two roles and says to ask main for the one wanted",
          http(APP, "/api/agents")[1] == [] and http(APP, "/api/chat/main")[1] == [] and [r["role"] for r in r_ok["roles"]] == ["market_analysis", "social_media"] and "created no specialist" in r_ok["roles_note"], r_ok.get("roles"))

    # ---- chat and agent creation work as before after completion; creation only by the explicit request
    c1 = chat_main("Hello main, who are you?")
    created = http(APP, "/api/chat/main", {"message": "CALL_TOOL:" + json.dumps({"name": "create_agent", "args": {
        "role": "market_analysis", "name": "Northloom Market Analyst", "objective": "Compare competitor quilts and prices with Northloom's supplied catalogue and report differences plainly.",
        "instructions": "You work for Northloom Demo Studio (a fictional demo business). Use only the supplied company facts and say plainly what you cannot do or verify.",
        "company_context_refs": ["brand"], "requested_tools": ["read_company_context", "memory", "skills"],
        "skills": [{"name": "competitor-review", "content": "# Competitor review\n1. Read the company context.\n2. Compare what the user supplies.\n3. Report observations and what is unverified."}]}}), "request_id": "t02-create"})
    agents = http(APP, "/api/agents")[1]
    c2 = http(APP, f"/api/chat/{agents[0]['agent_id']}", {"message": "Hello specialist", "request_id": "t02-spec"}) if agents else (0, {})
    check("T02-8 after completion ordinary main chat works (200), the operator's explicit request creates a specialist through the existing create_agent path, and that specialist chats",
          c1[0] == 200 and c1[1]["ok"] and created[0] == 200 and len(agents) == 1 and agents[0]["role"] == "market_analysis" and c2[0] == 200 and c2[1]["ok"], (c1[0], created[0], agents, c2[0]))
    c_man = http(APP, "/api/company", {"fields": {"brand": "Calm, factual, heritage"}})
    check("T02-9 the manual company-save route works again once onboarding is complete", c_man[0] == 200 and c_man[1]["ok"] and company()["company"]["brand"] == "Calm, factual, heritage", c_man)

    # ---- repeated submissions and restart after completion
    n2 = model_n()
    rep = ANS(good_answers("The studio also publishes short pattern guides."))
    diff = ANS(good_answers("different correction"))
    again_src = SRC()
    goal_before = company()["company"]["goal"]
    stop(srv)
    srv = start_server()
    after = http(APP, "/api/onboarding")[1]
    check("T02-10 the same answers again return the stored result, different answers are refused already_completed, a new source is refused already_ready; none calls the model or rewrites the "
          "company; a server restart keeps onboarding ready and chat unlocked",
          rep[0] == 200 and rep[1].get("replayed") is True and diff[0] == 409 and diff[1]["code"] == "already_completed" and again_src[0] == 409 and again_src[1]["code"] == "already_ready"
          and model_n() - n2 == 0 and company()["company"]["goal"] == goal_before and after["state"] == "ready" and after["chat_unlocked"] is True and chat_main("after restart")[0] == 200, (rep[0], diff, again_src))

    # ---- progress survives a restart while the operator is still answering
    ready_for_answers()
    n3 = model_n()
    stop(srv)
    srv = start_server()
    mid = http(APP, "/api/onboarding")[1]
    check("T02-11 a restart in the middle keeps awaiting_answers with the same questions, keeps the chat locked and calls no model", mid["state"] == "awaiting_answers" and len(mid["questions"]) == 5
          and chat_main()[0] == 409 and model_n() == n3, mid.get("state"))

    # ---- two simultaneous submissions make ONE model call
    ready_for_answers(REAL_SNAP)
    n4 = model_n()
    out = [None, None]
    body_ = good_answers("SLOW pattern guides")
    ths = [threading.Thread(target=lambda i=i: out.__setitem__(i, ANS(body_))) for i in (0, 1)]
    [t_.start() for t_ in ths]
    [t_.join() for t_ in ths]
    check("T02-12 two simultaneous identical submissions produce exactly ONE model call: one completes, the other returns the stored result", all(o[0] == 200 for o in out) and model_n() - n4 == 1
          and sorted(bool(o[1].get("replayed")) for o in out) == [False, True], (out[0][0], out[1][0], model_n() - n4))

    # ---- review finding 2: a correction must not be presented as a website fact
    ready_for_answers()
    st_c, r_c = ANS(good_answers("The studio is now called Cedar House. Our main competitor is Loomhaus."))
    pv = r_c.get("provenance", {})
    combined = ("name", "products", "customers", "brand", "competitors")
    check("T02-14 a correction that renames the studio (and names a competitor, a field no question covers) is saved and preserved word for word, but no model-combined field is labelled source-only: "
          "each says it was combined from the snapshot AND the operator's input; the goal stays the operator's own answer",
          st_c == 200 and company()["company"]["name"] == "Cedar House" and company()["company"]["competitors"] == "Loomhaus" and r_c["correction"] == "The studio is now called Cedar House. Our main competitor is Loomhaus."
          and all("combined" in pv[k] and "your answers" in pv[k] and not pv[k].startswith("source") for k in combined) and "prepared demo snapshot" in pv["source"]
          and pv["goal"].startswith("your own answer") and r_c["answers"][2]["answer"] == "Make clear promotional flyers for the quilt and understand competitor prices", pv)

    # ---- an existing runtime that never started onboarding keeps working
    reset_onboarding_row()
    check("T02-13 with no onboarding started (an existing runtime) chat is open and onboarding reads not_started: existing data stays usable until the operator explicitly starts the flow",
          http(APP, "/api/onboarding")[1]["state"] == "not_started" and chat_main("existing runtime chat")[0] == 200 and not chat_blocked_probe())

    # ---- review finding 3: starting onboarding must not interrupt an accepted turn, and the gate and admission cannot both pass
    chat_main("warm the main worker")
    w_before = [w for w in http(APP, "/api/workers")[1] if w["agent_id"] == "main"]
    n5 = model_n()
    chat_main("plain turn for the request count")
    per_turn = model_n() - n5
    n6 = model_n()
    slow_out = []
    slow_t = threading.Thread(target=lambda: slow_out.append(http(APP, "/api/chat/main", {"message": "SLOW accepted turn", "request_id": "c3-slow"})))
    slow_t.start()
    for _ in range(60):
        if "main" in http(APP, "/api/state")[1]:
            break
        time.sleep(0.2)
    busy_start = http(APP, "/api/onboarding/start", {})
    busy_src = SRC()
    slow_t.join()
    w_after = [w for w in http(APP, "/api/workers")[1] if w["agent_id"] == "main"]
    hist = [m for m in http(APP, "/api/chat/main")[1] if "SLOW accepted turn" in m["content"] or m["who"] != "user"]
    check("T02-15 starting onboarding while an accepted main turn is running answers a retryable 409 main_busy; the turn finishes normally on the SAME worker process with one reply and no extra model "
          "requests, and nothing was switched (no source accepted)",
          busy_start[0] == 409 and busy_start[1]["code"] == "main_busy" and busy_start[1]["retryable"] is True and busy_src[0] == 409 and busy_src[1]["code"] == "not_started"
          and slow_out and slow_out[0][0] == 200 and slow_out[0][1]["ok"] and slow_out[0][1]["text"] and w_before and w_after and w_before[0]["pid"] == w_after[0]["pid"]
          and model_n() - n6 == per_turn and len([m for m in hist if m["who"] == "agent"]) >= 1 and http(APP, "/api/onboarding")[1]["state"] == "not_started",
          (busy_start, busy_src, slow_out[0][0] if slow_out else None, slow_out[0][1].get("error") if slow_out else None, w_before, w_after, model_n() - n6, per_turn))
    st_after = http(APP, "/api/onboarding/start", {})
    refused = chat_main("after start")
    check("T02-16 once the turn is over, start succeeds, and new ordinary chat is then refused 409 onboarding_incomplete", st_after[0] == 200 and st_after[1]["state"] == "awaiting_source"
          and refused[0] == 409 and refused[1]["code"] == "onboarding_incomplete", (st_after, refused))
    def race_once(rnd):
        gate, res = threading.Barrier(2), {}

        def go(name, fn):
            gate.wait()
            res[name] = fn()

        ts_ = [threading.Thread(target=go, args=("start", lambda: http(APP, "/api/onboarding/start", {}))), threading.Thread(target=go, args=("chat", lambda: chat_main(f"race {rnd}")))]
        [t_.start() for t_ in ts_]
        [t_.join() for t_ in ts_]
        return res["start"][0], res["chat"][0]

    outcomes = []
    for rnd in range(5):   # gate check vs admission: whichever wins, the other must lose
        reset_onboarding_row()
        outcomes.append(race_once(rnd))
    check("T02-17 racing 'start onboarding' against 'accepted chat' five times: exactly one wins every time (chat 200 + start 409, or start 200 + chat 409), never both", all(o in ((409, 200), (200, 409)) for o in outcomes), outcomes)
    reset_onboarding_row()
finally:
    for p_ in procs:
        if p_.poll() is None:
            p_.terminate()
    print(f"{sum(results)}/{len(results)} checks passed (scripted model: wiring/enforcement only, NOT live model behaviour)", flush=True)
    sys.exit(0 if results and all(results) else 1)
