"""Behavioural tests of scripts/v2_06_demo.py against the scripted stand-ins ONLY (dummy credentials, synthetic placeholder inputs). Nothing here is live evidence.
Run with the Hermes interpreter from the project root:  python tests/v2_06_demo_test.py
It never touches the project's runtime, secrets or any auth file: every demo copy lives in a temp folder, and the isolation test uses a FAKE project root that holds
sentinel 'real' files to prove they are neither opened nor copied. Demo copies, archives and process logs are kept under .scratch/v206-test-<stamp>/ (ignored)."""
import hashlib, http.client, importlib.util, json, os, shutil, sqlite3, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNNER = ROOT / "scripts" / "v2_06_demo.py"
STAMP = time.strftime("%Y%m%dT%H%M%S")
TMP = ROOT / ".scratch" / f"v206-test-{STAMP}"   # ignored scratch: the demo copies, archives and logs stay inspectable after a passing run
TMP.mkdir(parents=True)
RED, GREEN = [210, 40, 40], [40, 170, 80]
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"\n     -> {str(detail)[:700]}"), flush=True)


def runner(*args, timeout=900):
    env = {k: v for k, v in os.environ.items() if not any(s in k.upper() for s in ("KEY", "TOKEN", "SECRET", "ECOM_", "HERMES_", "LLM_", "NEBIUS", "GEMINI", "SCRAPE"))}
    r = subprocess.run([sys.executable, str(RUNNER), *map(str, args)], capture_output=True, text=True, timeout=timeout, env=env | {"PYTHONUTF8": "1"})
    return r.returncode, (r.stdout + r.stderr)


def state(d):
    return json.loads((Path(d) / "runner_state.json").read_text(encoding="utf-8"))


def db(d, sql, *a):
    c = sqlite3.connect(f"file:{(Path(d) / 'runtime' / 'app.db').as_posix()}?mode=ro", uri=True)
    try:
        return c.execute(sql, a).fetchall()
    finally:
        c.close()


def mod_from(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def tree_bytes(d):
    return b"".join(p.read_bytes() for p in sorted(Path(d).rglob("*")) if p.is_file() and "__pycache__" not in p.parts)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def prepared(name):
    d = TMP / name
    rc, out = runner("prepare", "--dir", d, "--mode", "scripted")
    assert rc == 0, out
    return d


# ======================================================================= 1. isolation (fake project root holding sentinel 'real' files)
print("== 1. isolated preparation neither reads nor copies the real runtime, secrets or auth files", flush=True)
fake = TMP / "fakeroot"
for sub in ("app",):
    shutil.copytree(ROOT / sub, fake / sub, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
(fake / "scripts").mkdir()
for f in ("setup.py", "marketplace_check.py", "v2_06_demo.py", "v2_06_readiness.py"):
    shutil.copy2(ROOT / "scripts" / f, fake / "scripts" / f)
(fake / "tests").mkdir()
for f in ("mock_llm.py", "mock_gemini.py", "mock_fb_ads.py"):
    shutil.copy2(ROOT / "tests" / f, fake / "tests" / f)
SENT = {"auth": b'{"providers": {"openai-codex": {"tokens": {"access_token": "SENTINEL-REAL-ACCESS-TOKEN", "refresh_token": "SENTINEL-REAL-REFRESH-TOKEN"}}}}',
        "db": b"SENTINEL-REAL-APP-DB-CONTENT", "env": b"GEMINI_API_KEY=SENTINEL-REAL-GEMINI-KEY-0123456789\nSCRAPECREATORS_API_KEY=SENTINEL-REAL-SCRAPE-KEY-0123456789\n"}
(fake / "runtime" / "hermes_home" / "profiles" / "main").mkdir(parents=True)
(fake / "secrets").mkdir()
paths = {"auth": fake / "runtime" / "hermes_home" / "auth.json", "db": fake / "runtime" / "app.db", "env": fake / "secrets" / "local.env"}
for k, p in paths.items():
    p.write_bytes(SENT[k])
(fake / "runtime" / "hermes_home" / "profiles" / "main" / "auth.json").write_bytes(SENT["auth"])
sig0 = {k: (sha(p.read_bytes()), p.stat().st_mtime_ns) for k, p in paths.items()}
fm = mod_from(fake / "scripts" / "v2_06_demo.py", "v2_fake_runner")
opened, watching = [], [False]


def hook(ev, args):
    if watching[0] and ev == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
        opened.append(os.fsdecode(args[0]))


sys.addaudithook(hook)
iso = TMP / "iso-demo"
watching[0] = True
rc = fm.main(["prepare", "--dir", str(iso), "--mode", "scripted"])
watching[0] = False
bad_open = [p for p in opened if Path(p).resolve().is_relative_to((fake / "runtime").resolve()) or Path(p).resolve().is_relative_to((fake / "secrets").resolve())]
blob = tree_bytes(iso)
check("1a prepare completes from the fake root; no file under the fake root's runtime/ or secrets/ was opened by the runner process",
      rc == 0 and not bad_open, bad_open[:5] or rc)
check("1b no sentinel token, key or database content appears anywhere in the new demo copy, and no auth.json / app.db of the real tree exists in it",
      all(s not in blob for s in (b"SENTINEL-REAL-ACCESS-TOKEN", b"SENTINEL-REAL-REFRESH-TOKEN", b"SENTINEL-REAL-APP-DB", b"SENTINEL-REAL-GEMINI-KEY", b"SENTINEL-REAL-SCRAPE-KEY"))
      and not list(iso.rglob("auth.json")), [str(p) for p in iso.rglob("auth.json")])
check("1c the real files are byte-identical with unchanged modification times",
      all((sha(p.read_bytes()), p.stat().st_mtime_ns) == sig0[k] for k, p in paths.items()))
env_txt = (iso / "secrets" / "local.env").read_text(encoding="ascii")
check("1d the demo env file holds ONLY the labelled dummy values, with distinct scripted scopes recorded for provisioning, probe and demonstration",
      "TEST-GEMINI-KEY-SENTINEL" in env_txt and "SENTINEL-REAL" not in env_txt and len({v["flyer"] for v in state(iso)["scopes"].values()}) == 3
      and len({v["ads"] for v in state(iso)["scopes"].values()}) == 3, env_txt)
rc2, out2 = runner("prepare", "--dir", iso, "--mode", "scripted")
check("1e prepare refuses a non-empty directory", rc2 == 2 and "not empty" in out2, out2)
rc3, out3 = runner("prepare", "--dir", ROOT / "not-ignored-v206-test", "--mode", "scripted")
check("1f prepare refuses a folder inside the project that Git does not ignore (and creates nothing)", rc3 == 2 and not (ROOT / "not-ignored-v206-test").exists(), out3)
rc4, out4 = runner("prepare", "--dir", TMP / "live-no-inputs", "--mode", "live")
check("1g live prepare refuses without the private inputs and creates nothing", rc4 == 2 and not (TMP / "live-no-inputs").exists(), out4)

# live-mode guards (pure function: no process, no network)
lm = TMP / "live-state"
lm.mkdir()
lst = {"mode": "live", "auth_arrangement": "unresolved", "phases": {"prepare": {"status": "completed"}}}
R = fm.Refused


def refused(fn):
    try:
        fn()
    except R as e:
        return str(e)
    return None


m1 = refused(lambda: fm.begin(lm, lst, "provision", live_ok=False))
m2 = refused(lambda: fm.begin(lm, lst, "provision", live_ok=True))
lst["auth_arrangement"] = "demo-own-signin-accepted"
m3 = refused(lambda: fm.begin(lm, lst, "provision", live_ok=True))
check("1h live phases refuse without --live-authorized, while the authentication arrangement is unresolved, and without the demo's OWN sign-in; no phase is recorded",
      m1 and "--live-authorized" in m1 and m2 and "UNRESOLVED" in m2 and m3 and "no sign-in of its own" in m3 and "provision" not in lst["phases"], (m1, m2, m3))
(lm / "runtime" / "hermes_home").mkdir(parents=True)
check("1i the demonstration additionally needs an explicit approval after the probe",
      refused(lambda: fm.begin(lm, {**lst, "phases": {"prepare": {"status": "completed"}, "probe": {"status": "completed"}}}, "demo", live_ok=True)) is not None)

# ======================================================================= 2. full scripted pipeline, one separately invoked phase at a time
print("== 2. prepare -> provision -> zero-cap checks -> probe -> demonstration -> archive -> retrieval", flush=True)
A = prepared("A")
rc, out = runner("provision", "--dir", A, "--turn-timeout", 300)
sa = state(A)
prov = sa["phases"]["provision"]
sp = sa.get("specialist") or {}
import yaml  # noqa: E402  (Hermes interpreter)
cfg = lambda p: yaml.safe_load(Path(p).read_text(encoding="utf-8")).get("agent", {})
want_cfg = {"api_max_retries": 1, "auto_recovery_cycles": 0}
check("2a provisioning: one main request created exactly one social_media specialist through the real create_agent tool with the requested tools (plus the backend foundation)",
      rc == 0 and prov["status"] == "completed" and [x["tool"] for x in prov["activity"]] == ["create_agent"]
      and sp.get("agent_id") and {"generate_flyer", "inspect_flyer", "review_flyer", "finalize_flyer", "fb_ads_search", "inspect_image", "read_catalogue"} <= set(sp["granted_tools"]),
      (out, prov.get("activity"), sp))
check("2b provisioning made ZERO scraper, download and Gemini requests; no flyer or ad ledger row was consumed",
      prov["observed"]["provider_stand_ins"]["gemini_requests"] == 0 and prov["observed"]["provider_stand_ins"]["scraper_and_cdn_requests"] == 0
      and not [r for r in db(A, "SELECT * FROM flyer_allowance WHERE attempts_used>0")] and not db(A, "SELECT * FROM ad_calls"), prov.get("observed"))
check("2c demo-only retry/recovery settings are in the root, main and the NEW specialist's config before its first worker existed",
      cfg(A / "runtime" / "hermes_home" / "config.yaml") == want_cfg and cfg(A / "runtime" / "hermes_home" / "profiles" / "main" / "config.yaml") == want_cfg
      and cfg(A / "runtime" / "hermes_home" / "profiles" / sp.get("agent_id", "x") / "config.yaml") == want_cfg and sp.get("worker_existed_before_config_patch") is False, sp)
check("2d reasoning attempts were observed and recorded for the phase (provider stand-in counter and timing log)",
      prov["observed"]["provider_stand_ins"]["reasoning_requests"] >= 1 and prov["observed"]["timing_log"]["api_end_events"] >= 1, prov.get("observed"))

# zero caps reject BEFORE dispatch: ask the specialist (through the real chat API and Hermes) to use the scraper and Gemini under the PROVISIONING scopes
sm = mod_from(RUNNER, "v2_runner_main")
st_a = sa
zero_out = {}
with sm.Stack(A, st_a, "provision") as s:
    ag = sp["agent_id"]
    first_img = "hw-front"
    for nm, args in (("fb_ads_search", {"query": "quilted bedding"}),
                     ("generate_flyer", {"product_id": "harbor-wool-throw", "selected_product_image_ids": [first_img],
                                        "prompt": "Create a clean promotional flyer for the Heritage Wool Throw showing the declared price 64.5 EUR."})):
        code, r = sm._post(s.port, f"/api/chat/{ag}", {"message": "CALL_TOOL:" + json.dumps({"name": nm, "args": args}), "request_id": f"zero-{nm}"}, 300)
        zero_out[nm] = [json.loads(a["output"]) for a in r.get("activity", []) if a["tool"] == nm and a.get("output")]
    zc = s.provider_counts()
check("2e zero caps reject before dispatch: under the provisioning scopes the scraper search and the Gemini generation both answer allowance_exhausted and the stand-ins received no request",
      [o.get("code") for o in zero_out["fb_ads_search"]] == ["allowance_exhausted"] and [o.get("code") for o in zero_out["generate_flyer"]] == ["allowance_exhausted"]
      and zc["gemini_requests"] == 0 and zc["scraper_and_cdn_requests"] == 0, (zero_out, zc))
check("2f the zero-cap rows exist as durable scopes with max 0 and used 0",
      db(A, "SELECT attempts_max, attempts_used FROM flyer_allowance WHERE scope=?", sa["scopes"]["provision"]["flyer"]) == [(0, 0)]
      and db(A, "SELECT api_max, api_used, image_max, image_used FROM ad_allowance WHERE scope=?", sa["scopes"]["provision"]["ads"]) == [(0, 0, 0, 0)])

rc, out = runner("demo", "--dir", A, "--approve-demo")
check("2g the demonstration cannot start before a completed probe (and never automatically)", rc == 2 and "needs a completed probe" in out, out)
rc, out = runner("probe", "--dir", A, "--turn-timeout", 600)
pr = state(A)["phases"]["probe"]
acts = [x["tool"] for x in pr.get("activity", [])]
fid = (pr.get("flyer_for_this_request") or [{}])[0]
fl = db(A, "SELECT request_id, scope FROM flyer_runs")
rv = db(A, "SELECT request_id, verified, inspection_id, sha256, delivery FROM flyer_reviews")
ins = db(A, "SELECT kind, sha256 FROM image_inspections WHERE id=?", rv[0][2]) if rv else []
att = db(A, "SELECT outcome FROM flyer_attempts")
check("2h probe: ONE request did generate -> inspect_flyer -> review_flyer in that order; the run, the inspection and the review all carry that request id and the review is delivery-verified",
      rc == 0 and pr["status"] == "completed" and pr["posts"] == 1
      and [t for t in acts if t in ("generate_flyer", "inspect_flyer", "review_flyer")] == ["generate_flyer", "inspect_flyer", "review_flyer"]
      and fl == [(pr["request_id"], sa["scopes"]["probe"]["flyer"])] and [r[0] for r in rv] == [pr["request_id"]] and rv[0][1] == 1
      and ins == [("flyer_candidate", rv[0][3])] and fid.get("final") is None, (acts, fl, rv, ins))
check("2i probe dispatch bounds: exactly ONE Gemini request, ZERO scraper/download requests, no correction, no final selection, attempts 1 of 1",
      pr["observed"]["provider_stand_ins"]["gemini_requests"] == 1 and pr["observed"]["provider_stand_ins"]["scraper_and_cdn_requests"] == 0
      and acts.count("generate_flyer") == 1 and "finalize_flyer" not in acts and fid.get("attempts_used") == 1
      and db(A, "SELECT attempts_max, attempts_used FROM flyer_allowance WHERE scope=?", sa["scopes"]["probe"]["flyer"]) == [(1, 1)], (pr.get("observed"), acts))
rc, out = runner("probe", "--dir", A)
check("2j the probe cannot be run again in this directory (no reset, no new scope)", rc == 2 and "already attempted" in out, out)
rc, out = runner("demo", "--dir", A, "--approve-demo", "--turn-timeout", 900, "--scripted-opts", json.dumps({"colors": [RED, GREEN]}))
de = state(A)["phases"]["demo"]
dacts = [x["tool"] for x in de.get("activity", [])]
dfl = (de.get("flyer_for_this_request") or [{}])[0]
ledg = {r["scope"]: r for r in de["ledgers_after"]["ads_allowance"]}
check("2k demonstration: ad research -> generation -> inspect/review -> exactly one correction -> explicit final selection inside ONE request, status from verified reviews",
      rc == 0 and de["status"] == "completed" and de["posts"] == 1 and dacts.index("fb_ads_search") < dacts.index("generate_flyer") and dacts.count("generate_flyer") == 2
      and dacts[-1] == "finalize_flyer" and dfl.get("attempts_used") == 2 and dfl.get("final") and all(dfl.get("reviews_verified")) and dfl.get("status") == "agent_review_passed", (dacts, dfl))
check("2l demonstration allowances: Gemini <= 2 (used 2 of 2), scraper API <= 8 and ad-image downloads <= 4 as recorded by BOTH the ledgers and the stand-ins",
      de["observed"]["provider_stand_ins"]["gemini_requests"] == 2 and ledg[sa["scopes"]["demo"]["ads"]]["api_used"] <= 8 and ledg[sa["scopes"]["demo"]["ads"]]["image_used"] <= 4
      and de["observed"]["provider_stand_ins"]["scraper_and_cdn_requests"] == ledg[sa["scopes"]["demo"]["ads"]]["api_used"] + ledg[sa["scopes"]["demo"]["ads"]]["image_used"]
      and db(A, "SELECT attempts_max, attempts_used FROM flyer_allowance WHERE scope=?", sa["scopes"]["demo"]["flyer"]) == [(2, 2)], (de.get("observed"), ledg))
check("2m the three phases used three distinct durable scopes and the probe/provision scopes were not touched by the demonstration",
      db(A, "SELECT attempts_used FROM flyer_allowance WHERE scope=?", sa["scopes"]["probe"]["flyer"]) == [(1,)]
      and len(db(A, "SELECT scope FROM flyer_allowance")) == 3)

rc, out = runner("archive", "--dir", A)
arch = Path(state(A).get("archive_dir", TMP / "none"))
man = json.loads((arch / "manifest.json").read_text(encoding="utf-8")) if (arch / "manifest.json").is_file() else {"files": {}}
dummies = [b"TEST-GEMINI-KEY-SENTINEL", b"TEST-SCRAPE-KEY-SENTINEL", b"mock-key"]
leaks = [str(f.name) for f in arch.rglob("*") if f.is_file() and any(x in f.read_bytes() for x in dummies)]
final_rel = next((r for r in man["files"] if r.endswith("final.img") and dfl.get("flyer_id", "?") in r), None)
tr = json.loads((arch / "transcripts" / f"{sp['agent_id']}.json").read_text(encoding="utf-8")) if (arch / "transcripts").is_dir() else []
check("2n archive: manifest parses and every hash matches; final image, candidates, reference ad images, flyer/ad JSON, ledgers, transcripts with tool activity, timing and observed counts are present",
      rc == 0 and man["files"] and all(sha((arch / r).read_bytes()) == m["sha256"] for r, m in man["files"].items())
      and final_rel and any(r.startswith("ads/adrun-") and r.endswith(".img") for r in man["files"]) and "ledgers.json" in man["files"] and "observed.json" in man["files"]
      and "timing.jsonl" in man["files"] and any(x.get("activity") for x in tr), (out[-600:], list(man["files"])[:30]))
check("2o archive contains no dummy credential value, and the demo env file lost its key lines only AFTER the archive verified",
      not leaks and "GEMINI_API_KEY" not in (A / "secrets" / "local.env").read_text(encoding="ascii")
      and state(A)["phases"]["archive"].get("credentials_removed_from_demo_env") and state(A)["phases"]["archive"]["status"] == "completed", leaks)
sig_before = db(A, "SELECT (SELECT COUNT(*) FROM flyer_attempts),(SELECT COUNT(*) FROM ad_calls),(SELECT COALESCE(SUM(attempts_used),0) FROM flyer_allowance)")
rc, out = runner("retrieve", "--dir", A)
rt = state(A)["phases"]["retrieve"]
check("2p restart retrieval with inference credentials absent: final image and flyer data re-read, hashes match, ZERO new provider requests, dispatch tables unchanged",
      rc == 0 and rt["status"] == "completed" and rt["retrieval"]["provider_unusable"] is True and rt["retrieval"]["env_has_inference_credentials"] is False and rt["problems"] == []
      and not any(rt["provider_requests_during_retrieval"].values())
      and sig_before == db(A, "SELECT (SELECT COUNT(*) FROM flyer_attempts),(SELECT COUNT(*) FROM ad_calls),(SELECT COALESCE(SUM(attempts_used),0) FROM flyer_allowance)"), (out, rt))

# ======================================================================= 3. probe: a second generation and the scraper are rejected
print("== 3. probe rejects a second generation and any scraper use even when the specialist tries both", flush=True)
B = prepared("B")
runner("provision", "--dir", B, "--turn-timeout", 300)
rc, out = runner("probe", "--dir", B, "--turn-timeout", 600, "--scripted-opts",
                 json.dumps({"ads": True, "correct": True, "colors": [RED, GREEN], "markers": ["GENERATE_ANYWAY"]}))
sb = state(B)
pb = sb["phases"]["probe"]
bacts = [(x["tool"], x["status"]) for x in pb.get("activity", [])]
check("3a the probe specialist tried ad research and a correction: the scraper search and the SECOND generation were rejected (errors), the first generation and its review succeeded",
      rc in (0, 3) and ("fb_ads_search", "error") in bacts and [s for t, s in bacts if t == "generate_flyer"] == ["ok", "error"] and ("review_flyer", "ok") in bacts, bacts)
check("3b exactly one Gemini request and zero scraper/download requests reached the stand-ins; the probe ledgers read 1/1 flyer and 0/0 scraper",
      pb["observed"]["provider_stand_ins"]["gemini_requests"] == 1 and pb["observed"]["provider_stand_ins"]["scraper_and_cdn_requests"] == 0
      and db(B, "SELECT attempts_max, attempts_used FROM flyer_allowance WHERE scope=?", sb["scopes"]["probe"]["flyer"]) == [(1, 1)]
      and db(B, "SELECT api_max, api_used FROM ad_allowance WHERE scope=?", sb["scopes"]["probe"]["ads"]) == [(0, 0)], (pb.get("observed"), bacts))

# ======================================================================= 4. a failed / unknown dispatch stays counted; evidence is preserved, nothing is manufactured
print("== 4. unknown Gemini dispatch stays counted; archive preserves the incomplete outcome", flush=True)
C = prepared("C")
runner("provision", "--dir", C, "--turn-timeout", 300)
rc, out = runner("probe", "--dir", C, "--turn-timeout", 600, "--scripted-opts", json.dumps({"gem_mode": "drop"}))
sc = state(C)
pc_ = sc["phases"]["probe"]
cfl = (pc_.get("flyer_for_this_request") or [{}])[0]
check("4a a dropped Gemini connection leaves an UNKNOWN dispatched attempt that is counted (1 of 1), is never replayed, and has no verified review or final selection",
      pc_["observed"]["provider_stand_ins"]["gemini_requests"] == 1 and db(C, "SELECT attempts_used FROM flyer_allowance WHERE scope=?", sc["scopes"]["probe"]["flyer"]) == [(1,)]
      and cfl.get("status") != "agent_review_passed" and cfl.get("final") is None and not any(cfl.get("reviews_verified") or []), (pc_.get("observed"), cfl))
rc, out = runner("archive", "--dir", C)
arch_c = Path(state(C).get("archive_dir", TMP / "none"))
fj = [json.loads(p.read_text(encoding="utf-8")) for p in (arch_c / "flyers").glob("fly-*.json")] if (arch_c / "flyers").is_dir() else []
check("4b the archive of the incomplete outcome parses and records the flyer with its non-passed status, attempts used and no final selection",
      rc == 0 and len(fj) == 1 and fj[0].get("status") != "agent_review_passed" and not (fj[0].get("final") or {}).get("selected") and fj[0]["attempts"]["used"] == 1, (out, [f.get("status") for f in fj]))

# ======================================================================= 5. lost answer / timeout: no resubmission
print("== 5. lost or unknown completion stops without resubmission", flush=True)
D = prepared("D")
runner("provision", "--dir", D, "--turn-timeout", 300)
t0 = time.time()
rc, out = runner("probe", "--dir", D, "--turn-timeout", 4, "--settle", 2, "--scripted-opts", json.dumps({"markers": ["SLOW"]}))
sd = state(D)
pd = sd["phases"]["probe"]
users = db(D, "SELECT COUNT(*) FROM messages WHERE agent_id=? AND who='user'", sd["specialist"]["agent_id"])[0][0]
check("5a a timed-out turn is recorded as unknown_completion after exactly ONE post; the transcript holds exactly one user message and the runner exits non-zero",
      rc == 3 and pd["status"] == "unknown_completion" and pd["posts"] == 1 and users == 1 and pd.get("transport_error"), (out, pd.get("status"), users))
rc, out = runner("probe", "--dir", D)
check("5b running the probe again is refused (the lost request is never resent)", rc == 2 and "already attempted" in out, out)
rc, out = runner("demo", "--dir", D, "--approve-demo")
check("5c the demonstration is refused after an unknown probe", rc == 2 and "needs a completed probe" in out, out)
rc, out = runner("archive", "--dir", D)
ad = Path(state(D).get("archive_dir", TMP / "none"))
st_arch = json.loads((ad / "state.json").read_text(encoding="utf-8")) if (ad / "state.json").is_file() else {}
tr_d = json.loads((ad / "transcripts" / f"{sd['specialist']['agent_id']}.json").read_text(encoding="utf-8")) if (ad / "transcripts").is_dir() else []
check("5d partial evidence is preserved: the archive records the unknown_completion phase and the transcript with the single user message, and fabricates no flyer or final",
      rc == 0 and st_arch.get("phases", {}).get("probe", {}).get("status") == "unknown_completion" and [m["who"] for m in tr_d].count("user") == 1
      and not list((ad / "flyers").glob("*.json")), out)

# transport faults at the function level: exactly one POST, whatever the exception
fake_calls = []
d_unit = TMP / "unit"
d_unit.mkdir()
ust = {"phases": {"probe": {"status": "started"}}}
(d_unit / "runner_state.json").write_text(json.dumps(ust), encoding="utf-8")
sm.busy = lambda port, agent: False
for exc in (ConnectionResetError("reset"), http.client.IncompleteRead(b"x"), http.client.RemoteDisconnected("closed"), ValueError("not json"), TimeoutError("late")):
    fake_calls.clear()
    rec = ust["phases"]["probe"] = {"status": "started"}

    def boom(*a, _e=exc, **k):
        fake_calls.append(1)
        raise _e
    sm._post = boom
    res = sm.send_turn(d_unit, ust, rec, type("S", (), {"port": 1}), "agent", "msg", "rid-unit", 1, 0)
    check(f"5e {type(exc).__name__}: one POST, unknown_completion, no resubmission", res is None and len(fake_calls) == 1 and rec["status"] == "unknown_completion" and rec["posts"] == 1,
          (rec, len(fake_calls)))

# the answer is lost but the backend's own transcript confirms the finished turn: outcome taken from it (read-only), still exactly one POST
for who, want in (("agent", "completed"), ("error", "failed")):
    fake_calls.clear()
    rec = ust["phases"]["probe"] = {"status": "started"}
    sm._post = lambda *a, **k: (fake_calls.append(1), (_ for _ in ()).throw(ConnectionResetError("reset")))[1]
    sm.get = lambda port, path, raw=False, tries=5, _w=who: (200, [{"who": "user", "content": "msg"}, {"who": _w, "content": "done text", "activity": [{"tool": "generate_flyer", "status": "ok"}]}])
    res = sm.send_turn(d_unit, ust, rec, type("S", (), {"port": 1}), "agent", "msg", "rid-unit", 1, 0)
    check(f"5f lost answer + transcript row '{who}': status {want}, outcome read from the transcript, one POST, no resubmission",
          rec["status"] == want and rec.get("confirmed_from_transcript") and rec["activity"] == [{"tool": "generate_flyer", "status": "ok"}] and len(fake_calls) == 1
          and rec["posts"] == 1, rec)

# ======================================================================= 6. the demo-only retry setting really limits model attempts
print("== 6. api_max_retries=1 limits a failing provider to one request in the demo copy", flush=True)
E = prepared("E")
runner("provision", "--dir", E, "--turn-timeout", 300)
sm = mod_from(RUNNER, "v2_runner_main2")
se = state(E)
with sm.Stack(E, se, "probe") as s:
    try:
        code, r = sm._post(s.port, f"/api/chat/{se['specialist']['agent_id']}", {"message": "LLM_500 hello", "request_id": "retry-probe"}, 300)
    except Exception as e:
        code, r = None, {"error": repr(e)}
    n500 = sm.get(s.mock["llm"], "/stats")[1].get("failed_500", 0)
check("6a a provider that answers HTTP 500 is asked ONCE by the specialist's worker (no transport retry, no auto-recovery cycle) and the turn ends as a reported failure",
      code == 200 and n500 == 1 and r.get("ok") is False, (code, n500, str(r.get("error"))[:200]))

print(f"\n{sum(results)}/{len(results)} passed", flush=True)
print(f"artifacts kept at: {TMP}")
sys.exit(0 if results and all(results) else 1)
