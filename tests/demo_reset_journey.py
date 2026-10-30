"""Fresh-demo journey with the REAL server, HTTP API, SQLite, Hermes workers and the scripted model tests/mock_llm.py (no credential, scraper, Gemini, Supabase or tracing call).
Wipes the copy's runtime/ - run ONLY from a COPY of the project (no secrets/local.env):
  DEMO_RESET_I_AM_A_COPY=1 venv-python tests/demo_reset_journey.py
1 fresh start + onboarding; 2 a specialist with a private memory and a saved result; 3 a normal restart keeps everything; 4 busy refusal, cancelled confirmation, then Restart demo:
website step, nothing of the old demo active; 5 the same role again: fresh id, no old result or memory; 6 the fresh_demo launcher with the app running (shared API) and stopped (direct
reset), then a normal start. Credentials, model configuration, prepared assets and paid accounting are compared before and after."""
import hashlib, json, os, shutil, socket, sqlite3, subprocess, sys, threading, time, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if os.environ.get("DEMO_RESET_I_AM_A_COPY") != "1":
    sys.exit("Refusing to run: set DEMO_RESET_I_AM_A_COPY=1 and run from a COPY of the project.")
if (ROOT / "secrets" / "local.env").exists():
    sys.exit("Refusing to run: this copy holds secrets/local.env.")
APP, MOCK = 8863, 8813
ENV = {**os.environ, "PYTHONUTF8": "1", "ECOM_CLASSIFIER": "off", "ECOM_CHAT_MAX_ITERATIONS": "6", "MOCK_SLOW_S": "8"}
for k in ("LLM_PROVIDER", "LLM_MODEL", "NEBIUS_API_KEY", "NEBIUS_BASE_URL", "NEBIUS_MODEL", "ECOM_APP_ROOT", "HERMES_HOME", "ECOM_ASSUME_EXISTING_RUNTIME", "LOGBOOK_DATABASE_URL", "NEON_DATABASE_URL"):
    ENV.pop(k, None)
RT = ROOT / "runtime"
PROF = RT / "hermes_home" / "profiles"
results, procs = [], {}


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{str(detail)[:700]}]"), flush=True)


def call(path, body=None, port=APP, timeout=300):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def start_server():
    procs["server"] = subprocess.Popen([sys.executable, "-m", "app.server", str(APP)], cwd=ROOT, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(120):
        try:
            call("/api/status", timeout=5)
            return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("server did not start")


def stop_server():   # only the server process this script started (its workers are its children and stop with it)
    p = procs.pop("server", None)
    if p and p.poll() is None:
        p.terminate()
        p.wait(30)
    time.sleep(2)


def tree(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()} if root.exists() else {}


def accounting():
    c = sqlite3.connect(RT / "app.db")
    names = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'") if r[0] not in ("agents", "messages", "agent_config_log", "onboarding", "retired_agents", "sqlite_sequence")]   # sqlite_sequence only counts message ids (it grows with every chat)
    out = {n: sorted(map(repr, c.execute(f"SELECT * FROM {n}").fetchall())) for n in names}
    c.close()
    return out


def preserved():
    return {"secrets": tree(ROOT / "secrets"), "config": (RT / "hermes_home" / "config.yaml").read_bytes(), "catalogue": tree(ROOT / "tests" / "fixtures"), "db": accounting()}


def onboard():
    call("/api/onboarding/start", {})
    call("/api/onboarding/source", {"url": "https://northloom-demo.example.com"})
    st, o = call("/api/onboarding")
    ans = {q["id"]: ({"choice": 0} if q["topic"] != "goal" else {"write_in": "Draft one Marketplace listing for the demonstration quilt."}) for q in o["questions"]}
    return call("/api/onboarding/answers", {"answers": ans, "correction": "Synthetic operator answers for the reset journey."})


ANALYST = {"role": "market_analysis", "name": "Northloom Market Analyst", "objective": "Research comparable quilt listings and draft one evidence-backed Marketplace listing for the Chintz Applique Quilt.",
           "instructions": "You analyse comparable listings for Northloom Demo Studio. Use only the company context, the catalogue and evidence you actually retrieved; label assumptions; never invent prices.",
           "requested_tools": ["marketplace_locate", "marketplace_search", "marketplace_item", "marketplace_photo", "inspect_image", "read_catalogue", "save_listing_draft"], "company_context_refs": ["products", "customers", "goal"]}


def create(rid):
    st, r = call("/api/chat/main", {"message": "CALL_TOOL:" + json.dumps({"name": "create_agent", "args": ANALYST}), "request_id": rid})
    out = [json.loads(t["output"]) for t in r.get("tools", []) if t.get("name") == "create_agent" and t.get("output")]
    return out[0] if out else {"ok": False, "raw": r}


def memory_text(agent_id):
    m = PROF / agent_id / "memories"
    return "".join(p.read_text(encoding="utf-8", errors="replace") for p in m.glob("*")) if m.exists() else ""


def archives():
    a = RT / "demo_archives"
    return sorted(p.name for p in a.iterdir()) if a.exists() else []


def fresh_state(tag):
    st_o, o = call("/api/onboarding")
    agents, main_chat, comp = call("/api/agents")[1], call("/api/chat/main")[1], call("/api/company")[1]["company"]
    return o["state"] == "awaiting_source" and not o["chat_unlocked"] and agents == [] and main_chat == [] and not any(comp.values()), (tag, o["state"], agents, len(main_chat), comp)


try:
    shutil.rmtree(RT, ignore_errors=True)
    (ROOT / "secrets").mkdir(exist_ok=True)
    (ROOT / "secrets" / "local.env").write_text(f"LLM_PROVIDER=nebius-token-factory\nLLM_MODEL=mock-model\nNEBIUS_API_KEY=mock-key\nNEBIUS_BASE_URL=http://127.0.0.1:{MOCK}/v1\n", encoding="utf-8")
    subprocess.run([sys.executable, "scripts/setup.py"], cwd=ROOT, env=ENV, check=True, capture_output=True)
    procs["mock"] = subprocess.Popen([sys.executable, "tests/mock_llm.py", str(MOCK)], cwd=ROOT, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    start_server()
    # paid accounting that a restart must never renew: spent research scope, used ads/flyer allowances, a recorded call
    c = sqlite3.connect(RT / "app.db")
    c.execute("INSERT INTO research_allowance(scope, api_max, image_max, api_used, image_used, created_at) VALUES('journey-research', 4, 2, 4, 2, ?)", (time.time(),))
    c.execute("INSERT INTO ad_allowance(scope, api_max, image_max, created_at) VALUES('journey-ads', 8, 3, ?)", (time.time(),))
    c.execute("INSERT INTO flyer_allowance(scope, attempts_max, attempts_used, created_at) VALUES('journey-flyer', 2, 1, ?)", (time.time(),))
    c.execute("INSERT INTO research_calls(run_id, kind) VALUES('run-journey', 'search')")
    c.commit()
    c.close()

    # ---- 1 + 2: fresh start, onboarding, a specialist with a private memory and a saved result
    st0, o0 = call("/api/onboarding")
    st, r = onboard()
    check("J1 a fresh start shows the website step; onboarding completes and unlocks chat", o0["state"] == "not_started" and o0["required"] and st == 200 and r.get("ok"), (o0, st, r))
    call("/api/chat/main", {"message": "hello main", "request_id": "j-main-1"})
    a = create("j-create-1")
    A = a.get("agent_id")
    call(f"/api/chat/{A}", {"message": "remember: the operator prefers a calm tone PURPLE-OTTER", "request_id": "j-mem-1"})
    c = sqlite3.connect(RT / "app.db")
    try:
        mid = c.execute("SELECT max(id) FROM messages WHERE agent_id=? AND who='user'", (A,)).fetchone()[0]
        c.execute("INSERT INTO listing_drafts(draft_id, agent_id, conversation_id, product_id, status, title, description, visual_brief, rationale, limitations, missing, merchant_snapshot, product_snapshot, "
                  "listing_evidence, image_evidence, created_at, evidence_source, research_run_id, request_id, message_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  ("draft-journey-1", A, "conv-" + A, "chintz-applique-quilt-demo", "complete", "Old demo draft", "d", "v", "[]", "l", "[]", "{}", "{}", "[]", "[]", time.time(), "recorded_sample", None, "j-mem-1", mid))
        c.commit()
    finally:
        c.close()
    cards = call(f"/api/results?agent_id={A}")[1]
    check("J2 the specialist exists with a private memory and a saved result shown under its message", a.get("ok") and "PURPLE-OTTER" in memory_text(A) and len(cards) == 1 and cards[0]["associated"], (a, cards))
    before = preserved()

    # ---- 3: a normal restart keeps the demo
    stop_server()
    start_server()
    check("J3 after a normal restart the demo continues: onboarding ready, the specialist, its chat, memory and saved result are all still there",
          call("/api/onboarding")[1]["state"] == "ready" and [x["agent_id"] for x in call("/api/agents")[1]] == [A] and len(call(f"/api/chat/{A}")[1]) >= 2
          and "PURPLE-OTTER" in memory_text(A) and len(call(f"/api/results?agent_id={A}")[1]) == 1, call("/api/agents")[1])

    # ---- 4: busy refusal, cancelled confirmation, then Restart demo
    out = {}
    t = threading.Thread(target=lambda: out.update(r=call(f"/api/chat/{A}", {"message": "SLOW please think", "request_id": "j-slow-1"})))
    t.start()
    for _ in range(60):
        if A in call("/api/state")[1]:
            break
        time.sleep(0.25)
    code, rb = call("/api/demo/reset", {"confirm": True})
    n_arch = len(archives())
    t.join(120)
    check("J4 Restart demo while the specialist is working is refused (409 demo_busy) and nothing is archived or cleared; the running turn finishes normally",
          code == 409 and rb.get("code") == "demo_busy" and n_arch == 0 and out.get("r", (0, {}))[1].get("ok") and [x["agent_id"] for x in call("/api/agents")[1]] == [A], (code, rb, out))
    code, rc = call("/api/demo/reset", {})
    check("J5 without confirmation nothing happens (400) and the demo is untouched", code == 400 and rc.get("code") == "confirmation_required" and call("/api/onboarding")[1]["state"] == "ready", (code, rc))
    code, rr = call("/api/demo/reset", {"confirm": True})
    ok, why = fresh_state("after reset")
    check("J6 Restart demo succeeds and the app is back at the website step: no company details, no specialists, no chats", code == 200 and rr.get("ok") and ok, (code, rr, why))
    check("J7 the old specialist's profile (memory, history) and main's memory/sessions/history are gone from the runtime; the archive holds them",
          not (PROF / A).exists() and not (PROF / "main" / "state.db").exists() and not list((PROF / "main" / "memories").glob("*"))
          and "PURPLE-OTTER" in "".join(p.read_text(encoding="utf-8", errors="replace") for p in (ROOT / rr["archive"] / "profiles" / A / "memories").glob("*")), (rr, sorted(p.name for p in PROF.iterdir())))
    now = preserved()
    check("J8 credentials, model configuration, the prepared catalogue/photos and all paid accounting/evidence rows are unchanged", now == before,
          [k for k in before if now[k] != before[k]] + [t for t in before["db"] if now["db"].get(t) != before["db"][t]])
    st_rp, rp = call("/api/chat/main", {"message": "hello main", "request_id": "j-main-1"})
    check("J9 an old request id cannot replay the old demo's answer (the replay cache was emptied; chat is locked until onboarding)", st_rp == 409 and not rp.get("replayed"), (st_rp, rp))
    stop_server()
    start_server()
    ok, why = fresh_state("after normal restart")
    check("J10 a normal restart after Restart demo stays at the website step (the reset is durable, nothing comes back)", ok, why)

    # ---- 5: the same role again
    st, r = onboard()
    a2 = create("j-create-2")
    A2 = a2.get("agent_id")
    call(f"/api/chat/{A2}", {"message": "what do you remember?", "request_id": "j-mem-2"})
    sysp = call("/stats", port=MOCK)[1].get("last_system", "")
    check("J11 the same role with the same name is created again without a collision, under a fresh id; it has no old saved result and no old memory, and the model is not told the old memory",
          r.get("ok") and a2.get("ok") and A2 and A2 != A and call(f"/api/results?agent_id={A2}")[1] == [] and "PURPLE-OTTER" not in memory_text(A2) and "PURPLE-OTTER" not in sysp, (a2, A2, A))

    # ---- 6: the launcher, with the app running (shared API, no second server) and with it stopped (direct reset), then a normal start
    n0 = len(archives())
    lr = subprocess.run([sys.executable, "scripts/fresh_demo.py", "--yes", "--port", str(APP)], cwd=ROOT, env=ENV, capture_output=True, text=True, timeout=900)
    ok, why = fresh_state("launcher, app running")
    check("J12 fresh_demo with the app running restarts through the app's own reset API (exit 2: no second app), the app keeps running, a new archive exists",
          lr.returncode == 2 and procs["server"].poll() is None and ok and len(archives()) == n0 + 1 and "archived" in lr.stdout, (lr.returncode, lr.stdout[-400:], why))
    st, r = onboard()
    create("j-create-3")
    stop_server()
    lr = subprocess.run([sys.executable, "scripts/fresh_demo.py", "--yes", "--port", str(APP)], cwd=ROOT, env=ENV, capture_output=True, text=True, timeout=900)
    start_server()
    ok, why = fresh_state("launcher, app stopped")
    check("J13 fresh_demo with the app stopped resets directly (exit 0 = start the app) and lists the scope/catalogue settings it starts with; the started app is at the website step",
          lr.returncode == 0 and ok and len(archives()) == n0 + 2 and "ECOM_RESEARCH_SCOPE" in lr.stdout and "never renewed" in lr.stdout, (lr.returncode, lr.stdout[-500:], why))
    check("J14 after three restarts the credentials, configuration, prepared assets and paid accounting are still exactly as before the first", preserved() == before, None)
    c = sqlite3.connect(RT / "app.db")
    retired = sorted(r[0] for r in c.execute("SELECT agent_id FROM retired_agents"))
    c.close()
    check("J15 every specialist id used in an earlier demo is retired, so none can be reused", A in retired and A2 in retired, retired)

    # ---- 7: uncertain launcher status changes nothing; an interrupted reset is recovered from its ORIGINAL archive and blocks start-up until then
    onboard()
    create("j-create-4")
    stop_server()
    n_arch, agents_now = len(archives()), 1
    hang = socket.socket()   # a listener that accepts connections and never answers: the status request times out, like a busy or wedged app
    hang.bind(("127.0.0.1", APP))
    hang.listen(5)
    try:
        lr = subprocess.run([sys.executable, "scripts/fresh_demo.py", "--yes", "--port", str(APP)], cwd=ROOT, env=ENV, capture_output=True, text=True, timeout=120)
    finally:
        hang.close()
    c = sqlite3.connect(RT / "app.db")
    n_agents = c.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
    c.close()
    check("J16 an app whose status request times out is NOT treated as absent: the launcher exits 1 with 'nothing was changed' and archives nothing, clears nothing, starts no reset",
          lr.returncode == 1 and "Nothing was changed" in lr.stdout and len(archives()) == n_arch and n_agents == 1 and not (RT / "demo_reset_pending.json").exists(), (lr.returncode, lr.stdout[-300:], n_agents))
    boom = chr(10).join(["from app import demo_reset as D", "def boom(ids):", "    raise OSError(32, 'locked by another program')", "D._clear_profiles = boom", "print(D.reset()['code'])"])
    ir = subprocess.run([sys.executable, "-c", boom.replace("\n", chr(10))], cwd=ROOT, env=ENV, capture_output=True, text=True, timeout=120)
    marker = RT / "demo_reset_pending.json"
    orig_marker = marker.read_bytes() if marker.exists() else b""
    arch_after = archives()
    srv = subprocess.run([sys.executable, "-m", "app.server", str(APP)], cwd=ROOT, env=ENV, capture_output=True, text=True, timeout=120)
    stp = subprocess.run([sys.executable, "scripts/setup.py"], cwd=ROOT, env=ENV, capture_output=True, text=True, timeout=120)
    check("J17 a reset interrupted during clearing leaves the verified archive and a clearing marker; the app and setup both refuse to start and say to run fresh_demo.bat again",
          "reset_incomplete" in ir.stdout and b"clearing" in orig_marker and len(arch_after) == n_arch + 1 and srv.returncode != 0 and "fresh_demo.bat" in srv.stderr and stp.returncode != 0 and "fresh_demo.bat" in stp.stderr, (ir.stdout, ir.stderr[-200:], srv.stderr[-200:]))
    lr = subprocess.run([sys.executable, "scripts/fresh_demo.py", "--yes", "--port", str(APP)], cwd=ROOT, env=ENV, capture_output=True, text=True, timeout=900)
    check("J18 running fresh_demo again completes the SAME restart from the original archive: exit 0, marker removed, no second archive",
          lr.returncode == 0 and not marker.exists() and archives() == arch_after and json.loads(orig_marker)["archive"].endswith(arch_after[-1]), (lr.returncode, lr.stdout[-300:], archives(), arch_after))
    start_server()
    ok, why = fresh_state("after recovered reset")
    check("J19 the app starts again at the website step, and credentials, configuration, prepared assets and paid accounting are still exactly as before the first reset", ok and preserved() == before, why)
finally:
    stop_server()
    p = procs.pop("mock", None)
    if p and p.poll() is None:
        p.terminate()
        p.wait(30)
print(f"{sum(results)}/{len(results)} passed")
sys.exit(0 if results and all(results) else 1)
