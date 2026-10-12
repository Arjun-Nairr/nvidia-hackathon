"""Ticket 05 tests: live Marketplace research tools, finite persisted allowance, run scoping and the evidence -> inspect -> draft path.
Everything here uses SCRIPTED stand-ins: tests/mock_scrapecreators.py (invented documented-shape payloads and a local 'CDN') and tests/mock_llm.py
(a rule-based research policy, not a model). It proves backend behaviour and wiring; it is NOT live retrieval, NOT vision and NOT model quality.
Part A: public backend seams in-process (isolated app root). Part B: scripted specialist through the real server and Hermes workers.
Wipes the copy's runtime/ in part B - run ONLY from a COPY of the project:
  RESEARCH_I_AM_A_COPY=1 venv-python tests/research_test.py"""
import json, os, shutil, subprocess, sys, tempfile, threading, time, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if os.environ.get("RESEARCH_I_AM_A_COPY") != "1":
    sys.exit("Refusing to run: set RESEARCH_I_AM_A_COPY=1 and run from a COPY of the project.")
os.environ["HERMES_HOME"] = str(ROOT / "runtime" / "hermes_home" / "profiles" / "main")   # project-local, before any profile operation
FIX = ROOT / "tests" / "fixtures"
TMP = Path(tempfile.mkdtemp(prefix="res_"))
SC, MOCK, APP = 8791, 8775, 8824
KEY = "TEST-KEY-SENTINEL-0123456789"
os.environ.update({"ECOM_APP_ROOT": str(TMP), "ECOM_SCRAPECREATORS_URL": f"http://127.0.0.1:{SC}", "ECOM_PHOTO_HOSTS": "127.0.0.1",
                   "SCRAPECREATORS_API_KEY": KEY, "ECOM_CATALOGUE_FILE": str(FIX / "demo_catalogue.json"), "ECOM_EVIDENCE_FILE": str(FIX / "marketplace_sample.json")})
for k in ("ECOM_RESEARCH_SCOPE", "ECOM_RESEARCH_API_MAX", "ECOM_RESEARCH_IMAGE_MAX", "ECOM_RESEARCH_RUN_API_MAX", "ECOM_RESEARCH_RUN_IMAGE_MAX", "ECOM_IMAGE_DIRS"):
    os.environ.pop(k, None)
sys.path.insert(0, str(ROOT))
from app import core, listing, research, turn_state

results, procs = [], []
import atexit
atexit.register(lambda: [p.terminate() for p in procs if p.poll() is None])   # an aborted run must not leave stand-in servers behind


def check(name, ok, detail=""):
    ok = bool(ok); results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{str(detail)[:600]}]"), flush=True)


def http(port, path, body=None, timeout=600):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def sc_ctl(reset=True, **kw):
    return http(SC, "/control", {"reset": reset, **kw})[1]


def sc_stats():
    return http(SC, "/stats")[1]


def wait_up(port, path="/stats", tries=80):
    for _ in range(tries):
        try:
            http(port, path, timeout=5); return
        except Exception:
            time.sleep(0.25)
    raise RuntimeError(f"port {port} did not come up")


def spawn(args, env=None):
    p = subprocess.Popen([sys.executable, *args], cwd=ROOT, env=env or {**os.environ, "PYTHONUTF8": "1"}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(p)
    return p


spawn(["tests/mock_scrapecreators.py", str(SC)])
wait_up(SC)

core.update_company({"name": "Acme Linens", "products": "Cotton bedding", "customers": "Home buyers in the US", "goal": "Better listing photos"}, source="form")


def register(agent_id, tools):
    with core.db() as d:
        d.execute("INSERT OR REPLACE INTO agents VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (agent_id, agent_id, "market_analysis", "default", "o", "i", "[]", "[]", json.dumps(list(tools)), "[]", f"conv-{agent_id}", "idle", time.time()))


MP = list(core.MARKETPLACE_TOOLS)
register("lab", MP + ["save_listing_draft", "inspect_image", "read_catalogue"])
register("search-only", ["marketplace_search"])


def req(rid):
    turn_state.request_id, turn_state.run_id = rid, None


def code(r):
    return r.get("code") if isinstance(r, dict) and r.get("ok") is False else ("OK" if isinstance(r, dict) and r.get("ok") else r)


def scope(name, api=None, img=None, run_api=None, run_img=None):
    os.environ["ECOM_RESEARCH_SCOPE"] = name
    for k, v in (("ECOM_RESEARCH_API_MAX", api), ("ECOM_RESEARCH_IMAGE_MAX", img), ("ECOM_RESEARCH_RUN_API_MAX", run_api), ("ECOM_RESEARCH_RUN_IMAGE_MAX", run_img)):
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = str(v)


def used(name):
    return next((a for a in research.allowances() if a["scope"] == name), None)


# ================= A. public backend seams =================
print("PART A: backend seams (scripted ScrapeCreators stand-in; not live)", flush=True)
scope("a-main", api=50, img=10)
sc_ctl(first="irrelevant")
req("req-a1")
L = research.locate("lab", {"query": "Dallas, TX"})
S1 = research.search("lab", {"query": "queen quilted coverlet", "location_no": 1, "condition": "new", "radius_km": 50})
rows1 = S1.get("listings") or []
st = sc_stats()
check("A1 locate -> search works against documented shapes: numbered places, compact listings, allowance reported, key only in the API header",
      L["ok"] and L["locations"][0]["location_no"] == 1 and S1["ok"] and len(rows1) == 3 and {"listing_id", "title", "price", "detail_level"} <= set(rows1[0])
      and S1["allowance"]["api_attempts_left"] == 10 and all(r["has_key"] for r in st["requests"] if r["kind"] != "cdn")
      and "lat" in st["requests"][1]["params"] and st["requests"][1]["params"]["condition"] == "new", (L, S1.get("code"), st["requests"][:2]))
check("A1b an irrelevant first result is returned as it is (the backend does not rank or filter): the unrelated listings are visible for the agent to judge",
      [r["title"] for r in rows1] == ["Used mountain bike 21 speed", "Set of 4 truck tires", "Dining chair oak"], rows1)
S2 = research.search("lab", {"query": "comforter set", "location_no": 1, "condition": "new"})
ids = [r["listing_id"] for r in S2["listings"]]
IT = research.item("lab", {"listing_id": "9001"})
PH = research.photo("lab", {"listing_id": "9001"})
blob = json.dumps([L, S1, S2, IT, PH])
check("A2 item details (description, condition, photo references, source URL) and a photo download work; outputs carry no signed photo URL, key or seller identity",
      ids == ["9001", "9002", "9003", "9004"] and IT["ok"] and IT["listing"]["description"].startswith("Brand new queen") and IT["listing"]["condition"] == "new"
      and IT["listing"]["source_url"].endswith("/marketplace/item/9001/") and IT["listing"]["photos"][0]["photo_id"] == "p9001"
      and PH["ok"] and PH["image_id"] == "9001" and len(PH["sha256"]) == 64 and "PRIVATE-SIGNED" not in blob and KEY not in blob and "S-9001" not in blob and "Private Person" not in blob, blob[:400])
cdn = [r for r in sc_stats()["requests"] if r["kind"] == "cdn"]
check("A3 the photo download reached the CDN host WITHOUT any API credential header", len(cdn) == 1 and cdn[0]["has_key"] is False, cdn)
rv = research.run_view(research.run_for("lab", "req-a1")["run_id"])
check("A4 the run records every call (kind, params, outcome, credits, ms), the retrieved listings and the downloaded photo hash, without URLs or coordinates",
      [c["kind"] for c in rv["calls"]] == ["location", "search", "search", "item", "photo"] and all(c["status"] == "done" and c["outcome"] == "ok" for c in rv["calls"])
      and rv["calls"][1]["credits_charged"] == 1 and rv["calls"][1]["ms"] is not None and rv["listings_recorded"] == 7 and rv["photos"][0]["sha256"] == PH["sha256"]
      and "PRIVATE-SIGNED" not in json.dumps(rv) and "lat" not in rv["calls"][1]["params"] and rv["allowance"]["run_api_attempts"] == 4 and rv["allowance"]["run_photo_downloads"] == 1, rv)
n0 = sc_stats()["total"]
S2b = research.search("lab", {"query": "comforter set", "location_no": 1, "condition": "new"})
IT2 = research.item("lab", {"listing_id": "9001"})
check("A5 an identical successful search/item is answered from the run's stored result: nothing re-sent, nothing re-counted",
      S2b["ok"] and S2b.get("cached") and IT2.get("cached") and sc_stats()["total"] == n0 and S2b["allowance"]["api_attempts_left"] == IT["allowance"]["api_attempts_left"], (S2b.get("cached"), sc_stats()["total"], n0))

# --- arguments, grants, identity
n0 = sc_stats()["total"]
a0 = used("a-main")
bad = [research.search("lab", {"query": "x", "location_no": 1, **extra}) for extra in
       ({"max_requests": 999}, {"run_id": "run-0123456789"}, {"reset_allowance": True}, {"api_key": "x"}, {"url": "https://evil.example/"})]
bad += [research.item("lab", {"listing_id": "9001", "budget": 100}), research.photo("lab", {"listing_id": "9001", "url": "https://evil.example/x.png"}),
        research.locate("lab", {"query": "Dallas", "scope": "other"})]
check("A6 a tool call cannot carry allowance, run, credential or URL arguments: invalid_argument, nothing sent, allowance unchanged",
      all(code(b) == "invalid_argument" for b in bad) and sc_stats()["total"] == n0 and used("a-main") == a0, [code(b) for b in bad])
c_ng = code(research.locate("search-only", {"query": "Dallas"}))     # holds marketplace_search only
c_gh = code(research.locate("ghost", {"query": "Dallas"}))
req(None)
c_nr = code(research.locate("lab", {"query": "Dallas"}))
req("req-a1")
check("A7 an agent without that grant, an unregistered agent and a call outside a manual request are refused before anything is spent",
      c_ng == "not_granted" and c_gh == "unknown_agent" and c_nr == "no_manual_request" and sc_stats()["total"] == n0, (c_ng, c_gh, c_nr))
check("A8 unknown listing ids (not returned by this request's searches) cannot be requested or photographed",
      code(research.item("lab", {"listing_id": "1638806271151287"})) == "unknown_listing" and code(research.photo("lab", {"listing_id": "42"})) == "unknown_listing"
      and code(research.search("lab", {"query": "x", "location_no": 7})) == "bad_location_no")

# --- allowance
scope("a-tiny", api=3, img=1)
req("req-t1")
sc_ctl(first="irrelevant")
r1 = research.locate("lab", {"query": "Dallas, TX"})
r2 = research.search("lab", {"query": "coverlet", "location_no": 1})
sc_ctl(first="irrelevant", search_status=500)
r3 = research.search("lab", {"query": "different words", "location_no": 1})          # a FAILURE: still counted
sc_ctl(first="irrelevant")
n0 = sc_stats()["total"]
r4 = research.search("lab", {"query": "comforter set", "location_no": 1})
check("A9 failures are counted: with an allowance of 3, locate + search + a provider error use it; the 4th attempt is refused with nothing sent",
      r1["ok"] and r2["ok"] and code(r3) == "provider_error" and code(r4) == "allowance_exhausted" and sc_stats()["total"] == n0 and used("a-tiny")["api_used"] == 3, (code(r3), code(r4)))
os.environ["ECOM_RESEARCH_API_MAX"] = "500"                         # raising the environment later does not re-size an existing scope
req("req-t2")
r5 = research.locate("lab", {"query": "Dallas, TX"})
req("req-t3")
r6 = research.locate("lab", {"query": "Austin, TX"})
check("A10 an existing scope's cap cannot be raised by configuration, and new requests (new runs) do not refresh it: still exhausted",
      code(r5) == "allowance_exhausted" and code(r6) == "allowance_exhausted" and used("a-tiny")["api_max"] == 3 and used("a-tiny")["api_used"] == 3, (code(r5), used("a-tiny")))
req("req-t1")
check("A10b the same request cannot open a replacement run: one run per (agent, request)",
      research.open_run("lab", "req-t1")["run_id"] == research.run_for("lab", "req-t1")["run_id"] and len([r for r in research.list_runs("lab") if r["scope"] == "a-tiny"]) == 3)
scope("a-runcap", api=50, img=10, run_api=2)
req("req-r1")
x = [research.locate("lab", {"query": q}) for q in ("Dallas", "Austin", "Houston")]
req("req-r2")
y = research.locate("lab", {"query": "Dallas"})
check("A11 the per-run cap applies inside a larger scope allowance, and a later request gets its own run",
      x[0]["ok"] and x[1]["ok"] and code(x[2]) == "allowance_exhausted" and "run's" in x[2]["error"] and y["ok"], [code(i) for i in x])

# --- concurrency (real processes sharing the app database)
scope("a-conc", api=10, img=10)
sc_ctl(first="irrelevant")
CHILD = r'''
import json, os, sys
sys.path.insert(0, os.environ["ROOT_DIR"])
from app import research, turn_state
turn_state.request_id = "req-conc-" + sys.argv[1]
out = []
for j in range(4):
    r = research.locate("lab", {"query": f"place {sys.argv[1]} {j}"})
    out.append("OK" if r.get("ok") else r.get("code"))
print(json.dumps(out))
'''
env = {**os.environ, "PYTHONUTF8": "1", "ROOT_DIR": str(ROOT)}
n0 = sc_stats()["total"]
kids = [subprocess.Popen([sys.executable, "-c", CHILD, str(i)], env=env, stdout=subprocess.PIPE, text=True) for i in range(4)]
outs = [json.loads(k.communicate()[0].strip().splitlines()[-1]) for k in kids]
flat = [x for o in outs for x in o]
check("A12 four processes racing for a 10-attempt scope send exactly 10 requests and are refused the rest (atomic reservation, no overspend)",
      flat.count("OK") == 10 and flat.count("allowance_exhausted") == 6 and sc_stats()["total"] - n0 == 10 and used("a-conc")["api_used"] == 10, (flat, sc_stats()["total"] - n0, used("a-conc")))

# --- unknown outcome is never replayed
scope("a-drop", api=20, img=10)
sc_ctl(first="irrelevant", drop=["search"])
req("req-d1")
research.locate("lab", {"query": "Dallas, TX"})
d1 = research.search("lab", {"query": "queen coverlet", "location_no": 1})
n0 = sc_stats()["total"]
d2 = research.search("lab", {"query": "queen coverlet", "location_no": 1})
sc_ctl(reset=False, drop=[])
d3 = research.search("lab", {"query": "queen coverlet", "location_no": 1})
check("A13 a request whose outcome is unknown (connection dropped) is counted, reported honestly and NOT replayed - not by the backend and not by an identical retry",
      code(d1) == "network_error" and code(d2) == "uncertain_previous_attempt" and code(d3) == "uncertain_previous_attempt" and sc_stats()["total"] == n0, (code(d1), code(d2), code(d3)))
c = core.db()
rid = research.run_for("lab", "req-d1")["run_id"]
c.execute("INSERT INTO research_calls(run_id, kind, params, params_key, status, ts) VALUES(?,?,?,?,?,?)", (rid, "item", '{"id": "9002"}', '{"id": "9002"}', "reserved", time.time()))
c.execute("INSERT OR IGNORE INTO research_listings(run_id, listing_id, record, first_call, retrieved_at) VALUES(?,?,?,?,?)",
          (rid, "9002", json.dumps({"listing_id": "9002", "title": "t", "photos": [], "price": {}}), 1, "x"))
c.commit()
n0 = sc_stats()["total"]
d4 = research.item("lab", {"listing_id": "9002"})
check("A14 a crash leaves a 'reserved' call: the identical request is refused (outcome unknown), still counted, never re-sent", code(d4) == "uncertain_previous_attempt" and sc_stats()["total"] == n0, d4)

# --- photos
scope("a-photo", api=40, img=3)
sc_ctl(first="relevant", photo_fail=["9002"], photo_html=["9003"])
req("req-p1")
research.locate("lab", {"query": "Dallas, TX"})
research.search("lab", {"query": "bedding", "location_no": 1})
for l in ("9001", "9002", "9003"):
    research.item("lab", {"listing_id": l})
p1, p2, p3 = (research.photo("lab", {"listing_id": l}) for l in ("9001", "9002", "9003"))
p4 = research.photo("lab", {"listing_id": "9004"})
rvp = research.run_view(research.run_for("lab", "req-p1")["run_id"])
check("A15 missing/unusable photos fail explicitly and are counted (404, HTML page), a good one is kept, and the photo allowance stops the 4th download",
      p1["ok"] and code(p2) == "photo_unavailable" and code(p3) == "photo_unavailable" and code(p4) == "allowance_exhausted" and len(rvp["photos"]) == 1
      and [c["outcome"] for c in rvp["calls"] if c["kind"] == "photo"] == ["ok", "http_error", "not_image"], [code(p) for p in (p1, p2, p3, p4)])
reg = core.db().execute("SELECT listing_id FROM research_photos WHERE run_id=?", (rvp["run_id"],)).fetchall()
check("A15b a failed download leaves no registered file: inspect_image cannot see it", [r[0] for r in reg] == ["9001"] and core.prepare_image("9002")["code"] == "image_not_found")
# the OLD diagnostic photo cache is invisible inside a live run: a recorded photo cannot be inspected as if it had just been retrieved
old_cache = TMP / "runtime" / "marketplace_check" / "images"
old_cache.mkdir(parents=True, exist_ok=True)
(old_cache / "9004.png").write_bytes((research.image_dir(rvp["run_id"]) / "9001.png").read_bytes()) if (research.image_dir(rvp["run_id"]) / "9001.png").exists() else None
turn_state.run_id = None
seen_without_run = core.prepare_image("9004")
turn_state.run_id = rvp["run_id"]
seen_in_run = core.prepare_image("9004")
check("A15c inside a research run the old diagnostic photo cache is not visible: a cached recorded photo cannot masquerade as a fresh download",
      seen_without_run.get("ok") is True and code(seen_in_run) == "image_not_found", (code(seen_without_run), code(seen_in_run)))
sc_ctl(first="relevant")
# a listing with no photo reference and a host that is not an allowed CDN
c = core.db()
c.execute("INSERT OR REPLACE INTO research_listings(run_id, listing_id, record, first_call, retrieved_at) VALUES(?,?,?,?,?)",
          (rvp["run_id"], "7001", json.dumps({"listing_id": "7001", "title": "No photo bedding", "photos": [], "price": {}}), 1, "x"))
c.execute("INSERT OR REPLACE INTO research_listings(run_id, listing_id, record, first_call, retrieved_at) VALUES(?,?,?,?,?)",
          (rvp["run_id"], "7002", json.dumps({"listing_id": "7002", "title": "Evil host", "photos": [{"id": "x", "url": "https://evil.example/a.png"}], "price": {}}), 1, "x"))
c.commit()
n0 = sc_stats()["total"]
used0 = used("a-photo")["image_used"]
check("A16 a listing without a photo reference or with a non-CDN host is refused with nothing fetched and nothing spent",
      code(research.photo("lab", {"listing_id": "7001"})) == "no_photo_reference" and code(research.photo("lab", {"listing_id": "7002"})) == "photo_host_not_allowed"
      and sc_stats()["total"] == n0 and used("a-photo")["image_used"] == used0)
os.environ.pop("SCRAPECREATORS_API_KEY")
scope("a-nokey", api=5, img=5)
req("req-k1")
nk = research.locate("lab", {"query": "Dallas"})
os.environ["SCRAPECREATORS_API_KEY"] = KEY
check("A17 a missing credential is reported as such: nothing sent, nothing spent", code(nk) == "missing_credentials" and (used("a-nokey") or {"api_used": 0})["api_used"] == 0, nk)

# --- live-shaped evidence -> inspect -> draft (accurate provenance)
scope("a-draft", api=40, img=10)
sc_ctl(first="relevant")
req("req-g1")
research.locate("lab", {"query": "Dallas, TX"})
research.search("lab", {"query": "comforter set", "location_no": 1, "condition": "new"})
research.item("lab", {"listing_id": "9001"})
research.item("lab", {"listing_id": "9003"})
research.photo("lab", {"listing_id": "9001"})
research.photo("lab", {"listing_id": "9003"})
prep = core.prepare_image("9001")
listing.record_inspection("lab", prep, "image_part_sent")
listing.record_inspection("lab", core.prepare_image("9003"), "image_part_sent")
PID = "acme-cloud-quilt-queen"


def draft(**o):
    d = {"product_id": PID, "title": "Cloud Weave Quilted Coverlet, Queen, Oatmeal",
         "description": "A queen-size quilted coverlet in oatmeal with a 100% cotton shell and polyester fill. Machine washable. Supplied as a single coverlet, new. Price: $89 USD.",
         "visual_brief": "Shoot the coverlet fully made up on a queen bed against a plain light wall, daylight from the left, one close-up of the diamond quilting, "
                         "and a folded stack showing the oatmeal colour. Keep the frame uncluttered so the product is the focus.",
         "rationale": [{"claim": "A comparable new comforter set is listed at a low asking price with a sealed-bag photo.", "listing_ids": ["9001"], "image_ids": ["9001"]}],
         "image_observations": [{"image_id": "9001", "observations": "A flat orange-red colour field standing in for the photo; no detail visible.", "uncertainties": "Nothing readable."}],
         "limitations": "Asking prices only."}
    d.update(o)
    return d


r = listing.save_draft("lab", draft())
dr = listing.get_draft(r["draft_id"]) if r.get("ok") else {}
im = (dr.get("image_evidence") or [{}])[0]
le = (dr.get("listing_evidence") or [{}])[0]
check("A18 live evidence reaches inspect_image and the draft: COMPLETE, evidence_source live_research with the run id, source URL, retrieval time, supporting description/photo refs, "
      "photo kind live_listing_photo with a matching downloaded-file hash",
      r.get("ok") and r["status"] == "complete" and dr["evidence_source"] == "live_research" and dr["research_run_id"] == research.run_for("lab", "req-g1")["run_id"]
      and le["source_url"].endswith("/9001/") and le["retrieved_at"] and le["supporting"]["description"].startswith("Brand new queen") and le["evidence_file"].startswith("live-run:")
      and im["kind"] == "live_listing_photo" and im["provenance"] == "hash_match" and im["recorded_sha256"] == im["sha256"] == prep["sha256"] and im["delivery"] == "image_part_sent"
      and le["seller_ref"] == "seller_1", (r, im, le))
check("A19 a recorded-sample listing id cannot masquerade as fresh research: citing a Dallas-fixture listing in a live draft is refused (unknown_listing)",
      code(listing.save_draft("lab", draft(rationale=[{"claim": "A comparable listing from the old sample sold.", "listing_ids": ["1638806271151287"]}]))) == "unknown_listing"
      and code(listing.save_draft("lab", draft(rationale=[{"claim": "A comparable new listing asks a low price.", "listing_ids": ["1638806271151287"]}]))) == "unknown_listing")
check("A20 an agent holding live tools cannot save recorded-sample evidence, and one holding both must say which it is using",
      code(listing.save_draft("lab", draft(evidence_source="recorded_sample"))) == "evidence_source_not_granted"
      and (register("both", MP + ["save_listing_draft", "read_recorded_evidence", "inspect_image"]) or code(listing.save_draft("both", draft()))) == "evidence_source_required")
photo_path = next(research.image_dir(research.run_for("lab", "req-g1")["run_id"]).glob("9003.*"))
tampered = photo_path.read_bytes() + b"\0"
photo_path.write_bytes(tampered)
turn_state.run_id = research.run_for("lab", "req-g1")["run_id"]
listing.record_inspection("lab", core.prepare_image("9003"), "image_part_sent")
tam = listing.save_draft("lab", draft(rationale=[{"claim": "A second comparable new bedding set is listed.", "listing_ids": ["9003"], "image_ids": ["9003"]}],
                                      image_observations=[{"image_id": "9003", "observations": "A blue colour field standing in for the photo, nothing else visible."}]))
check("A21 a downloaded photo changed on disk afterwards is refused at save (image_provenance_mismatch against the hash recorded at download)", code(tam) == "image_provenance_mismatch", tam)
photo_path.write_bytes(tampered[:-1])
req("req-g-other")
check("A22 evidence is scoped to the request: another request of the same specialist has no live evidence and cannot cite this run's listings",
      code(listing.save_draft("lab", draft())) == "no_live_research", listing.save_draft("lab", draft()))
req("req-g1")
none_inspected = listing.save_draft("lab", draft(rationale=[{"claim": "A comparable new listing asks a low price.", "listing_ids": ["9004"]}], image_observations=[]))
check("A23 a live draft citing only a search-only listing and no inspected photo is an honest PARTIAL, never complete",
      none_inspected.get("ok") and none_inspected["status"] == "partial" and len(none_inspected["missing"]) == 2, none_inspected)
register("rec", ["save_listing_draft", "read_recorded_evidence"])
rec = listing.save_draft("rec", draft(rationale=[{"claim": "A search-only recorded listing shows an asking price for a comparable set.", "listing_ids": ["955699870493854"]}], image_observations=[]))
rdr = listing.get_draft(rec["draft_id"]) if rec.get("ok") else {}
check("A23b the recorded-sample path is unchanged and labelled: a draft from the fixture reads evidence_source recorded_sample with no research run",
      rec.get("ok") and rec["evidence_source"] == "recorded_sample" and rdr["evidence_source"] == "recorded_sample" and rdr["research_run_id"] is None
      and rdr["listing_evidence"][0]["evidence_file"] == "marketplace_sample.json", rec)

# --- catalogue / company context is explicit
os.environ["ECOM_CATALOGUE_FILE"] = str(FIX / "demo_catalogue.json")
core.update_company({"name": "Real Textiles Ltd"}, source="form")
rc, sd = listing.read_catalogue(), listing.save_draft("lab", draft())
check("A24 a catalogue that belongs to another merchant is NOT supplied to this company: explicit catalogue_company_mismatch for reads and saves",
      code(rc) == "catalogue_company_mismatch" and "Acme Linens" in rc["error"] and code(sd) == "catalogue_company_mismatch", (rc.get("code"), sd.get("code")))
austin = {"schema": 1, "demo": True, "notice": "FICTIONAL DEMO DATA: invented for tests.",
          "merchant": {"merchant_id": "demo-real", "name": "Real Textiles Ltd", "market": {"location_query": "Austin, TX", "radius_km": 30}},
          "products": [{"product_id": "real-flannel-throw", "name": "Real Flannel Throw Blanket", "category": "throws", "condition": "new",
                        "specifications": {"size": "50 x 60 in", "colour": "Grey", "material": "100% polyester flannel", "care": "Machine washable", "pieces": "1 throw"},
                        "price": {"amount": 24.5, "currency": "USD"}, "image": {"image_id": "real-throw", "kind": "synthetic illustration"}}]}
(TMP / "cat_austin.json").write_text(json.dumps(austin), encoding="utf-8")
os.environ["ECOM_CATALOGUE_FILE"] = str(TMP / "cat_austin.json")
ra = listing.read_catalogue()
check("A25 a configured alternative merchant, product and market location is used without code edits (read_catalogue exposes its location for the specialist to research)",
      ra["ok"] and ra["merchant"]["market"]["location_query"] == "Austin, TX" and ra["products"][0]["product_id"] == "real-flannel-throw", ra.get("code"))
os.environ["ECOM_CATALOGUE_FILE"] = str(TMP / "cat_missing_file.json")
rm = listing.read_catalogue()
os.environ["ECOM_CATALOGUE_FILE"] = str(FIX / "demo_catalogue.json")
shutil.rmtree(TMP / "runtime" / "company.json", ignore_errors=True)
try:
    (TMP / "runtime" / "company.json").unlink()
except OSError:
    pass
nc = listing.read_catalogue()
check("A26 a missing catalogue file and a missing company are explicit errors, never silently replaced by demo facts", code(rm) == "catalogue_missing" and code(nc) == "company_missing", (rm.get("code"), nc.get("code")))
core.update_company({"name": "Acme Linens", "products": "Cotton bedding", "customers": "Home buyers in the US", "goal": "Better listing photos"}, source="form")


# ================= R. ticket05 review corrections =================
print("PART R: review corrections (scripted stand-ins; not live)", flush=True)
RUN_SEQ = [0]


def new_req(tag):
    RUN_SEQ[0] += 1
    rid = f"req-{tag}-{RUN_SEQ[0]}"
    req(rid)
    return rid


def last_hit(kind):
    return [r for r in sc_stats()["requests"] if r["kind"] == kind][-1]


def snap(run_id):
    return json.dumps(research._load_records(run_id), sort_keys=True)


# --- R1: the place the specialist selected is the place that is searched (A -> B -> cached A)
scope("r-loc", api=30, img=5)
sc_ctl(first="relevant")
rid = new_req("loc")
research.locate("lab", {"query": "Dallas, TX"})
research.locate("lab", {"query": "Austin, TX"})
research.search("lab", {"query": "bedding", "location_no": 1})
lat_after_b = float(last_hit("search")["params"]["lat"])
n_before, u_before = sc_stats()["total"], used("r-loc")["api_used"]
cached_a = research.locate("lab", {"query": "Dallas, TX"})
n_mid, u_mid = sc_stats()["total"], used("r-loc")["api_used"]
s_a = research.search("lab", {"query": "comforter set", "location_no": 1})
hit = last_hit("search")["params"]
rv = research.run_view(research.run_for("lab", rid)["run_id"])
check("R1 locate Dallas -> locate Austin -> locate Dallas (cache hit) -> search location 1 searches DALLAS (the place the specialist was last shown), not Austin; "
      "after A -> B alone location 1 is Austin; the search result names the place searched",
      abs(lat_after_b - 30.2672) < 1e-6 and cached_a.get("cached") is True and abs(float(hit["lat"]) - 32.7774) < 1e-6 and abs(float(hit["lng"]) + 96.7977) < 1e-6
      and (s_a.get("place") or {}).get("name") == "Dallas, Texas", (lat_after_b, hit, s_a.get("place")))
check("R1b the cache hit is free and creates no duplicate paid call: no provider request, no counter change, two paid lookups in the run",
      n_mid == n_before and u_mid == u_before and [c["kind"] for c in rv["calls"]].count("location") == 2, (n_before, n_mid, u_before, u_mid, [c["kind"] for c in rv["calls"]]))
check("R1c an out-of-range location_no is judged against the SELECTED lookup, not the newest paid one",
      code(research.search("lab", {"query": "x", "location_no": 2})) == "bad_location_no")


# --- R2: a successful request whose result could not be saved is terminal for identical requests
def storage(broken):
    c = core.db()
    c.executescript("DROP TRIGGER IF EXISTS fail_ins; DROP TRIGGER IF EXISTS fail_upd;")
    if broken:
        c.executescript("CREATE TRIGGER fail_ins BEFORE INSERT ON research_listings BEGIN SELECT RAISE(ABORT, 'disk full'); END;"
                        "CREATE TRIGGER fail_upd BEFORE UPDATE ON research_listings BEGIN SELECT RAISE(ABORT, 'disk full'); END;")
    c.commit()
    c.close()


scope("r-unsaved", api=60, img=10)
sc_ctl(first="relevant")
rid = new_req("u-search")
research.locate("lab", {"query": "Dallas, TX"})
storage(True)
u1 = research.search("lab", {"query": "comforter set", "location_no": 1})
c1 = sc_stats()["counts"].get("search", 0)
a1 = research.allowance_view(research.run_for("lab", rid)["run_id"])["run_api_attempts"]
u2 = research.search("lab", {"query": "comforter set", "location_no": 1})
storage(False)
u3 = research.search("lab", {"query": "comforter set", "location_no": 1})
a3 = research.allowance_view(research.run_for("lab", rid)["run_id"])["run_api_attempts"]
check("R2 SEARCH: result not saved -> explicit storage_error; identical retries (also after local storage recovered) are refused with NO second provider request and no extra counted attempt",
      code(u1) == "storage_error" and code(u2) == "storage_error" and code(u3) == "storage_error" and sc_stats()["counts"].get("search", 0) == c1 == 1 and a1 == a3 == 2,
      (code(u1), code(u2), code(u3), sc_stats()["counts"], a1, a3))
check("R2b ... a different request in the same run still works (the block is per identical request, not a kill switch)",
      research.search("lab", {"query": "bedding set", "location_no": 1}).get("ok") is True)

rid = new_req("u-item")
research.locate("lab", {"query": "Dallas, TX"})
research.search("lab", {"query": "comforter set", "location_no": 1})
run_id = research.run_for("lab", rid)["run_id"]
before = snap(run_id)
storage(True)
i1 = research.item("lab", {"listing_id": "9001"})
n_item = sc_stats()["counts"].get("item", 0)
i2 = research.item("lab", {"listing_id": "9001"})
storage(False)
i3 = research.item("lab", {"listing_id": "9001"})
check("R2c ITEM: same behaviour: storage_error, identical retries refused with no second item request, previously saved evidence unchanged",
      code(i1) == "storage_error" and code(i2) == "storage_error" and code(i3) == "storage_error" and n_item == 1 and sc_stats()["counts"].get("item", 0) == 1
      and snap(run_id) == before, (code(i1), code(i2), code(i3), sc_stats()["counts"]))
check("R2d ... and normal item retrieval and its cache behaviour are unaffected for another listing",
      research.item("lab", {"listing_id": "9002"}).get("ok") is True and research.item("lab", {"listing_id": "9002"}).get("cached") is True)

rid = new_req("u-photo")
research.locate("lab", {"query": "Dallas, TX"})
research.search("lab", {"query": "comforter set", "location_no": 1})
run_id = research.run_for("lab", rid)["run_id"]
blocker = research.image_dir(run_id)
blocker.parent.mkdir(parents=True, exist_ok=True)
blocker.write_text("not a directory")                      # the photo directory cannot be created: a local persistence failure AFTER a successful download
p1 = research.photo("lab", {"listing_id": "9001"})
cdn1 = sc_stats()["counts"].get("cdn", 0)
img1 = used("r-unsaved")["image_used"]
p2 = research.photo("lab", {"listing_id": "9001"})
blocker.unlink()
p3 = research.photo("lab", {"listing_id": "9001"})
rows = core.db().execute("SELECT COUNT(*) FROM research_photos WHERE run_id=?", (run_id,)).fetchone()[0]
check("R2e PHOTO: download not saved -> storage_error; identical retries (also after the local fault is gone) are refused with NO second download and no extra counted photo; no photo registered",
      code(p1) == "storage_error" and code(p2) == "storage_error" and code(p3) == "storage_error" and sc_stats()["counts"].get("cdn", 0) == cdn1 == 1
      and used("r-unsaved")["image_used"] == img1 == 1 and rows == 0, (code(p1), code(p2), code(p3), sc_stats()["counts"], img1, rows))
check("R2f ... another listing's photo downloads normally afterwards", research.photo("lab", {"listing_id": "9002"}).get("ok") is True)

# a DATABASE failure while registering a downloaded photo is the same terminal outcome (it is not an OSError)
rid = new_req("u-photo-db")
research.locate("lab", {"query": "Dallas, TX"})
research.search("lab", {"query": "comforter set", "location_no": 1})
c = core.db()
c.executescript("CREATE TRIGGER fail_photo BEFORE INSERT ON research_photos BEGIN SELECT RAISE(ABORT, 'database or disk is full'); END;")
c.commit(); c.close()
cdn0 = sc_stats()["counts"].get("cdn", 0)
try:
    q1 = research.photo("lab", {"listing_id": "9004"})
except Exception as ex:
    q1 = {"raised": repr(ex)[:120]}
q2 = research.photo("lab", {"listing_id": "9004"})
c = core.db()
c.executescript("DROP TRIGGER fail_photo;")
c.commit(); c.close()
check("R2g PHOTO, database failure while registering the download: explicit storage_error (not an uncaught exception), identical retry refused, one download only",
      code(q1) == "storage_error" and code(q2) == "storage_error" and sc_stats()["counts"].get("cdn", 0) - cdn0 == 1, (q1, code(q2), sc_stats()["counts"]))

# --- R3: the response must be the listing that was asked for
scope("r-ident", api=80, img=10)


def ident_run(lid, override):
    sc_ctl(first="relevant", item_override={lid: override} if override else {})
    rid = new_req("ident")
    research.locate("lab", {"query": "Dallas, TX"})
    research.search("lab", {"query": "comforter set", "location_no": 1})
    return research.run_for("lab", rid)["run_id"]


run_id = ident_run("9001", None)
m = research.item("lab", {"listing_id": "9001"})
check("R3 matching id: stored, identity recorded as id_match", m.get("ok") and m["listing"].get("identity") == "id_match" and m["listing"]["description"].startswith("Brand new queen"), m)

run_id = ident_run("9001", "wrong:9002")
before = snap(run_id)
n0 = sc_stats()["counts"].get("item", 0)
w1 = research.item("lab", {"listing_id": "9001"})
n1 = sc_stats()["counts"].get("item", 0)
w2 = research.item("lab", {"listing_id": "9001"})
recs = research._load_records(run_id)
item_calls = [c for c in research.run_view(run_id)["calls"] if c["kind"] == "item"]
check("R3b MISMATCHED id: refused (item_identity_mismatch) with exactly one counted attempt and no retry; the searched listing is kept and neither listing receives the other's "
      "description, price or photos",
      code(w1) == "item_identity_mismatch" and n1 - n0 == 1 and sc_stats()["counts"].get("item", 0) == n1 and code(w2) == "item_identity_mismatch"
      and snap(run_id) == before and recs["9001"]["description"] is None and recs["9002"]["description"] is None and recs["9001"]["photos"] == []
      and len(item_calls) == 1 and item_calls[0]["outcome"] == "identity_mismatch", (code(w1), n1 - n0, [c["outcome"] for c in item_calls], recs["9001"].get("description")))

run_id = ident_run("9003", "no_id")
a = research.item("lab", {"listing_id": "9003"})
check("R3c ABSENT id whose source URL names the requested listing: accepted, recorded as url_match (not claimed as an id confirmation)",
      a.get("ok") and a["listing"].get("identity") == "url_match" and a["listing"]["description"].startswith("King size"), a)
run_id = ident_run("9004", "no_id_no_url")
b = research.item("lab", {"listing_id": "9004"})
check("R3d ABSENT id and no URL: accepted ONLY as unconfirmed - the record and the result say identity was not confirmed by the response",
      b.get("ok") and b["listing"].get("identity") == "unconfirmed_no_id_in_response" and "not" in (b.get("identity_note") or "").lower(), b)
run_id = ident_run("9002", "no_id_other_url:9004")
before = snap(run_id)
c = research.item("lab", {"listing_id": "9002"})
check("R3e ABSENT id but the URL names ANOTHER listing: refused as a mismatch, evidence unchanged", code(c) == "item_identity_mismatch" and snap(run_id) == before, (code(c), c))
sc_ctl(first="relevant")

# --- R3f-R3k: BOTH supplied identifiers are validated independently (id AND source URL), before anything is merged
def ident_case(tag, lid, override):
    run_id = ident_run(lid, override)
    before = snap(run_id)
    n0 = sc_stats()["counts"].get("item", 0)
    r1 = research.item("lab", {"listing_id": lid})
    n1 = sc_stats()["counts"].get("item", 0)
    r2 = research.item("lab", {"listing_id": lid})
    calls = [c for c in research.run_view(run_id)["calls"] if c["kind"] == "item"]
    return run_id, before, r1, r2, n1 - n0, sc_stats()["counts"].get("item", 0) - n1, calls


for tag, lid, ov, what in (("R3f", "9001", "url_other:9002", "MATCHING id but the source URL names ANOTHER listing"),
                           ("R3g", "9001", "id_other:9002", "WRONG id but the source URL names the requested listing"),
                           ("R3h", "9003", "id_other:9004", "WRONG id with a source URL naming the requested listing (different pair)")):
    run_id, before, r1, r2, sent, resent, calls = ident_case(tag, lid, ov)
    recs = research._load_records(run_id)
    check(f"{tag} {what}: item_identity_mismatch, one counted attempt, nothing merged (searched record, source URL and photos unchanged), identical retry sends nothing",
          code(r1) == "item_identity_mismatch" and code(r2) == "item_identity_mismatch" and sent == 1 and resent == 0 and snap(run_id) == before
          and len(calls) == 1 and calls[0]["outcome"] == "identity_mismatch" and recs[lid]["description"] is None and recs[lid]["photos"] == [],
          (code(r1), code(r2), sent, resent, [c["outcome"] for c in calls], recs[lid].get("source_url"), recs[lid].get("identity")))
    check(f"{tag}b the rejected response never reached the stored source URL (still the searched listing's own URL) and no listing holds the other's description",
          recs[lid]["source_url"].rstrip("/").endswith("/" + lid) and all(r.get("description") is None for r in recs.values()), recs[lid].get("source_url"))

run_id = ident_run("9001", "url_other:9001")   # both identifiers name the requested listing
b = research.item("lab", {"listing_id": "9001"})
check("R3i BOTH identifiers match: accepted as id_match (unchanged behaviour)", b.get("ok") and b["listing"].get("identity") == "id_match"
      and b["listing"]["source_url"].rstrip("/").endswith("/9001"), b)
run_id = ident_run("9002", "no_id_other_url:9002")
b = research.item("lab", {"listing_id": "9002"})
check("R3j MISSING id with a MATCHING URL: accepted as url_match (unchanged)", b.get("ok") and b["listing"].get("identity") == "url_match", b)
# (missing id + WRONG url is R3e; both absent is R3d)

# adjacent: a SEARCH row whose id and URL disagree is the same inconsistency (provenance of one listing stored under another's id)
scope("r-ident-s", api=40, img=5)
sc_ctl(first="relevant", search_url_override={"9002": "9004"})
rid = new_req("identsearch")
research.locate("lab", {"query": "Dallas, TX"})
sr = research.search("lab", {"query": "comforter set", "location_no": 1})
recs = research._load_records(research.run_for("lab", rid)["run_id"])
check("R3k a SEARCH row whose id and source URL name different listings is not stored (the other rows are); the result says one row was dropped",
      sr.get("ok") and "9002" not in recs and set(recs) == {"9001", "9003", "9004"} and sr.get("dropped_conflicting_rows") == 1
      and all(r["listing_id"] != "9002" for r in sr["listings"]), (sorted(recs), sr.get("dropped_conflicting_rows")))
sc_ctl(first="relevant")

# --- R4: redirect boundaries
scope("r-redir", api=60, img=10)
rid = new_req("redir")
research.locate("lab", {"query": "Dallas, TX"})
research.search("lab", {"query": "comforter set", "location_no": 1})
run_id = research.run_for("lab", rid)["run_id"]
sc_ctl(reset=False, api_redirect="localhost")                   # a different host name for the same stand-in server
loc_r = research.locate("lab", {"query": "Austin, TX"})
sea_r = research.search("lab", {"query": "bedding set", "location_no": 1})
ite_r = research.item("lab", {"listing_id": "9001"})
leaks = [r for r in sc_stats()["requests"] if r["kind"] == "leak"]
check("R4 an API redirect is never followed and the credential is never sent elsewhere: locate/search/item answered with a redirect are refused (redirect_refused), "
      "counted once each, and the redirect target received nothing",
      [code(loc_r), code(sea_r), code(ite_r)] == ["redirect_refused"] * 3 and not leaks, ([code(loc_r), code(sea_r), code(ite_r)], leaks))
sc_ctl(reset=False, api_redirect=None)


def photo_case(lid, target, hosts):
    os.environ["ECOM_PHOTO_HOSTS"] = hosts
    sc_ctl(reset=False, photo_redirect={lid: target})
    return research.photo("lab", {"listing_id": lid})


n_cdn = sc_stats()["counts"].get("cdn", 0)
d1 = photo_case("9001", f"http://localhost:{SC}/cdn/9001x.png", "127.0.0.1")
hits = [r for r in sc_stats()["requests"] if r["kind"] == "cdn"]
check("R4b a photo redirect to a host outside the allow-list is refused before it is followed (photo_redirect_refused): the destination received no request",
      code(d1) == "photo_redirect_refused" and all("9001x" not in r["path"] for r in hits) and used("r-redir")["image_used"] == 1, (code(d1), [r["path"] for r in hits]))
d2 = photo_case("9002", f"http://localhost:{SC}/cdn/9002x.png", "127.0.0.1,localhost")
reg = core.db().execute("SELECT host, sha256 FROM research_photos WHERE run_id=? AND listing_id='9002'", (run_id,)).fetchone()
hits = [r for r in sc_stats()["requests"] if r["kind"] == "cdn" and "9002x" in r["path"]]
check("R4c a redirect to ANOTHER permitted host is followed, carries no credential, and the stored host/hash describe the host that actually served the file",
      d2.get("ok") is True and reg is not None and reg["host"] == "localhost" and len(hits) == 1 and hits[0]["has_key"] is False, (code(d2), dict(reg) if reg else None, hits))
os.environ["ECOM_PHOTO_HOSTS"] = "127.0.0.1"
sc_ctl(reset=False, photo_redirect={})
try:
    rules = [research.photo_redirect_ok("https://scontent.xx.fbcdn.net/a.jpg", "http://other.fbcdn.net/b.jpg")[0],        # HTTPS -> HTTP downgrade
             research.photo_redirect_ok("https://scontent.xx.fbcdn.net/a.jpg", "https://evil.example/b.jpg")[0],            # outside the allow-list
             research.photo_redirect_ok("https://scontent.xx.fbcdn.net/a.jpg", "https://scontent-lga3-2.xx.fbcdn.net/b.jpg")[0],   # permitted hop
             research.photo_redirect_ok("https://scontent.xx.fbcdn.net/a.jpg", "file:///etc/passwd")[0]]
except AttributeError:
    rules = None
check("R4d the redirect rule: HTTPS->HTTP downgrade refused, non-allow-listed host refused, another Facebook CDN host over HTTPS allowed, non-HTTP schemes refused",
      rules == [False, False, True, False], rules)

if os.environ.get("RESEARCH_PART_A_ONLY") == "1":   # fast mutation checks of the backend seams
    for p in procs:
        p.terminate()
    shutil.rmtree(TMP, ignore_errors=True)
    print(f"{sum(results)}/{len(results)} checks passed (part A only)")
    sys.exit(0 if results and all(results) else 1)

# ================= B. scripted specialist through the real server and Hermes workers =================
print("PART B: scripted specialist through the real server + workers (scripted LLM policy and ScrapeCreators stand-in; not live, not vision)", flush=True)
for p in procs[1:]:
    pass


def start_server(extra):
    env = {**os.environ, "PYTHONUTF8": "1", "ECOM_CLASSIFIER": "off", **extra}
    for k in ("LLM_PROVIDER", "LLM_MODEL", "NEBIUS_API_KEY", "NEBIUS_BASE_URL", "NEBIUS_MODEL", "ECOM_APP_ROOT", "ECOM_CATALOGUE_FILE", "ECOM_EVIDENCE_FILE", "ECOM_IMAGE_DIRS",
              "ECOM_RESEARCH_SCOPE", "ECOM_RESEARCH_API_MAX", "ECOM_RESEARCH_IMAGE_MAX", "ECOM_RESEARCH_RUN_API_MAX", "ECOM_RESEARCH_RUN_IMAGE_MAX"):
        if k not in extra:
            env.pop(k, None)
    p = subprocess.Popen([sys.executable, "-m", "app.server", str(APP)], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(p)
    wait_up(APP, "/api/status")
    return p


def stop(p):
    p.terminate(); p.wait()


def tool(agent, name, args, rid=None):
    st, r = http(APP, f"/api/chat/{agent}", {"message": "CALL_TOOL:" + json.dumps({"name": name, "args": args}), **({"request_id": rid} if rid else {})})
    outs = [t for t in r.get("tools", []) if t.get("name") == name and t.get("output")]
    return (outs[0]["output"] if outs else None), r


def research_turn(agent, rid, note=""):
    st, r = http(APP, f"/api/chat/{agent}", {"message": f"RESEARCH_AGENT: create one listing draft for acme-cloud-quilt-queen {note}", "request_id": rid})
    steps = []
    for a in r.get("activity", []):
        try:
            args = json.loads(a["input"]) if isinstance(a.get("input"), str) else (a.get("input") or {})
        except ValueError:
            args = {}
        steps.append((a["tool"], args, a["status"]))
    return r, steps


try:
    ENVB = {"ECOM_RESEARCH_SCOPE": "b-main", "ECOM_RESEARCH_API_MAX": "60", "ECOM_RESEARCH_IMAGE_MAX": "20", "ECOM_VISION_MODELS": "nebius-token-factory:mock-model",
            "ECOM_CATALOGUE_FILE": str(FIX / "demo_catalogue.json")}
    shutil.rmtree(ROOT / "runtime", ignore_errors=True)
    (ROOT / "secrets").mkdir(exist_ok=True)
    (ROOT / "secrets" / "local.env").write_text(f"LLM_PROVIDER=nebius-token-factory\nLLM_MODEL=mock-model\nNEBIUS_API_KEY=mock-key\nNEBIUS_BASE_URL=http://127.0.0.1:{MOCK}/v1\n", encoding="utf-8")
    envs = {**os.environ, "PYTHONUTF8": "1"}
    for k in ("ECOM_APP_ROOT", "ECOM_CATALOGUE_FILE", "ECOM_EVIDENCE_FILE"):
        envs.pop(k, None)
    subprocess.run([sys.executable, "scripts/setup.py"], cwd=ROOT, env=envs, check=True, capture_output=True)
    spawn(["tests/mock_llm.py", str(MOCK)], env=envs)
    wait_up(MOCK, "/stats")
    srv = start_server(ENVB)
    stats = lambda: http(MOCK, "/stats")[1]
    http(APP, "/api/company", {"fields": {"name": "Acme Linens (fictional demo)", "products": "Cotton bedding and curtains", "customers": "Home buyers in the US",
                                           "goal": "Understand how competing bedding listings are presented and draft better listings"}})
    BASE = {"role": "market_analysis", "objective": "Turn live Marketplace research into one accurate, source-linked listing draft for the merchant's product.",
            "instructions": "You write listing drafts for Acme Linens (a fictional demo merchant). Research Facebook Marketplace within your allowance, choose comparables yourself, "
                            "and never invent specifications, discounts or delivery terms.",
            "skills": [{"name": "live-listing-research", "content": "# Live listing research\n1. Read the catalogue.\n2. Choose queries from the merchant's market and adapt to results.\n"
                                                                    "3. Detail, photograph and inspect only comparables you judge relevant.\n4. Save one draft and state limits."}]}
    LISTING = ["inspect_image", "read_catalogue", "save_listing_draft"]
    out, r = tool("main", "create_agent", {**BASE, "name": "Live Analyst", "requested_tools": LISTING + MP})
    o = json.loads(out)
    aid = o["agent_id"]
    check("B1 main grants the four marketplace tools through requested_tools together with the listing tools; response and registry agree; mandatory tools remain",
          o["ok"] and sorted(o["granted_tools"]) == sorted(LISTING + MP + ["memory", "read_company_context", "skills"])
          and sorted(http(APP, f"/api/agents/{aid}")[1]["granted_tools"]) == sorted(o["granted_tools"]), o)
    out2, _ = tool("main", "create_agent", {**BASE, "name": "Plain Analyst", "requested_tools": []})
    pid = json.loads(out2)["agent_id"]
    outs = [tool(pid, n, {"query": "x", "location_no": 1, "listing_id": "1"})[1]["text"] for n in MP]
    st, r = http(APP, f"/api/chat/{aid}", {"message": "hi"})
    names_text = r["text"]
    check("B2 an ungranted specialist cannot see or call any marketplace tool; main has none; a granted specialist still has no create_agent/update_company "
          "and no seller-contact or publishing tool exists",
          all("not available" in t for t in outs) and all("not available" in tool("main", n, {})[1]["text"] for n in MP)
          and all(n in names_text for n in MP) and not any(w in names_text for w in ("create_agent", "update_company", "send_message", "contact", "publish", "post_", "terminal", "web_search")), names_text[:300])
    cfg = (ROOT / "runtime" / "hermes_home" / "profiles" / aid / "config.yaml").read_text(encoding="utf-8")
    soul = (ROOT / "runtime" / "hermes_home" / "profiles" / aid / "SOUL.md").read_text(encoding="utf-8")
    check("B2b the specialist's SOUL states the connected Marketplace research and its limits (no stale 'research is not connected'); config disables hidden skill-review requests",
          "marketplace_search" in soul and "finite backend allowance" in soul and "NOT connected" in soul and "Live market research, web access" not in soul
          and "creation_nudge_interval: 0" in cfg, soul[-900:])
    sc_ctl(first="irrelevant")
    st0, n_llm0 = sc_stats()["total"], stats()["requests"]
    r, steps = research_turn(aid, "req-b3")
    queries = [a.get("query") for t, a, s in steps if t == "marketplace_search"]
    names = [t for t, a, s in steps]
    did = next((json.loads(a["output"]).get("draft_id") for a in r.get("activity", []) if a["tool"] == "save_listing_draft" and a["status"] == "ok"), None)
    check("B3 ADAPTATION: an irrelevant first search result makes the specialist change its query (chosen from the observation), then detail, photograph, inspect and save",
          queries == ["queen quilted coverlet", "comforter set"] and names == ["read_catalogue", "marketplace_locate", "marketplace_search", "marketplace_search", "marketplace_item",
                                                                             "marketplace_item", "marketplace_photo", "marketplace_photo", "inspect_image", "inspect_image", "save_listing_draft"]
          and did and "status complete" in r["text"], (queries, names, r.get("text")))
    print("   decisions:", [(t, a.get("query") or a.get("listing_id") or a.get("image_id") or a.get("location_no")) for t, a, s in steps], flush=True)
    run = http(APP, "/api/research/runs?agent_id=" + aid)[1][0]
    rv = http(APP, "/api/research/runs/" + run["run_id"])[1]
    full = http(APP, f"/api/drafts/{did}")[1]
    check("B4 the run API shows the decisions (calls with params/outcome/credits), the retrieved listings and photo hashes, the draft id and the allowance; "
          "the draft carries live provenance and verified (image_part_sent) images",
          [c["kind"] for c in rv["calls"]] == ["location", "search", "search", "item", "item", "photo", "photo"] and rv["draft_ids"] == [did] and len(rv["photos"]) == 2
          and rv["allowance"]["run_api_attempts"] == 5 and rv["allowance"]["run_photo_downloads"] == 2 and full["evidence_source"] == "live_research"
          and full["research_run_id"] == run["run_id"] and all(i["delivery"] == "image_part_sent" and i["counts_as_verified_evidence"] and i["provenance"] == "hash_match"
                                                              and i["kind"] == "live_listing_photo" for i in full["image_evidence"]), (rv["calls"][:3], full.get("status")))
    sc_total = sc_stats()["total"] - st0
    check("B4b every provider request and CDN download the model triggered is accounted for exactly: 5 API attempts + 2 photos in the run = what the scraper stand-in saw",
          sc_total == 7 and sc_stats()["counts"].get("cdn") == 2 and all(r2["has_key"] is False for r2 in sc_stats()["requests"] if r2["kind"] == "cdn"), sc_stats()["counts"])
    blob = json.dumps([r.get("activity"), rv, full])
    check("B4c nothing the specialist, the activity log or the read APIs show contains the API key or a signed photo URL", KEY not in blob and "PRIVATE-SIGNED" not in blob and "oh=" not in blob, blob[:200])
    mem_dir = ROOT / "runtime" / "hermes_home" / "profiles" / aid / "memories"
    mem = "".join(f.read_text(encoding="utf-8") for f in mem_dir.glob("*.md")) if mem_dir.exists() else ""
    check("B5 research records live in app.db, not in the specialist's memory", did not in mem and run["run_id"] not in mem and "9001" not in mem)

    # empty first result -> another step
    sc_ctl(first="empty")
    r, steps = research_turn(aid, "req-b6")
    q = [a.get("query") for t, a, s in steps if t == "marketplace_search"]
    check("B6 an EMPTY first result also leads to a changed query (the stand-in agent reads empty:true), and a second draft is saved from the new run",
          q == ["queen quilted coverlet", "comforter set"] and "Saved draft" in r["text"], (q, r["text"]))
    # provider error on the first candidate + missing photo
    sc_ctl(first="irrelevant", item_fail=["9001"], photo_fail=["9002"])
    r, steps = research_turn(aid, "req-b7")
    items = [(a.get("listing_id"), s) for t, a, s in steps if t == "marketplace_item"]
    photos = [(a.get("listing_id"), s) for t, a, s in steps if t == "marketplace_photo"]
    did7 = next((json.loads(a["output"]).get("draft_id") for a in r.get("activity", []) if a["tool"] == "save_listing_draft" and a["status"] == "ok"), None)
    d7 = http(APP, f"/api/drafts/{did7}")[1] if did7 else {}
    check("B7 a provider error on one candidate and a missing photo for another give an honest outcome: the agent moves to other listings; photo failure is explicit; "
          "the draft that rests on the inspected photos is saved and every failure is visible in the run",
          items[0] == ("9001", "error") and ("9002", "error") in photos and did7 and d7["status"] in ("complete", "partial"), (items, photos, r["text"]))
    rv7 = http(APP, "/api/research/runs?agent_id=" + aid)[1][-1]
    rv7 = http(APP, "/api/research/runs/" + rv7["run_id"])[1]
    check("B7b the failed attempts are persisted with their outcome (provider_error / http_error) and counted", {"provider_error", "http_error"} <= {c["outcome"] for c in rv7["calls"]}, [c["outcome"] for c in rv7["calls"]])
    # every photo fails -> partial draft, never complete
    sc_ctl(first="relevant", photo_fail=["9001", "9002", "9003", "9004"])
    r, steps = research_turn(aid, "req-b8")
    did8 = next((json.loads(a["output"]).get("draft_id") for a in r.get("activity", []) if a["tool"] == "save_listing_draft" and a["status"] == "ok"), None)
    d8 = http(APP, f"/api/drafts/{did8}")[1] if did8 else {}
    check("B8 when no photo can be downloaded the saved draft is an explicit PARTIAL (no verified competitor image), with the reason, never complete",
          did8 and d8["status"] == "partial" and d8["image_evidence"] == [] and any("competitor" in m for m in d8["missing"]), (d8.get("status"), d8.get("missing")))
    sc_ctl(first="irrelevant")
    # model-controlled reset attempts through the real tool path
    before = http(APP, "/api/research/allowance")[1]
    n_sc = sc_stats()["total"]
    o9, r9 = tool(aid, "marketplace_search", {"query": "x", "location_no": 1, "max_requests": 9999, "run_id": "run-0000000000", "reset_allowance": True}, rid="req-b9")
    o10, r10 = tool(aid, "marketplace_photo", {"listing_id": "9001", "url": "https://evil.example/a.png"}, rid="req-b10")
    after = http(APP, "/api/research/allowance")[1]
    check("B9 through the real tool path a model cannot reset or enlarge the allowance, name a run, or pass a URL: invalid_argument, nothing sent, counters unchanged",
          json.loads(o9)["code"] == "invalid_argument" and json.loads(o10)["code"] == "invalid_argument" and sc_stats()["total"] == n_sc and before == after, (o9, o10))
    # duplicate submit
    n_runs = len(http(APP, "/api/research/runs")[1])
    n_sc = sc_stats()["total"]
    st, again = http(APP, f"/api/chat/{aid}", {"message": "RESEARCH_AGENT: create one listing draft for acme-cloud-quilt-queen ", "request_id": "req-b3"})
    check("B10 an intentional retry of a completed request is answered from its stored result: no new run, no provider request, no model request",
          again.get("replayed") is True and len(http(APP, "/api/research/runs")[1]) == n_runs and sc_stats()["total"] == n_sc)
    box = {}
    t = threading.Thread(target=lambda: box.update(r=http(APP, f"/api/chat/{aid}", {"message": "RESEARCH_AGENT: slow " + "x", "request_id": "req-b11"})))
    sc_ctl(first="irrelevant", delay_ms=700)
    t.start()
    time.sleep(1.5)
    st2, busy = http(APP, f"/api/chat/{aid}", {"message": "RESEARCH_AGENT: another", "request_id": "req-b12"})
    t.join()
    sc_ctl(first="irrelevant")
    check("B11 a second request to the same specialist while one runs is rejected (agent_busy) before anything is recorded or spent", st2 == 409 and busy.get("code") == "agent_busy", (st2, busy))

    # allowance exhaustion across requests (new server, tiny scope)
    stop(srv)
    srv = start_server({**ENVB, "ECOM_RESEARCH_SCOPE": "b-tiny", "ECOM_RESEARCH_API_MAX": "6", "ECOM_RESEARCH_IMAGE_MAX": "1"})
    sc_ctl(first="irrelevant")
    n_sc0 = sc_stats()["total"]
    r, steps = research_turn(aid, "req-b13")
    rvt = http(APP, "/api/research/runs/" + http(APP, "/api/research/runs?agent_id=" + aid)[1][-1]["run_id"])[1]
    saved = next((json.loads(a["output"]) for a in r.get("activity", []) if a["tool"] == "save_listing_draft" and a["status"] == "ok"), {})
    check("B12 a photo allowance of 1 stops the second download explicitly (allowance_exhausted); the draft is built on the one inspected photo and says so",
          [t for t, a, s in steps if t == "marketplace_photo"] == ["marketplace_photo", "marketplace_photo"] and sum(1 for t, a, s in steps if t == "marketplace_photo" and s == "ok") == 1
          and rvt["allowance"]["run_photo_downloads"] == 1 and saved.get("ok"), (steps, rvt["allowance"]))
    r, steps = research_turn(aid, "req-b14")
    rv14 = http(APP, "/api/research/runs/" + http(APP, "/api/research/runs?agent_id=" + aid)[1][-1]["run_id"])[1]
    n_after = sc_stats()["total"] - n_sc0
    saved14 = [a for a in r.get("activity", []) if a["tool"] == "save_listing_draft"]
    check("B13 when the scope allowance runs out the specialist gets allowance_exhausted, states the blocker and saves nothing; the provider saw exactly the 6 allowed attempts + 1 photo",
          "BLOCKED" in r["text"] and not saved14 and n_after == 7 and http(APP, "/api/research/allowance")[1][-1]["api_used"] == 6, (r["text"], n_after, steps[-3:]))

    # text-only fallback model path (no vision declaration for a NEW specialist): images are not delivered -> honest partial
    stop(srv)
    srv = start_server({"ECOM_RESEARCH_SCOPE": "b-fallback", "ECOM_RESEARCH_API_MAX": "30", "ECOM_RESEARCH_IMAGE_MAX": "10", "ECOM_CATALOGUE_FILE": str(FIX / "demo_catalogue.json")})
    sc_ctl(first="irrelevant")
    out3, _ = tool("main", "create_agent", {**BASE, "name": "Fallback Analyst", "requested_tools": LISTING + MP})
    fid = json.loads(out3)["agent_id"]
    img0 = stats()["image_requests"]
    r, steps = research_turn(fid, "req-b15")
    did15 = next((json.loads(a["output"]).get("draft_id") for a in r.get("activity", []) if a["tool"] == "save_listing_draft" and a["status"] == "ok"), None)
    d15 = http(APP, f"/api/drafts/{did15}")[1] if did15 else {}
    check("B14 on a model path without image support no pixels reach the model and the live draft is PARTIAL with delivery text_fallback (supported-vision status preserved)",
          stats()["image_requests"] == img0 and d15 and d15["status"] == "partial" and d15["image_evidence"] and all(i["delivery"] == "text_fallback" for i in d15["image_evidence"]), (d15.get("status"), d15.get("missing")))

    # restart: saved drafts and research records come back with no inference and no scraping
    stop(srv)
    srv = start_server({"ECOM_SCRAPECREATORS_URL": "http://127.0.0.1:9", "ECOM_EVIDENCE_FILE": str(TMP / "gone.json"), "ECOM_CATALOGUE_FILE": str(FIX / "demo_catalogue.json")})
    time.sleep(4)
    n_llm, n_sc = stats()["requests"], sc_stats()["total"]
    full2 = http(APP, f"/api/drafts/{did}")[1]
    lst = http(APP, "/api/drafts")[1]
    rv2 = http(APP, "/api/research/runs/" + run["run_id"])[1]
    check("B15 after a restart the live draft, its supporting evidence and its research run (calls, photo hashes, allowance) are retrieved unchanged with ZERO model and ZERO scraper requests",
          full2 == full and rv2["calls"] == rv["calls"] and rv2["photos"] == rv["photos"] and did in [x["draft_id"] for x in lst]
          and stats()["requests"] == n_llm and sc_stats()["total"] == n_sc, (full2 == full, rv2 == rv))
    check("B16 the saved live draft reads as live research with its run id after the restart",
          full2["evidence_source"] == "live_research" and full2["research_run_id"] == run["run_id"])
finally:
    for p in procs:
        try:
            p.terminate()
        except Exception:
            pass
    shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{sum(results)}/{len(results)} checks passed (scripted stand-ins only: NOT live retrieval, NOT vision, NOT model quality)")
sys.exit(0 if results and all(results) else 1)
