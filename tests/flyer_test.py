"""V2-04 tests: one saved flyer for the independent social_media specialist. Everything here uses SCRIPTED stand-ins: tests/mock_gemini.py (a Gemini Interactions
stand-in that returns GENERATED PLACEHOLDER images), tests/mock_llm.py (a rule-based specialist policy, not a model) and GENERATED placeholder 'merchant photos' that
are labelled synthetic. It proves backend wiring, grants, asset rules, attempt accounting, integrity checks, storage and retrieval; it is NOT real Gemini output,
NOT image quality or product fidelity, NOT real merchant photographs, and NOT a paid call. No real credential is ever loaded: the run refuses to start if the
project copy holds secrets/local.env in part A.
Part A: backend seams in-process (isolated app root, real SQLite, real tool bodies, real HTTP to the stand-in).
Part B: the scripted specialist through the REAL server, HTTP chat API, Hermes workers and read APIs (classifier off). Wipes the copy's runtime/: COPY ONLY:
  FLYER_I_AM_A_COPY=1 venv-python tests/flyer_test.py"""
import hashlib, io, json, os, re, shutil, subprocess, sys, tempfile, time, urllib.error, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import role_hold

ROOT = Path(__file__).resolve().parent.parent
if os.environ.get("FLYER_I_AM_A_COPY") != "1":
    sys.exit("Refusing to run: set FLYER_I_AM_A_COPY=1 and run from a COPY of the project.")
if (ROOT / "secrets" / "local.env").exists():
    sys.exit("Refusing to run: this copy holds secrets/local.env. Real credentials must never be loaded by a test copy.")
os.environ["HERMES_HOME"] = str(ROOT / "runtime" / "hermes_home" / "profiles" / "main")
TMP = Path(tempfile.mkdtemp(prefix="flyer_"))
GEM, MOCK, APP = 8794, 8780, 8830
KEY = "TEST-GEMINI-KEY-SENTINEL"          # the value tests/mock_gemini.py expects; not a credential
IMGS, CATS = TMP / "merchant_images", TMP / "catalogues"
IMGS.mkdir()
CATS.mkdir()
os.environ.update({"ECOM_APP_ROOT": str(TMP), "ECOM_GEMINI_URL": f"http://127.0.0.1:{GEM}", "GEMINI_API_KEY": KEY, "ECOM_FLYER_ALLOW_SYNTHETIC": "1",
                   "ECOM_IMAGE_DIRS": str(IMGS)})
for k in ("ECOM_FLYER_SCOPE", "ECOM_FLYER_MAX_ATTEMPTS", "GEMINI_MODEL", "GEMINI_IMAGE_SIZE", "ECOM_CATALOGUE_FILE"):
    os.environ.pop(k, None)
sys.path.insert(0, str(ROOT))
from app import ads, core, flyer, listing, turn_state, hermes_plugin as hp 

results, procs = [], []
import atexit
atexit.register(lambda: [p.terminate() for p in procs if p.poll() is None])


def check(name, ok, detail=""):
    ok = bool(ok); results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{str(detail)[:700]}]"), flush=True)


def http(port, path, body=None, timeout=600, raw=False):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
    try:
        for attempt in range(5):   # an intermittent Windows loopback reset of a large READ (~70 KB history; cause undiagnosed): a GET is idempotent, so re-read it
            try:
                r = urllib.request.urlopen(req, timeout=timeout)
                data = r.read()
                break
            except ConnectionResetError:
                if body is not None or attempt == 4:
                    raise
                time.sleep(1)
        return r.status, (data if raw else json.loads(data)), r.headers.get("Content-Type")
    except urllib.error.HTTPError as e:
        data = e.read()
        try:
            return e.code, (data if raw else json.loads(data)), e.headers.get("Content-Type")
        except ValueError:
            return e.code, data, None


def gem_ctl(**kw):
    return http(GEM, "/control", {"reset": True, **kw})[1]


def gem_stats():
    return http(GEM, "/stats")[1]


def gem_n():
    return gem_stats()["total"]


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


def make_image(name, color, size=(600, 800), fmt="PNG", folder=IMGS):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", size, color)
    ImageDraw.Draw(im).ellipse([size[0] // 4, size[1] // 4, 3 * size[0] // 4, 3 * size[1] // 4], fill=(255, 255, 255))
    p = folder / f"{name}.{ {'PNG': 'png', 'JPEG': 'jpg', 'GIF': 'gif'}[fmt] }"
    im.save(p, fmt)
    return p


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def code(r):
    return r.get("code") if isinstance(r, dict) and r.get("ok") is False else ("OK" if isinstance(r, dict) and r.get("ok") else r)


NOTICE = "FICTIONAL TEST DATA for scripted plumbing tests: the merchant and product are invented and every image is a generated placeholder, not a photograph."
PV = {"owner": "Test fixture generator", "date": "2026-10-13", "usage_statement": "Generated placeholder for scripted tests only"}


def write_cat(name, data):
    p = CATS / name
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def img_entry(iid, **kw):
    return {"image_id": iid, "kind": "test placeholder image (synthetic)", **kw}


ALT = {"schema": 1, "demo": False, "notice": NOTICE, "merchant": {"merchant_id": "harbor-textiles", "name": "Harbor Textiles"},
       "products": [
           {"product_id": "harbor-wool-throw", "name": "Heritage Wool Throw", "category": "throws", "condition": "new",
            "specifications": {"size": "130 x 180 cm", "material": "100% wool", "care": "Dry clean"}, "price": {"amount": 64.5, "currency": "EUR"},
            "images": [img_entry("hw-front"), img_entry("hw-detail"), img_entry("hw-room"), img_entry("hw-ghost"), img_entry("hw-corrupt"), img_entry("hw-gif"),
                       img_entry("hw-mkt")]},
           {"product_id": "harbor-linen-sheet", "name": "Washed Linen Sheet Set", "category": "bedding", "condition": "new",
            "specifications": {"size": "Queen", "material": "100% linen"}, "price": {"amount": 119, "currency": "EUR"}, "images": ["hl-main"]}]}
make_image("hw-front", (200, 120, 60))
make_image("hw-detail", (60, 130, 190), fmt="JPEG")
make_image("hw-room", (90, 160, 90))
make_image("hl-main", (180, 180, 220))
make_image("hw-gif", (10, 10, 10), size=(100, 100), fmt="GIF")
(IMGS / "hw-corrupt.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"garbage" * 20)
ALT_FILE = write_cat("alt.json", ALT)
os.environ["ECOM_CATALOGUE_FILE"] = str(ALT_FILE)
# a catalogue that does NOT carry the synthetic labels: it exercises the real-asset provenance gate (data shape only; the bytes are still placeholders)
REAL_LIKE = {"schema": 1, "merchant": {"merchant_id": "harbor-textiles", "name": "Harbor Textiles"},
             "products": [{"product_id": "p-noprov", "name": "Throw A", "specifications": {"size": "130 x 180 cm"}, "price": {"amount": 10, "currency": "EUR"},
                           "images": [{"image_id": "hw-front", "kind": "photograph"}]},
                          {"product_id": "p-prov", "name": "Throw B", "specifications": {"size": "130 x 180 cm"}, "price": {"amount": 12, "currency": "EUR"},
                           "images": [{"image_id": "hw-front", "kind": "photograph", "provenance": PV}]}]}
REAL_FILE = write_cat("real_like.json", REAL_LIKE)
# the V1 catalogue shape (single image) and an unreadable-product catalogue
LEGACY_FILE = ROOT / "tests" / "fixtures" / "demo_catalogue.json"
(TMP / "runtime" / "marketplace_check" / "images").mkdir(parents=True)
make_image("hw-mkt", (1, 2, 3), folder=TMP / "runtime" / "marketplace_check" / "images")   # a MARKETPLACE diagnostic photo that happens to share a catalogue id

spawn(["tests/mock_gemini.py", str(GEM)])
wait_up(GEM)
core.update_company({"name": "Harbor Textiles", "products": "Wool throws and linen bedding", "customers": "Home buyers", "goal": "Present our textiles clearly",
                     "brand": "Calm, natural, plain-spoken"}, source="form")
FLYER2 = list(core.FLYER_TOOLS)


def register(agent_id, tools, role="social_media"):
    with core.db() as d:
        d.execute("INSERT OR REPLACE INTO agents VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (agent_id, agent_id, role, "default", "o", "i", "[]", "[]", json.dumps(sorted(set(tools) | {"read_company_context", "memory", "skills"})), "[]",
                   f"conv-{agent_id}", "idle", time.time()))


register("soc", FLYER2 + ["inspect_image", "read_catalogue"])
register("soc-noflyer", ["inspect_image", "read_catalogue"])
register("ana", FLYER2 + ["marketplace_search"], role="market_analysis")


def req(rid, agent="soc"):
    turn_state.request_id, turn_state.run_id, turn_state.ad_run_id = rid, None, None
    os.environ["ECOM_AGENT_ID"] = agent


def scope(name, cap=50):
    os.environ["ECOM_FLYER_SCOPE"] = name
    os.environ["ECOM_FLYER_MAX_ATTEMPTS"] = str(cap)


def G(args, agent="soc"):
    return flyer.generate(agent, args)


def n_runs():
    with core.db() as d:
        return d.execute("SELECT COUNT(*) FROM flyer_runs").fetchone()[0], d.execute("SELECT COUNT(*) FROM flyer_attempts").fetchone()[0]


PROMPT = ("Create a clean promotional flyer for the Heritage Wool Throw. Headline: Heritage Wool Throw. Show the price exactly as declared: 64.5 EUR. "
          "Keep the supplied product photo prominent on a plain backdrop with a short call to action.")
BASE = {"product_id": "harbor-wool-throw", "selected_product_image_ids": ["hw-front", "hw-detail"], "prompt": PROMPT}

# ================= A. backend seams =================
print("PART A: backend seams (scripted Gemini stand-in; placeholder images; not real Gemini)", flush=True)
scope("f-main")
gem_ctl()
req("req-1")
r1 = G(BASE)
st = gem_stats()
rq = st["requests"][0] if st["requests"] else {}
want_imgs = [{"mime_type": "image/png", "sha256": sha(IMGS / "hw-front.png"), "bytes": (IMGS / "hw-front.png").stat().st_size},
             {"mime_type": "image/jpeg", "sha256": sha(IMGS / "hw-detail.jpg"), "bytes": (IMGS / "hw-detail.jpg").stat().st_size}]
check("A1 the scripted provider received exactly ONE request carrying the chosen merchant photographs' ORIGINAL bytes (hash/mime/order), the prompt and the supplied product facts; "
      "key only in the header; store=false; documented request fields only",
      r1.get("ok") and st["total"] == 1 and rq["path"] == "/v1beta/interactions" and rq["has_key"] and not rq["key_in_query"] and rq["model"] == "gemini-nano-banana-2.1"
      and rq["store"] is False and rq["extra_fields"] == [] and rq["images"] == want_imgs and rq["n_input"] == 3
      and rq["response_format"] == {"type": "image", "aspect_ratio": "4:5", "image_size": "2K", "mime_type": "image/jpeg"}
      and rq["text"].startswith(PROMPT) and "Heritage Wool Throw" in rq["text"] and "64.5 EUR" in rq["text"] and "100% wool" in rq["text"] and "Calm, natural" in rq["text"], (r1, rq))
fid = r1.get("flyer_id")
f1 = flyer.get_flyer(fid) or {}
a1 = f1.get("attempt", {})
img1 = flyer.image_file(fid)
from PIL import Image
im1 = Image.open(io.BytesIO(img1[0])) if img1 else None
rr1 = a1.get("request", {})
check("A1b the outgoing request has NO response_format.delivery (the live service rejected it with HTTP 400 'Image delivery mode is not supported.' on 2026-10-25), and the recorded request metadata "
      "agrees with what was actually sent: same model, aspect ratio, size, mime type, store flag and image count, and no delivery key",
      "delivery" not in rq["response_format"] and "delivery" not in rr1 and rr1.get("model") == rq["model"] and rr1.get("store") is rq["store"] and rr1.get("input_images") == rq["n_input"] - 1
      and all(rr1.get(k) == rq["response_format"][k] for k in ("aspect_ratio", "image_size", "mime_type")), (rq["response_format"], rr1))
check("A2 the attempt record keeps the exact prompt/context snapshot, input hashes, product snapshot, provider/model/request settings, usage, and one candidate artifact whose "
      "stored hash equals its bytes; status unchecked; trusted identity bound by the backend",
      f1.get("status") == "unchecked" and f1["content_status"] == "unchecked" and a1["prompt"] == PROMPT and a1["context_text"] == rq["text"]
      and [(i["image_id"], i["sha256"], i["mime_type"]) for i in a1["inputs"]] == [("hw-front", want_imgs[0]["sha256"], "image/png"), ("hw-detail", want_imgs[1]["sha256"], "image/jpeg")]
      and a1["product"]["name"] == "Heritage Wool Throw" and a1["product"]["price"] == {"amount": 64.5, "currency": "EUR"} and a1["model"] == "gemini-nano-banana-2.1"
      and a1["request"]["store"] is False and a1["request"]["retries"] == 0 and a1["usage"]["total_output_tokens"] == 1120 and a1["outcome"] == "ok"
      and a1["candidate_id"] == r1["candidate_id"] and a1["output"]["sha256"] == hashlib.sha256(img1[0]).hexdigest() == r1["image"]["sha256"] and img1[1] == "image/jpeg"
      and im1 is not None and im1.format == "JPEG" and f1["identity"]["agent_id"] == "soc" and f1["identity"]["company_name"] == "Harbor Textiles"
      and f1["identity"]["request_id"] == "req-1" and f1["identity"]["product_id"] == "harbor-wool-throw" and f1["inputs_synthetic"] is True
      and (f1["attempts"]["used"], f1["attempts"]["enabled"], f1["attempts"]["final_max"]) == (1, 2, 2) and "UNCHECKED" in f1["note"], (f1.get("status"), a1.get("outcome")))
check("A2b the tool result carries identifiers and hashes only (no image payload, key or signed URL) and never claims review or approval",
      len(json.dumps(r1)) < 3000 and KEY not in json.dumps(r1) and "base64" not in json.dumps(r1) and r1["status"] == "unchecked" and "approved" not in r1["note"].lower().replace("not approved", ""),
      json.dumps(r1)[:200])
n0 = gem_n()
r1b = G(BASE)
r1c = G({**BASE, "prompt": PROMPT + " Please use a different headline now."})
check("A3 a repeated call in the same request (even with another prompt) returns the STORED result: nothing re-sent, nothing re-counted, one attempt row",
      r1b.get("cached") and r1b["flyer_id"] == fid and r1c.get("cached") and gem_n() == n0 and n_runs() == (1, 1), (code(r1b), code(r1c), n_runs()))

# --- failures after dispatch consume the attempt and are never replayed
MODES = [("refuse", "bad_request"), ("auth", "auth_failed"), ("rate", "rate_limited"), ("server", "provider_error"), ("failed", "provider_failed"), ("no_image", "no_image"),
         ("two_images", "multiple_images"), ("corrupt", "invalid_output"), ("bad_base64", "invalid_output"), ("wrong_mime", "invalid_output"), ("uri_only", "invalid_output"),
         ("tiny", "invalid_output"), ("redirect", "redirect_refused")]
bad_rows = []
for mode, want in MODES:
    gem_ctl(mode=mode)
    req(f"req-f-{mode}")
    n0 = gem_n()
    g = G(BASE)
    sent = gem_n() - n0
    f = flyer.get_flyer(g.get("flyer_id")) or {}
    again = G(BASE)
    bad_rows.append((mode, want, code(g), g.get("outcome"), sent, f.get("status"), (f.get("image") is None), code(again), gem_n() - n0, KEY in json.dumps(g)))
ok_rows = [r for r in bad_rows if r[2] == "generation_failed" and r[3] == r[1] and r[4] == 1 and r[5] == "failed" and r[6] and r[7] == "attempt_already_consumed" and r[8] == 1 and not r[9]]
check("A4 every dispatched failure (provider refusal/auth/rate/5xx/failed status/no image/TWO images/corrupt bytes/bad base64/mislabelled type/URI-only/tiny/redirect) is a structured error, "
      "consumes the single attempt, stores no usable image, and an immediate retry sends NOTHING (attempt_already_consumed)", len(ok_rows) == len(MODES), [r for r in bad_rows if r not in ok_rows])
gem_ctl(mode="drop")
req("req-f-drop")
n0 = gem_n()
gd = G(BASE)
fd = flyer.get_flyer(gd.get("flyer_id")) or {}
gd2 = G(BASE)
check("A5 a connection lost after the send is reported as an UNKNOWN outcome, consumes the attempt, and is not replayed by the backend or an identical retry",
      code(gd) == "generation_outcome_unknown" and fd["attempt"]["outcome"] == "network_error" and fd["status"] == "failed" and code(gd2) == "attempt_already_consumed"
      and gem_n() - n0 == 1, (code(gd), code(gd2), gem_n() - n0))
gem_ctl()
# a crash between reservation and outcome leaves a reserved attempt: reported as uncertain, never re-sent
req("req-f-crash")
state, run, att = flyer._reserve("soc", "req-f-crash", {"company_name": "Harbor Textiles", "product_id": "harbor-wool-throw", "prompt": "p", "context_text": "c", "model": "m",
                                                         "request": {}, "synthetic": True, "product": {}, "inputs": [], "references": []})
n0 = gem_n()
gc = G(BASE)
check("A6 a RESERVED attempt with no outcome (interrupted process or a call still running) is reported as uncertain; nothing is sent and no second attempt starts",
      state == "go" and code(gc) == "generation_outcome_unknown" and gc["status"] == "in_progress_or_unknown" and gem_n() == n0, (state, code(gc)))
# storage failure after a successful generation
req("req-f-store")
blocker = TMP / "blocker"
blocker.write_text("not a directory")
real_dir = flyer.flyer_dir
flyer.flyer_dir = lambda rid: blocker / rid
n0 = gem_n()
gs = G(BASE)
flyer.flyer_dir = real_dir
gs2 = G(BASE)
fs = flyer.get_flyer(gs.get("flyer_id")) or {}
check("A7 a valid generated image that cannot be stored is reported as a storage error (never success), consumes the attempt, is not generated again and is not served",
      code(gs) == "storage_error" and fs["attempt"]["outcome"] == "ok_unsaved" and fs["status"] == "failed" and flyer.image_file(gs["flyer_id"]) is None
      and code(gs2) == "attempt_already_consumed" and gem_n() - n0 == 1, (code(gs), code(gs2)))

# --- setup errors and validation never claim an attempt
runs0, n0 = n_runs(), gem_n()
os.environ.pop("GEMINI_API_KEY")
req("req-nokey")
nk = G(BASE)
os.environ["GEMINI_API_KEY"] = KEY
check("A8 a missing Gemini key is a clear structured setup error naming the field and file: nothing sent, no attempt row, no fallback generator",
      code(nk) == "missing_credentials" and "GEMINI_API_KEY" in nk["error"] and "secrets/local.env" in nk["error"] and gem_n() == n0 and n_runs() == runs0, nk)
req("req-val")
bad = []
for extra in ({"model": "x"}, {"api_key": "k"}, {"url": "https://evil.example/x.png"}, {"path": "C:/x.png"}, {"run_id": "fly-0000000000"}, {"attempt": 2}, {"allowance": 99},
              {"image_size": "4K"}):
    bad.append(("invalid_argument", code(G({**BASE, **extra}))))
bad += [("bad_argument", code(G({**BASE, "previous_candidate_id": "cand-0000000000"}))),   # V2-05: a correction needs BOTH previous_candidate_id and corrections
        ("bad_argument", code(G({**BASE, "corrections": "x"}))), ("bad_argument", code(G({**BASE, "product_id": 5}))), ("bad_argument", code(G({**BASE, "selected_product_image_ids": []}))),
        ("bad_argument", code(G({**BASE, "selected_product_image_ids": ["hw-front", "hw-detail", "hw-room", "hl-main"]}))),
        ("bad_argument", code(G({**BASE, "selected_product_image_ids": ["hw-front", "hw-front"]}))),
        ("bad_argument", code(G({**BASE, "selected_product_image_ids": ["../../app"]}))),
        ("bad_argument", code(G({**BASE, "selected_product_image_ids": ["C:\\x\\y.png"]}))), ("bad_argument", code(G({**BASE, "prompt": "too short"}))),
        ("unknown_product", code(G({**BASE, "product_id": "nope"}))),
        ("image_not_registered_for_product", code(G({**BASE, "selected_product_image_ids": ["hl-main"]}))),                 # another product's image
        ("image_not_registered_for_product", code(G({**BASE, "selected_product_image_ids": ["ad-1100000000000001-1"]}))),   # a competitor ad image
        ("image_not_registered_for_product", code(G({**BASE, "selected_product_image_ids": ["1638806271151287"]}))),         # a Marketplace listing photo id
        ("image_not_registered_for_product", code(G({**BASE, "selected_product_image_ids": ["random-unregistered"]}))),
        ("merchant_image_missing", code(G({**BASE, "selected_product_image_ids": ["hw-ghost"]}))),
        ("merchant_image_unreadable", code(G({**BASE, "selected_product_image_ids": ["hw-corrupt"]}))),
        ("merchant_image_unsupported", code(G({**BASE, "selected_product_image_ids": ["hw-gif"]})))]
flyer.MAX_INPUT_TOTAL = 100
bad.append(("inputs_too_large", code(G(BASE))))
flyer.MAX_INPUT_TOTAL = 12_000_000
os.environ["ECOM_FLYER_ALLOW_SYNTHETIC"] = "0"
bad.append(("synthetic_asset_not_allowed", code(G(BASE))))
os.environ["ECOM_FLYER_ALLOW_SYNTHETIC"] = "1"
os.environ["ECOM_CATALOGUE_FILE"] = str(REAL_FILE)
os.environ["ECOM_FLYER_ALLOW_SYNTHETIC"] = "0"
bad.append(("asset_provenance_missing", code(G({"product_id": "p-noprov", "selected_product_image_ids": ["hw-front"], "prompt": PROMPT}))))
os.environ["ECOM_FLYER_ALLOW_SYNTHETIC"] = "1"
os.environ["ECOM_CATALOGUE_FILE"] = str(ALT_FILE)
core.update_company({"name": "Some Other Company"}, source="form")
bad.append(("catalogue_company_mismatch", code(G(BASE))))
core.update_company({"name": "Harbor Textiles"}, source="form")
os.environ["ECOM_GEMINI_URL"] = "http://evil.example:9"
bad.append(("provider_config_invalid", code(G(BASE))))
os.environ["ECOM_GEMINI_URL"] = f"http://127.0.0.1:{GEM}"
os.environ["GEMINI_IMAGE_SIZE"] = "9K"
bad.append(("provider_config_invalid", code(G(BASE))))
os.environ.pop("GEMINI_IMAGE_SIZE")
wrong = [b for b in bad if b[0] != b[1]]
check("A9 invalid arguments, unregistered/competitor/Marketplace/other-product images, missing/corrupt/unsupported/oversized files, synthetic stand-ins, missing provenance, a company "
      "mismatch and bad provider settings are ALL rejected before dispatch: nothing sent, no run or attempt created", not wrong and gem_n() == n0 and n_runs() == runs0, (wrong, gem_n() - n0))
n1 = gem_n()
req("req-ok-prov")
os.environ["ECOM_CATALOGUE_FILE"] = str(REAL_FILE)
os.environ["ECOM_FLYER_ALLOW_SYNTHETIC"] = "0"
gp = G({"product_id": "p-prov", "selected_product_image_ids": ["hw-front"], "prompt": PROMPT})
os.environ["ECOM_FLYER_ALLOW_SYNTHETIC"] = "1"
os.environ["ECOM_CATALOGUE_FILE"] = str(ALT_FILE)
fp = flyer.get_flyer(gp.get("flyer_id")) or {}
check("A9b with documented provenance and no synthetic label the asset gate passes (no operator seam needed) and the record says the inputs were not flagged synthetic",
      gp.get("ok") and gem_n() - n1 == 1 and fp["inputs_synthetic"] is False and fp["attempt"]["inputs"][0]["provenance"] == PV, (code(gp), gp.get("error")))

# --- grants and roles
req("req-g")
n0 = gem_n()
c_ng = code(G(BASE, "soc-noflyer"))
c_ma = code(G(BASE, "ana"))
c_gh = code(G(BASE, "ghost"))
req(None)
c_nr = code(G(BASE))
c_rd = code(flyer.read_flyer("soc-noflyer", {}))
req("req-g")
check("A10 an ungranted social specialist, a market-analysis agent (even with edited grants), an unregistered agent and a call outside a manual request are refused; nothing is sent",
      (c_ng, c_ma, c_gh, c_nr, c_rd) == ("not_granted", "not_permitted_for_role", "unknown_agent", "no_manual_request", "not_granted") and gem_n() == n0, (c_ng, c_ma, c_gh, c_nr, c_rd))

# --- references are provenance only
req("req-ref")
orun = ads.open_run("soc", "req-ref")
with core.db() as d:
    d.execute("INSERT INTO ad_images(run_id, image_id, ad_archive_id, ad_no, image_no, source_field, sha256, bytes, width, height, content_type, format, host, fetched_at, path) "
              "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (orun["run_id"], "ad-1100000000000001-1", "1100000000000001", 1, 1, "images[0]", "ab" * 32, 10, 1, 1, "image/png", "PNG",
                                                       "127.0.0.1", time.time(), "x.png"))
    d.execute("INSERT INTO ad_records(run_id, ad_no, ad_archive_id, record, first_call, retrieved_at) VALUES(?,?,?,?,?,?)",
              (orun["run_id"], 1, "1100000000000001", json.dumps({"ad_archive_id": "1100000000000001", "source_url": "https://www.facebook.com/ads/library?id=1100000000000001"}), 0, "t"))
n0 = gem_n()
rbad = G({**BASE, "reference_ad_image_ids": ["ad-1100000000000009-1"]})
rok = G({**BASE, "reference_ad_image_ids": ["ad-1100000000000001-1"]})
rq2 = gem_stats()["requests"][-1]
fr = flyer.get_flyer(rok.get("flyer_id")) or {}
check("A11 a cited competitor ad image must be registered by THIS request's ad research, is stored as provenance (source ad id/link/hash) and is NEVER sent to Gemini "
      "(only the two merchant photographs are)",
      code(rbad) == "reference_not_registered" and rok.get("ok") and gem_n() - n0 == 1 and len(rq2["images"]) == 2
      and fr["attempt"]["references"] == [{"image_id": "ad-1100000000000001-1", "source_ad_id": "1100000000000001", "sha256": "ab" * 32,
                                            "source_url": "https://www.facebook.com/ads/library?id=1100000000000001", "sent_to_provider": False}], (code(rbad), fr.get("attempt", {}).get("references")))

# --- alternate configured merchant/product, the V1 single-image catalogue
req("req-alt")
ga = G({"product_id": "harbor-linen-sheet", "selected_product_image_ids": ["hl-main"], "prompt": "Create a calm flyer for the Washed Linen Sheet Set at 119 EUR, product photo large on a light background."})
rqa = gem_stats()["requests"][-1]
cat_alt = listing.read_catalogue()
os.environ["ECOM_CATALOGUE_FILE"] = str(LEGACY_FILE)
os.environ["ECOM_IMAGE_DIRS"] = str(ROOT / "tests" / "fixtures" / "demo_images")   # (the app root is the temp dir here, so the default fixture folder is named explicitly)
core.update_company({"name": "Acme Linens (fictional demo merchant)"}, source="form")
req("req-legacy")
gl = G({"product_id": "acme-cloud-quilt-queen", "selected_product_image_ids": ["demo-quilt-front"],
        "prompt": "Create a simple flyer for the Cloud Weave Quilted Coverlet, Queen at 89 USD with the supplied picture centred."})
rql = gem_stats()["requests"][-1]
cat_leg = listing.read_catalogue()
os.environ["ECOM_CATALOGUE_FILE"] = str(ALT_FILE)
os.environ["ECOM_IMAGE_DIRS"] = str(IMGS)
core.update_company({"name": "Harbor Textiles"}, source="form")
check("A12 a configured alternate merchant/product (bare-id image list, EUR price) and the V1 single-image demo catalogue both generate through the SAME code, with their own facts "
      "and image bytes; read_catalogue exposes registered images for both shapes",
      ga.get("ok") and "Washed Linen Sheet Set" in rqa["text"] and "119 EUR" in rqa["text"] and rqa["images"][0]["sha256"] == sha(IMGS / "hl-main.png")
      and gl.get("ok") and "Cloud Weave Quilted Coverlet" in rql["text"] and "89.0 USD" in rql["text"]
      and rql["images"][0]["sha256"] == sha(ROOT / "tests" / "fixtures" / "demo_images" / "demo-quilt-front.png")
      and [i["image_id"] for p in cat_alt["products"] for i in p["images"]][-1] == "hl-main" and cat_leg["products"][0]["images"][0]["image_id"] == "demo-quilt-front"
      and cat_leg["products"][0]["image_inspectable"] is True, (code(ga), code(gl), ga.get("error"), gl.get("error")))
req("req-mkt")
n0 = gem_n()
os.environ.pop("ECOM_IMAGE_DIRS")                                       # default roots: the Marketplace diagnostic cache IS an image root for inspect_image...
seen_by_inspect = core.prepare_image("hw-mkt").get("ok")
gm = G({**BASE, "selected_product_image_ids": ["hw-mkt"]})            # ...but never a merchant-photograph root
os.environ["ECOM_IMAGE_DIRS"] = str(IMGS)
check("A13 merchant photographs resolve only from the merchant image roots: a catalogue id that matches a Marketplace diagnostic photo file (visible to inspect_image) is NOT "
      "picked up from there",
      seen_by_inspect is True and code(gm) == "merchant_image_missing" and gem_n() == n0, (seen_by_inspect, code(gm)))

# --- allowance cannot be replenished
scope("f-cap", cap=2)
res = []
for i in range(3):
    req(f"req-cap-{i}")
    res.append(G(BASE))
os.environ["ECOM_FLYER_MAX_ATTEMPTS"] = "500"
req("req-cap-3")
r4 = G(BASE)
req("req-cap-0")
back = G(BASE)
with core.db() as d:
    al = dict(d.execute("SELECT * FROM flyer_allowance WHERE scope='f-cap'").fetchone())
check("A14 the per-scope attempt cap holds: two requests generate, the third is refused with nothing sent, a larger environment value does not re-size an existing scope, and an "
      "already-generated request still retrieves its stored result",
      res[0].get("ok") and res[1].get("ok") and code(res[2]) == "allowance_exhausted" and code(r4) == "allowance_exhausted" and al["attempts_max"] == 2 and al["attempts_used"] == 2
      and back.get("cached"), ([code(r) for r in res], code(r4), al))
scope("f-conc")

# --- concurrency: real processes racing for ONE manual request
CHILD = r'''
import json, os, sys
sys.path.insert(0, os.environ["ROOT_DIR"])
from app import flyer, turn_state
turn_state.request_id = "req-conc"
os.environ["ECOM_AGENT_ID"] = "soc"
a = json.loads(os.environ["ARGS_JSON"])
r = flyer.generate("soc", a)
print(json.dumps({"code": r.get("code") if r.get("ok") is False else "OK", "cached": r.get("cached"), "flyer": r.get("flyer_id")}))
'''
gem_ctl(delay_ms=1500)
n0 = gem_n()
env = {**os.environ, "PYTHONUTF8": "1", "ROOT_DIR": str(ROOT), "ARGS_JSON": json.dumps(BASE)}
kids = [subprocess.Popen([sys.executable, "-c", CHILD], env=env, stdout=subprocess.PIPE, text=True) for _ in range(4)]
outs = [json.loads(k.communicate()[0].strip().splitlines()[-1]) for k in kids]
sent_conc = gem_n() - n0
gem_ctl()
flat = [o["code"] for o in outs]
check("A15 four processes racing for ONE request send exactly ONE provider request: one OK, the rest report the in-flight attempt as uncertain or return the stored result",
      sent_conc == 1 and flat.count("OK") >= 1 and all(c in ("OK", "generation_outcome_unknown") for c in flat),
      (flat, sent_conc))
with core.db() as d:
    conc_attempts = d.execute("SELECT COUNT(*) FROM flyer_attempts a JOIN flyer_runs r ON r.run_id=a.run_id WHERE r.request_id='req-conc'").fetchone()[0]
check("A15b exactly one attempt row exists for that request", conc_attempts == 1, conc_attempts)


# ================= review corrections (Codex review 2026-10-13, research/v2-ticket04-review-20261013.md) =================
print("review corrections", flush=True)
scope("f-corr")
gem_ctl()
from PIL import Image as _PI  # the replacement image: a DIFFERENT but perfectly valid JPEG
_b = io.BytesIO()
_PI.new("RGB", (800, 1000), (3, 3, 3)).save(_b, "JPEG")
OTHER_VALID = _b.getvalue()


def GS(a):   # a defect must show up as a failed check, not as an aborted run
    try:
        return G(a)
    except Exception as ex:
        return {"ok": False, "code": "TEST_EXCEPTION", "error": repr(ex)}


def make_flyer(rid):
    req(rid)
    g = G(BASE)
    return g["flyer_id"], g


def art_path(ffid):
    with core.db() as d:
        return flyer.flyer_dir(ffid) / d.execute("SELECT out_path FROM flyer_attempts WHERE run_id=?", (ffid,)).fetchone()[0]


def scope_used():
    with core.db() as d:
        return d.execute("SELECT attempts_used FROM flyer_allowance WHERE scope='f-corr'").fetchone()[0]


# --- 1. persisted artifacts are validated on retrieval
fv, gv = make_flyer("req-c1-valid")
orig = art_path(fv).read_bytes()
sv = next(x for x in flyer.list_flyers("soc") if x["flyer_id"] == fv)
check("C1 a valid saved output is listed, detailed, returned from the cache and served, with an explicit valid integrity state",
      sv["status"] == "unchecked" and sv["image"]["url"] and sv.get("integrity", {}).get("state") == "valid" and flyer.image_file(fv)[0] == orig
      and flyer.get_flyer(fv)["attempt"]["output"]["sha256"] == gv["image"]["sha256"] and G(BASE).get("cached") is True, sv.get("integrity"))
dmg_rows, dmg_ids = [], {}


def unlink_(p):
    p.unlink()


def to_dir(p):
    p.unlink()
    p.mkdir()


DAMAGE = {"missing": unlink_, "truncated": lambda p: p.write_bytes(orig[: len(orig) // 2]), "replaced_valid": lambda p: p.write_bytes(OTHER_VALID),
          "zero_bytes": lambda p: p.write_bytes(b""), "not_a_file": to_dir}
for name, fn in DAMAGE.items():
    rid = f"req-c1-{name}"
    ffid, g0 = make_flyer(rid)
    used0, n_gem = scope_used(), gem_n()
    fn(art_path(ffid))
    s = next(x for x in flyer.list_flyers("soc") if x["flyer_id"] == ffid)
    d = flyer.get_flyer(ffid)
    img = flyer.image_file(ffid)
    req(rid)
    again = G(BASE)
    dmg_ids[name] = (ffid, rid)
    dmg_rows.append((name, s["status"], s["image"], (d.get("attempt") or {}).get("output"), img, code(again), again.get("status"), gem_n() - n_gem, d["attempt"]["outcome"],
                     d["attempts"]["used"], scope_used() - used0, bool(s.get("error")) and s.get("error_kind") == "storage_integrity" and s["integrity"]["state"] == "failed"))
good_rows = [r for r in dmg_rows if r[1] == "storage_failure" and r[2] is None and r[3] is None and r[4] is None and r[5] == "artifact_integrity_failed"
             and r[6] == "storage_failure" and r[7] == 0 and r[8] == "ok" and r[9] == 1 and r[10] == 0 and r[11]]
check("C2 a missing / truncated / replaced-by-another-valid-image / zero-byte / not-a-file artifact is an explicit storage-integrity failure in list, detail, the cached generation "
      "result and the image lookup (no image reference, no bytes), the ORIGINAL generation outcome and the attempt count are untouched and nothing is sent or regenerated",
      len(good_rows) == len(DAMAGE), [r for r in dmg_rows if r not in good_rows])
# an unreadable file (permission) and a tampered database path
fid_u, rid_u = make_flyer("req-c1-unreadable")
_target = art_path(fid_u).name
_real_rb = Path.read_bytes


def _deny(self):
    if self.name == _target:
        raise PermissionError(13, "denied (scripted)")
    return _real_rb(self)


Path.read_bytes = _deny
try:
    su = next(x for x in flyer.list_flyers("soc") if x["flyer_id"] == fid_u)
    iu = flyer.image_file(fid_u)
finally:
    Path.read_bytes = _real_rb
fid_t, rid_t = make_flyer("req-c1-tamper")
with core.db() as d:
    d.execute("UPDATE flyer_attempts SET out_path='../../app.db' WHERE run_id=?", (fid_t,))
st_ = next(x for x in flyer.list_flyers("soc") if x["flyer_id"] == fid_t)
check("C3 unreadable storage and a database path pointing outside the managed folder are explicit integrity failures too (never a successful file response)",
      su["status"] == "storage_failure" and iu is None and su["image"] is None and st_["status"] == "storage_failure" and flyer.image_file(fid_t) is None, (su["status"], st_["status"]))
p_miss = art_path(dmg_ids["missing"][0])
check("C3b integrity is computed on read, not stored: restoring the original bytes makes that flyer valid again without any generation or attempt change",
      (art_path(dmg_ids["truncated"][0]).write_bytes(orig), next(x for x in flyer.list_flyers("soc") if x["flyer_id"] == dmg_ids["truncated"][0])["status"])[1] == "unchecked"
      and scope_used() == 8 and not p_miss.exists(), scope_used())

# --- 2. malformed provider responses are classified, durable and consumed
MAL = ["toplevel_list", "steps_int", "steps_item_int", "content_int", "content_item_str"]
mal_rows, mal_ids = [], {}
for mode in MAL:
    gem_ctl(mode=mode)
    rid = f"req-c2-{mode}"
    req(rid)
    n_gem = gem_n()
    g = GS(BASE)
    sent = gem_n() - n_gem
    f = flyer.get_flyer(g.get("flyer_id")) or {}
    at = f.get("attempt") or {}
    again = G(BASE)
    mal_ids[mode] = (g.get("flyer_id"), rid)
    mal_rows.append((mode, code(g), g.get("outcome"), sent, at.get("status"), at.get("outcome"), at.get("http_status"), isinstance(at.get("ms"), int), bool(at.get("error")),
                     code(again), gem_n() - n_gem, f.get("status")))
gem_ctl()
ok_mal = [r for r in mal_rows if r[1] == "generation_failed" and r[2] == "bad_response" and r[3] == 1 and r[4] == "done" and r[5] == "bad_response" and r[6] == 200 and r[7]
          and r[8] and r[9] == "attempt_already_consumed" and r[10] == 1 and r[11] == "failed"]
check("C4 a COMPLETED 200 response with a malformed container (top-level array, steps: 1, steps: [1], content: 1, content: ['x']) is a structured terminal failure: "
      "one send, attempt done with HTTP status/timing/diagnostic, consumed, never an unknown or dispatched attempt, and an immediate retry sends nothing",
      len(ok_mal) == len(MAL), [r for r in mal_rows if r not in ok_mal])
gem_ctl(mode="steps_int")
req("req-c2-usage")
g_us = GS(BASE)
at_us = (flyer.get_flyer(g_us.get("flyer_id")) or {}).get("attempt", {})
gem_ctl()
check("C4b the usage totals the malformed response did carry are still recorded with the failure", (at_us.get("usage") or {}).get("total_output_tokens") == 1120, at_us.get("usage"))
gem_ctl(mode="usage_str")
req("req-c2-usage-str")
g_ustr = GS(BASE)
gem_ctl()
check("C4c valid handling is preserved: a malformed usage object (diagnostic only) does not fail an otherwise valid generation; it is simply not recorded",
      g_ustr.get("ok") and g_ustr.get("usage") in (None, {}) and g_ustr["status"] == "unchecked", g_ustr)

# --- 3. provider-derived diagnostics never keep or expose the API key
ECHO = ["echo_text", "echo_status", "echo_id", "echo_mime", "refuse"]
leaks = []
for mode in ECHO:
    gem_ctl(mode=mode)
    rid = f"req-c3-{mode}"
    req(rid)
    g = GS(BASE)
    ffid = g.get("flyer_id")
    with core.db() as d:
        row = json.dumps(dict(d.execute("SELECT * FROM flyer_attempts WHERE run_id=?", (ffid,)).fetchone()), default=str)
    rd = flyer.read_flyer("soc", {"flyer_id": ffid})
    blob = json.dumps([g, row, flyer.get_flyer(ffid), [x for x in flyer.list_flyers("soc") if x["flyer_id"] == ffid], rd, G(BASE)], default=str)
    leaks.append((mode, KEY in blob, "***" in blob or mode in ("echo_id",), code(g)))
gem_ctl()
_real_post = flyer._post


def _post_raises(*a, **k):
    raise ConnectionError(f"proxy refused and echoed {KEY}")


flyer._post = _post_raises
req("req-c3-exc")
g_ex = GS(BASE)
flyer._post = _real_post
with core.db() as d:
    row_ex = json.dumps(dict(d.execute("SELECT * FROM flyer_attempts WHERE run_id=?", (g_ex.get("flyer_id"),)).fetchone()), default=str)
leaks.append(("exception", KEY in json.dumps(g_ex) or KEY in row_ex, "***" in row_ex, code(g_ex)))
bad_leaks = [r for r in leaks if r[1] or not r[2]]
check("C5 an echoed API key (fake sentinel) in provider text blocks, the status string, the interaction id, an image label, a provider error message and a transport exception is "
      "redacted from the tool result, the stored attempt row, flyer detail/list and read_flyer", not bad_leaks, bad_leaks)

# ---- restart: fresh process, provider stopped, no key: damaged and malformed flyers stay explicit failures; nothing is sent
CHILD3 = r"""
import json, os, sys
sys.path.insert(0, os.environ["ROOT_DIR"])
os.environ.pop("GEMINI_API_KEY", None)
from app import flyer, turn_state
out = {}
os.environ["ECOM_AGENT_ID"] = "soc"
for ffid, rid in json.loads(os.environ["IDS_JSON"]):
    f = flyer.get_flyer(ffid)
    turn_state.request_id = rid
    r = flyer.generate("soc", json.loads(os.environ["ARGS_JSON"]))
    out[ffid] = [f["status"], f["image"], flyer.image_file(ffid) is None, r.get("code") if r.get("ok") is False else "OK", f["attempt"]["outcome"]]
print(json.dumps(out))
"""

# --- restart with the provider stopped and no key: stored results are read; a repeated call returns the stored result without credentials
procs[0].terminate()
procs[0].wait()
CHILD2 = r'''
import json, os, sys
sys.path.insert(0, os.environ["ROOT_DIR"])
os.environ.pop("GEMINI_API_KEY", None)
from app import flyer, turn_state
fid = sys.argv[1]
f = flyer.get_flyer(fid)
im = flyer.image_file(fid)
turn_state.request_id = "req-1"
os.environ["ECOM_AGENT_ID"] = "soc"
again = flyer.generate("soc", json.loads(os.environ["ARGS_JSON"]))
print(json.dumps({"status": f["status"], "sha": f["image"]["sha256"], "img": len(im[0]) if im else None, "n": len(flyer.list_flyers("soc")),
                  "bad": [flyer.image_file(x) for x in ("../../app.db", "fly-zzzzzzzzzz", None, "fly-0000000000")], "again": again.get("cached"), "again_code": again.get("code")}))
'''
env = {k: v for k, v in os.environ.items() if k != "GEMINI_API_KEY"} | {"PYTHONUTF8": "1", "ROOT_DIR": str(ROOT), "ARGS_JSON": json.dumps(BASE)}
o = subprocess.run([sys.executable, "-c", CHILD2, fid], env=env, capture_output=True, text=True)
got = json.loads(o.stdout.strip().splitlines()[-1]) if o.stdout.strip() else {"err": o.stderr[-300:]}
check("A16 with the provider STOPPED and no key, a fresh process lists/reads the saved flyer and its image bytes unchanged, malformed/path-like ids resolve to nothing, and a repeated "
      "generate_flyer in the same request returns the stored result (no credentials, no network)",
      got.get("status") == "unchecked" and got["sha"] == r1["image"]["sha256"] and got["img"] == r1["image"]["bytes"] and got["n"] >= 10 and got["bad"] == [None] * 4
      and got["again"] is True, got)


ids3 = [dmg_ids[k] for k in ("missing", "truncated", "replaced_valid", "zero_bytes", "not_a_file")] + [mal_ids[k] for k in MAL]
env3 = {k: v for k, v in os.environ.items() if k != "GEMINI_API_KEY"} | {"PYTHONUTF8": "1", "ROOT_DIR": str(ROOT), "ARGS_JSON": json.dumps(BASE), "IDS_JSON": json.dumps(ids3)}
o3 = subprocess.run([sys.executable, "-c", CHILD3], env=env3, capture_output=True, text=True)
got3 = json.loads(o3.stdout.strip().splitlines()[-1]) if o3.stdout.strip() else {"err": o3.stderr[-300:]}
want_dmg = ["storage_failure", None, True, "artifact_integrity_failed", "ok"]
want_mal = ["failed", None, True, "attempt_already_consumed", "bad_response"]
# (the 'truncated' flyer was restored above, so it is valid again: its stored result is returned)
bad3 = {fid: got3.get(fid) for fid, _ in ids3 if got3.get(fid) not in (want_dmg, want_mal, ["unchecked", got3.get(fid, [0, 0])[1], False, "OK", "ok"])}
check("C6 after a restart (fresh process, provider stopped, no key) damaged artifacts remain explicit integrity failures and malformed-response failures remain consumed failures: "
      "every retrieval and every repeated generate_flyer is answered from storage with ZERO provider requests",
      not bad3 and len(got3) == len(ids3), (bad3, o3.stderr[-200:]))

# --- roles, grants, SOUL, tool descriptions (pure)
soc_el, ana_el = core.ROLES["social_media"]["eligible_tools"], core.ROLES["market_analysis"]["eligible_tools"]
GOODSK = [{"name": "flyer-routine", "content": "# Flyer routine\n1. Read the catalogue.\n2. Inspect the photos.\n3. Generate one flyer."}]
okc, e = core.validate_create_agent({"role": "social_media", "name": "Harbor Social", "objective": "Produce one accurate promotional flyer per request for Harbor's textiles.",
                                     "instructions": "You work for Harbor Textiles (fictional). Use only supplied facts; the flyer is unchecked.", "skills": GOODSK,
                                     "requested_tools": FLYER2 + ["inspect_image", "read_catalogue"]})
ana_c, e2 = core.validate_create_agent({"role": "market_analysis", "name": "Harbor Analyst", "objective": "o" * 50, "instructions": "i" * 50, "skills": GOODSK,
                                        "requested_tools": ["generate_flyer"]})
soul_f = core.build_soul({"name": "S", "role": "social_media", "objective": "o", "instructions": "i", "tools": FLYER2 + ["inspect_image", "read_catalogue"]}, "Harbor")
soul_g = core.build_soul({"name": "S", "role": "social_media", "objective": "o", "instructions": "i", "tools": ["generate_flyer", "read_flyer", "inspect_image", "read_catalogue"]}, "Harbor")
soul_fa = core.build_soul({"name": "S", "role": "social_media", "objective": "o", "instructions": "i", "tools": FLYER2 + list(core.AD_TOOLS) + ["inspect_image", "read_catalogue"]}, "Harbor")
soul_n = core.build_soul({"name": "S", "role": "social_media", "objective": "o", "instructions": "i", "tools": ["inspect_image", "read_catalogue"]}, "Harbor")
soul_ads = core.build_soul({"name": "S", "role": "social_media", "objective": "o", "instructions": "i", "tools": list(core.AD_TOOLS) + ["inspect_image", "read_catalogue"]}, "Harbor")
soul_ma = core.build_soul({"name": "A", "role": "market_analysis", "objective": "o", "instructions": "i", "tools": ["marketplace_search"]}, "Harbor")
desc = hp.CREATE_SCHEMA["description"]
check("A17 generate_flyer/read_flyer are eligible only for social_media (never the analyst or main), granted only when requested and described honestly: the SOUL explains the "
      "one-attempt/UNCHECKED rules only when granted and says generation is NOT connected otherwise; existing wording for ad-only and plain specialists is unchanged",
      set(FLYER2) <= set(soc_el) and not (set(FLYER2) & set(ana_el)) and e is None and set(FLYER2) <= set(okc["tools"]) and e2 and e2["code"] == "tool_not_permitted"
      and "generate_flyer" in soul_f and "UNCHECKED" in soul_f and "ONE initial paid attempt" in soul_f and "ONE correction" in soul_f and "inspect_flyer" in soul_f
      and "Flyer generation is connected" in soul_f and "ONE paid attempt" in soul_g and "inspect_flyer" not in soul_g and "ONE correction" not in soul_g
      and "generate_flyer" in soul_fa and "Image or flyer generation is NOT connected" not in soul_fa and "Flyer generation is connected only through" in soul_fa
      and "generate_flyer" not in soul_n and "Facebook ad research and image or flyer generation are NOT connected" in soul_n
      and "generate_flyer" not in soul_ads and "Image or flyer generation is NOT connected" in soul_ads and "generate_flyer" not in soul_ma
      and "generate_flyer" in desc and "read_flyer" in desc and "image_generation" not in desc.split("ROLE social_media")[1].split("Capabilities that are NOT connected yet:")[1],
      (e, e2))
check("A18 the tool schemas expose no URL/path/credential/model/run/attempt arguments", set(hp.FLYER_GEN_SCHEMA["parameters"]["properties"]) == flyer.ARGS["generate_flyer"]
      and set(hp.FLYER_READ_SCHEMA["parameters"]["properties"]) == flyer.ARGS["read_flyer"] and hp.FLYER_GEN_SCHEMA["parameters"]["additionalProperties"] is False)

shutil.rmtree(TMP, ignore_errors=True)
if os.environ.get("FLYER_PART_A_ONLY") == "1":    # quick iteration while editing; the default full run still executes part B
    print(f"\nPART A only: {sum(results)}/{len(results)}", flush=True)
    sys.exit(0 if results and all(results) else 1)
print(f"\nPART A done: {sum(results)}/{len(results)}", flush=True)

# ================= B. real server + workers + scripted model + scripted Gemini =================
print("PART B: real server, HTTP chat API and Hermes workers (scripted model; scripted Gemini stand-in; placeholder images)", flush=True)
BD = Path(tempfile.mkdtemp(prefix="flyerB_"))
BIMGS = BD / "images"
BIMGS.mkdir()
make_image("hw-front", (200, 120, 60), folder=BIMGS)
make_image("hw-detail", (60, 130, 190), fmt="JPEG", folder=BIMGS)
make_image("hl-main", (180, 180, 220), folder=BIMGS)
BCAT = BD / "catalogue.json"
BCAT.write_text(json.dumps({**ALT, "products": [{**ALT["products"][0], "images": [img_entry("hw-front"), img_entry("hw-detail")]}, ALT["products"][1]]}), encoding="utf-8")
ENV = {**os.environ, "PYTHONUTF8": "1", "ECOM_CLASSIFIER": "off", "ECOM_VISION_MODELS": "nebius-token-factory:mock-model", "ECOM_CATALOGUE_FILE": str(BCAT),
       "ECOM_IMAGE_DIRS": str(BIMGS), "ECOM_FLYER_ALLOW_SYNTHETIC": "1", "ECOM_FLYER_SCOPE": "b-main", "ECOM_FLYER_MAX_ATTEMPTS": "20", "GEMINI_API_KEY": KEY}
for k in ("LLM_PROVIDER", "LLM_MODEL", "NEBIUS_API_KEY", "NEBIUS_BASE_URL", "NEBIUS_MODEL", "ECOM_APP_ROOT", "HERMES_HOME"):
    ENV.pop(k, None)
os.environ.pop("ECOM_APP_ROOT", None)
os.environ.pop("HERMES_HOME", None)
PKG_RE = re.compile(r"Flyer (fly-[0-9a-f]{10}) status (\w+) candidate (cand-[0-9a-f]{10})", re.I)


def chat(agent, message, rid=None, timeout=900):
    body = {"message": message}
    if rid:
        body["request_id"] = rid
    return http(APP, f"/api/chat/{agent}", body, timeout=timeout)[:2]


def tool(agent, name, a):
    with role_hold.second_of_role(ROOT, (a or {}).get('role') if name == 'create_agent' else None):   # older suite: build a second agent of one role (test-only hold)
        st_, r = chat(agent, "CALL_TOOL:" + json.dumps({"name": name, "args": a}))
    outs = [json.loads(t["output"]) for t in r.get("tools", []) if t.get("name") == name and t.get("output")]
    return (outs[0] if outs else None), r


def start_server(extra=None, drop=()):
    env = {k: v for k, v in {**ENV, **(extra or {})}.items() if k not in drop}
    p = subprocess.Popen([sys.executable, "-m", "app.server", str(APP)], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(p)
    for _ in range(80):
        try:
            http(APP, "/api/status", timeout=5)
            http(APP, "/api/flyers", timeout=10)   # ready only when a database-backed endpoint answers too (a restart race once reset the first read)
            return p
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("server did not start")


def stop(p):
    p.terminate()
    p.wait()
    time.sleep(2)


def tools_seen(reply):
    m = re.search(r"tools \[(.*)\]", reply or "")
    return sorted(x.strip(" '\"") for x in m.group(1).split(",")) if m else []


def acts(r):
    return [a["tool"] for a in r.get("activity", [])]


try:
    shutil.rmtree(ROOT / "runtime", ignore_errors=True)
    (ROOT / "secrets").mkdir(exist_ok=True)
    (ROOT / "secrets" / "local.env").write_text(f"LLM_PROVIDER=nebius-token-factory\nLLM_MODEL=mock-model\nNEBIUS_API_KEY=mock-key\nNEBIUS_BASE_URL=http://127.0.0.1:{MOCK}/v1\n", encoding="utf-8")
    subprocess.run([sys.executable, "scripts/setup.py"], cwd=ROOT, env=ENV, check=True, capture_output=True)
    spawn(["tests/mock_llm.py", str(MOCK)], env=ENV)
    gp_ = spawn(["tests/mock_gemini.py", str(GEM)])
    wait_up(MOCK, "/stats")
    wait_up(GEM)
    srv = start_server()
    http(APP, "/api/company", {"fields": {"name": "Harbor Textiles", "products": "Wool throws and linen bedding (fictional test data)", "customers": "Home buyers (fictional)",
                                          "goal": "Present our textiles clearly and accurately", "brand": "Calm, natural, plain-spoken"}})
    SK = [{"name": "flyer-routine", "content": "# Flyer routine\n1. Read the catalogue product.\n2. Inspect the photos you select.\n3. Generate one flyer and report it as unchecked."}]
    base_args = {"role": "social_media", "objective": "Produce one accurate promotional flyer per request from Harbor's own product photographs; nothing is posted.",
                 "instructions": "You work for Harbor Textiles (fictional test merchant). Use only the supplied product facts, select the merchant's own photographs, say what you "
                                 "could not verify and always say the flyer is unchecked.", "company_context_refs": [], "skills": SK}
    fa, _ = tool("main", "create_agent", {**base_args, "name": "Harbor Flyer Specialist", "requested_tools": FLYER2 + ["inspect_image", "read_catalogue"]})
    pl, _ = tool("main", "create_agent", {**base_args, "name": "Harbor Plain Social", "requested_tools": ["inspect_image", "read_catalogue"],
                                          "skills": [{"name": "brief-routine", "content": "# Brief routine\n1. Read the catalogue.\n2. Write one brief.\n3. List unknowns."}]})
    an, _ = tool("main", "create_agent", {"role": "market_analysis", "name": "Harbor Analyst", "objective": "Compare Harbor's textiles with Marketplace listings near Dallas.",
                                          "instructions": "You work for Harbor Textiles (fictional). Research read-only within your allowance and never invent prices.",
                                          "skills": [{"name": "price-review", "content": "# Price review\n1. Read the catalogue.\n2. Compare prices.\n3. Mark unknowns."}],
                                          "requested_tools": ["marketplace_locate", "marketplace_search", "marketplace_item", "marketplace_photo", "inspect_image", "read_catalogue",
                                                              "save_listing_draft"]})
    check("B1 main creates a social specialist WITH the flyer tools (grants = requested + foundation), one without them and an analyst, all through the real create_agent tool; "
          "the analyst cannot be given them",
          fa and fa.get("ok") and set(fa["granted_tools"]) == set(FLYER2) | {"inspect_image", "read_catalogue", "read_company_context", "memory", "skills"}
          and pl and pl.get("ok") and not (set(pl["granted_tools"]) & set(FLYER2)) and an and an.get("ok") and not (set(an["granted_tools"]) & set(FLYER2)), (fa, pl, an))
    F_ID, P_ID, M_ID = fa["agent_id"], pl["agent_id"], an["agent_id"]
    pr = ROOT / "runtime" / "hermes_home" / "profiles"
    soul_a = (pr / F_ID / "SOUL.md").read_text(encoding="utf-8")
    soul_p = (pr / P_ID / "SOUL.md").read_text(encoding="utf-8")
    soul_m = (pr / "main" / "SOUL.md").read_text(encoding="utf-8")
    grants_before = {a["agent_id"]: a["granted_tools"] for a in http(APP, "/api/agents")[1]}
    rs = {k: chat(v, "hello")[1] for k, v in (("flyer", F_ID), ("plain", P_ID), ("ana", M_ID), ("main", "main"))}
    ts = {k: tools_seen(v["text"]) for k, v in rs.items()}
    check("B2 tool exposure follows the stored grants and role: the flyer specialist sees generate_flyer/read_flyer; the plain social specialist, the analyst and main see neither; "
          "its SOUL describes the one-attempt/UNCHECKED rules; main's SOUL says flyer generation exists only with generate_flyer",
          set(FLYER2) <= set(ts["flyer"]) and not (set(FLYER2) & set(ts["plain"])) and not (set(FLYER2) & set(ts["ana"])) and not (set(FLYER2) & set(ts["main"]))
          and "generate_flyer" in soul_a and "UNCHECKED" in soul_a and "generate_flyer" not in soul_p and "only for a social_media specialist" in soul_m, ts)

    # ---- scenario 1: the scripted specialist selects registered photos, inspects them and generates ONE flyer
    gem_ctl()
    s0 = http(MOCK, "/stats")[1]
    st_, r = chat(F_ID, "FLYER_AGENT Make one promotional flyer for our wool throw. PRODUCT:harbor-wool-throw IMAGES:hw-front,hw-detail", rid="f-req-1")
    m = PKG_RE.search(r.get("text") or "")
    flyer_id = m.group(1) if m else None
    seq = acts(r)
    gs_ = gem_stats()
    grq = gs_["requests"][0] if gs_["requests"] else {}
    check("B3 through the real chat API the scripted specialist read the catalogue, looked at the two selected merchant photos, then called generate_flyer ONCE: the provider stand-in "
          "received exactly those photographs' original bytes plus the stored prompt/facts, and the saved flyer is UNCHECKED",
          st_ == 200 and r["ok"] and seq == ["read_catalogue", "inspect_image", "inspect_image", "generate_flyer"] and all(a["status"] == "ok" for a in r["activity"])
          and gs_["total"] == 1 and [i["sha256"] for i in grq["images"]] == [sha(BIMGS / "hw-front.png"), sha(BIMGS / "hw-detail.jpg")] and grq["has_key"]
          and "Heritage Wool Throw" in grq["text"] and m and m.group(2) == "unchecked", (seq, r["text"][:200], gs_["total"]))
    lst = http(APP, "/api/flyers?agent_id=" + F_ID)[1]
    det = http(APP, f"/api/flyers/{flyer_id}")[1]
    stc, body, ctype = http(APP, f"/api/flyers/images/{flyer_id}", raw=True)
    check("B4 read APIs: the list shows one UNCHECKED flyer with an image URL; the detail holds the exact prompt/context, selected inputs and hashes, identity and attempt accounting; "
          "the managed image endpoint returns the stored bytes (hash equals the recorded hash) as image/jpeg",
          len(lst) == 1 and lst[0]["status"] == "unchecked" and lst[0]["image"]["url"] == f"/api/flyers/images/{flyer_id}" and det["identity"]["request_id"] == "f-req-1"
          and det["attempt"]["prompt"].startswith("Create a clean promotional flyer") and det["attempt"]["context_text"] == grq["text"]
          and [i["image_id"] for i in det["attempt"]["inputs"]] == ["hw-front", "hw-detail"] and det["attempts"]["used"] == 1 and det["attempts"]["final_max"] == 2
          and stc == 200 and ctype == "image/jpeg" and hashlib.sha256(body).hexdigest() == det["attempt"]["output"]["sha256"], (lst, stc, ctype))
    odd = [http(APP, p_, raw=True)[0] for p_ in ("/api/flyers/images/..%2f..%2fapp.db", "/api/flyers/images/fly-zzzzzzzzzz", "/api/flyers/images/fly-0000000000",
                                                 "/api/flyers/images/cand-0000000000", "/api/flyers/fly-0000000000", "/api/flyers/..%2fagents", "/api/flyers/images/")]
    check("B5 malformed, path-like and unknown ids on the flyer endpoints are 404 (the managed image resolves only a validated flyer id through the database)",
          all(c_ == 404 for c_ in odd), odd)
    page = http(APP, "/", raw=True)[1].decode("utf-8")
    sts = http(APP, "/api/status")[1]
    check("B6 the page renders saved flyers as result cards from backend records (/api/results: status text, error, image, enlarge) and the status API reports whether generation is configured, without a key",
          "/api/results?agent_id=" in page and "cardHTML" in page and "data-zoom" in page and "Saved results" in page and sts["image_generation_configured"] is True and KEY not in json.dumps(sts), sts)
    if os.environ.get("FLYER_EVIDENCE_DIR"):   # the preserved, inspectable scripted flyer: image, record, exact provider request, the photographs sent
        ev = Path(os.environ["FLYER_EVIDENCE_DIR"])
        (ev / "inputs").mkdir(parents=True, exist_ok=True)
        (ev / "flyer.jpg").write_bytes(body)
        for p_ in (BIMGS / "hw-front.png", BIMGS / "hw-detail.jpg"):
            shutil.copy(p_, ev / "inputs" / p_.name)
        (ev / "flyer-record.json").write_text(json.dumps(det, indent=1), encoding="utf-8")
        (ev / "provider-request-as-received.json").write_text(json.dumps({"note": "What the SCRIPTED Gemini stand-in received (image bytes shown as hash/size only).", **grq}, indent=1), encoding="utf-8")
        (ev / "model-pixels-seen-by-reasoning-model.json").write_text(json.dumps(http(MOCK, "/stats")[1]["image_log"][len(s0["image_log"]):], indent=1), encoding="utf-8")

    # ---- duplicates: a replayed request id, and a second generate_flyer in the same request
    n0 = gem_n()
    st_, rep = chat(F_ID, "FLYER_AGENT Make one promotional flyer for our wool throw. PRODUCT:harbor-wool-throw IMAGES:hw-front,hw-detail", rid="f-req-1")
    st2, r2 = chat(F_ID, "FLYER_AGENT Another flyer, call it twice. TWICE PRODUCT:harbor-wool-throw IMAGES:hw-front", rid="f-req-2")
    g_calls = [json.loads(a["output"]) for a in r2.get("activity", []) if a["tool"] == "generate_flyer" and a.get("output")]
    check("B7 a replayed completed request id re-runs nothing; a second generate_flyer call inside one request returns the stored result: exactly ONE more provider request in total",
          rep.get("replayed") is True and gem_n() - n0 == 1 and len(g_calls) == 2 and g_calls[0].get("ok") and g_calls[1].get("cached") is True
          and len(http(APP, "/api/flyers?agent_id=" + F_ID)[1]) == 2, (rep.get("replayed"), gem_n() - n0, [c_.get("cached") for c_ in g_calls]))
    # ---- a provider refusal through the app: explicit failure card, attempt consumed
    gem_ctl(mode="refuse")
    st3, r3 = chat(F_ID, "FLYER_AGENT Make another flyer. NO_INSPECT PRODUCT:harbor-wool-throw IMAGES:hw-front", rid="f-req-3")
    lst3 = http(APP, "/api/flyers?agent_id=" + F_ID)[1]
    bad3 = next((x for x in lst3 if x["request_id"] == "f-req-3"), {})
    check("B8 a provider refusal reaches the user as an explicit failure (specialist text, failed flyer card with the error), no image is stored and the key never appears",
          "NOT generated" in r3["text"] and "generation_failed" in r3["text"] and bad3.get("status") == "failed" and bad3.get("image") is None and bad3.get("outcome") == "bad_request"
          and KEY not in json.dumps(lst3) and KEY not in r3["text"], (r3["text"][:200], bad3))
    gem_ctl()
    # ---- restart: provider stopped, no key anywhere: stored flyers still read and served
    before = {x["flyer_id"]: x for x in http(APP, "/api/flyers")[1]}
    stop(srv)
    stop(gp_)
    gp_ = spawn(["tests/mock_gemini.py", str(GEM)])
    wait_up(GEM)
    srv = start_server(drop=("GEMINI_API_KEY",))
    after = {x["flyer_id"]: x for x in http(APP, "/api/flyers")[1]}
    stc2, body2, _ = http(APP, f"/api/flyers/images/{flyer_id}", raw=True)
    rdf, _ = tool(F_ID, "read_flyer", {})
    check("B9 after an app restart with the provider stand-in replaced and NO key, the flyer list, detail, image bytes and the specialist's read_flyer tool return the same data with "
          "ZERO provider requests",
          after == before and stc2 == 200 and body2 == body and rdf and rdf.get("ok") and flyer_id in [x["flyer_id"] for x in rdf["flyers"]] and gem_n() == 0
          and http(APP, "/api/status")[1]["image_generation_configured"] is False, (len(after), gem_n()))
    # ---- missing key through the app: a clear setup error, no attempt claimed
    n_before = len(http(APP, "/api/flyers")[1])
    st4, r4_ = chat(F_ID, "FLYER_AGENT Make one more flyer. NO_INSPECT PRODUCT:harbor-wool-throw IMAGES:hw-front", rid="f-req-4")
    check("B10 without a configured key the specialist reports the setup error (missing_credentials), nothing is sent, no flyer record or attempt is created",
          "missing_credentials" in r4_["text"] and gem_n() == 0 and len(http(APP, "/api/flyers")[1]) == n_before, (r4_["text"][:200], gem_n()))
    check("B11 no stored grant or saved SOUL was widened or rewritten by any of this (existing specialists obtain flyer tools only by being created with them)",
          {a["agent_id"]: a["granted_tools"] for a in http(APP, "/api/agents")[1]} == grants_before and (pr / P_ID / "SOUL.md").read_text(encoding="utf-8") == soul_p
          and (pr / F_ID / "SOUL.md").read_text(encoding="utf-8") == soul_a)

    # ---- review corrections through the real app (Codex review 2026-10-13)
    art = next(ROOT.joinpath("runtime", "flyers", flyer_id).glob("cand-*.jpg"))
    good_bytes = art.read_bytes()
    art.write_bytes(good_bytes[: len(good_bytes) // 2])      # damage the saved image on disk
    lst_d = {x["flyer_id"]: x for x in http(APP, "/api/flyers?agent_id=" + F_ID)[1]}
    det_d = http(APP, f"/api/flyers/{flyer_id}")[1]
    st_img, img_err, _ = http(APP, f"/api/flyers/images/{flyer_id}", raw=False)
    rd_d, _ = tool(F_ID, "read_flyer", {})   # (the stored Activity output is cut at 3000 characters, so the list view is what can be parsed here)
    page2 = http(APP, "/", raw=True)[1].decode("utf-8")
    card_d = next(c for c in http(APP, f"/api/results?agent_id={lst_d[flyer_id]['agent_id']}")[1] if c["key"] == f"flyer:{flyer_id}")   # the same failure as the chat card shows it
    check("B12 a damaged saved image (truncated on disk) is an explicit storage-integrity failure everywhere: list and detail show storage_failure with no image reference, the image "
          "endpoint answers 409 artifact_integrity_failed (never the bytes), the specialist's read_flyer says so, the original outcome/attempt count are unchanged, and the UI "
          "has a rendering for it; zero provider requests",
          lst_d[flyer_id]["status"] == "storage_failure" and lst_d[flyer_id]["image"] is None and lst_d[flyer_id]["outcome"] == "ok" and lst_d[flyer_id]["error_kind"] == "storage_integrity"
          and det_d["status"] == "storage_failure" and det_d["attempts"]["used"] == 1 and det_d["attempt"]["output"] is None and st_img == 409
          and img_err.get("code") == "artifact_integrity_failed" and rd_d and next(x for x in rd_d["flyers"] if x["flyer_id"] == flyer_id)["status"] == "storage_failure"
          and card_d["status"] == "storage_failure" and card_d["image"] is None and "integrity" in card_d["status_text"].lower() and "storage_failure" in page2 and gem_n() == 0, (lst_d[flyer_id]["status"], st_img))
    if os.environ.get("FLYER_EVIDENCE_DIR"):   # correction evidence: what the API says about a damaged saved image (scripted; no real Gemini involved)
        cdir = Path(os.environ["FLYER_EVIDENCE_DIR"]) / "corrections"
        cdir.mkdir(parents=True, exist_ok=True)
        (cdir / "integrity-failure-api-views.json").write_text(json.dumps(
            {"note": "The saved image of the example flyer was truncated on disk (scripted test). List item, detail summary and the image endpoint answer:",
             "list_item": lst_d[flyer_id], "detail_status": det_d["status"], "detail_integrity": det_d["integrity"], "detail_attempts": det_d["attempts"],
             "image_endpoint": {"http_status": st_img, "body": img_err}}, indent=1), encoding="utf-8")
    stop(srv)
    srv = start_server(drop=("GEMINI_API_KEY",))
    st_r, img_r, _ = http(APP, f"/api/flyers/images/{flyer_id}")
    after_r = {x["flyer_id"]: x for x in http(APP, "/api/flyers")[1]}
    art.write_bytes(good_bytes)                                # repaired: valid again, computed from the file (no state was changed by the failure)
    st_ok, body_ok, _ = http(APP, f"/api/flyers/images/{flyer_id}", raw=True)
    check("B13 after an app restart the damaged flyer is still an explicit failure (zero provider requests); restoring the original bytes makes it served and valid again, "
          "with the attempt record unchanged",
          after_r[flyer_id]["status"] == "storage_failure" and st_r == 409 and st_ok == 200 and body_ok == good_bytes and gem_n() == 0
          and http(APP, f"/api/flyers/{flyer_id}")[1]["attempts"]["used"] == 1, (after_r[flyer_id]["status"], st_r, st_ok))
    # ---- malformed provider response and an echoed key, through the app (key configured again)
    stop(srv)
    srv = start_server()
    gem_ctl(mode="steps_int")
    n0 = gem_n()
    st5, r5 = chat(F_ID, "FLYER_AGENT Make one more flyer. NO_INSPECT PRODUCT:harbor-wool-throw IMAGES:hw-front", rid="f-req-5")
    f5 = next((x for x in http(APP, "/api/flyers?agent_id=" + F_ID)[1] if x["request_id"] == "f-req-5"), {})
    sent5 = gem_n()
    gem_ctl(mode="echo_text")           # (a control reset also clears the request log: counts are added up by hand)
    st6, r6 = chat(F_ID, "FLYER_AGENT Make a different flyer. NO_INSPECT PRODUCT:harbor-wool-throw IMAGES:hw-front", rid="f-req-6")
    f6 = next((x for x in http(APP, "/api/flyers?agent_id=" + F_ID)[1] if x["request_id"] == "f-req-6"), {})
    sent56 = sent5 + gem_n()
    if os.environ.get("FLYER_EVIDENCE_DIR"):
        cdir = Path(os.environ["FLYER_EVIDENCE_DIR"]) / "corrections"
        cdir.mkdir(parents=True, exist_ok=True)
        (cdir / "malformed-response-and-echoed-key-records.json").write_text(json.dumps(
            {"note": "Scripted provider: a 200 response with steps:1 (malformed) and a text-only completion that echoes the fake sentinel key. Both are terminal, consumed failures; the sentinel is redacted.",
             "malformed_steps_int": f5, "echoed_key_text_only": f6, "provider_requests_total": sent56}, indent=1), encoding="utf-8")
    surfaces = json.dumps([r5, r6, http(APP, "/api/flyers")[1], http(APP, f"/api/flyers/{f6.get('flyer_id')}")[1], http(APP, "/api/chat/" + F_ID)[1], http(APP, "/api/status")[1]])
    stop(srv)
    srv = start_server(drop=("GEMINI_API_KEY",))
    f5r = next((x for x in http(APP, "/api/flyers?agent_id=" + F_ID)[1] if x["request_id"] == "f-req-5"), {})
    check("B14 through the real app a malformed 200 response is an explicit consumed failure (one send, status failed / outcome bad_response, retrievable after restart with zero "
          "further requests) and a provider text that echoes the API key reaches no tool result, Activity, chat history, list, detail or status surface",
          "generation_failed" in r5["text"] and f5.get("status") == "failed" and f5.get("outcome") == "bad_response" and f5r.get("outcome") == "bad_response"
          and f6.get("status") == "failed" and f6.get("outcome") == "no_image" and sent56 == 2 and KEY not in surfaces and "***" in f6.get("error", ""), (f5, f6, sent56))
finally:
    for p in procs:
        try:
            p.terminate()
        except Exception:
            pass
    shutil.rmtree(BD, ignore_errors=True)
print(f"\n{sum(results)}/{len(results)} checks passed (scripted Gemini + scripted model + placeholder images: wiring/enforcement only, NOT real Gemini output or product fidelity)")
sys.exit(0 if results and all(results) else 1)
