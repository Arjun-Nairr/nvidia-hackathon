"""Ticket 05 correction tests: the live harness/launcher ARCHIVE behaviour, with SCRIPTED services only (tests/mock_scrapecreators.py, tests/mock_llm.py).
Nothing here is live: no ScrapeCreators request, no CDN download, no subscription model request, no Nebius. It proves that the result a run
produced survives a later failure, and that the throwaway copy is only deleted after the archive verified.
Scenarios (each through scripts/research_live_launch.py --scripted): normal run; exception AFTER the first archive write (injected); exception BEFORE it
(injected, evidence still collected); the process vanishing before anything is written (injected hard exit: nothing to archive -> copy retained);
refusal to start a real run without --live-authorized.
  RESEARCH_ARCHIVE_I_AM_A_COPY=1 venv-python tests/research_archive_test.py"""
import atexit, json, os, shutil, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if os.environ.get("RESEARCH_ARCHIVE_I_AM_A_COPY") != "1":
    sys.exit("Refusing to run: set RESEARCH_ARCHIVE_I_AM_A_COPY=1 and run from a COPY of the project.")
TMP = Path(tempfile.mkdtemp(prefix="arch_"))
SC, MOCK, PORT = 8793, 8776, 8833
KEY = "ARCHIVE-TEST-KEY-SENTINEL-987654"
results, procs = [], []
atexit.register(lambda: [p.terminate() for p in procs if p.poll() is None])


def check(name, ok, detail=""):
    ok = bool(ok); results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{str(detail)[:600]}]"), flush=True)


def wait_up(port, path):
    for _ in range(80):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=3).read(); return
        except Exception:
            time.sleep(0.25)
    raise RuntimeError(f"port {port} did not come up")


ENV = {**os.environ, "PYTHONUTF8": "1", "ECOM_CLASSIFIER": "off", "ECOM_SCRAPECREATORS_URL": f"http://127.0.0.1:{SC}", "ECOM_PHOTO_HOSTS": "127.0.0.1",
       "SCRAPECREATORS_API_KEY": KEY, "ECOM_VISION_MODELS": "nebius-token-factory:mock-model", "RESEARCH_LIVE_PORT": str(PORT)}
for k in ("RESEARCH_LIVE_SCRIPTED", "RESEARCH_LIVE_INJECT_FAIL", "ECOM_APP_ROOT", "HERMES_HOME", "ECOM_CATALOGUE_FILE", "ECOM_EVIDENCE_FILE", "ECOM_IMAGE_DIRS"):
    ENV.pop(k, None)
procs.append(subprocess.Popen([sys.executable, "tests/mock_scrapecreators.py", str(SC)], cwd=ROOT, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
procs.append(subprocess.Popen([sys.executable, "tests/mock_llm.py", str(MOCK)], cwd=ROOT, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
wait_up(SC, "/stats")
wait_up(MOCK, "/stats")


def launch(tag, inject=None, extra=()):
    arch = TMP / f"archive-{tag}"
    work = TMP / f"work-{tag}"
    env = dict(ENV)
    if inject:
        env["RESEARCH_LIVE_INJECT_FAIL"] = inject
    p = subprocess.run([sys.executable, "scripts/research_live_launch.py", "--scripted", "--mock-llm-port", str(MOCK), "--archive-dir", str(arch), "--workdir", str(work), *extra],
                       cwd=ROOT, env=env, capture_output=True, text=True, timeout=900)
    runs = sorted(arch.glob("*")) if arch.exists() else []
    d = runs[0] if runs else None
    out = {"rc": p.returncode, "stdout": p.stdout, "work": work, "dir": d}
    if d:
        out["manifest"] = json.loads((d / "manifest.json").read_text(encoding="utf-8")) if (d / "manifest.json").exists() else None
        out["result"] = json.loads((d / "result.json").read_text(encoding="utf-8")) if (d / "result.json").exists() else None
        out["log"] = (d / "harness.log").read_text(encoding="utf-8", errors="replace") if (d / "harness.log").exists() else ""
        out["all_text"] = "".join(f.read_text(encoding="utf-8", errors="replace") for f in d.iterdir() if f.is_file())
    return out


try:
    # ---- normal run
    r = launch("ok")
    res, man = r.get("result") or {}, r.get("manifest") or {}
    d = res.get("draft") or {}
    check("A1 normal scripted run: exit 0; the archive holds the draft (complete), the research run (calls with outcomes), usage, activity with tool outputs and the checks",
          r["rc"] == 0 and res.get("mode") == "scripted" and res.get("outcome") == "complete" and d.get("status") == "complete" and d.get("evidence_source") == "live_research"
          and [c["kind"] for c in res["run"]["calls"]].count("search") == 2 and res.get("scraper_attempts") == 5 and res.get("photo_downloads") == 2
          and res["activity"] and any(a["tool"] == "marketplace_search" and a["output"] for a in res["activity"]) and res["checks_total"] >= 8
          and res["checks_passed"] == res["checks_total"] and res.get("failure") is None, (r["rc"], res.get("outcome"), res.get("failure"), r["stdout"][-300:]))
    check("A2 the archive is sanitized: no API key, no signed photo URL or query string anywhere in the archived files",
          KEY not in r["all_text"] and "PRIVATE-SIGNED" not in r["all_text"] and "oh=" not in r["all_text"], KEY in r["all_text"])
    check("A3 the throwaway copy was deleted only after the archive verified; the manifest says so and lists file hashes",
          man.get("archive_verified") is True and man.get("copy_deleted") is True and not r["work"].exists() and {"result.json", "harness.log", "timing.jsonl"} <= set(man["files"]), man)

    # ---- exception after the first archive write
    r = launch("after", "after_archive")
    res, man = r.get("result") or {}, r.get("manifest") or {}
    d = res.get("draft") or {}
    check("A4 an exception AFTER the first archive write does not erase it: the archive keeps the draft, run record, usage and activity, and ADDS the failure (stage, type, message)",
          r["rc"] != 0 and d.get("status") == "complete" and res.get("run") and res.get("scraper_attempts") == 5 and res.get("activity")
          and (res.get("failure") or {}).get("type") == "RuntimeError" and "injected failure after" in res["failure"]["message"] and res["failure"]["stage"] == "collect",
          (r["rc"], res.get("failure"), bool(res.get("draft"))))
    check("A5 the failed harness exit code is returned, the harness log keeps the traceback, and the copy is still deleted because the archive verified",
          r["rc"] == man.get("harness_exit") and "injected failure after the archive write" in r["log"] and man.get("archive_verified") is True and not r["work"].exists(), (r["rc"], man))

    # ---- exception before the first archive write: evidence is still collected by the failure handler
    r = launch("before", "before_archive")
    res, man = r.get("result") or {}, r.get("manifest") or {}
    check("A6 an exception BEFORE the first archive write is archived with the failure and the evidence that still existed (draft, run, usage)",
          r["rc"] != 0 and (res.get("failure") or {}).get("message", "").startswith("injected failure before") and (res.get("draft") or {}).get("status") == "complete"
          and res.get("run") and res.get("scraper_attempts") == 5 and man.get("archive_verified") is True, (r["rc"], res.get("failure"), res.get("collect_errors")))

    # ---- the process vanishes before anything is written
    r = launch("hard", "hard_exit")
    man = r.get("manifest") or {}
    check("A7 when the harness dies with NOTHING archived the launcher keeps the copy (exit 3), says so, and keeps the harness log: the copy is not deleted",
          r["rc"] == 3 and man.get("archive_verified") is False and man.get("copy_deleted") is False and r["work"].exists() and man.get("harness_exit") == 9
          and "RETAINED" in r["stdout"] and (r["dir"] / "harness.log").exists() and r.get("result") is None, (r["rc"], man, r["stdout"][-200:]))
    check("A7b the retained copy still holds the database (the run record the first live run lost)", (r["work"] / "runtime" / "app.db").is_file())
    shutil.rmtree(r["work"], ignore_errors=True)

    # ---- real mode needs explicit authorization; nothing is created
    arch = TMP / "archive-refuse"
    p = subprocess.run([sys.executable, "scripts/research_live_launch.py", "--archive-dir", str(arch)], cwd=ROOT, env=ENV, capture_output=True, text=True, timeout=60)
    p2 = subprocess.run([sys.executable, "scripts/research_live_launch.py", "--live-authorized", "--scripted", "--mock-llm-port", "1", "--archive-dir", str(arch)],
                        cwd=ROOT, env=ENV, capture_output=True, text=True, timeout=60)
    check("A8 a run needs exactly one explicit mode: without --live-authorized (and when both modes are given) the launcher refuses and creates nothing",
          p.returncode == 2 and p2.returncode == 2 and not arch.exists(), (p.returncode, p2.returncode))
    # ---- archived stdout logs are sanitized by the launcher (the harness only sanitizes its JSON)
    import importlib.util
    sp = importlib.util.spec_from_file_location("launch", ROOT / "scripts" / "research_live_launch.py")
    lm = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(lm)
    folder = TMP / "scrub"
    folder.mkdir()
    (folder / "harness.log").write_text(f"error talking to provider with key {KEY} and again {KEY}\n", encoding="utf-8")
    (folder / "setup.log").write_text("nothing secret\n", encoding="utf-8")
    lm.scrub_files(folder, [KEY, ""])
    check("A9 the launcher removes the API key value from archived text logs", KEY not in (folder / "harness.log").read_text(encoding="utf-8")
          and "***" in (folder / "harness.log").read_text(encoding="utf-8") and (folder / "setup.log").read_text(encoding="utf-8") == "nothing secret\n")
    # ---- V1 clean demonstration mode: the specialist is created by the (scripted) main agent, the runtime is retained without credentials
    def sc_total():
        return json.loads(urllib.request.urlopen(f"http://127.0.0.1:{SC}/stats", timeout=10).read())["total"]
    r = launch("main", extra=("--via-main", "--scope", "v1-archive-test", "--retain-runtime"))
    res, man = r.get("result") or {}, r.get("manifest") or {}
    sp_ = res.get("specialist") or {}
    by = res.get("model_requests_by_agent") or {}
    check("A10 via-main run: routed to main, main's own create_agent made the one specialist with research + image + catalogue + draft tools and without the recorded-evidence "
          "tool, the specialist then researched and saved a complete live draft; creation and research model requests are counted together",
          r["rc"] == 0 and res.get("via_main") is True and res.get("outcome") == "complete" and (res.get("creation") or {}).get("route", {}).get("outcome") == "classifier_off_test_only"
          and any(t["tool"] == "create_agent" and t["status"] == "ok" for t in res["creation"]["tools"]) and len(sp_.get("agents_after_creation") or []) == 1
          and {"marketplace_locate", "marketplace_search", "marketplace_item", "marketplace_photo", "inspect_image", "read_catalogue", "save_listing_draft"} <= set(sp_.get("granted_tools") or [])
          and "read_recorded_evidence" not in (sp_.get("granted_tools") or []) and "main" in by and sp_["agent_id"] in by
          and res["model_requests_api_start"] == sum(by.values()) <= 16 and (res["draft"] or {}).get("status") == "complete" and res["checks_passed"] == res["checks_total"],
          (r["rc"], res.get("outcome"), by, res.get("failure"), r["stdout"][-300:]))
    rt = man.get("retained_runtime") or {}
    envtxt = (r["work"] / "secrets" / "local.env").read_text(encoding="utf-8") if (r["work"] / "secrets" / "local.env").is_file() else "?"
    check("A10b the verified runtime is RETAINED (database, profile, draft) with the copied login and API keys removed, and the manifest carries the startup command; "
          "the archive is still sanitized",
          man.get("archive_verified") is True and man.get("copy_deleted") is False and (r["work"] / "runtime" / "app.db").is_file() and rt.get("path") == str(r["work"])
          and not list((r["work"] / "runtime" / "hermes_home").rglob("auth.json")) and "KEY" not in envtxt and "LLM_PROVIDER=" in envtxt
          and "app.server 8840" in rt.get("start", "") and KEY not in r["all_text"] and "PRIVATE-SIGNED" not in r["all_text"], (man, envtxt))
    shutil.rmtree(r["work"], ignore_errors=True)

    n1 = sc_total()
    r = launch("nocreate", "no_research_tools", extra=("--via-main",))
    res, man = r.get("result") or {}, r.get("manifest") or {}
    check("A11 when main does NOT create a specialist with the research tools there is no fallback: nothing is researched (no scraper request), the archive says creation_failed with "
          "the creation record, and the failure is archived before the copy is deleted",
          r["rc"] != 0 and res.get("outcome") == "creation_failed" and res.get("run") is None and res.get("draft") is None and sc_total() == n1
          and (res.get("creation") or {}).get("tools") and man.get("archive_verified") is True and not r["work"].exists(), (r["rc"], res.get("outcome"), sc_total() - n1, man))

    # ---- the per-turn iteration caps come from the server's environment only, whole numbers 1-40, else the defaults
    def caps(**e):
        out = subprocess.run([sys.executable, "-c", "from app import core; print(core.CHAT_MAX_ITERATIONS, core.RESEARCH_MAX_ITERATIONS)"], cwd=ROOT,
                             env={**ENV, "ECOM_APP_ROOT": str(TMP / "caps"), **e}, capture_output=True, text=True, timeout=60)
        return out.stdout.strip()
    check("A12 ECOM_CHAT_MAX_ITERATIONS / ECOM_RESEARCH_MAX_ITERATIONS lower the caps (4/10 for the live demonstration); missing, non-numeric or out-of-range values keep 12/14",
          caps(ECOM_CHAT_MAX_ITERATIONS="4", ECOM_RESEARCH_MAX_ITERATIONS="10") == "4 10" and caps() == "12 14"
          and caps(ECOM_CHAT_MAX_ITERATIONS="abc", ECOM_RESEARCH_MAX_ITERATIONS="0") == "12 14" and caps(ECOM_CHAT_MAX_ITERATIONS="99", ECOM_RESEARCH_MAX_ITERATIONS="-3") == "12 14",
          (caps(ECOM_CHAT_MAX_ITERATIONS="4", ECOM_RESEARCH_MAX_ITERATIONS="10"), caps()))
    src = (ROOT / "tests" / "research_live_check.py").read_text(encoding="utf-8")
    check("A12b the live demonstration pins the caps to 4 and 10 iterations: (4+1) + (10+1) = 16 model requests at most across creation and research",
          '("4", "12") if SCRIPTED else ("4", "10")' in src and (4 + 1) + (10 + 1) == 16)
finally:
    for p in procs:
        p.terminate()
    shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{sum(results)}/{len(results)} checks passed (scripted stand-ins only: NOT live)")
sys.exit(0 if results and all(results) else 1)
