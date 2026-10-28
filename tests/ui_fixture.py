"""Isolated server for BROWSER checks of the workspace UI (UI-01). The REAL backend, HTTP API, SQLite registry, Hermes workers and hooks, with the SCRIPTED model tests/mock_llm.py
(a test double, NOT a model; Laya off). No credential, scraper, Gemini or Nebius call. Wipes the copy's runtime/ - run ONLY from a COPY of the project (no secrets/local.env):
  UI_FIXTURE_I_AM_A_COPY=1 venv-python tests/ui_fixture.py <fresh|ready|existing> [port]
fresh: empty installation, onboarding locked.  existing: a business without onboarding (chat open).  ready: onboarding completed through the API, one market analyst and one social specialist created through main's create_agent tool, and (when
UI_FIXTURE_FLYER_FROM names a project's runtime/ folder, read only) that project's saved flyer copied in so the saved-flyer view has a real image. Prints READY and serves until stopped."""
import json, os, shutil, sqlite3, subprocess, sys, time, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if os.environ.get("UI_FIXTURE_I_AM_A_COPY") != "1":
    sys.exit("Refusing to run: set UI_FIXTURE_I_AM_A_COPY=1 and run from a COPY of the project.")
if (ROOT / "secrets" / "local.env").exists():
    sys.exit("Refusing to run: this copy holds secrets/local.env.")
MODE = sys.argv[1] if len(sys.argv) > 1 else "fresh"
APP = int(sys.argv[2]) if len(sys.argv) > 2 else 8841
MOCK = APP - 50
ENV = {**os.environ, "PYTHONUTF8": "1", "ECOM_CLASSIFIER": "off", "ECOM_CHAT_MAX_ITERATIONS": "6", "MOCK_SLOW_S": os.environ.get("MOCK_SLOW_S", "8")}
for k in ("LLM_PROVIDER", "LLM_MODEL", "NEBIUS_API_KEY", "NEBIUS_BASE_URL", "NEBIUS_MODEL", "ECOM_APP_ROOT", "HERMES_HOME", "ECOM_ASSUME_EXISTING_RUNTIME", "LOGBOOK_DATABASE_URL", "NEON_DATABASE_URL"):
    ENV.pop(k, None)   # a shell value of ECOM_ASSUME_EXISTING_RUNTIME would hide the fresh-install lock
if MODE == "existing":   # an installation that already holds a business but never started onboarding (chat open, onboarding optional)
    ENV["ECOM_ASSUME_EXISTING_RUNTIME"] = "1"
procs = []


def call(path, body=None, timeout=300):
    req = urllib.request.Request(f"http://127.0.0.1:{APP}{path}", data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def create(args):
    st, r = call("/api/chat/main", {"message": "CALL_TOOL:" + json.dumps({"name": "create_agent", "args": args}), "request_id": "fixture-" + args["name"].lower().replace(" ", "-")})
    out = [json.loads(t["output"]) for t in r.get("tools", []) if t.get("name") == "create_agent" and t.get("output")]
    assert out and out[0].get("ok"), (st, out)


shutil.rmtree(ROOT / "runtime", ignore_errors=True)
(ROOT / "secrets").mkdir(exist_ok=True)
(ROOT / "secrets" / "local.env").write_text(f"LLM_PROVIDER=nebius-token-factory\nLLM_MODEL=mock-model\nNEBIUS_API_KEY=mock-key\nNEBIUS_BASE_URL=http://127.0.0.1:{MOCK}/v1\n", encoding="utf-8")
subprocess.run([sys.executable, "scripts/setup.py"], cwd=ROOT, env=ENV, check=True, capture_output=True)
src = os.environ.get("UI_FIXTURE_FLYER_FROM")
FLYER = "fly-6d6f2af62c"
if MODE == "ready" and src:   # make the flyer tables exist in the copy before they are filled
    subprocess.run([sys.executable, "-c", "from app import flyer; flyer.list_flyers()"], cwd=ROOT, env=ENV, check=True, capture_output=True)
procs.append(subprocess.Popen([sys.executable, "tests/mock_llm.py", str(MOCK)], cwd=ROOT, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
time.sleep(1)
CASE = {"name": "Northloom Demo Studio", "products": "The Chintz Applique Quilt (demonstration catalogue; not a real retail range).", "customers": "Traditional textile collectors",
        "goal": "Draft one Marketplace listing and produce one labelled demonstration flyer.", "brand": "Calm, factual and plain-spoken."}
try:
    procs.append(subprocess.Popen([sys.executable, "-m", "app.server", str(APP)], cwd=ROOT, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    for _ in range(80):
        try:
            call("/api/status", timeout=5)
            break
        except Exception:
            time.sleep(0.5)
    if MODE == "ready":
        call("/api/onboarding/start", {})
        call("/api/onboarding/source", {"url": "https://northloom-demo.example.com"})
        st, o = call("/api/onboarding")
        ans = {q["id"]: ({"choice": 0} if q["topic"] != "goal" else {"write_in": CASE["goal"]}) for q in o["questions"]}
        st, r = call("/api/onboarding/answers", {"answers": ans, "correction": "Synthetic operator answers for a UI fixture."})
        assert r.get("ok"), r
        create({"role": "market_analysis", "name": "Northloom Market Analyst", "objective": "Research comparable quilt listings and draft one evidence-backed Marketplace listing for the Chintz Applique Quilt.",
                "instructions": "You analyse comparable listings for Northloom Demo Studio. Use only the company context, the catalogue and evidence you actually retrieved; label assumptions; never invent prices.",
                "requested_tools": ["marketplace_locate", "marketplace_search", "marketplace_item", "marketplace_photo", "inspect_image", "read_catalogue", "save_listing_draft"],
                "company_context_refs": ["products", "customers", "goal"]})
        if src:
            create({"role": "social_media", "name": "Northloom Social Specialist", "objective": "Produce one accurate, clearly labelled demonstration flyer for Northloom Demo Studio from the supplied catalogue facts and photographs.",
                    "instructions": "Use only the catalogue facts and the supplied photographs. Never invent a fact.", "requested_tools": ["read_catalogue", "inspect_image", "fb_ads_search", "fb_ad_detail", "fb_ad_image", "save_ad_research", "generate_flyer", "inspect_flyer", "review_flyer", "finalize_flyer"],
                    "company_context_refs": ["brand", "products", "goal"]})
            sdb = sqlite3.connect(f"file:{Path(src) / 'app.db'}?mode=ro", uri=True)
            sdb.row_factory = sqlite3.Row
            ddb = sqlite3.connect(ROOT / "runtime" / "app.db")
            for t in ("flyer_runs", "flyer_attempts", "flyer_reviews"):
                for r in sdb.execute(f"SELECT * FROM {t} WHERE run_id=?", (FLYER,)):
                    r = dict(r)
                    if "agent_id" in r:
                        r["agent_id"] = "northloom-social-specialist"
                    ddb.execute(f"INSERT OR REPLACE INTO {t}({','.join(r)}) VALUES({','.join('?' * len(r))})", tuple(r.values()))
            ddb.commit()
            ddb.close()
            sdb.close()
            shutil.copytree(Path(src) / "flyers" / FLYER, ROOT / "runtime" / "flyers" / FLYER, dirs_exist_ok=True)
    print(f"READY {MODE} http://127.0.0.1:{APP}", flush=True)
    while True:
        time.sleep(3600)
finally:
    for p in procs:
        if p.poll() is None:
            p.terminate()
