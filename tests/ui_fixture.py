"""Isolated server for BROWSER checks of the workspace UI (UI-01). The REAL backend, HTTP API, SQLite registry, Hermes workers and hooks, with the SCRIPTED model tests/mock_llm.py
(a test double, NOT a model; Laya off). No credential, scraper, Gemini or Nebius call. Wipes the copy's runtime/ - run ONLY from a COPY of the project (no secrets/local.env):
  UI_FIXTURE_I_AM_A_COPY=1 venv-python tests/ui_fixture.py <fresh|ready|existing|results> [port]
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
if MODE in ("ready", "results") and src:   # make the flyer tables exist in the copy before they are filled
    subprocess.run([sys.executable, "-c", "from app import flyer; flyer.list_flyers()"], cwd=ROOT, env=ENV, check=True, capture_output=True)
procs.append(subprocess.Popen([sys.executable, "tests/mock_llm.py", str(MOCK)], cwd=ROOT, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
time.sleep(1)
def seed_results(src):
    """Mode 'results': saved results with BACKEND identities in the shapes the real tools store (rows written with SQL; no tool, model, provider or paid call). The licensed flyer image is copied
    READ-ONLY from the project runtime named by UI_FIXTURE_FLYER_FROM. Layout of the history (analyst A, social S):
      A: u1 -> reply + draft D1 (research run, hostile link/markup); u2 -> reply + PARTIAL draft D2 (direct identity); a LEGACY draft with no identity; u3 -> error reply with NO saved result;
         a long legacy reply (disclosure).
      S: u4 -> error reply with an ad-research package AND a failed flyer (partial work plus failure); u5 -> reply with the real flyer (agent review passed); u6 -> reply with a flyer that has
         unresolved issues; a LEGACY flyer with no identity."""
    db = sqlite3.connect(ROOT / "runtime" / "app.db")
    db.row_factory = sqlite3.Row
    t = time.time() - 3000

    def msg(agent, who, content, dt):
        return db.execute("INSERT INTO messages(agent_id,who,content,tools,ts) VALUES(?,?,?,?,?)", (agent, who, content, "[]", t + dt)).lastrowid

    A, S = "northloom-market-analyst", "northloom-social-specialist"
    sha = "b" * 64
    u1 = msg(A, "user", "Research comparable quilt listings and save one draft.", 1)
    msg(A, "agent", "I saved one listing draft built from two comparable Dallas listings. Next step: check the asking prices in the sources before you set yours.", 2)
    u2 = msg(A, "user", "Make a tighter second draft.", 3)
    msg(A, "agent", "The second draft is partial: only one comparable had full details. Add a second search if you want a fuller comparison.", 4)
    u3 = msg(A, "user", "Compare against sold prices.", 5)
    msg(A, "error", "[error] Backend error while running the turn: no sold-price source is connected.", 6)
    long = " ".join(f"Point {i}: the earlier version of this agent wrote a long reply with several observations, caveats and recommendations that are kept intact." for i in range(1, 17))
    msg(A, "agent", long, 7)
    u4 = msg(S, "user", "Research Facebook ads and make a flyer.", 8)
    msg(S, "error", "[error] The flyer attempt failed: provider error HTTP 500. The ad research was saved; nothing was generated again.", 9)
    u5 = msg(S, "user", "Make the flyer from the catalogue photos.", 10)
    msg(S, "agent", "The flyer is saved. The automated review passed, but it can miss problems, so look at the image yourself.", 11)
    u6 = msg(S, "user", "Try a variant with the detail photo.", 12)
    msg(S, "agent", "The variant has one unresolved layout issue, so treat it as an unapproved draft.", 13)
    listing_ev = [{"listing_id": "111", "title": "Antique <b>quilt</b> <img src=x onerror=alert(1)>", "price": {"amount": 75, "currency": "USD", "formatted": "$75"}, "condition": "used_good", "location": "Lakeside, TX",
                   "detail_level": "detailed", "source_url": "https://www.facebook.com/marketplace/item/111/", "seller_ref": "seller_1"},
                  {"listing_id": "222", "title": "Hostile link", "price": None, "condition": None, "location": None, "detail_level": "detailed", "source_url": "javascript:alert(document.cookie)", "seller_ref": "seller_2"},
                  {"listing_id": "333", "title": "Second listing", "price": {"amount": 170, "currency": "USD", "formatted": "$170"}, "condition": "used_good", "location": "Dallas, TX", "detail_level": "detailed",
                   "source_url": "https://www.facebook.com/marketplace/item/333/", "seller_ref": "seller_3"}]
    img_ev = [{"image_id": "111", "kind": "live_listing_photo", "listing_id": "111", "sha256": sha, "model_observations": "A quilt laid flat with appliqued bonneted figures.", "counts_as_verified_evidence": True}]
    cols = "(draft_id, agent_id, conversation_id, product_id, status, title, description, visual_brief, rationale, limitations, missing, merchant_snapshot, product_snapshot, listing_evidence, image_evidence, created_at, evidence_source, research_run_id, request_id, message_id)"

    def draft(did, title, status, req, mid, run, missing, dt):
        db.execute(f"INSERT INTO listing_drafts{cols} VALUES({','.join('?' * 20)})", (did, A, "conv-" + A, "chintz-applique-quilt-demo", status, title,
                   "Demonstration listing for a Chintz Applique Quilt: cotton, 158.8 x 174 cm, ca. 1820-30. The USD 79 amount is a demonstration value. <script>alert('x')</script>",
                   "Lead with the full front view; use the close-up for the motifs.", json.dumps([{"claim": "Comparable listings lead with a full-quilt photo.", "listing_ids": ["111"], "image_ids": ["111"]}]),
                   "Asking prices only, one search area, no sold prices.", json.dumps(missing), json.dumps({"merchant": {"name": "Northloom Demo Studio"}}),
                   json.dumps({"name": "Chintz Applique Quilt", "source_url": "https://www.metmuseum.org/art/collection/search/854568"}), json.dumps(listing_ev), json.dumps(img_ev), t + dt,
                   "live_research" if run else "recorded_sample", run, req, mid))

    db.execute("INSERT INTO research_runs(run_id, agent_id, conversation_id, request_id, message_id, scope, api_max, image_max, created_at) VALUES(?,?,?,?,?,?,?,?,?)", ("run-seed-1", A, "conv-" + A, "seed-req-a1", u1, "seed", 4, 2, t + 1))
    draft("draft-seed-1", "Chintz Applique Quilt - listing draft", "complete", None, None, "run-seed-1", [], 2)           # identity only through its research run (the pre-UI-02 shape)
    draft("draft-seed-2", "Tighter second draft", "partial", "seed-req-a2", u2, None, ["only one comparable listing has full details"], 4)
    draft("draft-seed-legacy", "Older draft with no identity", "complete", None, None, None, [], 5)
    # S: ad research package + failed flyer on the SAME request (u4)
    db.execute("INSERT INTO ad_runs(run_id, agent_id, company_id, company_name, conversation_id, request_id, message_id, scope, api_max, image_max, media_type, country, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
               ("adrun-seed-1", S, "default", "Northloom Demo Studio", "conv-" + S, "seed-req-s1", u4, "seed", 8, 3, "IMAGE_AND_MEME", "US", t + 8))
    refs = {"references": [{"ad_no": 2, "source_ad_id": "999", "source_url": "https://www.facebook.com/ads/library?id=999", "image_id": "ad-999-1", "sha256": sha, "why_relevant": "Shows the quilt large on a calm bed.",
                            "visual_features": ["full product shown large", "quiet palette"], "model_observations": "A bed with a patterned quilt."}],
            "cited_ads": [{"ad_no": 2, "source_ad_id": "999", "source_url": "https://www.facebook.com/ads/library?id=999", "advertiser": {"name": "Deerly's", "page_id": "1"}, "active": True, "card_count": 1,
                           "campaign": {"campaign_id": None}, "image_count": 1}]}
    gate = {"state": "disabled_reach_unavailable", "ranking_enabled": False, "metric": None, "geography": None, "period": None, "ads_recorded": 30, "ads_with_reported_reach": 0, "reason": "No ad carries a reach value."}
    db.execute("INSERT INTO ad_packages VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ("adpkg-seed-1", "adrun-seed-1", S, "default", "conv-" + S, "seed-req-s1", "complete", "One relevant ad was inspected for layout ideas.",
               "relevance_only", None, "Reach unknown; chosen by relevance.", json.dumps(gate), json.dumps(refs), json.dumps([{"ad_no": 2}]), json.dumps({"scraper_attempts": 5}), json.dumps({"request_id": "seed-req-s1"}), t + 9))
    sdb = sqlite3.connect(f"file:{Path(src) / 'app.db'}?mode=ro", uri=True)
    sdb.row_factory = sqlite3.Row
    real = {tn: [dict(r) for r in sdb.execute(f"SELECT * FROM {tn} WHERE run_id=?", (FLYER,))] for tn in ("flyer_runs", "flyer_attempts", "flyer_reviews")}
    sdb.close()
    real_file = Path(src) / "flyers" / FLYER / (real["flyer_attempts"][0]["candidate_id"] + ".jpg")

    def clone(run_id, cand, req, mid, dt, review=None, ok=True, final=True, error=None):
        r, a, v = dict(real["flyer_runs"][0]), dict(real["flyer_attempts"][0]), dict(real["flyer_reviews"][0])
        r.update(run_id=run_id, agent_id=S, request_id=req, message_id=mid, created_at=t + dt, final_candidate_id=cand if (ok and final) else None, research_json=None)
        a.update(candidate_id=cand, run_id=run_id, out_path=(cand + ".jpg") if ok else None, created_at=t + dt)
        if not ok:
            a.update(outcome="provider_error", http_status=500, error=error, out_sha256=None, out_bytes=None, out_width=None, out_height=None, out_mime=None)
        for tn, row in (("flyer_runs", r), ("flyer_attempts", a)):
            db.execute(f"INSERT INTO {tn}({','.join(row)}) VALUES({','.join('?' * len(row))})", tuple(row.values()))
        if ok:
            fd = ROOT / "runtime" / "flyers" / run_id
            fd.mkdir(parents=True, exist_ok=True)
            shutil.copy2(real_file, fd / (cand + ".jpg"))
            v.update(review_id="rev-" + cand[5:], candidate_id=cand, run_id=run_id, agent_id=S, request_id=req, created_at=t + dt, **(review or {}))
            db.execute(f"INSERT INTO flyer_reviews({','.join(v)}) VALUES({','.join('?' * len(v))})", tuple(v.values()))

    clone("fly-5ee0000001", "cand-5ee0000001", "seed-req-s1", u4, 9, ok=False, error="provider_error: HTTP 500 (the attempt was counted and is not repeated)")
    clone("fly-5ee0000002", "cand-5ee0000002", "seed-req-s2", u5, 10)    # the real review: passed
    issues = {"verdict": "defects_found", "defects_json": json.dumps([{"defect_no": 1, "check": "layout_readability", "description": "The inset photo overlaps the lower-left corner of the quilt.", "correction": "Move the inset clear of the product."}]),
              "checks_json": json.dumps({"product_appearance": {"result": "pass", "observation": "The quilt matches the supplied photo."}, "required_text_price": {"result": "pass", "observation": "Name, USD 79.00 and the demonstration label are visible."},
                                         "layout_readability": {"result": "fail", "observation": "The inset covers part of the quilt."}})}
    clone("fly-5ee0000003", "cand-5ee0000003", "seed-req-s3", u6, 12, review=issues)
    clone("fly-5ee0000004", "cand-5ee0000004", None, None, 14)           # legacy: no identity at all
    db.commit()
    db.close()


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
    if MODE in ("ready", "results"):
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
            if MODE == "results":
                seed_results(src)
        if src and MODE == "ready":
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
