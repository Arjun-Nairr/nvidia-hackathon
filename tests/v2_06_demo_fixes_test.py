"""Regression tests for the five findings of research/v2-ticket06-offline-runner-review-20261016.md, against the scripted stand-ins ONLY (dummy credentials,
synthetic placeholder inputs, no provider, no login). Nothing here is live evidence. Run with the Hermes interpreter from the project root:
    python tests/v2_06_demo_fixes_test.py [F1 F2 F3 F4 F5 ...]      (default: all)
Demo copies, archives and logs are kept under .scratch/v206-fix-<stamp>/ (ignored). Scenario sections are independent; one failing section never stops the others."""
import json, os, shutil, sqlite3, subprocess, sys, time, importlib.util
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent.parent
RUNNER = ROOT / "scripts" / "v2_06_demo.py"
TMP = ROOT / ".scratch" / f"v206-fix-{time.strftime('%Y%m%dT%H%M%S')}"
TMP.mkdir(parents=True)
RED, GREEN = [210, 40, 40], [40, 170, 80]
DUMMY_OAUTH = {"providers": {"openai-codex": {"tokens": {"access_token": "DUMMY-OAUTH-ACCESS-TOKEN-0001-NOT-REAL", "refresh_token": "DUMMY-OAUTH-REFRESH-TOKEN-0002-NOT-REAL"},
                                               "last_refresh": "2026-10-16T00:00:00Z", "auth_mode": "chatgpt"}}, "active_provider": "openai-codex"}
results = []
WANT = set(sys.argv[1:])


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"\n     -> {str(detail)[:900]}"), flush=True)


def runner(*args, timeout=1200, env=None):
    base = {k: v for k, v in os.environ.items() if not any(s in k.upper() for s in ("KEY", "TOKEN", "SECRET", "ECOM_", "HERMES_", "LLM_", "NEBIUS", "GEMINI", "SCRAPE"))}
    r = subprocess.run([sys.executable, str(RUNNER), *map(str, args)], capture_output=True, text=True, timeout=timeout, env=base | {"PYTHONUTF8": "1"} | (env or {}))
    return r.returncode, r.stdout + r.stderr


def state(d):
    return json.loads((Path(d) / "runner_state.json").read_text(encoding="utf-8"))


def phase(d, name):
    return state(d)["phases"].get(name) or {}


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


def swap(obj, a, b):
    if isinstance(obj, dict):
        return {k: swap(v, a, b) for k, v in obj.items()}
    if isinstance(obj, list):
        return [swap(v, a, b) for v in obj]
    return obj.replace(a, b) if isinstance(obj, str) else obj


def clone(src, name):
    """Copy a prepared/provisioned demo directory and re-point the absolute paths in its state at the copy."""
    dst = TMP / name
    shutil.copytree(src, dst)
    p = dst / "runner_state.json"
    p.write_text(json.dumps(swap(json.loads(p.read_text(encoding="utf-8")), str(Path(src)), str(dst)), indent=1), encoding="utf-8")
    return dst


def owned(d):
    """Live processes whose working directory is inside the demo directory (its servers, stand-ins and Hermes workers)."""
    out, d = [], Path(d).resolve()
    for p in psutil.process_iter(["pid", "name"]):
        try:
            if Path(p.cwd()).resolve().is_relative_to(d):
                out.append(p)
        except (psutil.Error, OSError, ValueError):
            pass
    return out


def reap(d):
    for p in owned(d):
        try:
            p.kill()
        except psutil.Error:
            pass
    time.sleep(1)


def section(name):
    def deco(fn):
        if WANT and name not in WANT:
            return fn
        print(f"== {name}: {fn.__doc__}", flush=True)
        try:
            fn()
        except Exception:   # a crashed section is a failed check, never a silent skip
            import traceback
            check(f"{name} section ran to the end", False, traceback.format_exc()[-700:])
        return fn
    return deco


# ---------------------------------------------------------------- shared bases (built once, cloned per scenario)
X0 = TMP / "X0"
rc, out = runner("prepare", "--dir", X0, "--mode", "scripted")
assert rc == 0, out
EXT = TMP / "external-originals"          # stands in for the merchant's private folder: supplied from OUTSIDE the demo copy
shutil.copytree(X0 / "inputs", EXT)
V = TMP / "V"                             # prepared from external originals and provisioned
rc, out = runner("prepare", "--dir", V, "--mode", "scripted", "--catalogue", EXT / "catalogue.json", "--images", EXT / "images")
assert rc == 0, out
rc, out = runner("provision", "--dir", V, "--turn-timeout", 300)
assert rc == 0 and state(V).get("specialist"), out
print("bases ready", flush=True)


def strip_vision(d):
    """Make the specialist's model text-only (drop the per-model vision flag its profile config carries), so image delivery to the reviewer cannot be confirmed."""
    import yaml
    f = Path(d) / "runtime" / "hermes_home" / "profiles" / state(d)["specialist"]["agent_id"] / "config.yaml"
    c = yaml.safe_load(f.read_text(encoding="utf-8"))
    c.pop("providers", None)
    f.write_text(yaml.safe_dump(c), encoding="utf-8")


def probe_in(name, opts, extra=()):
    d = clone(V, name)
    if opts.get("vision") is False:
        strip_vision(d)
    rc, out = runner("probe", "--dir", d, "--turn-timeout", 600, "--scripted-opts", json.dumps(opts), *extra)
    return d, rc, out


# ======================================================================= F1
@section("F1")
def f1():
    """probe/demo completion rests on authoritative artifacts and verified review, not on chat success"""
    bad = {"no flyer (explanatory reply only)": {"message": "Hello, please just say hi."},
           "generation failed": {"gem_mode": "refuse"},
           "generation unknown (connection dropped)": {"gem_mode": "drop"},
           "review missing (blind review refused)": {"markers": ["REVIEW_BLIND"]},
           "review unverified (pixels never delivered)": {"vision": False}}
    for label, opts in bad.items():
        d, rc, out = probe_in("F1-" + label.split()[0] + str(len(label)), opts)
        pr = phase(d, "probe")
        rc2, out2 = runner("demo", "--dir", d, "--approve-demo")
        check(f"F1 probe with {label}: chat succeeded but the phase is NOT completed, exits nonzero and the demonstration stays locked",
              pr.get("status") not in ("completed", None) and rc != 0 and rc2 == 2 and "needs a completed probe" in out2, (pr.get("status"), rc, (pr.get("outcome") or {}).get("problems"), out2[-200:]))
        check(f"F1 probe with {label}: the partial evidence is preserved (reply, activity, ledgers) with the blocking reason recorded",
              pr.get("activity") is not None and pr.get("ledgers_after") is not None and (pr.get("outcome") or {}).get("problems"), pr.get("outcome"))
    d, rc, out = probe_in("F1-negative", {"colors": [RED]})
    pr = phase(d, "probe")
    oc = pr.get("outcome") or {}
    check("F1 a technically valid probe whose VERIFIED review reports a content defect is a completed probe (honest negative verdict, no correction, no final)",
          rc == 0 and pr.get("status") == "completed" and oc.get("technical_ok") is True and oc.get("review_verified") is True and oc.get("review_verdict") == "defects_found"
          and oc.get("flyer_status") == "unresolved_issues" and not oc.get("final_selected"), (rc, pr.get("status"), oc, out[-300:]))
    P = clone(V, "F1-P")
    rc, out = runner("probe", "--dir", P, "--turn-timeout", 600)
    check("F1 the normal probe is completed with an outcome bound to the specialist, the request id, the probe scope and a delivery-verified review",
          rc == 0 and (phase(P, "probe").get("outcome") or {}).get("technical_ok") is True and (phase(P, "probe").get("outcome") or {}).get("request_id") == phase(P, "probe").get("request_id")
          and (phase(P, "probe").get("outcome") or {}).get("scope") == state(P)["scopes"]["probe"]["flyer"], (rc, phase(P, "probe").get("outcome"), out[-300:]))
    cases = {"ok": ({"colors": [RED, GREEN]}, True), "no research evidence": ({"markers": ["SKIP_ADS"]}, False), "no final selection": ({"markers": ["NO_FINALIZE"]}, False),
             "unresolved issues (both candidates defective)": ({"colors": [RED, RED]}, True)}
    for label, (opts, good) in cases.items():
        d = clone(P, "F1-D" + str(len(label)))
        rc, out = runner("demo", "--dir", d, "--approve-demo", "--turn-timeout", 900, "--scripted-opts", json.dumps(opts))
        de = phase(d, "demo")
        oc = de.get("outcome") or {}
        if good:
            ok = rc == 0 and de.get("status") == "completed" and oc.get("technical_ok") is True and oc.get("final_selected") is True and oc.get("ad_package_id") and oc.get("review_verified")
            if "unresolved" in label:
                ok = ok and oc.get("flyer_status") == "unresolved_issues" and oc.get("review_verdict") == "defects_found"   # honest, never turned into a pass
        else:
            ok = rc != 0 and de.get("status") not in ("completed", None) and (oc.get("problems") or [])
        check(f"F1 demonstration, {label}: {'completed with honest status' if good else 'incomplete (nonzero, reason recorded)'}", ok, (rc, de.get("status"), oc, out[-300:]))
    globals()["F1_DEMO_OK"] = clone(P, "F1-demo-ok-base")


# ======================================================================= F2
@section("F2")
def f2():
    """teardown stops and waits for every process this demo owns, and an unconfirmed shutdown is reported"""
    T = clone(V, "F2-T")
    rc, out = runner("probe", "--dir", T, "--turn-timeout", 3, "--settle", 0, "--scripted-opts", json.dumps({"markers": ["SLOW"]}))
    surv = [(p.pid, p.name()) for p in owned(T)]
    sig0 = (db(T, "SELECT (SELECT COUNT(*) FROM messages),(SELECT COUNT(*) FROM flyer_attempts),(SELECT COUNT(*) FROM ad_calls)"), (T / "runtime" / "app.db").stat().st_mtime_ns)
    check("F2 a deliberately blocked turn with zero settle time: after the runner exits NO process owned by the demo (server, worker, stand-in) is alive",
          rc == 3 and not surv, (rc, surv, out[-200:]))
    time.sleep(32)   # longer than the stand-in's 25 s hold: a surviving worker would act (or write) now
    sig1 = (db(T, "SELECT (SELECT COUNT(*) FROM messages),(SELECT COUNT(*) FROM flyer_attempts),(SELECT COUNT(*) FROM ad_calls)"), (T / "runtime" / "app.db").stat().st_mtime_ns)
    check("F2 after confirmed teardown nothing dispatches locally and the database is not modified again",
          sig0 == sig1 and not owned(T), (sig0, sig1))
    pr = phase(T, "probe")
    check("F2 the unknown completion is preserved (one POST, status unknown_completion, no flyer consumed) and the teardown is recorded as confirmed",
          pr.get("status") == "unknown_completion" and pr.get("posts") == 1 and (state(T).get("teardown") or {}).get("probe", {}).get("confirmed") is True, (pr.get("status"), state(T).get("teardown")))
    reap(T)
    U = clone(V, "F2-U")
    sm = mod_from(RUNNER, "v2_fix_runner_f2")
    stubborn = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"], cwd=U)
    try:
        had = hasattr(sm, "teardown_owned")
        orig = getattr(sm, "_stop", None)
        sm._stop = lambda proc, force=False: None   # a process that cannot be stopped
        res = sm.teardown_owned([], U, grace=2) if had else {}
        sm._stop = orig
        mine = {stubborn.pid, *[c.pid for c in psutil.Process(stubborn.pid).children(recursive=True)]}
        check("F2 an owned process that cannot be stopped is reported as a survivor and the shutdown is NOT confirmed",
              had and res.get("confirmed") is False and any(s.get("pid") in mine for s in res.get("survivors", [])), res)
        st = state(U)
        sm._stop = lambda proc, force=False: None
        with sm.Stack(U, st, "archive", inert=True):
            pass
        sm._stop = orig
        stateu = state(U)
        reap(U)
        rc, out = runner("archive", "--dir", U)
        man = json.loads((Path(state(U).get("archive_dir", TMP / "none")) / "manifest.json").read_text(encoding="utf-8")) if state(U).get("archive_dir") else {}
        rc2, out2 = runner("retrieve", "--dir", U)
        check("F2 an unconfirmed teardown makes the archive refuse to claim a stable snapshot (status unstable_snapshot, manifest says so) and retrieval is refused",
              stateu.get("unstable_teardown") is True and phase(U, "archive").get("status") == "unstable_snapshot" and rc == 3 and man.get("stable_snapshot") is False
              and rc2 == 2, (stateu.get("unstable_teardown"), phase(U, "archive").get("status"), rc, man.get("stable_snapshot"), rc2, out[-900:], out2[-200:]))
    finally:
        stubborn.kill()
        reap(U)


# ======================================================================= F3
@section("F3")
def f3():
    """one invocation owns a demo directory at a time; the lock is released after success and failure"""
    L = TMP / "F3-L"
    rc, out = runner("prepare", "--dir", L, "--mode", "scripted")
    sm = mod_from(RUNNER, "v2_fix_runner_f3")
    unit = hasattr(sm, "claim")
    second = None
    released = None
    if unit:
        with sm.claim(L):
            try:
                with sm.claim(L):
                    second = "acquired"
            except sm.Refused as e:
                second = str(e)
        try:
            with sm.claim(L):
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        try:
            with sm.claim(L):
                released = True
        except sm.Refused:
            released = False
    check("F3 a second claim on a held demo directory is refused explicitly, and the lock is released after an exception", unit and second not in (None, "acquired") and "another" in second and released is True, (unit, second, released))
    env = {"V2_06_TEST_LOAD_DELAY": "5"}   # both invocations read the state before either starts: the stale-reader window
    a = subprocess.Popen([sys.executable, str(RUNNER), "provision", "--dir", str(L), "--turn-timeout", "300"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         env={**{k: v for k, v in os.environ.items() if not any(s in k.upper() for s in ("KEY", "TOKEN", "SECRET", "ECOM_", "HERMES_"))}, "PYTHONUTF8": "1", **env})
    b = subprocess.Popen([sys.executable, str(RUNNER), "provision", "--dir", str(L), "--turn-timeout", "300"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         env={**{k: v for k, v in os.environ.items() if not any(s in k.upper() for s in ("KEY", "TOKEN", "SECRET", "ECOM_", "HERMES_"))}, "PYTHONUTF8": "1", **env})
    oa, ob = a.communicate(timeout=600)[0], b.communicate(timeout=600)[0]
    rcs = sorted([a.returncode, b.returncode])
    refusal = oa if a.returncode == 2 else ob
    users = db(L, "SELECT COUNT(*) FROM messages WHERE agent_id='main' AND who='user'")[0][0]
    agents = db(L, "SELECT COUNT(*) FROM agents")[0][0]
    check("F3 two simultaneous invocations of the same phase: exactly one accepted and one explicit refusal ('another invocation'), one main message, one specialist, intact state",
          rcs == [0, 2] and "another invocation" in refusal and users == 1 and agents == 1 and phase(L, "provision").get("posts") == 1 and phase(L, "provision").get("status") == "completed",
          (rcs, refusal[-250:], users, agents, phase(L, "provision")))
    rc, out = runner("provision", "--dir", L)
    check("F3 after the accepted invocation ended the lock is free: the next invocation gets the normal 'already attempted' refusal, not a lock error", rc == 2 and "already attempted" in out, out[-250:])
    check("F3 the state file is intact JSON and no temporary state file is left behind", state(L)["phases"]["provision"]["status"] == "completed" and not list(L.glob("*.tmp")), list(L.iterdir()))


# ======================================================================= F4
@section("F4")
def f4():
    """the merchant inputs actually used are preserved and validated against the generation records"""
    base = globals().get("F1_DEMO_OK")
    if base is None:
        P = clone(V, "F4-P")
        runner("probe", "--dir", P, "--turn-timeout", 600)
        base = clone(P, "F4-base")
    rc, out = runner("demo", "--dir", base, "--approve-demo", "--turn-timeout", 900, "--scripted-opts", json.dumps({"colors": [RED, GREEN]}))
    assert rc == 0, out
    # changed BEFORE archiving: an explicit mismatch, never a claim of preserved originals
    chg = clone(base, "F4-changed")
    sti = state(chg)["inputs"]
    img = next(Path(sti["images"]).glob("hw-front.*"))
    original_bytes = img.read_bytes()
    from PIL import Image
    Image.new("RGB", (600, 800), (1, 2, 3)).save(img, "PNG")
    new_sha = __import__("hashlib").sha256(img.read_bytes()).hexdigest()
    rc, out = runner("archive", "--dir", chg)
    arch = Path(state(chg).get("archive_dir", TMP / "none"))
    chk = json.loads((arch / "inputs_check.json").read_text(encoding="utf-8")) if (arch / "inputs_check.json").is_file() else {}
    archived_front = [f for f in (arch / "inputs").rglob("hw-front*") if f.is_file()] if (arch / "inputs").is_dir() else []
    check("F4 inputs changed before archiving: the archive is NOT claimed complete (nonzero), the mismatch names the image with recorded and current hashes",
          rc == 3 and phase(chg, "archive").get("status") == "inputs_mismatch" and (chk.get("images", {}).get("hw-front") or {}).get("state") == "mismatch"
          and (chk.get("images", {}).get("hw-front") or {}).get("current_sha256") == new_sha, (rc, phase(chg, "archive").get("status"), chk.get("images")))
    check("F4 the replacement file is not archived under the original generation's identity (no hw-front file whose hash is the replacement's)",
          all(__import__("hashlib").sha256(f.read_bytes()).hexdigest() != new_sha for f in archived_front), [str(f) for f in archived_front])
    check("F4 the mismatched archive still carries the other evidence (flyer detail, images, transcripts) and the unaffected catalogue/photo are preserved and verified",
          (arch / "manifest.json").is_file() and any(arch.glob("flyers/fly-*.json")) and (chk.get("catalogue") or {}).get("state") == "match"
          and (chk.get("images", {}).get("hw-detail") or {}).get("state") == "match", chk)
    img.write_bytes(original_bytes)
    # originals moved AFTER the demonstration: the archive is still inspectable
    moved = clone(base, "F4-moved")
    stm = state(moved)["inputs"]
    ext_present = Path(stm["images"]).resolve().is_relative_to(moved.resolve())
    if EXT.exists():
        shutil.move(str(EXT), str(EXT) + "-moved")
    rc, out = runner("archive", "--dir", moved)
    arch2 = Path(state(moved).get("archive_dir", TMP / "none"))
    chk2 = json.loads((arch2 / "inputs_check.json").read_text(encoding="utf-8")) if (arch2 / "inputs_check.json").is_file() else {}
    cat_a = arch2 / "inputs" / "catalogue.json"
    ok_imgs = {k: v for k, v in (chk2.get("images") or {}).items()}
    check("F4 external originals moved away after the demonstration: archive completes; catalogue (with provenance) and every used photo are in the archive with hashes equal to the generation records",
          rc == 0 and phase(moved, "archive").get("status") == "completed" and cat_a.is_file() and ok_imgs and all(v.get("state") == "match" for v in ok_imgs.values())
          and (chk2.get("catalogue") or {}).get("state") == "match" and all(any((arch2 / "inputs" / "images").glob(f"{k}.*")) for k in ok_imgs), (rc, ext_present, chk2, out[-300:]))
    man = json.loads((arch2 / "manifest.json").read_text(encoding="utf-8")) if (arch2 / "manifest.json").is_file() else {"files": {}}
    prov = json.loads(cat_a.read_text(encoding="utf-8")) if cat_a.is_file() else {}
    check("F4 the archived catalogue is the exact bytes the generation recorded and the archive's manifest hashes cover the inputs",
          cat_a.is_file() and any(r.startswith("inputs/") for r in man["files"]) and prov.get("merchant", {}).get("name") == "Harbor Textiles"
          and "Harbor Textiles" in cat_a.read_text(encoding="utf-8"), list(man["files"])[:12])
    if Path(str(EXT) + "-moved").exists():
        shutil.move(str(EXT) + "-moved", str(EXT))
    globals()["F4_ARCHIVED"] = moved


# ======================================================================= F5
@section("F5")
def f5():
    """restart retrieval runs where no inference credential (API key or OAuth) is accessible"""
    base = globals().get("F4_ARCHIVED")
    if base is None:
        P = clone(V, "F5-P")
        runner("probe", "--dir", P, "--turn-timeout", 600)
        runner("demo", "--dir", P, "--approve-demo", "--turn-timeout", 900, "--scripted-opts", json.dumps({"colors": [RED, GREEN]}))
        runner("archive", "--dir", P)
        base = P
    R = clone(base, "F5-R")
    # a demo with a dummy OAuth login and API keys back in place, configured for the OAuth provider (retrieval does no inference either way)
    (R / "runtime" / "hermes_home" / "auth.json").write_text(json.dumps(DUMMY_OAUTH), encoding="utf-8")
    (R / "runtime" / "hermes_home" / "profiles" / "main").mkdir(parents=True, exist_ok=True)
    (R / "runtime" / "hermes_home" / "profiles" / "main" / "auth.json").write_text(json.dumps(DUMMY_OAUTH), encoding="utf-8")
    (R / "secrets" / "local.env").write_text("LLM_PROVIDER=openai-codex\nLLM_MODEL=gpt-5.6-terra\nGEMINI_API_KEY=TEST-GEMINI-KEY-SENTINEL\nSCRAPECREATORS_API_KEY=TEST-SCRAPE-KEY-SENTINEL\n", encoding="ascii")
    sm = mod_from(RUNNER, "v2_fix_runner_f5")
    sv = sm.secret_values(R)
    check("F5 the credential scan covers the demo's OAuth tokens as well as API keys", "DUMMY-OAUTH-ACCESS-TOKEN-0001-NOT-REAL" in sv and "DUMMY-OAUTH-REFRESH-TOKEN-0002-NOT-REAL" in sv and "TEST-GEMINI-KEY-SENTINEL" in sv, sv)
    sig_before = db(R, "SELECT (SELECT COUNT(*) FROM flyer_attempts),(SELECT COUNT(*) FROM flyer_reviews),(SELECT COUNT(*) FROM ad_calls),(SELECT COALESCE(SUM(attempts_used),0) FROM flyer_allowance)")
    auth_before = [(p, p.read_bytes()) for p in (R / "runtime" / "hermes_home").rglob("auth.json")]
    rc, out = runner("retrieve", "--dir", R)
    rt = phase(R, "retrieve")
    rv = rt.get("retrieval") or {}
    root = Path(rv.get("root", TMP / "none"))
    inv_files = [str(p) for p in root.rglob("*") if p.is_file() and (p.name == "auth.json" or "token" in p.name.lower())] if root.is_dir() else ["no retrieval root recorded"]
    blob = b"".join(p.read_bytes() for p in root.rglob("*") if p.is_file() and p.suffix in (".json", ".env", ".yaml", ".md", ".txt", ".log", ".db", "")) if root.is_dir() else b""
    check("F5 retrieval runs from an isolated copy that holds NO auth file and none of the demo's key or OAuth values (searched byte for byte)",
          rc == 0 and root.is_dir() and root.resolve() != R.resolve() and not inv_files and not any(s.encode() in blob for s in sv), (rc, str(root), inv_files[:5], out[-300:]))
    check("F5 the application's own provider-readiness check, asked INSIDE the retrieval process, reports inference unusable (OAuth not signed in), and no inference credential reached its environment",
          rv.get("provider_unusable") is True and rv.get("provider_problem") and rv.get("env_has_inference_credentials") is False, rv)
    check("F5 zero new provider requests (reasoning, Gemini, scraper) while retrieving, and the demo's dispatch records and ledgers are unchanged",
          not any((rt.get("provider_requests_during_retrieval") or {"x": 1}).values()) and sig_before == db(R, "SELECT (SELECT COUNT(*) FROM flyer_attempts),(SELECT COUNT(*) FROM flyer_reviews),(SELECT COUNT(*) FROM ad_calls),(SELECT COALESCE(SUM(attempts_used),0) FROM flyer_allowance)")
          and rt.get("problems") == [], (rt.get("provider_requests_during_retrieval"), rt.get("problems")))
    check("F5 the demo's own OAuth files were neither altered nor deleted by retrieval (and the runner never touched the real project's login)",
          all(p.is_file() and p.read_bytes() == b for p, b in auth_before) and auth_before, [str(p) for p, _ in auth_before])
    check("F5 final image and flyer data served after the restart match the archived hashes", rt.get("status") == "completed" and rv.get("images_verified", 0) >= 1, (rt.get("status"), rv))


# ======================================================================= F6 (adjacent): a crash is recorded; only the read-only phases may be repeated
@section("F6")
def f6():
    """a crashed phase is recorded as crashed; a crashed READ-ONLY phase may be repeated, a crashed paid phase never"""
    X = clone(V, "F6-X")
    sm = mod_from(RUNNER, "v2_fix_runner_f6")
    real_get = sm.get

    def flaky(port, path, raw=False, tries=5):
        if path == "/api/company":
            raise OSError("simulated persistent read failure")
        return real_get(port, path, raw=raw, tries=tries)
    sm.get = flaky
    rc = sm.main(["archive", "--dir", str(X)])
    sm.get = real_get
    ph = phase(X, "archive")
    check("F6 an archive that crashes on a read failure is recorded as crashed (exit 1), not left as 'started'", rc == 1 and ph.get("status") == "crashed" and "OSError" in (ph.get("error") or ""), (rc, ph))
    rc2, out2 = runner("archive", "--dir", X)
    ph2 = phase(X, "archive")
    check("F6 the read-only archive may be repeated after a crash (it sends nothing to any provider) and keeps a record of the earlier attempt",
          rc2 == 0 and ph2.get("status") == "completed" and (ph2.get("earlier_attempts") or [{}])[0].get("status") == "crashed", (rc2, ph2.get("status"), ph2.get("earlier_attempts"), out2[-200:]))
    W = clone(V, "F6-W")
    calls = []
    orig_wait = sm.Stack._wait

    def stall_once(self, port, path, tries=120):
        calls.append(port)
        if len(calls) == 1:
            raise RuntimeError(f"service on port {port} did not start within the bound")
        return orig_wait(self, port, path, tries)
    sm.Stack._wait = stall_once
    try:
        with sm.Stack(W, state(W), "archive", inert=True) as s:
            retries, answered = s.start_retries, sm.get(s.port, "/api/status")[0]
    finally:
        sm.Stack._wait = orig_wait
    check("F6 a local start-up stall before anything was sent is retried ONCE on fresh ports (recorded), the first stack is torn down, and the second serves",
          retries == 1 and answered == 200 and not owned(W) and (state(W).get("teardown") or {}).get("archive", {}).get("start_retries") == 1, (retries, answered, [p.pid for p in owned(W)]))
    Y = clone(V, "F6-Y")
    sty = state(Y)
    sty["phases"]["probe"] = {"status": "crashed", "started": "x"}
    (Y / "runner_state.json").write_text(json.dumps(sty), encoding="utf-8")
    rc3, out3 = runner("probe", "--dir", Y)
    check("F6 a crashed PAID phase is never repeated", rc3 == 2 and "already attempted" in out3, out3[-200:])


print(f"\n{sum(results)}/{len(results)} passed", flush=True)
print(f"artifacts kept at: {TMP}")
sys.exit(0 if results and all(results) else 1)
