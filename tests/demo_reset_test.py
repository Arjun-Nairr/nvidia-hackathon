"""Fresh-demo reset (app/demo_reset.py + the server's admission gate): archive, verify, then clear demo progress, never accounting. No model, provider, server socket or credential:
a TEMPORARY app root with a populated runtime written directly (the shapes the app stores), the real modules, and the server's functions called in-process with the turn runner stubbed.
Seams: demo_reset.reset() (what is archived, cleared and preserved; failure paths), core agent ids (a retired id is never reused), server.reset_demo / chat / onboarding_op / save_company
(busy refusal, confirmation, no operation slips in during a reset). The full journey with real servers and workers is tests/demo_reset_journey.py.
  venv-python tests/demo_reset_test.py"""
import hashlib, json, os, shutil, sqlite3, sys, tempfile, threading, time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="demo-reset-test-"))
os.environ["ECOM_APP_ROOT"] = str(TMP)
os.environ["ECOM_CLASSIFIER"] = "off"
for k in ("HERMES_HOME", "ECOM_ASSUME_EXISTING_RUNTIME", "LOGBOOK_DATABASE_URL", "NEON_DATABASE_URL"):
    os.environ.pop(k, None)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import core, onboarding  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{str(detail)[:700]}]"), flush=True)


try:
    from app import demo_reset as DR
except ImportError as e:
    DR = None
    check("app/demo_reset.py exists", False, e)

PROFILES = core.HERMES_ROOT / "profiles"
PROGRESS = ("agents", "messages", "agent_config_log", "onboarding")


def put(p, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    (p.write_bytes if isinstance(data, bytes) else lambda x: p.write_text(x, encoding="utf-8"))(data)


def seed(tag):
    """A demo in progress: onboarding done, company saved, one analyst with chat, memory and a saved result; paid accounting with spent counters."""
    d = core.db()
    d.execute(onboarding._SCHEMA)
    now = time.time()
    d.execute("INSERT OR REPLACE INTO onboarding(id, state, url, summary, questions_json, answers_json, context_json, provenance_json, created_at, updated_at) VALUES(1,'ready','https://northloom-demo.example.com','s','[]','{}','{}','{}',?,?)", (now, now))
    d.execute("INSERT INTO agents VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (f"acme-analyst{tag}", "Acme Analyst", "market_analysis", "default", "obj " * 12, "ins " * 12, "[]", "[]",
                                                                    json.dumps(["read_company_context", "memory", "skills"]), "[]", f"conv-acme-analyst{tag}", "idle", now))
    for who, aid, text in (("user", "main", "hello main"), ("agent", "main", "hi"), ("user", f"acme-analyst{tag}", "draft please"), ("agent", f"acme-analyst{tag}", "saved")):
        d.execute("INSERT INTO messages(agent_id,who,content,tools,ts) VALUES(?,?,?,?,?)", (aid, who, text, "[]", now))
    mid = d.execute("SELECT max(id) FROM messages WHERE who='user'").fetchone()[0]
    d.execute("INSERT INTO agent_config_log(agent_id, ts, request_id, requested, applied) VALUES(?,?,?,?,?)", (f"acme-analyst{tag}", now, "r", "{}", "{}"))
    d.execute("INSERT INTO listing_drafts(draft_id, agent_id, conversation_id, product_id, status, title, description, visual_brief, rationale, limitations, missing, merchant_snapshot, product_snapshot, "
              "listing_evidence, image_evidence, created_at, evidence_source, research_run_id, request_id, message_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (f"draft-{tag or 'a'}", f"acme-analyst{tag}", "c", "p", "complete", "Old draft", "d", "v", "[]", "l", "[]", "{}", "{}", "[]", "[]", now, "recorded_sample", None, "req-1", mid))
    d.execute("INSERT OR IGNORE INTO research_allowance(scope, api_max, image_max, api_used, image_used, created_at) VALUES('journey-research', 4, 2, 4, 2, ?)", (now,))
    d.execute("INSERT OR IGNORE INTO ad_allowance(scope, api_max, image_max, created_at) VALUES('journey-ads', 8, 3, ?)", (now,))
    d.execute("INSERT OR IGNORE INTO flyer_allowance(scope, attempts_max, attempts_used, created_at) VALUES('journey-flyer', 2, 1, ?)", (now,))
    d.execute("INSERT INTO research_calls(run_id, kind) VALUES('run-x', 'search')")
    d.commit()
    d.close()
    core.update_company({"name": "Acme Quilts", "products": "Quilts", "customers": "Collectors", "goal": "Sell one quilt"}, source="form")
    put(PROFILES / "main" / "SOUL.md", "# Main agent\n")
    put(PROFILES / "main" / "config.yaml", "model: {}\n")
    put(PROFILES / "main" / ".env", "# no values\n")
    put(PROFILES / "main" / "plugins" / "ecom-agents" / "plugin.yaml", "name: ecom-agents\n")
    put(PROFILES / "main" / "skills" / "hermes-agent" / "SKILL.md", "baseline\n")
    put(PROFILES / "main" / "memories" / "MEMORY.md", f"main remembers ORANGE-HERON{tag}\n")
    put(PROFILES / "main" / "sessions" / "s1.json", "{}")
    put(PROFILES / "main" / "state.db", b"main history")
    a = PROFILES / f"acme-analyst{tag}"
    put(a / "SOUL.md", "# Acme Analyst\n")
    put(a / ".env", "# no values\n")
    put(a / "memories" / "MEMORY.md", f"prefers calm tone PURPLE-OTTER{tag}\n")
    put(a / "state.db", b"analyst history")
    put(a / "cache" / "big.bin", b"x" * 10)


def tables(exclude=PROGRESS + ("retired_agents",)):
    c = sqlite3.connect(core.DB_PATH)
    names = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name") if r[0] not in exclude]
    out = {n: sorted(map(repr, c.execute(f"SELECT * FROM {n}").fetchall())) for n in names}
    c.close()
    return out


def count(t):
    c = sqlite3.connect(core.DB_PATH)
    n = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    c.close()
    return n


def tree(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()} if root.exists() else {}


def preserved():
    """What a reset must never change: credentials, model configuration, prepared assets and every non-progress table (paid accounting, allowances, evidence, results)."""
    return {"secrets": tree(TMP / "secrets"), "auth": (core.HERMES_ROOT / "auth.json").read_text(encoding="utf-8"), "root_config": (core.HERMES_ROOT / "config.yaml").read_text(encoding="utf-8"),
            "assets": tree(TMP / "demo"), "db": tables()}


put(TMP / "secrets" / "local.env", "LLM_PROVIDER=nebius-token-factory\nLLM_MODEL=mock-model\nNEBIUS_API_KEY=not-a-real-key\n")
put(core.HERMES_ROOT / "auth.json", "{\"project\": \"login\"}")   # stands in for the project login; checked byte-for-byte
put(core.HERMES_ROOT / "config.yaml", "model: {provider: nebius-token-factory}\n")
put(TMP / "demo" / "inputs" / "catalogue.json", "{\"demo\": true}")
put(TMP / "demo" / "inputs" / "quilt.jpg", b"\xff\xd8 photo bytes")
seed("")

if DR:
    before, live_before = preserved(), tree(TMP / "runtime")
    stopped = []
    r = DR.reset(stop_workers=lambda: stopped.append(1))
    arch = TMP / r.get("archive", "missing") if r.get("ok") else None
    st = onboarding.status()
    check("DR-1 reset succeeds and returns to website entry: onboarding awaiting the website, chat locked, no company details, no agents, no messages, no config log",
          r.get("ok") and st["state"] == "awaiting_source" and not st["chat_unlocked"] and not core.load_company()["name"] and all(count(t) == 0 for t in ("agents", "messages", "agent_config_log")), (r, st))
    check("DR-2 the app's own idle workers are stopped before any profile is touched", stopped == [1], stopped)
    check("DR-3 the specialist's profile (memory, history) is gone from the active runtime; main keeps its SOUL, config, plugin and baseline skill but loses its memory, sessions and history",
          not (PROFILES / "acme-analyst").exists() and not (PROFILES / "main" / "state.db").exists() and not list((PROFILES / "main" / "memories").glob("*"))
          and not list((PROFILES / "main" / "sessions").glob("*")) and all((PROFILES / "main" / f).exists() for f in ("SOUL.md", "config.yaml", ".env", "plugins/ecom-agents/plugin.yaml", "skills/hermes-agent/SKILL.md")),
          sorted(p.name for p in PROFILES.iterdir()))
    after = preserved()
    check("DR-4 credentials, project login, model configuration, prepared catalogue/photos and EVERY non-progress table (paid counters, allowances, evidence, saved results) are byte-identical",
          before == after, {k: before[k] == after[k] for k in before})
    a_db = sqlite3.connect(arch / "app.db") if arch else None
    check("DR-5 the archive holds the whole previous database (progress rows included, integrity ok), company.json and the profiles with matching content, and no credential file",
          arch and a_db.execute("PRAGMA integrity_check").fetchone()[0] == "ok" and a_db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 4
          and json.loads((arch / "company.json").read_text(encoding="utf-8"))["name"] == "Acme Quilts"
          and "PURPLE-OTTER" in (arch / "profiles" / "acme-analyst" / "memories" / "MEMORY.md").read_text(encoding="utf-8")
          and "ORANGE-HERON" in (arch / "profiles" / "main" / "memories" / "MEMORY.md").read_text(encoding="utf-8")
          and not [p for p in arch.rglob("*") if p.name in (".env", "auth.json", "auth.lock")], sorted(p.relative_to(arch).as_posix() for p in arch.rglob("*"))[:30] if arch else r)
    if a_db:
        a_db.close()
    man = json.loads((arch / "manifest.json").read_text(encoding="utf-8")) if arch and (arch / "manifest.json").exists() else {}
    check("DR-6 the archive carries a manifest (file hashes, progress row counts, retired agent ids) and plain recovery instructions",
          man.get("progress_rows", {}).get("messages") == 4 and man.get("retired_agents") == ["acme-analyst"] and man.get("files") and (arch / "README.txt").exists()
          and "accounting" in (arch / "README.txt").read_text(encoding="utf-8").lower(), man)
    check("DR-7 no pending-reset marker remains after a successful reset", DR.pending() is None, DR.pending())
    with core.db() as d:
        free = core.free_agent_id(d, "acme-analyst") if hasattr(core, "free_agent_id") else None
    check("DR-8 a retired agent id is never handed out again (a new specialist with the same name gets a fresh id, so old results cannot attach to it)",
          free and free != "acme-analyst" and free.startswith("acme-analyst"), free)
    from app import results as RS
    check("DR-9 the fresh id has no saved results; the old draft still exists only under the retired id", free and RS.cards(free) == [] and len(RS.cards("acme-analyst")) == 1, None)

    # ---- reusable: a second demo, a second reset
    seed("-2")
    before2 = preserved()
    r2 = DR.reset(stop_workers=lambda: None)
    with core.db() as d:
        retired = sorted(x[0] for x in d.execute("SELECT agent_id FROM retired_agents"))
    check("DR-10 the reset is reusable: a second demo is archived in a NEW folder and cleared the same way, accounting again unchanged, both ids retired",
          r2.get("ok") and r2["archive"] != r["archive"] and count("messages") == 0 and not (PROFILES / "acme-analyst-2").exists() and preserved() == before2
          and retired == ["acme-analyst", "acme-analyst-2"] and onboarding.status()["state"] == "awaiting_source", (r2, retired))

    # ---- archive failure: nothing is cleared, the demo stays usable, no success is reported
    seed("-3")
    snap_live, snap_keep, n_arch = tree(TMP / "runtime" / "hermes_home"), preserved(), len(list((TMP / "runtime" / "demo_archives").iterdir()))
    real_copy, calls = DR._copy, []

    def broken_copy(src, dst):
        calls.append(src)
        if len(calls) == 3:
            raise OSError(28, "No space left on device")
        return real_copy(src, dst)
    DR._copy = broken_copy
    try:
        r3 = DR.reset(stop_workers=lambda: None)
    finally:
        DR._copy = real_copy
    check("DR-11 when the archive cannot be written the reset FAILS (ok False, actionable message) and nothing is cleared: progress, company, profiles and accounting are unchanged",
          r3.get("ok") is False and r3.get("code") == "archive_failed" and "unchanged" in r3.get("error", "") and count("messages") == 4 and core.load_company()["name"] == "Acme Quilts"
          and tree(TMP / "runtime" / "hermes_home") == snap_live and preserved() == snap_keep and onboarding.status()["state"] == "ready", r3)
    check("DR-12 the failed attempt leaves no half-written archive and no pending marker (the next start-up is not blocked)",
          len(list((TMP / "runtime" / "demo_archives").iterdir())) == n_arch and DR.pending() is None, sorted(p.name for p in (TMP / "runtime" / "demo_archives").iterdir()))

    # ---- interrupted clearing: the archive is complete, the marker stays, start-up refuses, a repeated reset finishes the job
    real_clear = DR._clear_profiles

    def stop_mid(ids):
        raise OSError(32, "The process cannot access the file because it is being used by another process")
    DR._clear_profiles = stop_mid
    try:
        r4 = DR.reset(stop_workers=lambda: None)
    finally:
        DR._clear_profiles = real_clear
    pend = DR.pending()
    check("DR-13 an interruption after the verified archive reports failure (never success), keeps a pending marker naming the archive and explains how to finish",
          r4.get("ok") is False and r4.get("code") == "reset_incomplete" and pend and pend.get("archive") == r4.get("archive") and (TMP / pend["archive"] / "manifest.json").exists()
          and "fresh_demo.bat" in r4.get("error", ""), (r4, pend))
    try:
        DR.refuse_if_pending()
        refused = False
    except SystemExit as e:
        refused = "fresh_demo.bat" in str(e)
    check("DR-14 while a reset is unfinished, a normal start refuses with the recovery instruction (no half-cleared demo is resumed)", refused, None)
    r5 = DR.reset(stop_workers=lambda: None)
    check("DR-15 repeating the reset finishes it: marker gone, profile cleared, website entry", r5.get("ok") and DR.pending() is None and not (PROFILES / "acme-analyst-3").exists()
          and onboarding.status()["state"] == "awaiting_source", r5)

# ---- the server's admission gate (in-process; the turn runner is stubbed, nothing reaches a model)
from app import server  # noqa: E402
if DR:
    seed("-4")
    gate, entered = threading.Event(), threading.Event()

    def slow_turn(agent_id, text, **kw):
        entered.set()
        gate.wait(30)
        return {"text": "done", "tools": [], "error": None}
    real_turn, core.run_turn = core.run_turn, slow_turn
    out = {}
    t = threading.Thread(target=lambda: out.update(chat=server.chat("acme-analyst-4", "work", "req-busy")))
    t.start()
    entered.wait(10)
    n_arch = len(list((TMP / "runtime" / "demo_archives").iterdir()))
    code, rb = server.reset_demo({"confirm": True})
    check("DR-20 a reset while a chat turn is running is refused (409 demo_busy, names the busy agent) and archives or clears nothing",
          code == 409 and rb.get("code") == "demo_busy" and "acme-analyst-4" in json.dumps(rb) and count("agents") == 1 and len(list((TMP / "runtime" / "demo_archives").iterdir())) == n_arch, (code, rb))
    gate.set()
    t.join(30)
    core.run_turn = real_turn
    code, rc = server.reset_demo({})
    check("DR-21 without explicit confirmation nothing happens (400 confirmation_required; agents and chat untouched)", code == 400 and rc.get("code") == "confirmation_required" and count("agents") == 1 and count("messages") == 6, (code, rc))

    # a reset in progress: every new operation is refused instead of slipping in after the idle check
    hold, inside = threading.Event(), threading.Event()
    real_reset = DR.reset

    def held_reset(**kw):
        inside.set()
        hold.wait(30)
        return real_reset(**kw)
    DR.reset = held_reset
    server.done["old-req"] = ("main", {"ok": True, "text": "old answer"})
    res = {}
    t = threading.Thread(target=lambda: res.update(r=server.reset_demo({"confirm": True})))
    t.start()
    inside.wait(10)
    n_msgs = count("messages")
    c1, r1 = server.chat("acme-analyst-4", "sneak in", "req-sneak")
    c2, r2 = server.onboarding_op("source", {"url": "https://northloom-demo.example.com"})
    c3, r3 = server.save_company({"fields": {"name": "Sneaky"}})
    c4, r4 = server.reset_demo({"confirm": True})
    check("DR-22 while a reset runs, a chat, an onboarding step, a company save and a second reset are all refused (409) and nothing is written",
          (c1, c2, c3, c4) == (409, 409, 409, 409) and r1.get("code") == r2.get("code") == r3.get("code") == r4.get("code") == "demo_restarting" and count("messages") == n_msgs
          and core.load_company()["name"] == "Acme Quilts", [(c1, r1.get("code")), (c2, r2.get("code")), (c3, r3.get("code")), (c4, r4.get("code"))])
    hold.set()
    t.join(60)
    DR.reset = real_reset
    code, rr = res["r"]
    check("DR-23 the reset then completes (200), the replay cache of finished requests is emptied (an old request id cannot replay an old answer) and the gate opens again",
          code == 200 and rr.get("ok") and not server.done and server.onboarding_op("start", {})[0] == 200, (code, rr, list(server.done)))
    # an onboarding step running blocks the reset
    seed("-5")
    og, oin = threading.Event(), threading.Event()
    real_src = onboarding.submit_source

    def slow_source(url):
        oin.set()
        og.wait(30)
        return 200, {"ok": True}
    onboarding.submit_source = slow_source
    t = threading.Thread(target=lambda: server.onboarding_op("source", {"url": "x"}))
    t.start()
    oin.wait(10)
    code, ro = server.reset_demo({"confirm": True})
    og.set()
    t.join(30)
    onboarding.submit_source = real_src
    check("DR-24 a reset while an onboarding step is running is refused (409 demo_busy) and changes nothing", code == 409 and ro.get("code") == "demo_busy" and count("agents") == 1, (code, ro))
    check("DR-25 the reset is not an agent tool: no Hermes plugin tool or role exposes it", "reset" not in json.dumps(core.ROLES).lower() and "demo_reset" not in (ROOT / "app" / "hermes_plugin.py").read_text(encoding="utf-8"), None)


# ================= corrections round (2026-10-30): (1) interrupted-reset recovery keeps its original archive and guard, (2) the launcher acts offline only on DEFINITE absence =================
import contextlib, importlib.util, io, socket, urllib.error, urllib.request  # noqa: E402
if DR:
    ARCH_DIR = TMP / "runtime" / "demo_archives"

    def archive_names():
        return sorted(p.name for p in ARCH_DIR.iterdir()) if ARCH_DIR.exists() else []

    def marker():
        return DR.PENDING.read_bytes() if DR.PENDING.exists() else b"<missing>"

    def blocked_chat():
        try:
            code, r = server.chat("main", "sneak", "rq-blocked")
        except Exception as e:  # noqa: BLE001
            return "raised", type(e).__name__
        return code, r.get("code")

    # ---- (1) interrupt after a verified archive and partial clearing; recovery must keep the ORIGINAL archive and guard
    DR.reset(stop_workers=lambda: None)   # start the recovery scenarios from a cleared demo
    seed("-6")
    acc0 = tables()
    real_clear, real_archive = DR._clear_profiles, DR._archive

    def stop_mid2(ids):
        raise OSError(32, "The process cannot access the file because it is being used by another process")
    DR._clear_profiles = stop_mid2
    try:
        r1 = DR.reset(stop_workers=lambda: None)
    finally:
        DR._clear_profiles = real_clear
    orig_marker = marker()
    orig_arch = TMP / r1.get("archive", "missing")
    orig_tree = tree(orig_arch)
    names0 = archive_names()
    check("DR-30 setup: the reset stopped during clearing (registry already cleared, profile still there), the archive is verified and the marker says stage clearing",
          r1.get("code") == "reset_incomplete" and count("agents") == 0 and (PROFILES / "acme-analyst-6").exists() and (orig_arch / "manifest.json").exists()
          and json.loads(orig_marker or b"{}").get("stage") == "clearing", (r1, orig_marker))

    def broken_archive(arch):
        raise OSError(28, "No space left on device")
    DR._archive, DR._clear_profiles = broken_archive, stop_mid2
    try:
        r2 = DR.reset(stop_workers=lambda: None)
    finally:
        DR._archive, DR._clear_profiles = real_archive, real_clear
    check("DR-31 a retry that fails again reports FAILURE and keeps the original marker byte-for-byte; it does not archive the half-cleared state (no new archive, the original archive is unchanged)",
          r2.get("ok") is False and r2.get("code") == "reset_incomplete" and DR.PENDING.exists() and marker() == orig_marker and archive_names() == names0 and tree(orig_arch) == orig_tree, (r2, archive_names(), names0))
    try:
        DR.refuse_if_pending()
        still = False
    except SystemExit:
        still = True
    check("DR-32 after the failed retry ordinary start-up is still blocked and the server still refuses chat, onboarding and company changes (409 demo_restart_incomplete)",
          still and blocked_chat() == (409, "demo_restart_incomplete") and server.onboarding_op("source", {"url": "x"})[1].get("code") == "demo_restart_incomplete"
          and server.save_company({"fields": {"name": "Sneaky"}})[1].get("code") == "demo_restart_incomplete", blocked_chat())
    # the recovery archive is damaged -> clearing must not rely on it
    victim = next(p for p in sorted(orig_arch.rglob("*")) if p.is_file() and p.parent.name == "memories")
    good = victim.read_bytes()
    victim.write_bytes(b"tampered")
    r3 = DR.reset(stop_workers=lambda: None)
    victim.write_bytes(good)
    check("DR-33 a recovery whose archive no longer matches its manifest is refused (recovery_archive_invalid): nothing is cleared, the marker and guard stay",
          r3.get("ok") is False and r3.get("code") == "recovery_archive_invalid" and (PROFILES / "acme-analyst-6").exists() and marker() == orig_marker, r3)
    r4 = DR.reset(stop_workers=lambda: None)
    check("DR-34 the retry with the real functions COMPLETES the original operation: same archive, marker removed, the old profile is gone, website step, no new archive",
          r4.get("ok") is True and r4.get("archive") == r1["archive"] and DR.pending() is None and not (PROFILES / "acme-analyst-6").exists()
          and onboarding.status()["state"] == "awaiting_source" and archive_names() == names0, (r4, archive_names(), names0))
    check("DR-35 paid accounting is untouched by the recovery (every non-progress table equals what it was before the interrupted reset) and the live app.db was not replaced",
          tables() == acc0 and count("messages") == 0, None)
    check("DR-36 the archive that recovery used still holds the old progress (the progress rows and the memory file)", sqlite3.connect(orig_arch / "app.db").execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 4
          and "PURPLE-OTTER" in (orig_arch / "profiles" / "acme-analyst-6" / "memories" / "MEMORY.md").read_text(encoding="utf-8"), None)

    # ---- (1b) an unreadable or invalid marker never means "no reset pending"
    seed("-7")
    n_msgs, n_arch = count("messages"), len(archive_names())
    shapes = {"not json": b"{broken", "empty file": b"", "a list": b"[1, 2]", "no archive": b'{"stage": "clearing"}', "unknown stage": b'{"archive": "runtime/demo_archives/x", "stage": "weird"}',
              "archive outside the archive folder": b'{"archive": "runtime/hermes_home", "stage": "clearing"}'}
    outcome = {}
    for label, raw in shapes.items():
        DR.PENDING.write_bytes(raw)
        try:
            DR.refuse_if_pending()
            blocked = False
        except SystemExit:
            blocked = True
        except Exception:  # noqa: BLE001  (a crash is not a clean block)
            blocked = False
        try:
            res = DR.reset(stop_workers=lambda: None)
        except Exception as e:  # noqa: BLE001
            res = {"ok": None, "code": "raised " + type(e).__name__}
        outcome[label] = (blocked, res.get("ok"), res.get("code"), marker() == raw)
    check("DR-37 an unreadable or invalid marker (garbage, empty, wrong shape, unknown stage, an archive outside demo_archives) blocks start-up and a reset REFUSES, leaving the marker, progress and archives as they were",
          all(v == (True, False, "reset_marker_invalid", True) for v in outcome.values()) and count("messages") == n_msgs and len(archive_names()) == n_arch, outcome)
    check("DR-38 the server also refuses while the marker is unreadable (409)", blocked_chat()[0] == 409, blocked_chat())
    DR.PENDING.unlink(missing_ok=True)

    # ---- (1c) interrupted ARCHIVING (stage archiving: nothing was cleared): safe to restart from scratch; a clearing marker whose archive is incomplete never clears
    part = ARCH_DIR / "20200101-000000-000001"
    (part / "profiles").mkdir(parents=True)
    (part / "app.db").write_bytes(b"partial")   # no manifest.json: the archive was never completed
    DR.PENDING.write_text(json.dumps({"archive": "runtime/demo_archives/20200101-000000-000001", "stage": "archiving"}), encoding="utf-8")
    r5 = DR.reset(stop_workers=lambda: None)
    check("DR-39 an interrupted ARCHIVING stage is redone from scratch (nothing had been cleared): the unfinished archive is discarded, a new verified archive is made, and the reset completes",
          r5.get("ok") is True and not part.exists() and r5["archive"] != "runtime/demo_archives/20200101-000000-000001" and DR.pending() is None and count("messages") == 0, (r5, archive_names()))
    seed("-8")
    inc = ARCH_DIR / "20200101-000000-000002"
    (inc / "profiles").mkdir(parents=True)
    DR.PENDING.write_text(json.dumps({"archive": "runtime/demo_archives/20200101-000000-000002", "stage": "clearing"}), encoding="utf-8")
    r6 = DR.reset(stop_workers=lambda: None)
    check("DR-40 a marker that says clearing but whose archive has no manifest is refused (recovery_archive_invalid): progress is NOT cleared with an unverified archive",
          r6.get("ok") is False and r6.get("code") == "recovery_archive_invalid" and count("messages") == 4 and (PROFILES / "acme-analyst-8").exists() and DR.pending() is not None, r6)
    DR.PENDING.unlink(missing_ok=True)
    shutil.rmtree(inc)
    DR.reset(stop_workers=lambda: None)   # tidy: the real functions clear -8

    # ---- (2) the launcher: absent / running / uncertain are three outcomes; only DEFINITE absence permits the offline reset
    spec = importlib.util.spec_from_file_location("fresh_demo", ROOT / "scripts" / "fresh_demo.py")
    FD = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(FD)
    with socket.socket() as s0:
        s0.bind(("127.0.0.1", 0))
        FREE = s0.getsockname()[1]
    APP_STATUS = json.dumps({"provider": "p", "model": "m", "problem": None, "classifier": {}, "company": {}, "secrets_file": "secrets/local.env"}).encode()

    class Resp:
        def __init__(self, body, status=200):
            self.body, self.status = body, status

        def read(self):
            return self.body

        def getcode(self):
            return self.status

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(plan, log):
        def f(req, timeout=None, **kw):
            url = req if isinstance(req, str) else req.full_url
            log.append((url, None if isinstance(req, str) else req.data))
            what = plan(url, req)
            if isinstance(what, BaseException):
                raise what
            return what
        return f

    def run_launcher(plan):
        log, out = [], io.StringIO()
        calls = {"reset": 0, "archive": 0, "clear": 0}
        real = (urllib.request.urlopen, DR.reset, DR._archive, DR._clear_profiles)

        def count_reset(**kw):
            calls["reset"] += 1
            return {"ok": True, "archive": "runtime/demo_archives/stub"}

        def count_archive(a):
            calls["archive"] += 1
            raise OSError("must not archive")

        def count_clear(ids):
            calls["clear"] += 1
        urllib.request.urlopen, DR.reset, DR._archive, DR._clear_profiles = fake_urlopen(plan, log), count_reset, count_archive, count_clear
        try:
            with contextlib.redirect_stdout(out):
                try:
                    code = FD.main(["--yes", "--port", str(FREE)])
                except BaseException as e:  # noqa: BLE001
                    code = f"raised {type(e).__name__}: {e}"
        finally:
            urllib.request.urlopen, DR.reset, DR._archive, DR._clear_profiles = real
        return code, out.getvalue(), calls, log

    profiles_before, arch_before = tree(core.HERMES_ROOT / "profiles"), archive_names()
    seed("-9")
    profiles_before = tree(core.HERMES_ROOT / "profiles")
    ambiguous = {"read timeout": lambda u, r: socket.timeout("timed out"), "connection reset": lambda u, r: ConnectionResetError(10054, "forcibly closed"),
                 "unexpected response (not JSON)": lambda u, r: Resp(b"<html>hello</html>"), "unexpected service (JSON, not this app)": lambda u, r: Resp(b'{"hello": "world"}'),
                 "HTTP 500": lambda u, r: urllib.error.HTTPError(u, 500, "boom", {}, io.BytesIO(b"{}")), "URLError wrapping a timeout": lambda u, r: urllib.error.URLError(socket.timeout("timed out"))}
    res = {k: run_launcher(p) for k, p in ambiguous.items()}
    check("DR-50 when the status of the app is uncertain (read timeout, connection reset, malformed or foreign response, HTTP 500) the launcher stops with a clear message and changes NOTHING: exit 1, no reset/archive/profile operation, no POST, no archive folder, no marker",
          all(v[0] == 1 and v[2] == {"reset": 0, "archive": 0, "clear": 0} and all(d is None for _, d in v[3]) and "nothing was changed" in v[1].lower() and "restart demo" in v[1].lower() for v in res.values())
          and archive_names() == arch_before and DR.pending() is None and tree(core.HERMES_ROOT / "profiles") == profiles_before and count("agents") == 1, {k: (v[0], v[2], v[1][-120:]) for k, v in res.items()})

    def running_plan(post):
        return lambda u, r: Resp(APP_STATUS) if u.endswith("/api/status") else post(u, r)
    code, out_text, calls, log = run_launcher(running_plan(lambda u, r: Resp(json.dumps({"ok": True, "archive": "runtime/demo_archives/via-app"}).encode())))
    posts = [(u, d) for u, d in log if d]
    check("DR-51 a CONFIRMED running app is restarted through its own reset endpoint (exit 2, confirm true) and never reset directly",
          code == 2 and calls["reset"] == 0 and len(posts) == 1 and posts[0][0].endswith("/api/demo/reset") and json.loads(posts[0][1]) == {"confirm": True} and "via-app" in out_text, (code, calls, posts, out_text[-200:]))
    busy = urllib.error.HTTPError("u", 409, "Conflict", {}, io.BytesIO(json.dumps({"ok": False, "code": "demo_busy", "error": "Something is still running (x). Wait."}).encode()))
    code, out_text, calls, log = run_launcher(running_plan(lambda u, r: busy))
    check("DR-52 when the running app refuses (busy) the launcher reports its reason, exits 1 and does not fall back to a direct reset", code == 1 and calls["reset"] == 0 and "Something is still running" in out_text, (code, out_text[-200:]))
    code, out_text, calls, log = run_launcher(lambda u, r: urllib.error.URLError(ConnectionRefusedError(10061, "refused")))
    check("DR-53 a DEFINITE absence (connection refused) permits the direct reset exactly once (exit 0 = start the app)", code == 0 and calls["reset"] == 1, (code, calls, out_text[-200:]))
    with socket.socket() as s1:
        s1.bind(("127.0.0.1", FREE))
        s1.listen(1)
        code, out_text, calls, log = run_launcher(lambda u, r: urllib.error.URLError(ConnectionRefusedError(10061, "refused")))
    check("DR-54 if the port turns out to be taken at the moment the launcher wants to hold it (an app started in between) it stops, changes nothing and does not reset", code == 1 and calls["reset"] == 0 and "nothing was changed" in out_text.lower(), (code, calls, out_text[-200:]))
    claim = getattr(FD, "claim_port", None)
    held = claim(FREE) if claim else None
    if os.name == "nt" and held:
        s2 = socket.socket()
        s2.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)   # what ThreadingHTTPServer sets
        try:
            s2.bind(("127.0.0.1", FREE))
            taken = True
        except OSError:
            taken = False
        finally:
            s2.close()
    else:
        taken = None
    if held:
        held.close()
    check("DR-55 while the offline reset holds the app's port exclusively, the app cannot start on it (its bind fails) - the launcher's ownership of the reset window", held is not None and taken in (False, None), (held, taken))
    seed_reset = DR.reset(stop_workers=lambda: None)   # tidy: clears -9 for whatever follows

shutil.rmtree(TMP, ignore_errors=True)
print(f"{sum(results)}/{len(results)} passed")
sys.exit(0 if results and all(results) else 1)
