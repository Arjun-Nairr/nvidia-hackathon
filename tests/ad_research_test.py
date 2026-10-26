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
_api = [0]


def HOP(vs, image=True, respond=True):
    """What Hermes does after a tool batch: ONE model request carrying the tool result(s) (list content with the image parts when its vision gate passes, the text
    summary otherwise), then that request's response. Drives the same two hook entry points the plugin registers (pre_api_request / post_api_request)."""
    _api[0] += 1
    aid = f"ad-api-{_api[0]}"
    vs = vs if isinstance(vs, list) else [vs]
    content = [part for v in vs for part in v["content"]] if image else " ".join(v["text_summary"] for v in vs)
    hp._api_request(request_messages=[{"role": "system", "content": "s"}, {"role": "tool", "tool_call_id": "c1", "content": content}], api_request_id=aid)
    if respond:
        hp._api_response(api_request_id=aid)
    return aid


def INSP(image_id):
    """inspect_image followed by the model round trip that delivers its pixels (a LATER step than any save in the same batch)."""
    v = hp._inspect_image({"image_id": image_id})
    if isinstance(v, dict) and v.get("_multimodal"):
        HOP(v, image=turn_state.image_delivery() == "image_part_sent")
    return v


def insp_row(image_id, request_id):
    with core.db() as d:
        return [dict(r) for r in d.execute("SELECT * FROM image_inspections WHERE agent_id='soc' AND image_id=? AND request_id=? ORDER BY id", (image_id, request_id))]



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
check("A21 PRESENT reach (Meta's documented eu_total_reach on detail): kept with metric, value, EU geography and provenance, measurement period NOT stated; two same-metric, "
      "same-geography values are still NOT comparable while the period is unknown, so the gate stays disabled (review correction 4)",
      pr["state"] == "reported" and pr["metric"] == "eu_total_reach" and pr["value"] == 27000 and pr["geography"] == "EU" and pr["period"] is None and "NOT US reach" in pr["meaning"]
      and pr["source"] == "provider field aaa_info.eu_total_reach"
      and g0 == "disabled_reach_unavailable" and g1 == "disabled_single_value" and dp2["reach_gate"]["state"] == "disabled_period_unknown"
      and dp2["reach_gate"]["ranking_enabled"] is False and dp2["reach_gate"]["metric"] is None and dp2["reach_gate"]["ads_with_reported_reach"] == 2
      and dp2["reach_gate"]["ads_recorded"] == 4, (pr, g0, g1, dp2["reach_gate"]))
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
INSP(IMI["image_id"])
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
va = hp._inspect_image({"image_id": ia["image_id"]})            # the real inspect_image tool body: trusted inspection log
vb = hp._inspect_image({"image_id": ib["image_id"]})
HOP([va, vb])                                                    # the next model request carried both images and its response completed
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
      and pkg["references"][0]["inspection_sha256"] == ia["sha256"] and all(r["delivery"] == "image_part_sent" and r["counts_as_verified_evidence"] and r.get("delivery_confirmed") is True and r.get("delivered_at") for r in pkg["references"])
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
# delivery CONFIRMATION: visual evidence exists only once the model REQUEST carried these exact pixels and a response followed (the inspect_flyer mechanism, hooks pre/post_api_request)
scope("a-deliv", api=40, img=12)
fb_ctl(first="relevant")
req("req-v1")
S = ads.search("soc", {"query": "comforter set"})
nv = {a["source_ad_id"]: a["ad_no"] for a in S["ads"]}["1100000000000001"]
iv = ads.image("soc", {"ad_no": nv, "image_no": 1})
turn_state.vision_probe = lambda: "text_fallback"
vt = hp._inspect_image({"image_id": iv["image_id"]})
HOP(vt, image=False)                                 # a text-only request: no pixels reached the model, although a response followed
turn_state.vision_probe = lambda: "image_part_sent"
PV = ads.save_package("soc", {**base, "references": [ref(nv, iv["image_id"])]})
check("A30 an image whose pixels only reached the model as a text fallback cannot back a reference: image_not_delivered with a corrective hint, no package saved",
      code(PV) == "image_not_delivered" and "inspect_image" in (PV.get("hint") or "") and not [p for p in ads.list_packages("soc") if p["request_id"] == "req-v1"], PV)
v1 = hp._inspect_image({"image_id": iv["image_id"]})  # a fresh inspection: the capability prediction says image_part_sent
PS = ads.save_package("soc", {**base, "references": [ref(nv, iv["image_id"])]})   # ... but it is saved in the SAME batch, before any request carried it
row_s = insp_row(iv["image_id"], "req-v1")[-1]
check("A31 same-batch inspection and save: the predicted delivery (image_part_sent) is NOT confirmation: refused image_not_delivered, the row has no delivered_at",
      code(PS) == "image_not_delivered" and row_s["delivery"] == "image_part_sent" and row_s["delivered_at"] is None and row_s["boundary_at"] is None, (PS, row_s))
HOP(v1, respond=False)                               # an image-bearing request was sent but NO response completed (dispatch failed or was cut off)
PF = ads.save_package("soc", {**base, "references": [ref(nv, iv["image_id"])]})
row_f = insp_row(iv["image_id"], "req-v1")[-1]
check("A32 a failed image-bearing request (no response) does not confirm: still image_not_delivered and no delivered_at",
      code(PF) == "image_not_delivered" and row_f["delivered_at"] is None, (PF, row_f))
HOP(v1)                                              # the next request carries the pixels and its response completes
PC = ads.save_package("soc", {**base, "references": [ref(nv, iv["image_id"])]})
pc = ads.get_package(PC["package_id"]) if PC.get("ok") else {}
row_c = insp_row(iv["image_id"], "req-v1")[-1]
rc_ = (pc.get("references") or [{}])[0]
check("A33 after the request that carried these exact pixels and its response, the same reference saves with CONFIRMED evidence: delivered_at/boundary_at stored, "
      "counts_as_verified_evidence and delivery_confirmed true, the package complete",
      PC.get("ok") and PC["status"] == "complete" and row_c["delivered_at"] and row_c["boundary_at"] and rc_.get("counts_as_verified_evidence") is True
      and rc_.get("delivery_confirmed") is True and rc_.get("delivered_at") and rc_["inspection_request_id"] == "req-v1", (PC, row_c))
# another request / run / image cannot satisfy the reference
req("req-v2")
S2 = ads.search("soc", {"query": "comforter set"})
no2 = {a["source_ad_id"]: a["ad_no"] for a in S2["ads"]}
i2a = ads.image("soc", {"ad_no": no2["1100000000000001"], "image_no": 1})
INSP(i2a["image_id"])                                # request v2 confirms the IDENTICAL bytes of ad 1
req("req-v3")
S3 = ads.search("soc", {"query": "comforter set"})
no3 = {a["source_ad_id"]: a["ad_no"] for a in S3["ads"]}
i3a = ads.image("soc", {"ad_no": no3["1100000000000001"], "image_no": 1})
i3b = ads.image("soc", {"ad_no": no3["1100000000000002"], "image_no": 1})
v3a = hp._inspect_image({"image_id": i3a["image_id"]})   # request v3 inspects ad 1 but nothing has carried it yet
INSP(i3b["image_id"])                                    # ... while ANOTHER image of this request is confirmed delivered
PO = ads.save_package("soc", {**base, "references": [ref(no3["1100000000000001"], i3a["image_id"])]})
check("A34 neither another request's confirmed inspection of identical bytes nor another image's confirmation in this request satisfies the reference: image_not_delivered",
      i2a["sha256"] == i3a["sha256"] and code(PO) == "image_not_delivered", (code(PO), i2a["sha256"] == i3a["sha256"]))
# a worker restart between the inspection and the round trip loses the pending confirmation; confirmed rows are in the database and survive
req("req-v4")
S4 = ads.search("soc", {"query": "comforter set"})
no4 = {a["source_ad_id"]: a["ad_no"] for a in S4["ads"]}["1100000000000001"]
i4 = ads.image("soc", {"ad_no": no4, "image_no": 1})
v4 = hp._inspect_image({"image_id": i4["image_id"]})
turn_state.pending_images.clear()                    # the worker process restarted before the model round trip
HOP(v4)
PR1 = ads.save_package("soc", {**base, "references": [ref(no4, i4["image_id"])]})
v4b = hp._inspect_image({"image_id": i4["image_id"]})   # the restarted worker inspects again; this time the round trip completes
HOP(v4b)
turn_state.pending_images.clear()                    # another restart AFTER the confirmation: it is stored, not in memory
PR2 = ads.save_package("soc", {**base, "references": [ref(no4, i4["image_id"])]})
check("A35 a restart before the round trip loses the confirmation (refused); a confirmation already stored survives a later restart (saved from the database row)",
      code(PR1) == "image_not_delivered" and PR2.get("ok") and PR2["status"] == "complete", (code(PR1), code(PR2)))
# a legacy / bound-but-unconfirmed row never counts
req("req-v5")
S5 = ads.search("soc", {"query": "comforter set"})
no5 = {a["source_ad_id"]: a["ad_no"] for a in S5["ads"]}["1100000000000001"]
i5 = ads.image("soc", {"ad_no": no5, "image_no": 1})
with core.db() as d:
    d.execute("INSERT INTO image_inspections(agent_id, image_id, kind, sha256, width, height, ts, delivery, request_id, run_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
              ("soc", i5["image_id"], "live_ad_image", i5["sha256"], i5["width"], i5["height"], time.time() + 1, "image_part_sent", "req-v5", ads.run_for("soc", "req-v5")["run_id"]))
PL = ads.save_package("soc", {**base, "references": [ref(no5, i5["image_id"])]})
check("A36 a legacy-style row (predicted delivery image_part_sent, bound to the request and run, never confirmed) does not qualify", code(PL) == "image_not_delivered", PL)
# an honest blocker still saves without any visual reference
PBK = ads.save_package("soc", {"summary": "Relevant ads were found but their images could not be confirmed as delivered to the model, so there is no visual reference.",
                               "selection_basis": "relevance_only", "references": [], "blocker": "No inspected image reached the model; no reference can be verified."})
check("A37 a blocker package (no references) is still saved when nothing could be confirmed", PBK.get("ok") and PBK["status"] == "blocked", PBK)

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
check("A35 the create_agent description tells main exactly which tools make ad research available to a social specialist; flyer generation is described only as the separate generate_flyer tool",
      "fb_ads_find_advertiser" in desc and "fb_ad_image" in desc and "save_ad_research" in desc and "generate_flyer" in desc and "facebook_ad_research" not in desc.split("ROLE social_media")[1].split("Capabilities that are NOT connected yet:")[1])
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

# ================= review corrections (Codex review 2026-10-12, research/v2-ticket03-review-20261012.md) =================
print("review corrections", flush=True)
spawn(["tests/mock_fb_ads.py", str(FB)])           # A31 stopped the stand-in to prove stored retrieval; these checks need a provider again
wait_up(FB)
# --- 1. inspections are bound to the trusted request and run
scope("c-bind", api=80, img=20)
fb_ctl(first="relevant")
req("req-bind-A")
sa = ads.search("soc", {"query": "comforter set"})
nA = {a["source_ad_id"]: a["ad_no"] for a in sa["ads"]}["1100000000000004"]
imA = ads.image("soc", {"ad_no": nA, "image_no": 1})                 # request A downloads the ad image and does NOT inspect it
run_bindA = ads.run_for("soc", "req-bind-A")["run_id"]
req("req-bind-B")
sb = ads.search("soc", {"query": "comforter set"})
nB = {a["source_ad_id"]: a["ad_no"] for a in sb["ads"]}["1100000000000004"]
imB = ads.image("soc", {"ad_no": nB, "image_no": 1})                 # request B downloads and inspects the IDENTICAL ad image bytes
INSP(imB["image_id"])                                                 # B's inspection is even CONFIRMED delivered: still not A's
req("req-bind-A")                                                    # request A resumes with a fresh turn state (as after a restart)
n0 = n_req()
ads.image("soc", {"ad_no": nA, "image_no": 1})                       # the first ad tool call re-binds the run (answered from the store)
save_a1 = ads.save_package("soc", {**base, "references": [ref(nA, imA["image_id"])]})
check("C1 request B's inspection of identical ad bytes does NOT satisfy resumed request A: image_not_inspected, no package saved, nothing sent",
      imA["image_id"] == imB["image_id"] and imA["sha256"] == imB["sha256"] and code(save_a1) == "image_not_inspected" and n_req() == n0
      and not [p for p in ads.list_packages("soc") if p["request_id"] == "req-bind-A"], (code(save_a1), imA["sha256"] == imB["sha256"]))
INSP(imA["image_id"])                                                # now A inspects its own download (delivered in the next request)
save_a2 = ads.save_package("soc", {**base, "references": [ref(nA, imA["image_id"])]})
pa = ads.get_package(save_a2["package_id"]) if save_a2.get("ok") else {}
try:
    with core.db() as d:
        rows_ins = [dict(r) for r in d.execute("SELECT request_id, run_id, kind FROM image_inspections WHERE agent_id='soc' AND image_id=? ORDER BY id", (imA["image_id"],))]
except Exception as ex:   # before the correction the columns do not exist: report it as a failed check, not a crash
    rows_ins = repr(ex)
check("C2 an inspection performed inside request A (its own run) satisfies A; the stored inspection rows carry the backend-supplied request id and ad run id, and the package shows them",
      save_a2.get("ok") and save_a2["status"] == "complete"
      and rows_ins == [{"request_id": "req-bind-B", "run_id": ads.run_for("soc", "req-bind-B")["run_id"], "kind": "live_ad_image"},
                       {"request_id": "req-bind-A", "run_id": run_bindA, "kind": "live_ad_image"}]
      and pa["references"][0]["inspection_request_id"] == "req-bind-A" and pa["references"][0]["inspection_run_id"] == run_bindA, (save_a2.get("code"), rows_ins))
req("req-bind-L")
sl = ads.search("soc", {"query": "comforter set"})
nL = {a["source_ad_id"]: a["ad_no"] for a in sl["ads"]}["1100000000000004"]
imL = ads.image("soc", {"ad_no": nL, "image_no": 1})
with core.db() as d:   # a row written before request/run identity existed: same agent, image id, hash and a recent timestamp, but NO request or run
    d.execute("INSERT INTO image_inspections(agent_id, image_id, kind, sha256, width, height, ts, delivery) VALUES(?,?,?,?,?,?,?,?)",
              ("soc", imL["image_id"], "live_ad_image", imL["sha256"], imL["width"], imL["height"], time.time() + 1, "image_part_sent"))
save_l = ads.save_package("soc", {**base, "references": [ref(nL, imL["image_id"])]})
check("C3 a legacy/unbound inspection row cannot establish verified current-request evidence", code(save_l) == "image_not_inspected", code(save_l))
from app import listing as _listing
req("req-bind-ana")
_listing.record_inspection("soc", {"image_id": "ana-cat-x", "sha256": "0" * 64, "width": 1, "height": 1}, "unknown")
try:
    with core.db() as d:
        ana_row = dict(d.execute("SELECT request_id, run_id, kind FROM image_inspections WHERE image_id='ana-cat-x'").fetchone())
except Exception as ex:
    ana_row = repr(ex)
check("C3b the log stays additive for non-ad inspections (analyst/catalogue): the same table and kinds, the request id is recorded, no ad run is invented",
      ana_row == {"request_id": "req-bind-ana", "run_id": None, "kind": "other"}, ana_row)

# --- 2. pagination stops at the terminal page
scope("c-page", api=60, img=4)
fb_ctl(first="relevant", pages=2)
req("req-pg1")
pg1 = ads.search("soc", {"query": "bedding"})
pg2 = ads.search("soc", {"query": "bedding", "next_page": True})
n0, u0 = n_req(), used("c-page")["api_used"]
pg3 = ads.search("soc", {"query": "bedding", "next_page": True})
pg4 = ads.search("soc", {"query": "bedding", "next_page": True})
check("C4 keyword search: page 1 has a cursor, page 2 is terminal (ads, no cursor); every further next_page is an explicit no_next_page stop with NO provider call and no allowance used",
      pg1["ok"] and pg1["has_more_pages"] and len(pg1["ads"]) == 2 and pg2["ok"] and pg2["has_more_pages"] is False and len(pg2["ads"]) == 2
      and code(pg3) == "no_next_page" and code(pg4) == "no_next_page" and "last page" in pg3["error"] and n_req() == n0 and used("c-page")["api_used"] == u0,
      (code(pg3), pg3.get("error"), n_req() - n0))
qa = ads.search("soc", {"query": "quilted coverlet"})
qb = ads.search("soc", {"query": "quilted coverlet", "next_page": True})
cached1 = ads.search("soc", {"query": "bedding"})
n1 = n_req()
stop_again = ads.search("soc", {"query": "bedding", "next_page": True})
check("C5 a different query pages independently (its own page 1 and its own cursor), re-reading page 1 from the store does not revive a consumed cursor, and the stop holds",
      qa["has_more_pages"] and qb["ok"] and qb["has_more_pages"] is False and cached1.get("cached") and code(stop_again) == "no_next_page" and n_req() == n1,
      (qa["has_more_pages"], code(qb), code(stop_again)))
ads.find_advertiser("soc", {"query": "Harbor Home Linens"})
ca1 = ads.search("soc", {"advertiser_no": 1})
ca2 = ads.search("soc", {"advertiser_no": 1, "next_page": True})
n2 = n_req()
ca3 = ads.search("soc", {"advertiser_no": 1, "next_page": True})
check("C6 an advertiser's ads page the same way: page 1 cursor, page 2 terminal, the third attempt stops without a request; a next_page with no earlier page is also explicit",
      ca1["ok"] and ca1["has_more_pages"] and ca2["ok"] and ca2["has_more_pages"] is False and code(ca3) == "no_next_page" and n_req() == n2
      and code(ads.search("soc", {"query": "never searched", "next_page": True})) == "no_next_page", (code(ca3), ca2.get("has_more_pages")))

# --- 3. explicitly incompatible platforms
scope("c-plat", api=60, img=20)
PL = {"1100000000000001": ["FACEBOOK"], "1100000000000002": ["FACEBOOK", "INSTAGRAM"], "1100000000000003": ["INSTAGRAM"], "1100000000000004": "missing"}
fb_ctl(first="relevant", list_platforms=PL, detail_platforms={"1100000000000004": ["INSTAGRAM"]})
req("req-plat")
sp = ads.search("soc", {"query": "bedding"})
pp = {a["source_ad_id"]: a for a in sp["ads"]}
run_pl = ads.run_for("soc", "req-plat")["run_id"]
rec_pl = ads._load_ads(run_pl)
n03 = next(n for n, r in rec_pl.items() if r["ad_archive_id"] == "1100000000000003")
c0, d0 = n_req(["cdn"]), n_req(["detail"])
im03, de03 = ads.image("soc", {"ad_no": n03, "image_no": 1}), ads.detail("soc", {"ad_no": n03})
check("C7 search results: Facebook-only and Facebook+Instagram ads qualify, a missing platform list stays 'unknown' (not invented), an Instagram-only ad is excluded and disclosed; "
      "its image and detail cannot be requested (nothing sent)",
      sorted(pp) == ["1100000000000001", "1100000000000002", "1100000000000004"] and pp["1100000000000001"]["platform_status"] == "facebook"
      and pp["1100000000000002"]["platform_status"] == "facebook" and pp["1100000000000004"]["platform_status"] == "unknown"
      and sp["skipped"] == {"excluded_non_facebook_ads": 1} and code(im03) == "ad_not_on_facebook" and code(de03) == "ad_not_on_facebook"
      and n_req(["cdn"]) == c0 and n_req(["detail"]) == d0, (sorted(pp), sp.get("skipped"), code(im03), code(de03)))
n01, n02, n04 = pp["1100000000000001"]["ad_no"], pp["1100000000000002"]["ad_no"], pp["1100000000000004"]["ad_no"]
i01, i02, i04 = (ads.image("soc", {"ad_no": n, "image_no": 1}) for n in (n01, n02, n04))   # the unknown-platform ad is still downloadable
for i in (i01, i02, i04):
    INSP(i["image_id"])
d04 = ads.detail("soc", {"ad_no": n04})                                # its detail now says Instagram-only
n_c = n_req(["cdn"])
im04 = ads.image("soc", {"ad_no": n04, "image_no": 1})
sp2 = ads.search("soc", {"query": "bedding"})                           # the cached page no longer offers it
check("C8 an ad whose platform was unknown and is identified as Instagram-only by its detail response becomes ineligible: marked excluded, no longer downloadable "
      "(even though the file exists), not offered by the cached search page",
      i04["ok"] and d04["ok"] and d04["ad"].get("platform_status") == "excluded_not_on_facebook" and d04["ad"].get("platforms") == ["INSTAGRAM"]
      and "Facebook" in (d04["ad"].get("excluded") or "")
      and code(im04) == "ad_not_on_facebook" and n_req(["cdn"]) == n_c
      and sorted(a["source_ad_id"] for a in sp2["ads"]) == ["1100000000000001", "1100000000000002"] and sp2["skipped"] == {"excluded_non_facebook_ads": 2},
      (d04.get("ad", {}).get("excluded"), code(im04), sp2.get("skipped")))
sv04 = ads.save_package("soc", {**base, "references": [ref(n04, i04["image_id"])]})
sv_ok = ads.save_package("soc", {**base, "references": [ref(n01, i01["image_id"]), ref(n02, i02["image_id"])]})
pkg_pl = ads.get_package(sv_ok["package_id"]) if sv_ok.get("ok") else {}
cons = {c["source_ad_id"]: c for c in pkg_pl.get("ads_considered", [])}
check("C9 an ineligible ad cannot be selected even with a registered, inspected image; Facebook-only and mixed ads are accepted; the package discloses the exclusions (platforms listed)",
      code(sv04) == "ad_not_on_facebook" and sv_ok.get("ok") and sv_ok["status"] == "complete"
      and sorted(sv_ok.get("excluded_ads", []), key=lambda x: x["source_ad_id"])
      == [{"ad_no": n03, "source_ad_id": "1100000000000003", "reason": "not_on_facebook", "platforms": ["INSTAGRAM"]},
          {"ad_no": n04, "source_ad_id": "1100000000000004", "reason": "not_on_facebook", "platforms": ["INSTAGRAM"]}]
      and cons["1100000000000003"].get("excluded") == "not_on_facebook" and cons["1100000000000004"].get("platforms") == ["INSTAGRAM"]
      and cons["1100000000000002"].get("excluded") is None and cons["1100000000000002"].get("platforms") == ["FACEBOOK", "INSTAGRAM"] and {r["source_ad_id"] for r in pkg_pl["references"]} == {"1100000000000001", "1100000000000002"},
      (code(sv04), sv_ok.get("code"), sv_ok.get("excluded_ads")))
# the same ad identified by a LATER SEARCH (not a detail): the existing record is updated, not left eligible
scope("c-plat2", api=30, img=6)
fb_ctl(first="relevant", list_platforms={}, detail_platforms={})
req("req-plat2")
s_a = ads.search("soc", {"query": "bedding"})
na = {a["source_ad_id"]: a["ad_no"] for a in s_a["ads"]}["1100000000000001"]
fb_ctl(reset=False, first="relevant", list_platforms={"1100000000000001": ["INSTAGRAM"]})
s_b = ads.search("soc", {"query": "bedding", "status": "ALL"})
im_x = ads.image("soc", {"ad_no": na, "image_no": 1})
check("C10 a later search that reports an already-recorded ad as Instagram-only makes the stored ad ineligible too",
      "1100000000000001" in [a["source_ad_id"] for a in s_a["ads"]] and "1100000000000001" not in [a["source_ad_id"] for a in s_b["ads"]] and code(im_x) == "ad_not_on_facebook",
      (code(im_x),))
fb_ctl(first="relevant")


# --- 4. reach comparability needs an established period
def _mk(aid, eu, start=None, end=None, period=None):
    aaa = {"eu_total_reach": eu}
    if period is not None:
        aaa["reach_period"] = period
    return ads.norm_ad({"ad_archive_id": aid, "page_id": "1001", "start_date": start, "end_date": end, "aaa_info": aaa}, "detail", 1, "t")


r_a, r_b = _mk("1100000000000001", 20000, 1757000000, 1759000000), _mk("1100000000000002", 41000, 1700000000, 1710000000)
r_c, r_d = _mk("1100000000000003", 1000, 1757000000, None), _mk("1100000000000004", 2000, 1757000000, None)
g_diff, g_same = ads.reach_gate([r_a, r_b]), ads.reach_gate([r_c, r_d])
va = ads.reach_view(r_a)
check("C11 two same-metric/same-geography values with DIFFERENT ad dates, and two with IDENTICAL ad dates, are both gated: ad start/end dates are never a measurement period; "
      "values and provenance are preserved",
      g_diff["state"] == "disabled_period_unknown" and not g_diff["ranking_enabled"] and g_same["state"] == "disabled_period_unknown" and not g_same["ranking_enabled"]
      and va["state"] == "reported" and va["value"] == 20000 and va["geography"] == "EU" and va["period"] is None and va["source"] == "provider field aaa_info.eu_total_reach"
      and "period" in g_diff["reason"].lower(), (g_diff, va))
r_p = ads.norm_ad({"ad_archive_id": "1100000000000001", "page_id": "1001", "aaa_info": {"eu_total_reach": 5, "reach_period": "lifetime"}}, "detail", 1, "t")
check("C12 no documented field names the measurement window, so a lookalike field (reach_period) is NOT read as one: the period stays unknown",
      getattr(ads, "REACH_PERIOD_FIELD", "MISSING") is None and ads.reach_view(r_p)["period"] is None and "reach_period" not in json.dumps(r_p["reach_raw"]))
ads.REACH_PERIOD_FIELD = "reach_period"          # HYPOTHETICAL documented contract, injected by this test only; no such field exists in the documented schema
try:
    p1, p2 = _mk("1100000000000001", 20000, period="lifetime"), _mk("1100000000000002", 41000, period="lifetime")
    p3, nop = _mk("1100000000000003", 3000, period="last_7_days"), _mk("1100000000000004", 4000)
    g_ok, g_inc, g_mix = ads.reach_gate([p1, p2]), ads.reach_gate([p1, p3]), ads.reach_gate([p1, nop])
    g_amb = ads.reach_gate([p1, p2, nop])
finally:
    ads.REACH_PERIOD_FIELD = None
check("C13 the gate logic itself (hypothetical documented period): the same stated period enables ranking; different periods are incompatible; a missing period on any ranked "
      "value keeps it disabled",
      g_ok["state"] == "enabled" and g_ok["ranking_enabled"] and g_ok["metric"] == "eu_total_reach" and g_ok["geography"] == "EU" and g_ok.get("period") == "lifetime"
      and g_inc["state"] == "disabled_incompatible_metrics" and not g_inc["ranking_enabled"] and g_mix["state"] == "disabled_period_unknown"
      and g_amb["state"] == "disabled_period_unknown", (g_ok["state"], g_inc["state"], g_mix["state"], g_amb["state"]))
# end to end: present reach on detail -> reach_ranked refused, relevance_only package keeps the values and the unknown period
scope("c-reach", api=30, img=6)
fb_ctl(first="relevant", reach="present", list_platforms={}, detail_platforms={})
req("req-reach-c")
s_r = ads.search("soc", {"query": "bedding"})
nr = {a["source_ad_id"]: a["ad_no"] for a in s_r["ads"]}
d_r1, d_r2 = ads.detail("soc", {"ad_no": nr["1100000000000001"]}), ads.detail("soc", {"ad_no": nr["1100000000000004"]})
i_r = ads.image("soc", {"ad_no": nr["1100000000000001"], "image_no": 1})
INSP(i_r["image_id"])
rk = ads.save_package("soc", {**base, "selection_basis": "reach_ranked", "references": [ref(nr["1100000000000001"], i_r["image_id"])]})
ro = ads.save_package("soc", {**base, "selection_basis": "relevance_only", "references": [ref(nr["1100000000000001"], i_r["image_id"])]})
pr_ = ads.get_package(ro["package_id"]) if ro.get("ok") else {}
check("C14 end to end: two ads carry reported EU reach (period unknown) -> reach_ranked is rejected with the gate state; the same research saves as relevance_only with the reported "
      "values, geography and unknown period preserved and the gate disclosed",
      d_r2["reach_gate"]["state"] == "disabled_period_unknown" and code(rk) == "reach_ranking_unavailable" and rk.get("reach_gate", {}).get("state") == "disabled_period_unknown"
      and ro.get("ok") and pr_["selection_basis"] == "relevance_only" and pr_["reach_gate"]["ranking_enabled"] is False and pr_["reach_gate"]["state"] == "disabled_period_unknown"
      and pr_["cited_ads"][0]["reach"]["state"] == "reported" and pr_["cited_ads"][0]["reach"]["value"] == 27000 and pr_["cited_ads"][0]["reach"]["geography"] == "EU"
      and pr_["cited_ads"][0]["reach"]["period"] is None and pr_["cited_ads"][0]["reach"]["source"] == "provider field aaa_info.eu_total_reach", (code(rk), ro.get("code")))
fb_ctl(first="relevant")
# the pure gate must ignore ineligible ads
r_ig = _mk("1100000000000003", 9000)
r_ig["platforms"] = ["INSTAGRAM"]
r_ok1 = _mk("1100000000000001", 100)
g_pl = ads.reach_gate([r_ig, r_ok1])
check("C15 an ad excluded for platform does not contribute a reach value to the gate (one eligible value is a single value)",
      g_pl["state"] == "disabled_single_value" and g_pl["ads_with_reported_reach"] == 1 and g_pl["ads_recorded"] == 1, g_pl)

if os.environ.get("ADS_PART_A_ONLY") == "1":    # quick iteration while editing; the default full run still executes part B
    print(f"\nPART A only: {sum(results)}/{len(results)}", flush=True)
    sys.exit(0 if results and all(results) else 1)

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
          and got and all(g.get("size") == [240, 300] for g in got) and all(x["delivery"] == "image_part_sent" and x["counts_as_verified_evidence"] and x.get("delivery_confirmed") is True and x.get("delivered_at") for x in refs.values())
          and all(file_ok.values()), (set(refs), [g.get("mean") for g in got], file_ok))
    import sqlite3
    con = sqlite3.connect(ROOT / "runtime" / "app.db")
    insp_rows = con.execute("SELECT image_id, request_id, run_id, kind FROM image_inspections WHERE agent_id=? ORDER BY id", (A_ID,)).fetchall()
    con.close()
    check("B8b the REAL worker's inspect_image wrote the backend-supplied request id and ad run id on every inspection row, and the package's references show them",
          {r_[0] for r_ in insp_rows} == set(refs) and all(r_[1] == "b-req-1" and r_[2] == PKG["identity"]["run_id"] and r_[3] == "live_ad_image" for r_ in insp_rows)
          and all(x["inspection_request_id"] == "b-req-1" and x["inspection_run_id"] == PKG["identity"]["run_id"] for x in refs.values()), insp_rows)
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

    # ---- scenario 2: reach present on detail responses (documented EU field, measurement period NOT stated) + one Instagram-only ad
    fb_ctl(first="relevant", reach="present", list_platforms={"1100000000000003": ["INSTAGRAM"]})
    st, r = chat(A_ID, "AD_AGENT Research US Facebook image ads for our quilted coverlet. FIRST_QUERY:queen quilted coverlet", rid="b-req-2")
    P2, _ = package_of(r)
    excl2 = [c for c in P2.get("ads_considered", []) if c.get("excluded")]
    check("B11 reach PRESENT but its measurement period is unknown: the package keeps metric/value/EU geography/provenance, the gate is disabled_period_unknown (ranking is never "
          "accepted on values whose periods are not established), the scripted specialist selects by relevance and still completes; the Instagram-only ad is excluded and disclosed",
          P2.get("status") == "complete" and P2["reach_gate"]["state"] == "disabled_period_unknown" and P2["reach_gate"]["ranking_enabled"] is False
          and P2["selection_basis"] == "relevance_only"
          and all(a["reach"]["state"] == "reported" and a["reach"]["geography"] == "EU" and a["reach"]["value"] and a["reach"]["period"] is None for a in P2["cited_ads"])
          and "NOT US reach" in P2["cited_ads"][0]["reach"]["meaning"]
          and [(c["source_ad_id"], c["excluded"], c["platforms"]) for c in excl2] == [("1100000000000003", "not_on_facebook", ["INSTAGRAM"])]
          and "1100000000000003" not in {a["source_ad_id"] for a in P2["cited_ads"]} and P2["counts"]["ads_excluded"] == 1, (r["text"][:200], P2.get("reach_gate"), excl2))
    if os.environ.get("ADS_DUMP_CORRECTED"):   # the corrected, inspectable package: reach reported but gated, Instagram-only ad disclosed, inspection identity on each reference
        Path(os.environ["ADS_DUMP_CORRECTED"]).write_text(json.dumps({"package": P2, "run": http(APP, f"/api/ads/runs/{P2['identity']['run_id']}")[1]}, indent=1), encoding="utf-8")

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
