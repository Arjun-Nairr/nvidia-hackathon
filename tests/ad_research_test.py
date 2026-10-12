"""V2-03 tests: Facebook image-ad research for the independent social_media specialist. Everything here uses SCRIPTED stand-ins: tests/mock_fb_ads.py (invented
documented-shape payloads and a local 'CDN') and tests/mock_llm.py (a rule-based ad-research policy, not a model). It proves backend behaviour, grants, budgets,
provenance and wiring; it is NOT live retrieval, NOT real US ad data, NOT real reach and NOT model quality or vision quality.
Part A: public backend seams in-process (isolated app root, real SQLite, real tool bodies, real HTTP to the stand-in).
Part B: the scripted specialist through the REAL server, HTTP chat API and Hermes workers (classifier off).
Wipes the copy's runtime/ in part B - run ONLY from a COPY of the project:
  ADS_I_AM_A_COPY=1 venv-python tests/ad_research_test.py"""
import hashlib, importlib.util, json, os, re, shutil, subprocess, sys, tempfile, time, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if os.environ.get("ADS_I_AM_A_COPY") != "1":
    sys.exit("Refusing to run: set ADS_I_AM_A_COPY=1 and run from a COPY of the project.")
os.environ["HERMES_HOME"] = str(ROOT / "runtime" / "hermes_home" / "profiles" / "main")   # project-local, before any profile operation
FIX = ROOT / "tests" / "fixtures"
TMP = Path(tempfile.mkdtemp(prefix="ads_"))
FB, MOCK, APP = 8792, 8779, 8828
KEY = "TEST-KEY-SENTINEL-0123456789"
os.environ.update({"ECOM_APP_ROOT": str(TMP), "ECOM_SCRAPECREATORS_URL": f"http://127.0.0.1:{FB}", "ECOM_PHOTO_HOSTS": "127.0.0.1", "SCRAPECREATORS_API_KEY": KEY,
                   "ECOM_CATALOGUE_FILE": str(FIX / "demo_catalogue.json"), "ECOM_EVIDENCE_FILE": str(FIX / "marketplace_sample.json")})
for k in ("ECOM_ADS_SCOPE", "ECOM_ADS_API_MAX", "ECOM_ADS_IMAGE_MAX", "ECOM_ADS_RUN_API_MAX", "ECOM_ADS_RUN_IMAGE_MAX", "ECOM_ADS_MEDIA_TYPE", "ECOM_IMAGE_DIRS",
          "ECOM_RESEARCH_SCOPE"):
    os.environ.pop(k, None)
sys.path.insert(0, str(ROOT))
from app import ads, core, turn_state, hermes_plugin as hp

_spec = importlib.util.spec_from_file_location("mock_fb_ads", ROOT / "tests" / "mock_fb_ads.py")
FBM = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(FBM)

results, procs = [], []
import atexit
atexit.register(lambda: [p.terminate() for p in procs if p.poll() is None])


def check(name, ok, detail=""):
    ok = bool(ok); results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{str(detail)[:700]}]"), flush=True)


def http(port, path, body=None, timeout=600, raw=False):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        data = r.read()
        return r.status, (data if raw else json.loads(data))
    except urllib.error.HTTPError as e:
        data = e.read()
        return e.code, (data if raw else json.loads(data))


def fb_ctl(reset=True, **kw):
    return http(FB, "/control", {"reset": reset, **kw})[1]


def fb_stats():
    return http(FB, "/stats")[1]


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


spawn(["tests/mock_fb_ads.py", str(FB)])
wait_up(FB)
core.update_company({"name": "Acme Linens", "products": "Cotton bedding", "customers": "Home buyers in the US", "goal": "Present our bedding clearly"}, source="form")
AD6 = list(core.AD_TOOLS)
SOC_FULL = AD6 + ["inspect_image", "read_catalogue"]


def register(agent_id, tools, role="social_media"):
    with core.db() as d:
        d.execute("INSERT OR REPLACE INTO agents VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (agent_id, agent_id, role, "default", "o", "i", "[]", "[]", json.dumps(sorted(set(tools) | {"read_company_context", "memory", "skills"})), "[]",
                   f"conv-{agent_id}", "idle", time.time()))


register("soc", SOC_FULL)
register("soc-noad", ["inspect_image", "read_catalogue"])
register("ana", AD6 + ["marketplace_search"], role="market_analysis")   # an analyst whose stored grants were (wrongly) edited to hold ad tools: the role gate still refuses


def req(rid, agent="soc"):
    turn_state.request_id, turn_state.run_id, turn_state.ad_run_id = rid, None, None
    os.environ["ECOM_AGENT_ID"] = agent


def code(r):
    return r.get("code") if isinstance(r, dict) and r.get("ok") is False else ("OK" if isinstance(r, dict) and r.get("ok") else r)


def scope(name, api=None, img=None, run_api=None, run_img=None):
    os.environ["ECOM_ADS_SCOPE"] = name
    for k, v in (("ECOM_ADS_API_MAX", api), ("ECOM_ADS_IMAGE_MAX", img), ("ECOM_ADS_RUN_API_MAX", run_api), ("ECOM_ADS_RUN_IMAGE_MAX", run_img)):
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = str(v)


def used(name):
    return next((a for a in ads.allowances() if a["scope"] == name), None)


def n_req(kinds=None):
    s = fb_stats()
    return s["total"] if kinds is None else sum(s["counts"].get(k, 0) for k in kinds)


turn_state.vision_probe = lambda: "image_part_sent"
A = lambda agent, tool, args: getattr(ads, tool)(agent, args)

# ================= A. public backend seams =================
print("PART A: backend seams (scripted Facebook-ads stand-in; not live)", flush=True)
scope("a-main", api=50, img=10)
fb_ctl(first="irrelevant")
req("req-a1")
F1 = ads.find_advertiser("soc", {"query": "Harbor Home Linens"})
S1 = ads.search("soc", {"query": "home organisation tips"})
rows1 = S1.get("ads") or []
st = fb_stats()
check("A1 advertiser lookup returns numbered candidates (no page id), allowance reported; the API key travels only in the API header",
      F1["ok"] and F1["advertisers"][0]["advertiser_no"] == 1 and F1["advertisers"][0]["name"] == "Harbor Home Linens" and "page_id" not in F1["advertisers"][0]
      and F1["allowance"]["api_attempts_left"] == 7 and all(r["has_key"] for r in st["requests"] if r["kind"] != "cdn"), (F1, st["requests"][:2]))
check("A2 an irrelevant first result is returned as it is (no backend ranking/filtering); fixed US + image media type + status are sent; public source links keep 16-digit ids",
      S1["ok"] and [a["advertiser"]["name"] for a in rows1] == ["Quick Auto Parts", "Slice Pizza Co"] and rows1[0]["source_ad_id"] == "1200000000000001"
      and rows1[0]["source_url"] == "https://www.facebook.com/ads/library?id=1200000000000001"
      and st["requests"][1]["params"] == {"country": "US", "media_type": "IMAGE_AND_MEME", "status": "ACTIVE", "query": "home organisation tips", "search_type": "keyword_unordered"}
      and S1["reach_gate"]["state"] == "disabled_reach_unavailable", (rows1, st["requests"][1]))
S2 = ads.search("soc", {"query": "queen quilted coverlet"})
ids = [(a["ad_no"], a["source_ad_id"]) for a in S2["ads"]]
by = {a["source_ad_id"]: a for a in S2["ads"]}
blob = json.dumps([F1, S1, S2])
check("A3 a refined search finds relevant ads: four DISTINCT ad ids (campaign grouping and cards do not merge or add ads); campaign recorded separately; no signed URL or key leaks",
      [i[1] for i in ids] == ["1100000000000001", "1100000000000002", "1100000000000003", "1100000000000004"] and len({i[0] for i in ids}) == 4
      and by["1100000000000001"]["campaign"]["campaign_id"] == by["1100000000000002"]["campaign"]["campaign_id"] == "5000000000000001"
      and by["1100000000000001"]["campaign"]["campaign_ad_count"] == 2 and by["1100000000000001"]["campaign"]["recorded_ad_nos_in_campaign"] == [3, 4]
      and by["1100000000000004"]["campaign"]["campaign_id"] is None, (ids, by["1100000000000001"]["campaign"]))
check("A3b the carousel ad is ONE ad with variants: its three cards are counted as cards/images of that ad, never as extra ads; nothing private in any output",
      len(S2["ads"]) == 4 and by["1100000000000003"]["image_count"] == 3 and by["1100000000000003"]["card_count"] == 3
      and "PRIVATE-SIGNED" not in blob and KEY not in blob and "utm=" not in blob, (by["1100000000000003"], blob[:200]))
ad1, ad3 = by["1100000000000001"]["ad_no"], by["1100000000000003"]["ad_no"]
D1 = ads.detail("soc", {"ad_no": ad1})
D3 = ads.detail("soc", {"ad_no": ad3})
check("A4 ad detail (camelCase fields, numeric adArchiveID) is identity-checked against the requested ad, merged into the same record, keeps campaign/cards, reach stays unavailable",
      D1["ok"] and D1["ad"]["detail_level"] == "detailed" and D1["ad"]["identity"] == "id_match" and D1["ad"]["source_ad_id"] == "1100000000000001"
      and D1["ad"]["reach"]["state"] == "unavailable" and D1["ad"]["reach"]["source"] == "not_provided" and D1["reach_gate"]["state"] == "disabled_reach_unavailable"
      and D3["ad"]["card_count"] == 3 and [c["title"] for c in D3["ad"]["cards"]] == ["Quilt set", "Sheet set", "Pillow shams"]
      and D3["ad"]["landing_domain"] == "example.com" and "utm=" not in json.dumps(D3), (D1.get("code"), D1.get("ad")))
IM1 = ads.image("soc", {"ad_no": ad1, "image_no": 1})
IM3 = ads.image("soc", {"ad_no": ad3, "image_no": 2})
cdn = [r for r in fb_stats()["requests"] if r["kind"] == "cdn"]
rid_a = ads.run_for("soc", "req-a1")["run_id"]
check("A5 an image download registers a managed image id (ad-<ad id>-<n>) with hash and size, is stored under the run, and reaches the CDN WITHOUT any API credential",
      IM1["ok"] and IM1["image_id"] == "ad-1100000000000001-1" and len(IM1["sha256"]) == 64 and IM3["image_id"] == "ad-1100000000000003-2" and len(cdn) == 2
      and all(c["has_key"] is False for c in cdn) and (ads.image_dir(rid_a) / "ad-1100000000000001-1.png").is_file()
      and hashlib.sha256((ads.image_dir(rid_a) / "ad-1100000000000001-1.png").read_bytes()).hexdigest() == IM1["sha256"], (IM1, cdn))
n0 = n_req()
D1b, IM1b, S2b = ads.detail("soc", {"ad_no": ad1}), ads.image("soc", {"ad_no": ad1, "image_no": 1}), ads.search("soc", {"query": "queen quilted coverlet"})
check("A6 identical successful detail/image/search calls are answered from the run store: nothing re-sent, nothing re-counted",
      D1b.get("cached") and IM1b.get("cached") and S2b.get("cached") and n_req() == n0 and S2b["allowance"] == ads.allowance_view(rid_a), (D1b.get("cached"), n_req(), n0))
rv = ads.run_view(rid_a)
check("A7 the run records every call (kind, endpoint, outcome, credits, ms), the ads recorded and the image hash; counts are attempts, not ads",
      [c["kind"] for c in rv["calls"]] == ["advertiser", "search", "search", "detail", "detail", "image", "image"] and all(c["outcome"] == "ok" for c in rv["calls"])
      and rv["accounting"]["scraper_attempts"] == 5 and rv["accounting"]["image_download_attempts"] == 2 and rv["ads_recorded"] == 6
      and rv["accounting"]["by_kind"]["search"]["attempts"] == 2 and len(rv["images"]) == 2 and "PRIVATE-SIGNED" not in json.dumps(rv), rv["accounting"])

# --- arguments, grants, identity
n0, a0 = n_req(), used("a-main")
bad = [ads.search("soc", {"query": "x", **extra}) for extra in ({"country": "GB"}, {"max_requests": 999}, {"run_id": "adrun-0123456789"}, {"reset_allowance": True},
                                                                 {"api_key": "x"}, {"url": "https://evil.example/x"}, {"page_id": "1001"}, {"cursor": "abc"})]
bad += [ads.detail("soc", {"ad_no": ad1, "budget": 100}), ads.image("soc", {"ad_no": ad1, "image_no": 1, "url": "https://evil.example/x.png"}),
        ads.find_advertiser("soc", {"query": "Harbor", "scope": "other"}), ads.save_package("soc", {"summary": "x" * 50, "selection_basis": "relevance_only", "run_id": "r"})]
check("A8 a tool call cannot carry country, page id, cursor, allowance, run, credential or URL arguments: invalid_argument, nothing sent, allowance unchanged",
      all(code(b) == "invalid_argument" for b in bad) and n_req() == n0 and used("a-main") == a0, [code(b) for b in bad])
bad2 = [ads.search("soc", {}), ads.search("soc", {"query": "a", "advertiser_no": 1}), ads.detail("soc", {"ad_no": "https://evil.example/ad"}), ads.detail("soc", {"ad_no": True}),
        ads.image("soc", {"ad_no": ad1, "image_no": "1"}), ads.search("soc", {"query": "quilt", "status": "DELETED"}), ads.search("soc", {"query": "quilt", "order": "total_impressions"})]
check("A8b malformed inputs are corrective errors: neither/both query and advertiser_no, URL or bool ad_no, string image_no, bad enum values - nothing sent",
      all(code(b) == "bad_argument" for b in bad2) and n_req() == n0, [code(b) for b in bad2])
c_ng = code(ads.find_advertiser("soc-noad", {"query": "Harbor"}))
c_ma = code(ads.find_advertiser("ana", {"query": "Harbor"}))
c_gh = code(ads.find_advertiser("ghost", {"query": "Harbor"}))
req(None)
c_nr = code(ads.find_advertiser("soc", {"query": "Harbor"}))
req("req-a1")
check("A9 an ungranted social specialist, a market-analysis agent (even with edited grants), an unregistered agent and a call outside a manual request are refused before anything is spent",
      c_ng == "not_granted" and c_ma == "not_permitted_for_role" and c_gh == "unknown_agent" and c_nr == "no_manual_request" and n_req() == n0, (c_ng, c_ma, c_gh, c_nr))
check("A10 unknown ad/advertiser numbers (not returned by this request's searches) and unknown image numbers cannot be requested; nothing sent",
      code(ads.detail("soc", {"ad_no": 999})) == "unknown_ad" and code(ads.image("soc", {"ad_no": 999, "image_no": 1})) == "unknown_ad"
      and code(ads.image("soc", {"ad_no": ad1, "image_no": 7})) == "unknown_image" and code(ads.search("soc", {"advertiser_no": 9})) == "unknown_advertiser" and n_req() == n0)

# --- allowance
scope("a-tiny", api=3, img=1)
req("req-t1")
fb_ctl(first="irrelevant")
r1 = ads.find_advertiser("soc", {"query": "Harbor"})
r2 = ads.search("soc", {"query": "coverlet"})
fb_ctl(reset=False, search_status=500)
r3 = ads.search("soc", {"query": "different words"})     # a FAILURE: still counted
fb_ctl(reset=False, search_status=None)
n0 = n_req()
r4 = ads.search("soc", {"query": "comforter set"})
check("A11 failures are counted: with an allowance of 3, advertiser lookup + search + a provider error use it; the 4th attempt is refused with nothing sent",
      r1["ok"] and r2["ok"] and code(r3) == "provider_error" and code(r4) == "allowance_exhausted" and n_req() == n0 and used("a-tiny")["api_used"] == 3, (code(r3), code(r4)))
os.environ["ECOM_ADS_API_MAX"] = "500"                    # raising the environment later does not re-size an existing scope
req("req-t2")
r5 = ads.find_advertiser("soc", {"query": "Harbor"})
req("req-t3")
r6 = ads.find_advertiser("soc", {"query": "Northwind"})
check("A12 an existing scope's cap cannot be raised by configuration, and new requests (new runs) do not refresh it: still exhausted",
      code(r5) == "allowance_exhausted" and code(r6) == "allowance_exhausted" and used("a-tiny")["api_max"] == 3 and used("a-tiny")["api_used"] == 3, (code(r5), used("a-tiny")))
req("req-t1")
check("A12b the same request cannot open a replacement run: one run per (agent, request)",
      ads.open_run("soc", "req-t1")["run_id"] == ads.run_for("soc", "req-t1")["run_id"] and len([r for r in ads.list_runs("soc") if r["scope"] == "a-tiny"]) == 3)
scope("a-runcap", api=50, img=10, run_api=2)
req("req-r1")
x = [ads.find_advertiser("soc", {"query": q}) for q in ("Harbor", "Northwind", "Quick")]
req("req-r2")
y = ads.find_advertiser("soc", {"query": "Harbor"})
check("A13 the per-request cap (default 8 attempts / 4 images, configurable) applies inside a larger scope allowance, and a later request gets its own run",
      x[0]["ok"] and x[1]["ok"] and code(x[2]) == "allowance_exhausted" and "request's" in x[2]["error"] and y["ok"]
      and ads.DEFAULTS["run_api"] == 8 and ads.DEFAULTS["run_images"] == 4, [code(i) for i in x])
scope("a-defaults")
os.environ.pop("ECOM_ADS_RUN_API_MAX", None)
req("req-def")
ads.find_advertiser("soc", {"query": "Harbor"})
dv = ads.allowance_view(ads.run_for("soc", "req-def")["run_id"])
check("A13b with no override a manual request is capped at 8 scraper attempts and 4 image downloads (the model cannot change it)", dv["run_api_max"] == 8 and dv["run_image_max"] == 4, dv)

# --- concurrency (real processes sharing the app database)
scope("a-conc", api=10, img=10)
fb_ctl(first="irrelevant")
CHILD = r'''
import json, os, sys
sys.path.insert(0, os.environ["ROOT_DIR"])
from app import ads, turn_state
turn_state.request_id = "req-conc-" + sys.argv[1]
os.environ["ECOM_AGENT_ID"] = "soc"
out = []
for j in range(4):
    r = ads.find_advertiser("soc", {"query": f"brand {sys.argv[1]} {j}"})
    out.append("OK" if r.get("ok") else r.get("code"))
print(json.dumps(out))
'''
env = {**os.environ, "PYTHONUTF8": "1", "ROOT_DIR": str(ROOT)}
n0 = n_req()
kids = [subprocess.Popen([sys.executable, "-c", CHILD, str(i)], env=env, stdout=subprocess.PIPE, text=True) for i in range(4)]
outs = [json.loads(k.communicate()[0].strip().splitlines()[-1]) for k in kids]
flat = [x for o in outs for x in o]
check("A14 four processes racing for a 10-attempt scope send exactly 10 requests and are refused the rest (atomic reservation, no overspend)",
      flat.count("OK") == 10 and flat.count("allowance_exhausted") == 6 and n_req() - n0 == 10 and used("a-conc")["api_used"] == 10, (flat, n_req() - n0, used("a-conc")))

# --- unknown outcome is never replayed
scope("a-drop", api=20, img=10)
fb_ctl(first="irrelevant", drop=["search"])
req("req-d1")
d1 = ads.search("soc", {"query": "queen coverlet"})
n0 = n_req()
d2 = ads.search("soc", {"query": "queen coverlet"})
fb_ctl(reset=False, drop=[])
d3 = ads.search("soc", {"query": "queen coverlet"})
check("A15 a request whose outcome is unknown (connection dropped) is counted, reported honestly and NOT replayed - not by the backend and not by an identical retry",
      code(d1) == "network_error" and code(d2) == "uncertain_previous_attempt" and code(d3) == "uncertain_previous_attempt" and n_req() == n0, (code(d1), code(d2), code(d3)))
d4 = ads.search("soc", {"query": "comforter set"})
c = core.db()
rid_d = ads.run_for("soc", "req-d1")["run_id"]
no_d = ads._store_ads(rid_d, 1, [ads.norm_ad({"ad_archive_id": "1100000000000004", "page_id": "1003", "snapshot": {}}, "keyword", 1, "t")])[0]
c.execute("INSERT INTO ad_calls(run_id, kind, endpoint, params, params_key, status, ts) VALUES(?,?,?,?,?,?,?)",
          (rid_d, "detail", "detail", '{"id": "1100000000000004"}', ads._pkey({"endpoint": "detail", "id": "1100000000000004"}), "reserved", time.time()))
c.commit()
c.close()
n0 = n_req()
d5 = ads.detail("soc", {"ad_no": no_d})
check("A16 a crash leaves a 'reserved' call: the identical request is refused (outcome unknown), still counted, never re-sent",
      d4["ok"] and code(d5) == "uncertain_previous_attempt" and n_req() == n0, (code(d5), n_req(), n0))

# --- images: failure, redirect, allowance
scope("a-img", api=40, img=3)
fb_ctl(first="relevant", image_fail=["1100000000000002-1"], image_html=["1100000000000004-1"],
       image_redirect={"1100000000000001-1": f"http://evil.example:{FB}/stolen.png"})
req("req-i1")
S = ads.search("soc", {"query": "bedding"})
no = {a["source_ad_id"]: a["ad_no"] for a in S["ads"]}
i1 = ads.image("soc", {"ad_no": no["1100000000000001"], "image_no": 1})     # redirect to a host that is not on the CDN allow-list
i2 = ads.image("soc", {"ad_no": no["1100000000000002"], "image_no": 1})     # 404
i3 = ads.image("soc", {"ad_no": no["1100000000000004"], "image_no": 1})     # an HTML page, not an image
i4 = ads.image("soc", {"ad_no": no["1100000000000003"], "image_no": 1})     # fourth attempt > allowance of 3
rvi = ads.run_view(ads.run_for("soc", "req-i1")["run_id"])
check("A17 unusable images fail explicitly and are counted (redirect to a non-CDN host, 404, HTML page); the image allowance stops the 4th download; nothing reached the redirect host",
      code(i1) == "image_redirect_refused" and code(i2) == "image_unavailable" and code(i3) == "image_unavailable" and code(i4) == "allowance_exhausted"
      and [c["outcome"] for c in rvi["calls"] if c["kind"] == "image"] == ["redirect_refused", "http_error", "not_image"] and rvi["images"] == [], [code(i) for i in (i1, i2, i3, i4)])
check("A17b a failed download leaves no registered file: inspect_image cannot see it",
      core.prepare_image("ad-1100000000000002-1")["code"] == "image_not_found", core.prepare_image("ad-1100000000000002-1"))

# --- API redirect never forwards the credential
scope("a-redir", api=10, img=3)
fb_ctl(first="irrelevant", api_redirect="127.0.0.1")
req("req-x1")
x1 = ads.search("soc", {"query": "queen coverlet"})
leak = [r for r in fb_stats()["requests"] if r["kind"] == "leak"]
check("A18 a redirecting API endpoint is refused and counted: the credential is never sent to the redirect target, and nothing is retried",
      code(x1) == "redirect_refused" and leak == [] and used("a-redir")["api_used"] == 1, (code(x1), leak))

# --- identity validation
scope("a-ident", api=30, img=5)
fb_ctl(first="relevant", detail_override={"1100000000000001": "wrong:1100000000000004", "1100000000000002": "url_other:1100000000000004",
                                       "1100000000000003": "page_other:1003", "1100000000000004": "no_id"})
req("req-id1")
S = ads.search("soc", {"query": "bedding"})
no = {a["source_ad_id"]: a["ad_no"] for a in S["ads"]}
dd = {k: ads.detail("soc", {"ad_no": v}) for k, v in no.items()}
n0 = n_req()
again = ads.detail("soc", {"ad_no": no["1100000000000001"]})
rec1 = ads._load_ads(ads.run_for("soc", "req-id1")["run_id"])
check("A19 each identifier the detail response supplies is checked: another ad's id, another ad's id in its URL and another page are refused (counted, merged nowhere); "
      "a response with no id is accepted but flagged unconfirmed; the identical request is not replayed",
      code(dd["1100000000000001"]) == "ad_identity_mismatch" and code(dd["1100000000000002"]) == "ad_identity_mismatch" and code(dd["1100000000000003"]) == "ad_identity_mismatch"
      and dd["1100000000000004"]["ok"] and dd["1100000000000004"]["ad"]["identity"] == "unconfirmed_no_id_in_response" and "identity_note" in dd["1100000000000004"]
      and code(again) == "ad_identity_mismatch" and n_req() == n0
      and all(rec1[no[k]]["detail_level"] == "list_only" for k in ("1100000000000001", "1100000000000002", "1100000000000003")), [code(v) for v in dd.values()])

# --- reach fixtures: absent / ambiguous / present
scope("a-reach", api=40, img=5)
req("req-re1")
fb_ctl(first="relevant", reach="ambiguous")
S = ads.search("soc", {"query": "bedding"})
no = {a["source_ad_id"]: a["ad_no"] for a in S["ads"]}
d_amb = ads.detail("soc", {"ad_no": no["1100000000000001"]})
amb = d_amb["ad"]["reach"]
check("A20 AMBIGUOUS reach: a bare reach_estimate is preserved with its raw value and field name but classified ambiguous, gives no geography/period, and the gate stays disabled",
      amb["state"] == "ambiguous" and amb["metric"] == "reach_estimate" and amb["provider_value"] == 11500 and amb["value"] is None and amb["geography"] is None
      and S["reach_gate"]["state"] == "disabled_reach_ambiguous" and S["reach_gate"]["ranking_enabled"] is False and d_amb["reach_gate"]["ads_with_ambiguous_reach"] >= 1, (amb, S["reach_gate"]))
req("req-re2")
fb_ctl(first="relevant", reach="present")
S = ads.search("soc", {"query": "bedding"})
no = {a["source_ad_id"]: a["ad_no"] for a in S["ads"]}
g0 = S["reach_gate"]["state"]
dp1 = ads.detail("soc", {"ad_no": no["1100000000000001"]})
g1 = dp1["reach_gate"]["state"]
dp2 = ads.detail("soc", {"ad_no": no["1100000000000004"]})
pr = dp1["ad"]["reach"]
check("A21 PRESENT reach (Meta's documented eu_total_reach on detail): kept with metric, value and EU geography, period unstated; the gate needs two comparable values "
      "(list-only ads carry none) and then enables ranking only for that metric/geography",
      pr["state"] == "reported" and pr["metric"] == "eu_total_reach" and pr["value"] == 27000 and pr["geography"] == "EU" and pr["period"] is None and "NOT US reach" in pr["meaning"]
      and g0 == "disabled_reach_unavailable" and g1 == "disabled_single_value" and dp2["reach_gate"]["state"] == "enabled" and dp2["reach_gate"]["ranking_enabled"]
      and dp2["reach_gate"]["metric"] == "eu_total_reach" and dp2["reach_gate"]["geography"] == "EU" and dp2["reach_gate"]["ads_recorded"] == 4, (pr, g0, g1, dp2["reach_gate"]))
req("req-re3")
fb_ctl(first="relevant", reach="absent")
S = ads.search("soc", {"query": "bedding"})
check("A22 ABSENT reach: nulls (including impressions_index -1) stay unknown, never zero; gate disabled_reach_unavailable; relevant ads are still returned for visual research",
      S["reach_gate"]["state"] == "disabled_reach_unavailable" and len(S["ads"]) == 4 and all(a["reach"]["state"] == "unavailable" and a["reach"]["value"] is None for a in S["ads"])
      and all("other_metrics" not in a for a in S["ads"]), S["reach_gate"])

# impressions/spend are available metrics, not reach: persisted and labelled, never ranked
scope("a-imp", api=30, img=4)
fb_ctl(first="relevant", reach="impressions")
req("req-im1")
S = ads.search("soc", {"query": "bedding"})
ni = S["ads"][0]["ad_no"]
DI = ads.detail("soc", {"ad_no": ni})
IMI = ads.image("soc", {"ad_no": ni, "image_no": 1})
hp._inspect_image({"image_id": IMI["image_id"]})
PI = ads.save_package("soc", {**{"summary": "One reference from a fixture ad that carries impressions and spend but no reach.", "selection_basis": "relevance_only"},
                              "references": [{"ad_no": ni, "image_id": IMI["image_id"], "why_relevant": "A quilted bedding ad that is relevant to the merchant's product type.",
                                              "visual_features": ["large product shot"], "observations": "The image shows a quilted coverlet on a plain background."}]})
pim = ads.get_package(PI["package_id"])
check("A22b IMPRESSIONS/SPEND are persisted as available metrics with a 'not reach' label but are never reach: the ad's reach stays unavailable and the gate stays disabled",
      DI["ad"]["reach"]["state"] == "unavailable" and DI["ad"]["other_metrics"]["impressions_text"] == "1K-5K" and DI["ad"]["other_metrics"]["spend"] == {"lower_bound": 100, "upper_bound": 199}
      and "NOT reach" in DI["ad"]["other_metrics"]["note"] and DI["reach_gate"]["state"] == "disabled_reach_unavailable" and PI["ok"]
      and pim["cited_ads"][0]["other_metrics"]["impressions_index"] == 3 and pim["reach_gate"]["ranking_enabled"] is False and pim["cited_ads"][0]["reach"]["value"] is None,
      (DI.get("ad", {}).get("other_metrics"), PI))

# --- odd provider rows
scope("a-odd", api=30, img=5)
fb_ctl(first="relevant", include_video=True, dup_rows=True, no_id_row=True)
req("req-od1")
S = ads.search("soc", {"query": "bedding"})
check("A23 a video ad, a repeated row and a row without an ad id are not offered as image ads and are disclosed (not silently dropped, not counted as extra ads)",
      S["ok"] and len(S["ads"]) == 4 and S["skipped"] == {"dropped_without_id": 1, "duplicates_in_response": 1, "excluded_video_ads": 1}
      and "1300000000000001" not in json.dumps(S["ads"]), S.get("skipped"))
fb_ctl(first="empty", never_relevant=True)
req("req-od2")
S = ads.search("soc", {"query": "queen quilted coverlet"})
check("A24 an empty result is explicit (empty=true with a note to change the query), counted, and has no ads", S["ok"] and S.get("empty") is True and S["ads"] == [] and "Change the query" in S["note"])

# --- storage failure: sent and counted, not kept, never re-sent
scope("a-store", api=30, img=5)
fb_ctl(first="relevant")
req("req-s1")
real_store = ads._store_ads
ads._store_ads = lambda *a, **k: (_ for _ in ()).throw(OSError("disk full (injected)"))
n0 = n_req()
s1 = ads.search("soc", {"query": "bedding"})
ads._store_ads = real_store
n1 = n_req()
s2 = ads.search("soc", {"query": "bedding"})
rs = ads.run_view(ads.run_for("soc", "req-s1")["run_id"])
check("A25 a failed local save after a successful search: reported as sent+counted+not saved, never re-sent, outcome ok_unsaved; the identical retry is refused with storage_error",
      code(s1) == "storage_error" and n1 - n0 == 1 and code(s2) == "storage_error" and n_req() == n1 and rs["calls"][0]["outcome"] == "ok_unsaved" and rs["ads_recorded"] == 0, (code(s1), code(s2)))
S = ads.search("soc", {"query": "comforter set"})
no = {a["source_ad_id"]: a["ad_no"] for a in S["ads"]}
blocker = ads.image_dir(ads.run_for("soc", "req-s1")["run_id"])
blocker.parent.mkdir(parents=True, exist_ok=True)
blocker.write_text("not a directory")           # the image folder cannot be created
n0 = n_req(["cdn"])
im = ads.image("soc", {"ad_no": no["1100000000000001"], "image_no": 1})
im2 = ads.image("soc", {"ad_no": no["1100000000000001"], "image_no": 1})
check("A26 a download that cannot be stored is counted and reported (storage_error) and NOT downloaded again",
      code(im) == "storage_error" and code(im2) == "storage_error" and n_req(["cdn"]) - n0 == 1, (code(im), code(im2), n_req(["cdn"]) - n0))

# --- saved package: validation, content, retrieval
scope("a-pkg", api=40, img=6)
fb_ctl(first="irrelevant", reach="absent")
req("req-p1")
pk_none = ads.save_package("soc", {"summary": "x" * 50, "selection_basis": "relevance_only", "references": [], "blocker": "z" * 30})
S0 = ads.search("soc", {"query": "home organisation tips"})
S = ads.search("soc", {"query": "queen quilted coverlet"})
no = {a["source_ad_id"]: a["ad_no"] for a in S["ads"]}
n1_, n3_ = no["1100000000000001"], no["1100000000000003"]
ads.detail("soc", {"ad_no": n1_})
ads.detail("soc", {"ad_no": n3_})
ia, ib = ads.image("soc", {"ad_no": n1_, "image_no": 1}), ads.image("soc", {"ad_no": n3_, "image_no": 2})
base = {"summary": "Researched US Facebook image ads for quilted bedding and selected two references from different campaigns.", "selection_basis": "relevance_only"}
ref = lambda n, i, **kw: {"ad_no": n, "image_id": i, "why_relevant": "A quilted bedding ad whose layout shows what shoppers meet for this product.",
                         "visual_features": ["product large on plain backdrop"], "observations": "The image shows a quilted coverlet on a pale background with a headline.", **kw}
notinsp = ads.save_package("soc", {**base, "references": [ref(n1_, ia["image_id"])]})
hp._inspect_image({"image_id": ia["image_id"]})                  # the real inspect_image tool body: trusted inspection log
hp._inspect_image({"image_id": ib["image_id"]})
unreg = ads.save_package("soc", {**base, "references": [ref(n1_, "ad-1100000000000004-1")]})
wrongad = ads.save_package("soc", {**base, "references": [ref(n3_, ia["image_id"])]})
rr = ads.save_package("soc", {**base, "selection_basis": "reach_ranked", "references": [ref(n1_, ia["image_id"])]})
claim = ads.save_package("soc", {**base, "summary": "This ad clearly performed well and is a best seller among shoppers.", "references": [ref(n1_, ia["image_id"])]})
claim2 = ads.save_package("soc", {**base, "references": [ref(n1_, ia["image_id"], why_relevant="A proven high-performing quilted bedding ad for this product type.")]})
noblock = ads.save_package("soc", {**base, "references": []})
dup = ads.save_package("soc", {**base, "references": [ref(n1_, ia["image_id"]), ref(n1_, ia["image_id"])]})
check("A27 package validation: cited images must be registered for THAT ad and inspected (with this run's bytes); no research -> nothing to save; reach_ranked refused while the gate is "
      "disabled; sales/effectiveness claims refused; no references needs a blocker; duplicates refused",
      code(pk_none) == "no_research_in_request" and code(notinsp) == "image_not_inspected" and code(unreg) == "image_not_registered" and code(wrongad) == "image_not_registered"
      and code(rr) == "reach_ranking_unavailable" and rr["reach_gate"]["state"] == "disabled_reach_unavailable" and code(claim) == "unsupported_claim" and code(claim2) == "unsupported_claim"
      and code(noblock) == "blocker_required" and code(dup) == "duplicate_reference", [code(x) for x in (pk_none, notinsp, unreg, wrongad, rr, claim, claim2, noblock, dup)])
PK = ads.save_package("soc", {**base, "references": [ref(n1_, ia["image_id"]), ref(n3_, ib["image_id"], uncertainties="Colours not assessed.")], "limitations": "Scripted fixture."})
pkg = ads.get_package(PK["package_id"]) if PK.get("ok") else {}
again = ads.save_package("soc", {**base, "references": [ref(n1_, ia["image_id"])]})
check("A28 ONE package per request is saved: complete with verified delivery; two references from two distinct ads; identity, public links, hashes and lineage recorded; a second save is refused",
      PK.get("ok") and PK["status"] == "complete" and PK["independent_ads_cited"] == 2 and PK["ads_recorded"] == 6 and code(again) == "package_already_saved"
      and again["package_id"] == PK["package_id"] and pkg["identity"]["agent_id"] == "soc" and pkg["identity"]["company_id"] == "default" and pkg["identity"]["country"] == "US"
      and pkg["identity"]["request_id"] == "req-p1" and pkg["identity"]["run_id"].startswith("adrun-")
      and [r["image_id"] for r in pkg["references"]] == [ia["image_id"], ib["image_id"]] and pkg["references"][0]["sha256"] == ia["sha256"]
      and pkg["references"][0]["inspection_sha256"] == ia["sha256"] and all(r["delivery"] == "image_part_sent" and r["counts_as_verified_evidence"] for r in pkg["references"])
      and pkg["references"][0]["source_url"] == "https://www.facebook.com/ads/library?id=1100000000000001", PK)
check("A28b the package states the reach gate honestly, keeps campaign grouping and card counts apart from ad counts, and carries exact call accounting; no signed URL or key anywhere",
      pkg["reach_gate"]["state"] == "disabled_reach_unavailable" and pkg["selection_basis"] == "relevance_only"
      and any("reach ranking was unavailable" in m for m in PK["missing"]) and pkg["counts"]["independent_ads_cited"] == 2 and pkg["counts"]["ads_recorded"] == 6
      and pkg["counts"]["cards_in_cited_ads"] == 3 and len(pkg["campaigns_cited"]) == 2 and pkg["counts"]["campaigns_cited"] == 2
      and pkg["call_accounting"]["scraper_attempts"] == 4
      and pkg["call_accounting"]["image_download_attempts"] == 2 and pkg["call_accounting"]["by_kind"]["detail"]["attempts"] == 2
      and "PRIVATE-SIGNED" not in json.dumps(pkg) and KEY not in json.dumps(pkg) and "utm=" not in json.dumps(pkg), pkg["counts"])
check("A28c every recorded ad (relevant or not) is listed compactly as 'considered'; unrelated ads are not in the cited set",
      len(pkg["ads_considered"]) == 6 and {a["source_ad_id"] for a in pkg["ads_considered"]} >= {"1200000000000001", "1100000000000001"}
      and {a["source_ad_id"] for a in pkg["cited_ads"]} == {"1100000000000001", "1100000000000003"})
# a blocked package: honest blocker after only unrelated/empty results
scope("a-block", api=20, img=2)
fb_ctl(first="empty", never_relevant=True)
req("req-b1")
ads.search("soc", {"query": "queen quilted coverlet"})
ads.search("soc", {"query": "comforter set"})
PB = ads.save_package("soc", {"summary": "No relevant US Facebook image ads were found for the merchant's quilted bedding after two refined queries.", "selection_basis": "relevance_only",
                              "references": [], "blocker": "Both queries returned no ads; the allowance for this request does not justify more searching."})
pb = ads.get_package(PB["package_id"])
check("A29 an honest blocker is a saved, retrievable package: status blocked, no references, the blocker text, the two counted searches and an unavailable gate",
      PB["ok"] and PB["status"] == "blocked" and pb["blocker"].startswith("Both queries") and pb["references"] == [] and pb["call_accounting"]["scraper_attempts"] == 2
      and pb["reach_gate"]["state"] == "disabled_reach_unavailable" and pb["counts"]["independent_ads_cited"] == 0, PB)
# delivery: a text-only vision path is not verified visual evidence
scope("a-deliv", api=20, img=3)
fb_ctl(first="relevant")
req("req-v1")
S = ads.search("soc", {"query": "comforter set"})
nv = S["ads"][0]["ad_no"]
iv = ads.image("soc", {"ad_no": nv, "image_no": 1})
turn_state.vision_probe = lambda: "text_fallback"
hp._inspect_image({"image_id": iv["image_id"]})
turn_state.vision_probe = lambda: "image_part_sent"
PV = ads.save_package("soc", {**base, "references": [ref(nv, iv["image_id"])]})
check("A30 an image whose pixels only reached the model as a text fallback is saved but the package is partial: the observation is model text, not verified visual evidence",
      PV["ok"] and PV["status"] == "partial" and any("text-only fallback" in m for m in PV["missing"])
      and ads.get_package(PV["package_id"])["references"][0]["counts_as_verified_evidence"] is False, PV)

# --- retrieval needs no provider request: stop the stand-in, read the package in a fresh process
procs[0].terminate()
procs[0].wait()
CHILD2 = r'''
import json, os, sys
sys.path.insert(0, os.environ["ROOT_DIR"])
from app import ads
p = ads.get_package(sys.argv[1])
im = ads.image_file(p["identity"]["run_id"], p["references"][0]["image_id"])
print(json.dumps({"status": p["status"], "refs": len(p["references"]), "gate": p["reach_gate"]["state"], "img": len(im[0]) if im else None,
                  "bad": ads.image_file("adrun-0000000000", "../../app.db"), "list": len(ads.list_packages("soc")), "runs": len(ads.list_runs("soc"))}))
'''
o = subprocess.run([sys.executable, "-c", CHILD2, PK["package_id"]], env={**os.environ, "PYTHONUTF8": "1", "ROOT_DIR": str(ROOT)}, capture_output=True, text=True)
got = json.loads(o.stdout.strip().splitlines()[-1]) if o.stdout.strip() else {"err": o.stderr[-300:]}
req("req-read")
RP = ads.read_package("soc", {})
RP1 = ads.read_package("soc", {"package_id": PK["package_id"]})
RP2 = ads.read_package("soc-noad", {})
RP3 = ads.read_package("soc", {"package_id": "adpkg-0000000000"})
check("A31 with the provider stand-in STOPPED, a fresh process reads the saved package and its managed image bytes; path-like ids resolve to nothing; read_ad_research needs no request",
      got.get("status") == "complete" and got["refs"] == 2 and got["gate"] == "disabled_reach_unavailable" and got["img"] and got["bad"] is None and got["list"] >= 3
      and RP["ok"] and any(p["package_id"] == PK["package_id"] for p in RP["packages"]) and RP1["ok"] and RP1["package"]["package_id"] == PK["package_id"]
      and code(RP2) == "not_granted" and code(RP3) == "unknown_package", (got, code(RP2), code(RP3)))

# --- roles, grants, role guidance, SOUL, image roots (pure)
soc_el = core.ROLES["social_media"]["eligible_tools"]
check("A32 only social_media may be granted the ad tools: eligible for it, not for the analyst; Marketplace tools stay out of social_media; creation validates and unions the foundation",
      set(AD6) <= set(soc_el) and not (set(AD6) & set(core.ROLES["market_analysis"]["eligible_tools"]))
      and not any(t.startswith("marketplace_") or t in ("save_listing_draft", "read_recorded_evidence") for t in soc_el))
GOOD = [{"name": "ad-reference-routine", "content": "# Ad reference routine\n1. Search ads for the product.\n2. Inspect the images you rely on.\n3. Save one package."}]
okc, e = core.validate_create_agent({"role": "social_media", "name": "Acme Social", "objective": "Research US Facebook image ads and propose accurate creative briefs for Acme's bedding.",
                                     "instructions": "You work for Acme Linens (fictional). Research ads within your allowance and never invent claims.", "skills": GOOD, "requested_tools": AD6})
mp, e2 = core.validate_create_agent({"role": "social_media", "name": "Acme Social", "objective": "o" * 50, "instructions": "i" * 50, "skills": GOOD, "requested_tools": ["marketplace_search"]})
ana, e3 = core.validate_create_agent({"role": "market_analysis", "name": "Acme Analyst", "objective": "o" * 50, "instructions": "i" * 50, "skills": GOOD, "requested_tools": ["fb_ads_search"]})
check("A33 requesting the ad tools for a social specialist grants them (plus the foundation); Marketplace tools for social and ad tools for the analyst are tool_not_permitted",
      e is None and set(okc["tools"]) == set(AD6) | {"read_company_context", "memory", "skills"} and e2 and e2["code"] == "tool_not_permitted" and e3 and e3["code"] == "tool_not_permitted", (e, e2, e3))
soul_ad = core.build_soul({"name": "S", "role": "social_media", "objective": "o", "instructions": "i", "tools": SOC_FULL}, "Acme")
soul_no = core.build_soul({"name": "S", "role": "social_media", "objective": "o", "instructions": "i", "tools": ["inspect_image", "read_catalogue"]}, "Acme")
soul_ma = core.build_soul({"name": "A", "role": "market_analysis", "objective": "o", "instructions": "i", "tools": ["marketplace_search"]}, "Acme")
check("A34 the SOUL describes capabilities as granted: with the ad tools it explains the research and the reach rules and still says generation/posting are NOT connected; "
      "without them it says ad research is NOT connected; the analyst SOUL has no ad text",
      "fb_ads_search" in soul_ad and "rank by reach ONLY when the gate says" in soul_ad and "Image or flyer generation is NOT connected" in soul_ad and "campaign" in soul_ad
      and "fb_ads_search" not in soul_no and "Facebook ad research and image or flyer generation are NOT connected" in soul_no
      and "fb_ads" not in soul_ma and "Facebook ad" not in soul_ma, soul_ad[:200])
desc = hp.CREATE_SCHEMA["description"]
check("A35 the create_agent description tells main exactly which tools make ad research available to a social specialist and that generation is not connected",
      "fb_ads_find_advertiser" in desc and "fb_ad_image" in desc and "save_ad_research" in desc and "image_generation" in desc and "facebook_ad_research" not in desc.split("ROLE social_media")[1].split("Capabilities that are NOT connected yet:")[1])
turn_state.ad_run_id = ads.run_for("soc", "req-p1")["run_id"]
visible_in = core.prepare_image(ia["image_id"])["ok"]
rt = core.image_roots()
turn_state.ad_run_id = None
turn_state.run_id = None
visible_out = core.prepare_image(ia["image_id"]).get("code")
check("A36 an ad image is visible to inspect_image only inside its own request's run; the old diagnostic photo cache is not visible inside a run",
      visible_in and visible_out == "image_not_found" and (core.RUNTIME / "marketplace_check" / "images") not in rt, (visible_in, visible_out))
kinds = {r["image_id"]: r["kind"] for r in core.db().execute("SELECT image_id, kind FROM image_inspections WHERE agent_id='soc'")}
check("A37 the trusted inspection log records an inspected ad image as kind live_ad_image (never as a Marketplace photo)",
      kinds.get(ia["image_id"]) == "live_ad_image" and kinds.get(ib["image_id"]) == "live_ad_image", kinds)

shutil.rmtree(TMP, ignore_errors=True)
print(f"\nPART A done: {sum(results)}/{len(results)}", flush=True)
# ================= B. real server + workers + scripted model =================
print("PART B: real server, HTTP chat API and Hermes workers (scripted model; scripted provider stand-in)", flush=True)
ENV = {**os.environ, "PYTHONUTF8": "1", "ECOM_CLASSIFIER": "off", "ECOM_VISION_MODELS": "nebius-token-factory:mock-model"}
for k in ("LLM_PROVIDER", "LLM_MODEL", "NEBIUS_API_KEY", "NEBIUS_BASE_URL", "NEBIUS_MODEL", "ECOM_APP_ROOT", "HERMES_HOME", "ECOM_ADS_SCOPE", "ECOM_ADS_API_MAX", "ECOM_ADS_IMAGE_MAX",
          "ECOM_ADS_RUN_API_MAX", "ECOM_ADS_RUN_IMAGE_MAX", "ECOM_RESEARCH_SCOPE"):
    ENV.pop(k, None)
ENV.update(ECOM_ADS_SCOPE="b-main", ECOM_ADS_API_MAX="60", ECOM_ADS_IMAGE_MAX="20")
os.environ.pop("ECOM_APP_ROOT", None)
os.environ.pop("HERMES_HOME", None)
PKG_RE = re.compile(r"package (adpkg-[0-9a-f]{10}) status (\w+)", re.I)


def chat(agent, message, rid=None, timeout=900):
    body = {"message": message}
    if rid:
        body["request_id"] = rid
    return http(APP, f"/api/chat/{agent}", body, timeout=timeout)


def tool(agent, name, a):
    st, r = chat(agent, "CALL_TOOL:" + json.dumps({"name": name, "args": a}))
    outs = [json.loads(t["output"]) for t in r.get("tools", []) if t.get("name") == name and t.get("output")]
    return (outs[0] if outs else None), r


def start_server(extra=None):
    p = subprocess.Popen([sys.executable, "-m", "app.server", str(APP)], cwd=ROOT, env={**ENV, **(extra or {})}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(p)
    for _ in range(80):
        try:
            http(APP, "/api/status", timeout=5)
            return p
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("server did not start")


def stop(p):
    p.terminate()
    p.wait()
    time.sleep(2)


def llm_stats():
    return http(MOCK, "/stats")[1]


def tools_seen(reply):
    m = re.search(r"tools \[(.*)\]", reply or "")
    return sorted(x.strip(" '\"") for x in m.group(1).split(",")) if m else []


def acts(r):
    return [a["tool"] for a in r.get("activity", [])]


def mean_close(got, want, tol=8):
    return bool(got) and all(abs(a - b) <= tol for a, b in zip(got, want))


def package_of(r):
    m = PKG_RE.search(r.get("text") or "")
    return (http(APP, f"/api/ads/packages/{m.group(1)}")[1], m.group(1)) if m else ({}, None)


try:
    shutil.rmtree(ROOT / "runtime", ignore_errors=True)
    (ROOT / "secrets").mkdir(exist_ok=True)
    (ROOT / "secrets" / "local.env").write_text(f"LLM_PROVIDER=nebius-token-factory\nLLM_MODEL=mock-model\nNEBIUS_API_KEY=mock-key\nNEBIUS_BASE_URL=http://127.0.0.1:{MOCK}/v1\n", encoding="utf-8")
    subprocess.run([sys.executable, "scripts/setup.py"], cwd=ROOT, env=ENV, check=True, capture_output=True)
    spawn(["tests/mock_llm.py", str(MOCK)], env=ENV)
    spawn(["tests/mock_fb_ads.py", str(FB)])
    wait_up(MOCK, "/stats")
    wait_up(FB)
    fb_ctl(first="irrelevant")
    srv = start_server()
    http(APP, "/api/company", {"fields": {"name": "Acme Linens (fictional demo merchant)", "products": "Quilted coverlets and cotton bedding (fictional demo)",
                                          "customers": "Home buyers in the US (fictional demo)", "goal": "Present our bedding clearly and accurately to shoppers"}})
    SKILL = [{"name": "ad-reference-routine", "content": "# Ad reference routine\n1. Read the catalogue product.\n2. Search ads, inspect the images you rely on.\n3. Save one package and report limits."}]
    base_args = {"role": "social_media", "objective": "Research US Facebook image ads for Acme's bedding and propose accurate, original creative briefs; nothing is posted.",
                 "instructions": "You work for Acme Linens (fictional demo merchant). Research ads read-only within your backend allowance, choose queries and images yourself, "
                                 "use only supplied product facts and say what you could not verify.", "company_context_refs": [], "skills": SKILL}
    adr, _ = tool("main", "create_agent", {**base_args, "name": "Acme Ad Researcher", "requested_tools": AD6 + ["inspect_image", "read_catalogue"]})
    plain, _ = tool("main", "create_agent", {**base_args, "name": "Acme Plain Social", "requested_tools": ["inspect_image", "read_catalogue"],
                                             "skills": [{"name": "brief-routine", "content": "# Brief routine\n1. Read the catalogue.\n2. Write one brief.\n3. List what could not be verified."}]})
    ana, _ = tool("main", "create_agent", {"role": "market_analysis", "name": "Acme Analyst", "objective": "Compare Acme's bedding with Marketplace listings near Dallas and save an accurate listing draft.",
                                           "instructions": "You work for Acme Linens (fictional demo). Research Marketplace read-only within your allowance and never invent prices.",
                                           "skills": [{"name": "price-review", "content": "# Price review\n1. Read the catalogue.\n2. Compare asking prices.\n3. Mark unknowns."}],
                                           "requested_tools": ["marketplace_locate", "marketplace_search", "marketplace_item", "marketplace_photo", "inspect_image", "read_catalogue",
                                                               "save_listing_draft"]})
    check("B1 main creates a social specialist WITH the ad tools (backend grants = requested + foundation), another without them, and an analyst; all through the real create_agent tool",
          adr and adr.get("ok") and set(adr["granted_tools"]) == set(AD6) | {"inspect_image", "read_catalogue", "read_company_context", "memory", "skills"}
          and plain and plain.get("ok") and not (set(plain["granted_tools"]) & set(AD6)) and ana and ana.get("ok") and not (set(ana["granted_tools"]) & set(AD6)), (adr, plain, ana))
    A_ID, P_ID, M_ID = adr["agent_id"], plain["agent_id"], ana["agent_id"]
    pr = ROOT / "runtime" / "hermes_home" / "profiles"
    soul_a, soul_p = (pr / A_ID / "SOUL.md").read_text(encoding="utf-8"), (pr / P_ID / "SOUL.md").read_text(encoding="utf-8")
    bl_a = (pr / A_ID / "skills" / "social-media-flyer-baseline" / "SKILL.md").read_text(encoding="utf-8")
    grants_before = {a["agent_id"]: a["granted_tools"] for a in http(APP, "/api/agents")[1]}
    check("B2 profile files: the ad specialist's SOUL and baseline skill describe the ad tools, the reach rules and that generation/posting are NOT connected; the other social "
          "specialist's SOUL says ad research is NOT connected",
          "fb_ads_search" in soul_a and "Image or flyer generation is NOT connected" in soul_a and "Researching Facebook image ads" in bl_a and "**Reach.**" in bl_a
          and "fb_ads_search" not in soul_p and "Facebook ad research and image or flyer generation are NOT connected" in soul_p, soul_a[:300])
    rs = {k: chat(v, "hello")[1] for k, v in (("ad", A_ID), ("plain", P_ID), ("ana", M_ID), ("main", "main"))}
    ts = {k: tools_seen(v["text"]) for k, v in rs.items()}
    check("B3 tool exposure follows the stored grants and the role: the ad specialist sees the six fb_* tools + inspect/catalogue; the plain social specialist none; the analyst its "
          "Marketplace tools and no fb_*; main only create_agent/update_company/context",
          set(AD6) <= set(ts["ad"]) and "inspect_image" in ts["ad"] and not any(t.startswith("marketplace_") or t in ("create_agent", "update_company") for t in ts["ad"])
          and not (set(AD6) & set(ts["plain"])) and "marketplace_search" in ts["ana"] and not any(t.startswith("fb_") or t in ("save_ad_research", "read_ad_research") for t in ts["ana"])
          and "create_agent" in ts["main"] and not any(t.startswith("fb_") for t in ts["main"]), ts)
    o1, r1 = tool("main", "fb_ads_search", {"query": "quilt"})
    o2, r2 = tool(A_ID, "fb_ads_search", {"query": "quilt", "country": "GB", "url": "http://evil.example/x", "max_requests": 99})
    o3, r3 = tool(P_ID, "fb_ads_search", {"query": "quilt"})
    check("B4 main and an ungranted specialist cannot call the ad tools (the tool does not exist for them); a granted specialist's arguments are validated server-side: "
          "country/url/budget arguments are refused and nothing reaches the provider",
          o1 is None and "not available" in r1["text"] and o3 is None and "not available" in r3["text"] and o2 and o2.get("code") == "invalid_argument" and fb_stats()["total"] == 0,
          (r1["text"][:100], o2, fb_stats()["total"]))

    # ---- scenario 1: irrelevant first results -> refinement -> advertiser path -> details -> images -> inspection -> package (reach absent)
    fb_ctl(first="irrelevant", reach="absent")
    s0 = llm_stats()
    MSG1 = "AD_AGENT Research US Facebook image ads for our quilted coverlet. FIRST_QUERY:home organisation tips VIA_ADVERTISER"
    st, r = chat(A_ID, MSG1, rid="b-req-1")
    seq = acts(r)
    PKG, pid = package_of(r)
    S = fb_stats()
    check("B5 the scripted specialist adapted instead of following a fixed chain: an irrelevant first search, a refined search, an advertiser lookup + that advertiser's ads, details, "
          "images, inspections, then ONE saved package (Activity shows each step)",
          st == 200 and r["ok"] and seq[0] == "read_catalogue" and seq.count("fb_ads_search") == 3 and seq.count("fb_ads_find_advertiser") == 1 and seq.count("fb_ad_detail") == 2
          and seq.count("fb_ad_image") == 2 and seq.count("inspect_image") == 2 and seq[-1] == "save_ad_research" and PKG.get("status") == "complete"
          and all(a["status"] == "ok" for a in r["activity"]) and "Searching Facebook image ads" in [a["label"] for a in r["activity"]], (seq, r["text"][:200]))
    runs = http(APP, "/api/ads/runs?agent_id=" + A_ID)[1]
    RUN = http(APP, f"/api/ads/runs/{PKG['identity']['run_id']}")[1]
    check("B6 the saved package is retrievable over the API with trusted identity, public source links, distinct ads, campaign grouping kept apart from the ad count and the gate state",
          PKG["identity"]["agent_id"] == A_ID and PKG["identity"]["request_id"] == "b-req-1" and PKG["identity"]["company_name"].startswith("Acme Linens")
          and PKG["counts"]["independent_ads_cited"] == 2 and PKG["counts"]["ads_recorded"] == 6 and PKG["counts"]["cards_in_cited_ads"] == 3
          and sorted(a["source_ad_id"] for a in PKG["cited_ads"]) == ["1100000000000001", "1100000000000003"]
          and all(a["source_url"].startswith("https://www.facebook.com/ads/library?id=") for a in PKG["cited_ads"])
          and PKG["reach_gate"]["state"] == "disabled_reach_unavailable" and PKG["selection_basis"] == "relevance_only" and len(runs) == 1, PKG.get("counts"))
    exact = {k: S["counts"].get(k, 0) for k in ("advertiser", "company", "search", "detail", "cdn")}
    acc = PKG["call_accounting"]
    check("B7 exact call accounting: the package's and the run's counts equal what the provider stand-in actually received (6 scraper requests incl. 1 advertiser + 1 company-ads, "
          "2 image downloads), within the default allowance of 8/4",
          exact == {"advertiser": 1, "company": 1, "search": 2, "detail": 2, "cdn": 2} and acc["scraper_attempts"] == 6 and acc["image_download_attempts"] == 2
          and RUN["accounting"]["scraper_attempts"] == sum(exact[k] for k in ("advertiser", "company", "search", "detail")) and RUN["allowance"]["api_attempts_left"] == 2
          and RUN["allowance"]["image_downloads_left"] == 2 and acc["credits_reported_charged"] == 6 and all(c["outcome"] == "ok" for c in acc["calls"]), (exact, acc["by_kind"]))

    # ---- actual-image delivery: the model REQUEST carried the registered images' pixels (independent of what the scripted model wrote)
    log = llm_stats()["image_log"][len(s0["image_log"]):]
    got = [im for e in log for im in e["images"]]
    want_colors = {"ad-1100000000000001-1": FBM.ADS["1100000000000001"][3][0], "ad-1100000000000003-1": (100, 120, 170)}
    refs = {x["image_id"]: x for x in PKG["references"]}
    file_ok = {}
    for iid, x in refs.items():
        f = ROOT / "runtime" / "ad_research" / PKG["identity"]["run_id"] / "images" / f"{iid}.png"
        file_ok[iid] = f.is_file() and hashlib.sha256(f.read_bytes()).hexdigest() == x["sha256"]
    check("B8 actual-image delivery, verified on the model request itself: pixels with each registered image's colour and size reached the model (not just a scripted description); "
          "the package records delivery image_part_sent and the stored file hash equals the recorded hash",
          set(refs) == set(want_colors) and all(any(mean_close(g.get("mean"), c) for g in got) for c in want_colors.values())
          and got and all(g.get("size") == [240, 300] for g in got) and all(x["delivery"] == "image_part_sent" and x["counts_as_verified_evidence"] for x in refs.values())
          and all(file_ok.values()), (set(refs), [g.get("mean") for g in got], file_ok))
    if os.environ.get("ADS_DUMP"):   # evidence for the result note: the saved package as the API returns it, the run view, and what the provider stand-in and model stand-in saw
        Path(os.environ["ADS_DUMP"]).write_text(json.dumps({"package": PKG, "run": RUN, "provider_requests": {"counts": S["counts"], "total": S["total"]},
                                                            "model_images_in_requests": got, "registered_colours": {k: list(v) for k, v in want_colors.items()}}, indent=1), encoding="utf-8")
    st_img, body = http(APP, f"/api/ads/images/{PKG['identity']['run_id']}/ad-1100000000000001-1", raw=True)
    st_bad = [http(APP, f"/api/ads/images/{PKG['identity']['run_id']}/{x}", raw=True)[0] for x in ("..%2f..%2fapp.db", "ad-1-1", "x.png")] + \
             [http(APP, "/api/ads/images/adrun-0000000000/ad-1100000000000001-1", raw=True)[0]]
    check("B9 the managed image endpoint serves only a registered image of a run (hash equal to the recorded one); traversal-like, unknown and malformed ids are 404",
          st_img == 200 and hashlib.sha256(body).hexdigest() == refs["ad-1100000000000001-1"]["sha256"] and st_bad == [404, 404, 404, 404], (st_img, st_bad))

    # ---- duplicate request id: the completed request is replayed from the store, nothing is re-run or re-sent
    n0 = fb_stats()["total"]
    st, rep = chat(A_ID, MSG1, rid="b-req-1")
    check("B10 retrying the same completed request returns the stored result (replayed) with no new provider request and no new package",
          st == 200 and rep.get("replayed") is True and fb_stats()["total"] == n0 and len(http(APP, "/api/ads/packages?agent_id=" + A_ID)[1]) == 1)

    # ---- scenario 2: reach present on detail responses -> ranking enabled (same metric/geography only)
    fb_ctl(first="relevant", reach="present")
    st, r = chat(A_ID, "AD_AGENT Research US Facebook image ads for our quilted coverlet. FIRST_QUERY:queen quilted coverlet", rid="b-req-2")
    P2, _ = package_of(r)
    check("B11 reach PRESENT (documented EU field on detail): the package keeps metric/value/geography, the gate is enabled for that metric only, and the scripted specialist's "
          "reach_ranked selection is accepted because every cited ad carries it",
          P2.get("reach_gate", {}).get("state") == "enabled" and P2["reach_gate"]["metric"] == "eu_total_reach" and P2["reach_gate"]["geography"] == "EU"
          and P2["selection_basis"] == "reach_ranked" and all(a["reach"]["state"] == "reported" and a["reach"]["geography"] == "EU" and a["reach"]["value"] for a in P2["cited_ads"])
          and "NOT US reach" in P2["cited_ads"][0]["reach"]["meaning"], (r["text"][:200], P2.get("reach_gate")))

    # ---- scenario 3: ambiguous reach -> ranking stays off, raw value preserved
    fb_ctl(first="relevant", reach="ambiguous")
    st, r = chat(A_ID, "AD_AGENT Research US Facebook image ads for our quilted coverlet. FIRST_QUERY:queen quilted coverlet", rid="b-req-3")
    P3, _ = package_of(r)
    check("B12 reach AMBIGUOUS: raw provider value preserved, never ranked; gate disabled_reach_ambiguous; the specialist still produced a complete relevance-only package",
          P3.get("status") == "complete" and P3["reach_gate"]["state"] == "disabled_reach_ambiguous" and P3["selection_basis"] == "relevance_only"
          and all(a["reach"]["state"] == "ambiguous" and a["reach"]["provider_value"] and a["reach"]["value"] is None for a in P3["cited_ads"]), (r["text"][:200], P3.get("reach_gate")))

    # ---- scenario 4: honest blocker after empty/irrelevant results; scenario 5: provider outage
    fb_ctl(first="empty", never_relevant=True, reach="absent")
    st, r = chat(A_ID, "AD_AGENT Research US Facebook image ads for our quilted coverlet.", rid="b-req-4")
    P4, _ = package_of(r)
    check("B13 empty results after refinement: the specialist stops with an honest, saved blocker package (no references, counted searches), not a fabricated reference",
          P4.get("status") == "blocked" and P4["references"] == [] and P4["blocker"] and P4["call_accounting"]["scraper_attempts"] == 3
          and P4["counts"]["independent_ads_cited"] == 0 and "BLOCKED" in r["text"], (r["text"][:200], P4.get("call_accounting", {}).get("scraper_attempts")))
    fb_ctl(first="relevant", search_status=500)
    st, r = chat(A_ID, "AD_AGENT Research US Facebook image ads for our quilted coverlet.", rid="b-req-5")
    P5, _ = package_of(r)
    check("B14 provider failure (HTTP 500): every failed attempt is counted, none is replayed, and the outcome is an explicit blocked package",
          P5.get("status") == "blocked" and P5["call_accounting"]["by_kind"]["search"] == {"attempts": 3, "ok": 0, "failed": 3, "unknown": 0}
          and all(c["outcome"] == "provider_error" for c in P5["call_accounting"]["calls"]), (r["text"][:200], P5.get("call_accounting", {}).get("by_kind")))

    # ---- isolation: other agents hold no ad data; their profiles carry no ad text; analyst keeps its Marketplace tools
    listed = http(APP, "/api/ads/packages")[1]
    txt = lambda pid_: "".join(f.read_text(encoding="utf-8", errors="ignore") for f in (pr / pid_).rglob("*.md"))
    check("B15 the analyst and the plain social specialist hold no ad runs or packages; the analyst's profile contains no ad research text and it keeps its Marketplace tools",
          {p["agent_id"] for p in listed} == {A_ID} and not http(APP, "/api/ads/runs?agent_id=" + M_ID)[1] and not http(APP, "/api/ads/runs?agent_id=" + P_ID)[1]
          and "fb_ads" not in txt(M_ID) and "Facebook ad" not in txt(M_ID) and "marketplace_search" in tools_seen(chat(M_ID, "hello again")[1]["text"]),
          {p["agent_id"] for p in listed})
    check("B16 no stored grant or saved SOUL was widened or rewritten by any of this (existing specialists obtain new tools only by being created with them)",
          {a["agent_id"]: a["granted_tools"] for a in http(APP, "/api/agents")[1]} == grants_before and (pr / P_ID / "SOUL.md").read_text(encoding="utf-8") == soul_p
          and (pr / A_ID / "SOUL.md").read_text(encoding="utf-8") == soul_a)

    # ---- restart: stored research is read with no provider request
    pk_before = {p["package_id"]: http(APP, f"/api/ads/packages/{p['package_id']}")[1] for p in listed}
    stop(srv)
    fb_ctl(first="relevant")                       # fresh log: anything the retrieval touched would show up
    srv = start_server()
    pk_after = {p["package_id"]: http(APP, f"/api/ads/packages/{p['package_id']}")[1] for p in http(APP, "/api/ads/packages")[1]}
    st, body2 = http(APP, f"/api/ads/images/{PKG['identity']['run_id']}/ad-1100000000000001-1", raw=True)
    rd, _ = tool(A_ID, "read_ad_research", {})   # (the stored Activity output is cut at 3000 characters, so the list view is what can be parsed here)
    check("B17 after an app restart the packages (including the blocked ones), runs, images and the specialist's read_ad_research tool return the same data with ZERO provider requests",
          pk_after == pk_before and len(pk_after) == 5 and st == 200 and hashlib.sha256(body2).hexdigest() == refs["ad-1100000000000001-1"]["sha256"]
          and rd and rd.get("ok") and pid in [p["package_id"] for p in rd["packages"]] and len(rd["packages"]) == 5 and fb_stats()["total"] == 0, (len(pk_after), fb_stats()["total"]))

    # ---- allowance survives a restart and a new request id: a small scope stays exhausted
    stop(srv)
    fb_ctl(first="irrelevant", reach="absent")   # the first query is unrelated, so the two attempts go to two searches and the details are refused
    srv = start_server({"ECOM_ADS_SCOPE": "b-small", "ECOM_ADS_API_MAX": "2", "ECOM_ADS_IMAGE_MAX": "1"})
    n0 = fb_stats()["total"]
    st, r6 = chat(A_ID, "AD_AGENT Research US Facebook image ads for our quilted coverlet. FIRST_QUERY:home organisation tips", rid="b-req-6")
    used_first = fb_stats()["total"] - n0
    P6, _ = package_of(r6)
    stop(srv)
    srv = start_server({"ECOM_ADS_SCOPE": "b-small", "ECOM_ADS_API_MAX": "50", "ECOM_ADS_IMAGE_MAX": "50"})   # a larger cap in the environment must not re-size the scope
    n1 = fb_stats()["total"]
    st, r7 = chat(A_ID, "AD_AGENT Research US Facebook image ads for our quilted coverlet. FIRST_QUERY:home organisation tips", rid="b-req-7")
    sc = next((a for a in http(APP, "/api/ads/allowance")[1] if a["scope"] == "b-small"), {})
    P7, _ = package_of(r7)
    check("B18 a scope allowance (2 scraper attempts) spent by one request stays spent across an app restart, a new request id and a larger cap in the environment: exactly 2 requests "
          "were sent, the next attempts were refused with nothing sent, and each request ended in an honest blocked package",
          used_first == 2 and fb_stats()["total"] - n1 == 0 and sc.get("api_used") == 2 and sc.get("api_max") == 2 and P6.get("status") == "blocked" and P7.get("status") == "blocked"
          and P6["call_accounting"]["scraper_attempts"] == 2 and P7["call_accounting"]["scraper_attempts"] == 0, (used_first, sc, r6["text"][:120], r7["text"][:160]))
finally:
    for p in procs:
        try:
            p.terminate()
        except Exception:
            pass
print(f"\n{sum(results)}/{len(results)} checks passed (scripted provider + scripted model: wiring/enforcement only, NOT live ad data, reach or model behaviour)")
sys.exit(0 if results and all(results) else 1)
