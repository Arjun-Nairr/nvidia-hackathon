"""V2-05 tests: actual-image review and at most ONE correction for the independent social_media specialist. Everything here uses SCRIPTED stand-ins:
tests/mock_gemini.py (Gemini Interactions stand-in; its 'colors' control returns SOLID known-control images), tests/mock_llm.py (a rule-based specialist whose
content judgement follows the pixels it receives), tests/mock_fb_ads.py (invented ad data) and GENERATED placeholder 'merchant photos'. It proves backend wiring,
binding of reviews to the delivered candidate pixels, the two-attempt bound, correction linkage and preservation of the original inputs, final selection, integrity
vs content distinctness, persistence and retrieval. It is NOT real Gemini output, NOT image quality, NOT real visual-review accuracy and NOT a paid call. No real
credential is ever loaded: the run refuses to start if the project copy holds secrets/local.env.
Part A: backend seams in-process (isolated app root, real SQLite, real tool bodies, real HTTP to the stand-in).
Part B: the scripted specialist through the REAL server, HTTP chat API, Hermes workers and read APIs (classifier off). Wipes the copy's runtime/: COPY ONLY:
  REVIEW_I_AM_A_COPY=1 venv-python tests/flyer_review_test.py"""
import base64, hashlib, http.client as http_client, io, json, os, re, shutil, subprocess, sys, tempfile, time, urllib.error, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import role_hold

ROOT = Path(__file__).resolve().parent.parent
if os.environ.get("REVIEW_I_AM_A_COPY") != "1":
    sys.exit("Refusing to run: set REVIEW_I_AM_A_COPY=1 and run from a COPY of the project.")
if (ROOT / "secrets" / "local.env").exists():
    sys.exit("Refusing to run: this copy holds secrets/local.env. Real credentials must never be loaded by a test copy.")
os.environ["HERMES_HOME"] = str(ROOT / "runtime" / "hermes_home" / "profiles" / "main")
TMP = Path(tempfile.mkdtemp(prefix="review_"))
GEM, MOCK, APP, FB = 8794, 8780, 8830, 8792
KEY = "TEST-GEMINI-KEY-SENTINEL"          # the value tests/mock_gemini.py expects; not a credential
IMGS, CATS = TMP / "merchant_images", TMP / "catalogues"
IMGS.mkdir()
CATS.mkdir()
os.environ.update({"ECOM_APP_ROOT": str(TMP), "ECOM_GEMINI_URL": f"http://127.0.0.1:{GEM}", "GEMINI_API_KEY": KEY, "ECOM_FLYER_ALLOW_SYNTHETIC": "1",
                   "ECOM_IMAGE_DIRS": str(IMGS)})
for k in ("ECOM_FLYER_SCOPE", "ECOM_FLYER_MAX_ATTEMPTS", "GEMINI_MODEL", "GEMINI_IMAGE_SIZE", "ECOM_CATALOGUE_FILE"):
    os.environ.pop(k, None)
sys.path.insert(0, str(ROOT))
from app import ads, core, flyer, turn_state, hermes_plugin as hp
from PIL import Image, ImageStat

results, procs = [], []
import atexit
atexit.register(lambda: [p.terminate() for p in procs if p.poll() is None])


def check(name, ok, detail=""):
    ok = bool(ok)
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{str(detail)[:900]}]"), flush=True)


def http(port, path, body=None, timeout=600, raw=False):
    req_ = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req_, timeout=timeout)
        data = r.read()
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
            http(port, path, timeout=5)
            return
        except Exception:
            time.sleep(0.25)
    raise RuntimeError(f"port {port} did not come up")


def spawn(args, env=None):
    p = subprocess.Popen([sys.executable, *args], cwd=ROOT, env=env or {**os.environ, "PYTHONUTF8": "1"}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(p)
    return p


def make_image(name, color, size=(600, 800), fmt="PNG", folder=IMGS):
    from PIL import ImageDraw
    im = Image.new("RGB", size, color)
    ImageDraw.Draw(im).ellipse([size[0] // 4, size[1] // 4, 3 * size[0] // 4, 3 * size[1] // 4], fill=(255, 255, 255))
    p = folder / f"{name}.{ {'PNG': 'png', 'JPEG': 'jpg'}[fmt] }"
    im.save(p, fmt)
    return p


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def mean_of(raw):
    return [round(v) for v in ImageStat.Stat(Image.open(io.BytesIO(raw)).convert("RGB")).mean]


def close(a, b, tol=10):
    return len(a) == len(b) and all(abs(x - y) <= tol for x, y in zip(a, b))


def code(r):
    return r.get("code") if isinstance(r, dict) and r.get("ok") is False else ("OK" if isinstance(r, dict) and r.get("ok") else r)


NOTICE = "FICTIONAL TEST DATA for scripted plumbing tests: the merchant and product are invented and every image is a generated placeholder, not a photograph."
CAT = {"schema": 1, "demo": False, "notice": NOTICE, "merchant": {"merchant_id": "harbor-textiles", "name": "Harbor Textiles"},
       "products": [{"product_id": "harbor-wool-throw", "name": "Heritage Wool Throw", "category": "throws", "condition": "new",
                     "specifications": {"size": "130 x 180 cm", "material": "100% wool", "care": "Dry clean"}, "price": {"amount": 64.5, "currency": "EUR"},
                     "images": [{"image_id": "hw-front", "kind": "test placeholder image (synthetic)"}, {"image_id": "hw-detail", "kind": "test placeholder image (synthetic)"},
                                {"image_id": "hw-ghost", "kind": "test placeholder image (synthetic)"}]}]}
CAT_FILE = CATS / "cat.json"
CAT_FILE.write_text(json.dumps(CAT), encoding="utf-8")
os.environ["ECOM_CATALOGUE_FILE"] = str(CAT_FILE)
make_image("hw-front", (200, 120, 60))
make_image("hw-detail", (60, 130, 190), fmt="JPEG")
FRONT, DETAIL = IMGS / "hw-front.png", IMGS / "hw-detail.jpg"
FRONT_BYTES = FRONT.read_bytes()
RED, GREEN = [210, 40, 40], [40, 170, 80]

spawn(["tests/mock_gemini.py", str(GEM)])
wait_up(GEM)
core.update_company({"name": "Harbor Textiles", "products": "Wool throws and linen bedding", "customers": "Home buyers", "goal": "Present our textiles clearly",
                     "brand": "Calm, natural, plain-spoken"}, source="form")
TOOLS = list(core.FLYER_TOOLS)
NEW_TOOLS = ["inspect_flyer", "review_flyer", "finalize_flyer"]


def register(agent_id, tools, role="social_media"):
    with core.db() as d:
        d.execute("INSERT OR REPLACE INTO agents VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (agent_id, agent_id, role, "default", "o", "i", "[]", "[]", json.dumps(sorted(set(tools) | {"read_company_context", "memory", "skills"})), "[]",
                   f"conv-{agent_id}", "idle", time.time()))


register("soc", TOOLS + ["inspect_image", "read_catalogue"])
register("soc2", TOOLS + ["inspect_image", "read_catalogue"])
register("soc-noreview", ["generate_flyer", "read_flyer", "inspect_image", "read_catalogue"])
register("ana", TOOLS, role="market_analysis")


def req(rid, agent="soc"):
    turn_state.request_id, turn_state.run_id, turn_state.ad_run_id = rid, None, None
    os.environ["ECOM_AGENT_ID"] = agent


def scope(name, cap=60):
    os.environ["ECOM_FLYER_SCOPE"] = name
    os.environ["ECOM_FLYER_MAX_ATTEMPTS"] = str(cap)


def deliver(v):
    turn_state.vision_probe = lambda: v


PROMPT = ("Create a clean promotional flyer for the Heritage Wool Throw. Headline: Heritage Wool Throw. Show the price exactly as declared: 64.5 EUR. "
          "Keep the supplied product photo prominent on a plain backdrop with a short call to action.")
BASE = {"product_id": "harbor-wool-throw", "selected_product_image_ids": ["hw-front", "hw-detail"], "prompt": PROMPT}
CNAMES = ("product_appearance", "required_text_price", "layout_readability")


def G(args, agent="soc"):
    return flyer.generate(agent, args)


_api = [0]


def HOP(v, image=True, respond=True, only_candidate=False, aid=None):
    """What Hermes does after a tool batch: ONE model request carrying the tool result (list content with the image parts when its vision gate passes, the text
    summary otherwise), then that request's response. Drives the same two hook entry points the plugin registers (pre_api_request / post_api_request)."""
    _api[0] += 1
    aid = aid or f"api-{_api[0]}"
    content = v["content"] if image else v["text_summary"]
    if image and only_candidate:
        content = v["content"][:2]
    flyer.note_request([{"role": "system", "content": "s"}, {"role": "tool", "tool_call_id": "c1", "content": content}], aid)
    if respond:
        flyer.note_response(aid)
    return aid


def n_reviews(cid):
    with core.db() as d:
        return d.execute("SELECT COUNT(*) FROM flyer_reviews WHERE candidate_id=?", (cid,)).fetchone()[0]


def INSP(cid, agent="soc", send=True):
    """inspect_flyer, followed (send=True) by the model round trip Hermes performs next: ONE request carrying the tool result, then its response (see HOP)."""
    v = flyer.inspect(agent, {"candidate_id": cid})
    if send and isinstance(v, dict) and v.get("_multimodal"):
        HOP(v, image=turn_state.image_delivery() == "image_part_sent")
    return v


def REV(cid, sha_, res=("pass", "pass", "pass"), defects=None, **kw):
    return {"candidate_id": cid, "candidate_sha256": sha_,
            "checks": {n: {"result": r, "observation": f"Scripted observation of {n}: {r} (test)."} for n, r in zip(CNAMES, res)},
            "defects": defects or [], "summary": "Scripted review summary written by the test.", **kw}


def DEF(check="required_text_price", n=None):
    return {"check": check, "description": "The price shown on the flyer is not the declared price.", "correction": "Show the price exactly as declared in the supplied facts."}


def CORR(cid, n=1, text="Show the price exactly as declared: 64.5 EUR, and change nothing else."):
    return {"previous_candidate_id": cid, "corrections": [{"defect_no": n, "instruction": text}]}


def sha_of(g):
    return g["image"]["sha256"]


def start(rid, colors=None, d="image_part_sent", **ctl):
    """new request: fresh stand-in log/behaviour, delivery state, and the first generation (initial attempt)."""
    gem_ctl(colors=colors, **ctl)
    deliver(d)
    req(rid)
    return G(BASE)


def fly_dir():
    return core.RUNTIME / "flyers"


def art(run_id, cand_id):
    return next((fly_dir() / run_id).glob(cand_id + ".*"))


def n_attempts(fid):
    with core.db() as d:
        return d.execute("SELECT COUNT(*) FROM flyer_attempts WHERE run_id=?", (fid,)).fetchone()[0]


def scope_used(name):
    with core.db() as d:
        return d.execute("SELECT attempts_used FROM flyer_allowance WHERE scope=?", (name,)).fetchone()[0]


def finish_pass(cid, sha_):
    return flyer.review("soc", REV(cid, sha_))


print("PART A: backend seams (scripted Gemini stand-in; placeholder images; not real Gemini)", flush=True)
scope("r-main")

# ---------------- R1: an acceptable first candidate makes ONE generation ----------------
g1 = start("r1", [GREEN])
fid1, c1 = g1.get("flyer_id"), g1.get("candidate_id")
v1 = INSP(c1)
urls = [p["image_url"]["url"] for p in (v1.get("content") or []) if p.get("type") == "image_url"]
raws = [base64.b64decode(u.split(",", 1)[1]) for u in urls]
cand_raw = art(fid1, c1).read_bytes()
cand_im = Image.open(io.BytesIO(cand_raw))
rv1 = flyer.review("soc", REV(c1, sha_of(g1)))
fin1 = flyer.finalize("soc", {"candidate_id": c1, "rationale": "The only candidate; the reviewer found no defect. Reviewer decisions are fallible."})
f1 = flyer.get_flyer(fid1) or {}
check("R1 an acceptable first candidate: ONE provider request; inspect_flyer delivers the candidate's real pixels first and the merchant's selected photographs after; the review is "
      "bound to the delivered hash and trusted identity; finalize selects it; the status says 'agent review passed' (never approved)",
      g1.get("ok") and gem_n() == 1 and v1.get("_multimodal") is True and len(raws) == 3 and Image.open(io.BytesIO(raws[0])).size == cand_im.size
      and close(mean_of(raws[0]), GREEN) and close(mean_of(raws[1]), mean_of(FRONT_BYTES)) and close(mean_of(raws[2]), mean_of(DETAIL.read_bytes()))
      and v1["meta"]["sha256"] == sha_of(g1) == hashlib.sha256(cand_raw).hexdigest() and [r["image_id"] for r in v1["meta"]["references"]] == ["hw-front", "hw-detail"]
      and rv1.get("ok") and rv1["verdict"] == "passed" and rv1["verified"] is True and rv1["delivery"] == "image_part_sent" and fin1.get("ok")
      and fin1["status"] == "agent_review_passed" and f1["status"] == "agent_review_passed" and f1["final"]["candidate_id"] == c1 and f1["final"]["selected"] is True
      and f1["attempts"]["used"] == 1 and f1["identity"]["request_id"] == "r1" and f1["identity"]["agent_id"] == "soc" and f1["review"]["sha256"] == sha_of(g1)
      and "agent review passed" in json.dumps(f1).lower() and "not human approval" in f1["review"]["note"] and "approved by" not in json.dumps(f1).lower()
      and KEY not in json.dumps([v1.get("text_summary"), f1]),
      (code(g1), code(rv1), code(fin1), f1.get("status"), len(raws), gem_n()))

# ---------------- R2: a defective first candidate gets ONE specific correction and a second review ----------------
g2 = start("r2", [RED, GREEN])
fid2, c2a = g2.get("flyer_id"), g2.get("candidate_id")
INSP(c2a)
rv2a = flyer.review("soc", REV(c2a, sha_of(g2), res=("pass", "fail", "pass"), defects=[DEF()]))
first_row_before = json.dumps(flyer.get_flyer(fid2)["candidates"][0], sort_keys=True, default=str)
cor = G(CORR(c2a, 1, "Show the price exactly as declared: 64.5 EUR, and change nothing else."))
rq_all = gem_stats()["requests"]
rq2 = rq_all[1] if len(rq_all) > 1 else {}
c2b = cor.get("candidate_id")
INSP(c2b)
rv2b = flyer.review("soc", REV(c2b, cor["image"]["sha256"]))
fin2 = flyer.finalize("soc", {"candidate_id": c2b, "rationale": "The corrected candidate passed the agent's visual review; the first had a wrong price."})
f2 = flyer.get_flyer(fid2) or {}
cands2 = f2.get("candidates") or []
PRED2 = {
    "defect numbered": rv2a.get("verdict") == "defects_found" and rv2a["defects"][0]["defect_no"] == 1 and rv2a["defects"][0]["check"] == "required_text_price",
    "correction ok/linked": bool(cor.get("ok")) and cor.get("correction") is True and cor.get("predecessor_id") == c2a and cor["attempts"]["used"] == 2 and len(rq_all) == 2,
    "images order": [i["sha256"] for i in rq2.get("images", [])] == [sha(FRONT), sha(DETAIL), sha_of(g2)] and rq2.get("n_input") == 4,
    "text": rq2.get("text", "").startswith(PROMPT) and "Declared price: 64.5 EUR" in rq2.get("text", "") and "100% wool" in rq2.get("text", "")
            and "Show the price exactly as declared: 64.5 EUR, and change nothing else." in rq2.get("text", ""),
    "request flags": rq2.get("store") is False and rq2.get("extra_fields") == [] and "delivery" not in (rq2.get("response_format") or {}),
    "correction record agrees with what was sent": (lambda r: "delivery" not in r and all(r.get(k) == rq2["response_format"][k] for k in ("aspect_ratio", "image_size", "mime_type"))
                                                     and r.get("store") is rq2["store"] and r.get("input_images") == rq2["n_input"] - 1)(
        json.loads(core.db().execute("SELECT request_json FROM flyer_attempts WHERE candidate_id=?", (c2b,)).fetchone()[0])),
    "second review+final": rv2b.get("verdict") == "passed" and fin2.get("status") == "agent_review_passed" and f2.get("status") == "agent_review_passed"
                           and f2["final"]["candidate_id"] == c2b and len(cands2) == 2,
    "candidate records": cands2[0]["candidate_id"] == c2a and cands2[1]["predecessor_id"] == c2a and cands2[0]["review"]["verdict"] == "defects_found"
                         and cands2[1]["review"]["verdict"] == "passed" and cands2[1]["corrections"][0]["defect_no"] == 1,
    "prompts/outputs": cands2[0]["prompt"] == PROMPT and cands2[1]["prompt"] == PROMPT and cands2[0]["output"]["sha256"] == sha_of(g2)
                       and cands2[1]["output"]["sha256"] == cor["image"]["sha256"],
    "attempts": f2["attempts"]["used"] == 2 and f2["attempts"]["enabled"] == 2 and f2["attempts"]["final_max"] == 2 and f2["attempt"]["candidate_id"] == c2b}
check("R2 defective first candidate: the review records the failed check as a numbered defect; ONE correction names that defect; the second request carries the ORIGINAL merchant photographs "
      "(same bytes, same order), then the previous draft, the original prompt/facts and the specific instruction; the second candidate is reviewed too and selected; both attempts "
      "keep their own prompt, inputs, output and review", all(PRED2.values()), [k for k, v in PRED2.items() if not v])
check("R2b the first attempt's evidence is not overwritten by the correction: its record, review and image are byte-for-byte what they were before",
      cands2[0]["output"]["sha256"] == sha_of(g2) and hashlib.sha256(art(fid2, c2a).read_bytes()).hexdigest() == sha_of(g2) and cands2[0]["review"]["verdict"] == "defects_found"
      and json.dumps(flyer.get_flyer(fid2)["candidates"][0], sort_keys=True, default=str) == first_row_before
      and flyer.get_flyer(fid2)["candidates"][0]["context_text"] == rq_all[0]["text"] and cands2[1]["context_text"] == rq2["text"],
      (cands2[0].get("context_text") == rq_all[0]["text"]))

# ---------------- R3: a defective second candidate cannot trigger a third generation ----------------
g3 = start("r3", [RED, RED])
fid3, c3a = g3["flyer_id"], g3["candidate_id"]
INSP(c3a)
flyer.review("soc", REV(c3a, sha_of(g3), res=("pass", "fail", "pass"), defects=[DEF()]))
cor3 = G(CORR(c3a))
c3b = cor3["candidate_id"]
INSP(c3b)
rv3b = flyer.review("soc", REV(c3b, cor3["image"]["sha256"], res=("pass", "fail", "pass"), defects=[DEF()]))
n_before = gem_n()
t_a = G(CORR(c3b))                      # a second correction (from the corrected candidate)
t_b = G(CORR(c3a))                      # the same correction again
t_c = G(BASE)                           # a plain generation again
t_d = G({**BASE, "prompt": PROMPT + " Use a different headline."})
fin3 = flyer.finalize("soc", {"candidate_id": c3b, "rationale": "Both candidates still show the wrong price; the second is the best available draft and stays UNAPPROVED."})
f3 = flyer.get_flyer(fid3) or {}
img3 = flyer.image_state(fid3)
check("R3 a defective second candidate: no third generation by any route (second correction, repeated correction, plain call, changed prompt): explicit refusal or the stored result, "
      "nothing sent; the final draft is file-valid, flagged UNRESOLVED with the defect visible, never 'agent review passed'",
      rv3b["verdict"] == "defects_found" and code(t_a) == "correction_limit_reached" and t_b.get("cached") is True and t_b["candidate_id"] == c3b and t_c.get("cached") is True
      and t_d.get("cached") is True and gem_n() == n_before == 2 and n_attempts(fid3) == 2 and f3["status"] == "unresolved_issues" and f3["final"]["selected"] is True
      and f3["final"]["candidate_id"] == c3b and f3["unresolved_issues"] and "price" in f3["unresolved_issues"][0]["description"].lower() and img3[0] == "ok"
      and "unapproved" in json.dumps(f3).lower() and "agent review passed" not in json.dumps(f3).lower(), (code(t_a), gem_n(), f3.get("status")))

# ---------------- R4: a review is bound to trusted request/run, candidate and the delivered hash ----------------
g4 = start("r4", [GREEN])
fid4, c4 = g4["flyer_id"], g4["candidate_id"]
blind = flyer.review("soc", REV(c4, sha_of(g4)))                        # never looked at the pixels
via_img = core.prepare_image(c4)                                         # the generic image tool cannot show a candidate
v4 = INSP(c4)
wrong_hash = flyer.review("soc", REV(c4, "0" * 64))
other_cand = flyer.review("soc", REV("cand-0000000000", sha_of(g4)))
bad_forms = [flyer.review("soc", {**REV(c4, sha_of(g4)), "checks": {k: v for k, v in REV(c4, sha_of(g4))["checks"].items() if k != "layout_readability"}}),
             flyer.review("soc", REV(c4, sha_of(g4), res=("pass", "fail", "pass"))),                       # a failed check with no defect
             flyer.review("soc", REV(c4, sha_of(g4), defects=[DEF()])),                                   # a defect for a passed check
             flyer.review("soc", REV(c4, sha_of(g4), res=("pass", "maybe", "pass"))),
             flyer.review("soc", {**REV(c4, sha_of(g4)), "summary": "short"}),
             flyer.review("soc", {**REV(c4, sha_of(g4)), "extra": 1})]
req("r4-other")                                                          # another manual request of the same specialist
cross = flyer.review("soc", REV(c4, sha_of(g4)))
cross_i = INSP(c4)
req("r4-other-agent", "soc2")
cross_a = flyer.review("soc2", REV(c4, sha_of(g4)))
req("r4")
n_ins = None
with core.db() as d:
    n_ins = d.execute("SELECT COUNT(*) FROM image_inspections WHERE kind='flyer_candidate' AND image_id=?", (c4,)).fetchone()[0]
    row = dict(d.execute("SELECT * FROM image_inspections WHERE kind='flyer_candidate' AND image_id=?", (c4,)).fetchone())
saved = flyer.review("soc", REV(c4, sha_of(g4)))
check("R4 a review cannot be established without the delivered pixels: no inspection, the generic inspect_image, a wrong echoed hash, an unknown/other-run candidate, another request "
      "of the same agent and another agent are all refused with explicit codes; malformed review forms are refused; the inspection row is backend-written and bound to agent, request, "
      "run, candidate id and the file's hash",
      code(blind) == "candidate_not_inspected" and via_img.get("code") == "image_not_found" and v4.get("_multimodal") and code(wrong_hash) == "candidate_hash_mismatch"
      and code(other_cand) == "candidate_not_in_request" and [code(x) for x in bad_forms] == ["bad_review"] * 5 + ["invalid_argument"] and code(cross) == "candidate_not_in_request"
      and code(cross_i) == "candidate_not_in_request" and code(cross_a) == "candidate_not_in_request" and n_ins == 1 and row["agent_id"] == "soc" and row["request_id"] == "r4"
      and row["run_id"] == fid4 and row["sha256"] == sha_of(g4) and row["delivery"] == "image_part_sent" and saved.get("ok") and saved["verdict"] == "passed",
      (code(blind), code(wrong_hash), [code(x) for x in bad_forms], code(cross), code(cross_a), n_ins))
again = flyer.review("soc", REV(c4, sha_of(g4), res=("fail", "pass", "pass"), defects=[DEF("product_appearance")]))
check("R4b one review per candidate: a second save returns the stored review (review_already_saved) and cannot flip a passed review into a failed one or the reverse",
      code(again) == "review_already_saved" and again["review"]["verdict"] == "passed" and flyer.get_flyer(fid4)["review"]["verdict"] == "passed", code(again))

# stale / replaced file after inspection: an integrity failure, not a content verdict
g4s = start("r4s", [GREEN])
c4s = g4s["candidate_id"]
INSP(c4s)
p4s = art(g4s["flyer_id"], c4s)
orig4s = p4s.read_bytes()
buf4s = io.BytesIO()
Image.new("RGB", (800, 1000), (5, 5, 5)).save(buf4s, "JPEG")
p4s.write_bytes(buf4s.getvalue())
stale = flyer.review("soc", REV(c4s, sha_of(g4s)))
again_i = INSP(c4s)
p4s.write_bytes(orig4s)
check("R4c a candidate file replaced after inspection (another valid image) is an INTEGRITY failure on review and on a new inspection; the inspection of the old bytes cannot be reused",
      code(stale) == "artifact_integrity_failed" and code(again_i) == "artifact_integrity_failed" and flyer.get_flyer(g4s["flyer_id"])["status"] in ("unchecked",), (code(stale), code(again_i)))

# text-only / unknown delivery: stored, explicit, never 'review passed'
res_td = {}
for dv in ("text_fallback", "unknown"):
    g = start(f"r4-{dv}", [RED], d=dv)
    iv = INSP(g["candidate_id"])
    rv = flyer.review("soc", REV(g["candidate_id"], sha_of(g), res=("pass", "fail", "pass"), defects=[DEF()]))
    cr = G(CORR(g["candidate_id"]))
    fz = flyer.finalize("soc", {"candidate_id": g["candidate_id"], "rationale": "Only candidate; its review could not be verified."})
    fs = flyer.get_flyer(g["flyer_id"])
    res_td[dv] = (iv.get("_multimodal"), rv.get("ok"), rv.get("verified"), rv.get("verdict"), rv.get("delivery"), code(cr), fz.get("status"), fs["status"], fs["review"]["verified"],
                  fs["unresolved_issues"], gem_n())
check("R4d when the pixels did not reach the model (text fallback or unknown delivery) the review is stored as UNVERIFIED: it cannot support a correction, the result stays explicitly "
      "UNCHECKED, its defects are not presented as verified, and nothing is generated",
      all(v[0] and v[1] and v[2] is False and v[3] == "unverified" and v[5] == "review_not_verified" and v[6] == "unchecked" and v[7] == "unchecked" and v[8] is False and v[9] == [] and v[10] == 1
          for v in res_td.values()) and res_td["text_fallback"][4] == "text_fallback" and res_td["unknown"][4] == "unknown", res_td)
deliver("image_part_sent")

# ---------------- R5: correction eligibility and argument discipline ----------------
g5 = start("r5", [RED, GREEN])
fid5, c5 = g5["flyer_id"], g5["candidate_id"]
n0 = gem_n()
no_review = G(CORR(c5))
INSP(c5)
passed_first = None
flyer.review("soc", REV(c5, sha_of(g5), res=("pass", "fail", "pass"), defects=[DEF()]))
bad_corr = [G(CORR(c5, 7)), G({"previous_candidate_id": c5, "corrections": []}), G({"previous_candidate_id": c5, "corrections": "fix the price"}),
            G({"previous_candidate_id": c5, "corrections": [{"defect_no": 1, "instruction": "x"}]}),
            G({"previous_candidate_id": c5, "corrections": [{"defect_no": 1, "instruction": "Show the price exactly as declared."},
                                                           {"defect_no": 1, "instruction": "Show the price exactly as declared again."}]}),
            G({"previous_candidate_id": c5}), G({"corrections": [{"defect_no": 1, "instruction": "Show the price exactly as declared."}]})]
changed = [G({**CORR(c5), "product_id": "harbor-linen-sheet"}), G({**CORR(c5), "prompt": "A completely different brief for something else, with new text and a new price."}),
           G({**CORR(c5), "selected_product_image_ids": ["hw-front"]})]
extras = [G({**CORR(c5), k: v}) for k, v in (("run_id", "fly-0000000000"), ("attempt_no", 3), ("model", "x"), ("allowance", 5), ("url", "https://evil.example/x"))]
unknown_prev = [G(CORR("cand-0000000000")), G(CORR("../../app.db"))]
req("r5-other")
foreign = G(CORR(c5))
req("r5")
check("R5 a correction is refused (nothing sent, no attempt, no slot used) without a recorded verified review, with an unknown defect number, empty/vague/duplicate/malformed corrections, "
      "a missing previous candidate, a changed product/prompt/images (the original inputs are fixed), extra control arguments, an unknown or path-like candidate, or another request's candidate",
      code(no_review) == "review_required" and [code(x) for x in bad_corr] == ["unknown_defect", "bad_argument", "bad_argument", "bad_argument", "bad_argument", "bad_argument", "bad_argument"]
      and [code(x) for x in changed] == ["correction_cannot_change_original"] * 3 and [code(x) for x in extras] == ["invalid_argument"] * 5
      and [code(x) for x in unknown_prev] == ["candidate_not_in_request", "bad_argument"]
      and code(foreign) == "no_prior_candidate" and gem_n() == n0 and n_attempts(fid5) == 1,
      (code(no_review), [code(x) for x in bad_corr], [code(x) for x in changed], [code(x) for x in extras], [code(x) for x in unknown_prev], code(foreign)))
gp = start("r5p", [GREEN])
INSP(gp["candidate_id"])
flyer.review("soc", REV(gp["candidate_id"], sha_of(gp)))
no_def = G(CORR(gp["candidate_id"]))
fail_first = start("r5f", None, mode="refuse")
c_failed = fail_first["candidate_id"]
insp_failed = INSP(c_failed)
rv_failed2 = flyer.review("soc", REV(c_failed, "0" * 64))
corr_failed = G(CORR(c_failed))
n_after = gem_n()
check("R5b no content review is invented to authorise another generation: a passed review leaves nothing to correct; a first attempt that FAILED (provider refusal) has no candidate image to "
      "inspect or review and cannot be corrected: an honest blocker, and no second request is sent",
      code(no_def) == "no_defect_to_correct" and code(insp_failed) == "no_candidate_image" and code(rv_failed2) == "no_candidate_image" and code(corr_failed) == "no_eligible_candidate"
      and n_after == 1 and flyer.get_flyer(fail_first["flyer_id"])["status"] == "failed", (code(no_def), code(insp_failed), code(rv_failed2), code(corr_failed), n_after))

# ---------------- R6: concurrency, duplicates, uncertain outcomes, restart ----------------
g6 = start("r6", [RED, GREEN])
fid6, c6 = g6["flyer_id"], g6["candidate_id"]
INSP(c6)
flyer.review("soc", REV(c6, sha_of(g6), res=("pass", "fail", "pass"), defects=[DEF()]))
gem_ctl(colors=[GREEN], delay_ms=900)
CH = r"""
import json, os, sys
sys.path.insert(0, os.environ["ROOT_DIR"])
from app import flyer, turn_state
turn_state.request_id = "r6"
os.environ["ECOM_AGENT_ID"] = "soc"
r = flyer.generate("soc", json.loads(os.environ["ARGS_JSON"]))
print(json.dumps({"code": r.get("code") if r.get("ok") is False else "OK", "cached": r.get("cached"), "cand": r.get("candidate_id"), "status": r.get("status")}))
"""
env6 = {**os.environ, "PYTHONUTF8": "1", "ROOT_DIR": str(ROOT), "ARGS_JSON": json.dumps(CORR(c6))}
kids = [subprocess.Popen([sys.executable, "-c", CH], env=env6, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(4)]
outs = []
for k in kids:
    o, e = k.communicate(timeout=120)
    outs.append(json.loads(o.strip().splitlines()[-1]) if o.strip() else {"err": e[-200:]})
sent6 = gem_n()
gem_ctl()
check("R6 four processes issue the SAME correction at once: exactly ONE provider request and two attempt rows in total; the others get the stored result or an explicit unknown-outcome "
      "answer, never a second send",
      sent6 == 1 and n_attempts(fid6) == 2 and sum(1 for o in outs if o.get("code") == "OK" and not o.get("cached")) == 1
      and all(o.get("code") in ("OK", "generation_outcome_unknown") for o in outs) and scope_used("r-main") >= 2, (outs, sent6, n_attempts(fid6)))

g6b = start("r6b", [RED, GREEN])
fid6b, c6b = g6b["flyer_id"], g6b["candidate_id"]
INSP(c6b)
flyer.review("soc", REV(c6b, sha_of(g6b), res=("pass", "fail", "pass"), defects=[DEF()]))
gem_ctl(mode="drop")
n0 = 0
lost = G(CORR(c6b))
n_lost = gem_n()
gem_ctl()
retry = G(CORR(c6b))
third = G(CORR(c6b, 1, "Show the price exactly as declared: 64.5 EUR, with a larger price tag."))
plain = G(BASE)
f6b = flyer.get_flyer(fid6b)
check("R6b a correction whose connection is lost after the send is an UNKNOWN outcome that consumes the second slot: an identical retry, a reworded correction and a plain call send "
      "nothing, and the request never exceeds two dispatched attempts",
      code(lost) == "generation_outcome_unknown" and n_lost == 1 and gem_n() == 0 and code(retry) in ("attempt_already_consumed", "generation_outcome_unknown")
      and code(third) in ("attempt_already_consumed", "generation_outcome_unknown") and code(plain) in ("attempt_already_consumed", "generation_outcome_unknown")
      and n_attempts(fid6b) == 2 and f6b["status"] == "unresolved_issues" and f6b["attempts"]["used"] == 2, (code(lost), code(retry), code(third), code(plain), f6b["status"]))
g6c = start("r6c", [RED, GREEN])
fid6c, c6c = g6c["flyer_id"], g6c["candidate_id"]
INSP(c6c)
flyer.review("soc", REV(c6c, sha_of(g6c), res=("pass", "fail", "pass"), defects=[DEF()]))
state_, run_, att_ = flyer._reserve_correction("soc", "r6c", c6c, {"prompt": PROMPT, "context_text": "c", "model": "m", "request": {}, "corrections": [{"defect_no": 1, "instruction": "x" * 12}],
                                                                  "inputs": [], "synthetic": True, "product": {}, "references": []})
n0 = gem_n()
crash = G(CORR(c6c))
check("R6c a second attempt that was reserved but has no outcome (crash or a call still running) is reported as uncertain; nothing is sent and no other attempt starts",
      state_ == "go" and code(crash) == "generation_outcome_unknown" and gem_n() == n0 and n_attempts(fid6c) == 2, (state_, code(crash), n_attempts(fid6c)))
# restart: a fresh process with no key and no provider reads everything and re-answers calls from storage
RC = r"""
import json, os, sys
sys.path.insert(0, os.environ["ROOT_DIR"])
os.environ.pop("GEMINI_API_KEY", None)
os.environ["ECOM_GEMINI_URL"] = "http://127.0.0.1:9"
from app import flyer, turn_state
out = {}
for fid, rid, args in json.loads(os.environ["JOBS"]):
    turn_state.request_id = rid
    os.environ["ECOM_AGENT_ID"] = "soc"
    f = flyer.get_flyer(fid)
    r = flyer.generate("soc", args)
    s = flyer.image_state(fid)
    out[fid] = {"detail": json.dumps(f, sort_keys=True, default=str), "code": r.get("code") if r.get("ok") is False else "OK", "cached": r.get("cached"),
                "image": [s[0], len(s[1]) if isinstance(s[1], bytes) else s[1]], "list": [x for x in flyer.list_flyers("soc") if x["flyer_id"] == fid][0]["status"]}
print(json.dumps(out))
"""
before6 = {fid2: json.dumps(flyer.get_flyer(fid2), sort_keys=True, default=str), fid3: json.dumps(flyer.get_flyer(fid3), sort_keys=True, default=str)}
n0 = gem_n()
envr = {k: v for k, v in os.environ.items() if k != "GEMINI_API_KEY"} | {"PYTHONUTF8": "1", "ROOT_DIR": str(ROOT),
        "JOBS": json.dumps([[fid2, "r2", CORR(c2a)], [fid3, "r3", CORR(c3a)]])}
orc = subprocess.run([sys.executable, "-c", RC], env=envr, capture_output=True, text=True)
rc = json.loads(orc.stdout.strip().splitlines()[-1]) if orc.stdout.strip() else {"err": orc.stderr[-300:]}
check("R6d after a restart (fresh process, no key, provider unreachable) the final selection, both candidates, reviews, prompts and the final image are returned unchanged and a repeated "
      "correction request is answered from storage: zero provider requests",
      rc.get(fid2, {}).get("detail") == before6[fid2] and rc.get(fid3, {}).get("detail") == before6[fid3] and rc[fid2]["code"] == "OK" and rc[fid2]["cached"] is True
      and rc[fid3]["cached"] is True and rc[fid2]["image"][0] == "ok" and rc[fid3]["list"] == "unresolved_issues" and gem_n() == n0, (rc.get("err"), orc.stderr[-300:]))

# ---------------- R7: the original inputs survive the correction; changed or missing inputs fail explicitly ----------------
g7 = start("r7", [RED, GREEN])
fid7, c7 = g7["flyer_id"], g7["candidate_id"]
INSP(c7)
flyer.review("soc", REV(c7, sha_of(g7), res=("pass", "fail", "pass"), defects=[DEF()]))
saved_front = FRONT.read_bytes()
make_image("hw-front", (10, 200, 10))                                  # same id, DIFFERENT bytes
chg = G(CORR(c7))
FRONT.write_bytes(saved_front)
saved_detail = DETAIL.read_bytes()
DETAIL.unlink()
miss = G(CORR(c7))
DETAIL.write_bytes(saved_detail)
cat2 = json.loads(CAT_FILE.read_text(encoding="utf-8"))
cat2["products"][0]["price"] = {"amount": 70.0, "currency": "EUR"}
alt_cat = CATS / "cat-price.json"
alt_cat.write_text(json.dumps(cat2), encoding="utf-8")
os.environ["ECOM_CATALOGUE_FILE"] = str(alt_cat)
facts = G(CORR(c7))
cat3 = json.loads(CAT_FILE.read_text(encoding="utf-8"))
cat3["products"][0]["specifications"]["material"] = "60% wool, 40% acrylic"
alt_cat.write_text(json.dumps(cat3), encoding="utf-8")
facts2 = G(CORR(c7))
os.environ["ECOM_CATALOGUE_FILE"] = str(CAT_FILE)
n_bad = gem_n()
ok7 = G(CORR(c7))
rq7 = gem_stats()["requests"][-1]
f7 = flyer.get_flyer(fid7)
a1_inputs, a2_inputs = f7["candidates"][0]["inputs"], f7["candidates"][1]["inputs"]
check("R7 the original product facts and merchant-photo hashes survive: a replaced photograph (same id, other bytes), a missing photograph, a changed declared price and a changed "
      "specification are explicit failures (nothing sent, the second slot NOT consumed); once restored the correction runs with the ORIGINAL bytes, facts and provenance",
      code(chg) == "original_input_changed" and "hw-front" in chg["error"] and code(miss) == "merchant_image_missing" and code(facts) == "original_facts_changed"
      and code(facts2) == "original_facts_changed" and n_bad == 1 and ok7.get("ok") and [i["sha256"] for i in rq7["images"][:2]] == [sha(FRONT), sha(DETAIL)]
      and sha(FRONT) == hashlib.sha256(saved_front).hexdigest() and "Declared price: 64.5 EUR" in rq7["text"] and "100% wool" in rq7["text"]
      and [(i["image_id"], i["sha256"], i.get("provenance")) for i in a1_inputs] == [(i["image_id"], i["sha256"], i.get("provenance")) for i in a2_inputs]
      and f7["candidates"][0]["product"] == f7["candidates"][1]["product"], (code(chg), code(miss), code(facts), code(facts2), n_bad))

# ---------------- R8: integrity failures stay distinct from content defects ----------------
g8 = start("r8", [RED, GREEN])
fid8, c8 = g8["flyer_id"], g8["candidate_id"]
INSP(c8)
flyer.review("soc", REV(c8, sha_of(g8), res=("pass", "fail", "pass"), defects=[DEF()]))
f8_content = flyer.get_flyer(fid8)
p8 = art(fid8, c8)
orig8 = p8.read_bytes()
p8.write_bytes(orig8[: len(orig8) // 2])
f8_int = flyer.get_flyer(fid8)
corr_int = G(CORR(c8))
insp_int = INSP(c8)
fin_int = flyer.finalize("soc", {"candidate_id": c8, "rationale": "Selecting the damaged first candidate must be impossible."})
p8.write_bytes(orig8)
f8_back = flyer.get_flyer(fid8)
check("R8 content defect and integrity failure are distinct: a file-valid defective candidate is 'unresolved_issues' with an image; a damaged one is 'storage_failure' with no image "
      "reference, cannot be inspected, corrected or selected (artifact_integrity_failed, not a defect), and becomes valid again when the file is restored",
      f8_content["status"] == "unresolved_issues" and f8_content["image"] is not None and f8_int["status"] == "storage_failure" and f8_int["image"] is None
      and f8_int["error_kind"] == "storage_integrity" and code(corr_int) == "artifact_integrity_failed" and code(insp_int) == "artifact_integrity_failed"
      and code(fin_int) == "artifact_integrity_failed" and f8_back["status"] == "unresolved_issues" and gem_n() == 1 and n_attempts(fid8) == 1, (f8_content["status"], f8_int["status"]))
g8b = start("r8b", [RED, GREEN])
fid8b, c8b1 = g8b["flyer_id"], g8b["candidate_id"]
INSP(c8b1)
flyer.review("soc", REV(c8b1, sha_of(g8b), res=("pass", "fail", "pass"), defects=[DEF()]))
cor8b = G(CORR(c8b1))
c8b2 = cor8b["candidate_id"]
INSP(c8b2)
flyer.review("soc", REV(c8b2, cor8b["image"]["sha256"]))
p8b = art(fid8b, c8b1)
o8b = p8b.read_bytes()
p8b.write_bytes(o8b[:100])
fin8b = flyer.finalize("soc", {"candidate_id": c8b2, "rationale": "The corrected candidate passed review; the first file is damaged but irrelevant."})
f8b = flyer.get_flyer(fid8b)
p8b.write_bytes(o8b)
check("R8b a damaged SUPERSEDED candidate does not spoil the selected one: the final stays 'agent_review_passed' and the damaged candidate is reported as an integrity failure of that candidate only",
      fin8b.get("ok") and f8b["status"] == "agent_review_passed" and f8b["candidates"][0]["integrity"]["state"] == "failed" and f8b["candidates"][1]["integrity"]["state"] == "valid"
      and f8b["candidates"][0]["image"] is None and f8b["candidates"][1]["image"] is not None, (code(fin8b), f8b["status"]))

# ---------------- R9: the scope allowance still bounds corrections ----------------
scope("r-tiny", cap=1)
g9 = start("r9", [RED, GREEN])
INSP(g9["candidate_id"])
flyer.review("soc", REV(g9["candidate_id"], sha_of(g9), res=("pass", "fail", "pass"), defects=[DEF()]))
cap9 = G(CORR(g9["candidate_id"]))
f9 = flyer.get_flyer(g9["flyer_id"])
os.environ["ECOM_FLYER_MAX_ATTEMPTS"] = "500"
cap9b = G(CORR(g9["candidate_id"]))
check("R9 an exhausted scope allowance refuses the correction before anything is sent (explicit allowance_exhausted; the first candidate stays a file-valid unresolved draft); "
      "raising the environment later does not re-size the scope",
      code(cap9) == "allowance_exhausted" and code(cap9b) == "allowance_exhausted" and gem_n() == 1 and f9["status"] == "unresolved_issues" and f9["image"] is not None
      and n_attempts(g9["flyer_id"]) == 1, (code(cap9), code(cap9b), gem_n()))
scope("r-main")

# ---------------- R10: the final candidate is selected explicitly, never 'whichever is newest' ----------------
g10 = start("r10", [RED, [225, 35, 35]])
fid10, c10a = g10["flyer_id"], g10["candidate_id"]
INSP(c10a)
flyer.review("soc", REV(c10a, sha_of(g10), res=("pass", "fail", "pass"), defects=[DEF()]))
cor10 = G(CORR(c10a))
c10b = cor10["candidate_id"]
INSP(c10b)
flyer.review("soc", REV(c10b, cor10["image"]["sha256"], res=("fail", "pass", "pass"), defects=[DEF("product_appearance")]))
undecided = flyer.get_flyer(fid10)
img_undecided = flyer.image_state(fid10)
img_c_a, img_c_b = flyer.image_state(c10a), flyer.image_state(c10b)
fin10 = flyer.finalize("soc", {"candidate_id": c10a, "rationale": "The first candidate's only defect is the price; the second changed the product's appearance, which is worse."})
again10 = flyer.finalize("soc", {"candidate_id": c10a, "rationale": "The first candidate's only defect is the price; the second changed the product's appearance, which is worse."})
other10 = flyer.finalize("soc", {"candidate_id": c10b, "rationale": "Changed my mind: pick the newest candidate instead of the first one."})
f10 = flyer.get_flyer(fid10)
img10 = flyer.image_state(fid10)
claims = flyer.finalize("soc2", {"candidate_id": c10a, "rationale": "x" * 30})
check("R10 two valid candidates and no selection = 'awaiting_selection' (no default image for the flyer id, each candidate retrievable); finalize selects ONE explicitly (here the OLDER "
      "candidate), is idempotent for the same choice and refuses a different one; the flyer's image is the selected candidate; the selection rationale and its issues are stored",
      undecided["status"] == "awaiting_selection" and undecided["final"]["selected"] is False and undecided["image"] is None and img_undecided[0] == "unselected"
      and img_c_a[0] == "ok" and img_c_b[0] == "ok" and fin10.get("ok") and fin10["final"]["candidate_id"] == c10a and again10.get("ok") and code(other10) == "final_already_selected"
      and f10["final"]["candidate_id"] == c10a and f10["final"]["rationale"].startswith("The first candidate's only defect") and f10["status"] == "unresolved_issues"
      and img10[0] == "ok" and img10[1] == img_c_a[1] and img10[1] != img_c_b[1] and f10["final"]["selected_at"] and code(claims) == "candidate_not_in_request",
      (undecided["status"], img_undecided[0], code(fin10), code(other10), f10["status"]))
rat = [flyer.finalize("soc", {"candidate_id": c10b, "rationale": r}) for r in ("short", "x" * 700, "Approved by the merchant owner; guaranteed to match the product exactly.")]
check("R10b the rationale is bounded and cannot claim human approval or guarantees", [code(x) for x in rat] == ["bad_argument"] * 3, [code(x) for x in rat])

# ---------------- R11: research links; missing reach never blocks relevance-based generation ----------------
gem_ctl(colors=[GREEN])
deliver("image_part_sent")
req("r11")
run11 = ads.open_run("soc", "r11")
GATE = {"state": "disabled_period_unknown", "ranking_enabled": False, "metric": "aaa_info.eu_total_reach", "note": "no measurement period is stated"}
with core.db() as d:
    d.execute("INSERT INTO ad_packages(package_id, run_id, agent_id, company_id, conversation_id, request_id, status, summary, selection_basis, blocker, limitations, reach_gate, "
              "references_json, ads_considered, call_accounting, identity, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              ("adpkg-1234567890", run11["run_id"], "soc", "default", "conv-soc", "r11", "complete", "scripted package", "relevance_only", None, None, json.dumps(GATE),
               json.dumps({"cited_ads": [], "references": [{"ad_no": 1, "image_id": "ad-1100000000000001-1"}]}), "[]", "{}", "{}", time.time()))
g11 = G(BASE)
INSP(g11["candidate_id"])
flyer.review("soc", REV(g11["candidate_id"], sha_of(g11)))
flyer.finalize("soc", {"candidate_id": g11["candidate_id"], "rationale": "Passed the agent's visual review; ranking by reach was unavailable so relevance decided."})
f11 = flyer.get_flyer(g11["flyer_id"])
g11b = start("r11b", [GREEN])
INSP(g11b["candidate_id"])
flyer.review("soc", REV(g11b["candidate_id"], sha_of(g11b)))
flyer.finalize("soc", {"candidate_id": g11b["candidate_id"], "rationale": "Passed the agent's visual review; no ad research was saved in this request."})
f11b = flyer.get_flyer(g11b["flyer_id"])
check("R11 the final record links the request's saved ad research (package, selection basis, reach-gate state as recorded) and review/correction decisions; a request with NO ad research "
      "still generates, reviews and finalises, with the research link explicitly absent (missing reach/ads never blocks generation)",
      f11["research"]["ad_package_id"] == "adpkg-1234567890" and f11["research"]["selection_basis"] == "relevance_only" and f11["research"]["reach_gate"]["state"] == "disabled_period_unknown"
      and f11["research"]["status"] == "complete" and f11b["status"] == "agent_review_passed" and f11b["research"]["ad_package_id"] is None
      and f11b["research"]["reach_gate"]["state"] == "no_ad_research_saved", (f11.get("research"), f11b.get("research")))

# ---------------- R12: grants, role isolation, schemas ----------------
req("r12")
deliver("image_part_sent")
tools_try = {}
for tool_, fn_args in (("inspect_flyer", {"candidate_id": c1}), ("review_flyer", REV(c1, "0" * 64)), ("finalize_flyer", {"candidate_id": c1, "rationale": "x" * 30})):
    fn = {"inspect_flyer": flyer.inspect, "review_flyer": flyer.review, "finalize_flyer": flyer.finalize}[tool_]
    tools_try[tool_] = (code(fn("soc-noreview", fn_args)), code(fn("ana", fn_args)), code(fn("ghost", fn_args)))
req(None)
no_req = code(flyer.inspect("soc", {"candidate_id": c1}))
req("r12")
el = core.ROLES["social_media"]["eligible_tools"]
ana_el = core.ROLES["market_analysis"]["eligible_tools"]
okc, e = core.validate_create_agent({"role": "social_media", "name": "Harbor Social", "objective": "Produce one accurate promotional flyer per request for Harbor's textiles.",
                                     "instructions": "You work for Harbor Textiles (fictional). Use only supplied facts; reviews are fallible agent reviews.",
                                     "skills": [{"name": "flyer-routine", "content": "# Flyer routine\n1. Read the catalogue.\n2. Generate.\n3. Review the pixels."}],
                                     "requested_tools": TOOLS + ["inspect_image", "read_catalogue"]})
bad_ana, e2 = core.validate_create_agent({"role": "market_analysis", "name": "Harbor Analyst", "objective": "o" * 50, "instructions": "i" * 50,
                                          "skills": [{"name": "x-routine", "content": "# Price review routine\n1. Read the catalogue.\n2. Compare prices.\n3. Mark what is unknown."}], "requested_tools": ["review_flyer"]})
schemas = [hp.FLYER_GEN_SCHEMA, hp.FLYER_READ_SCHEMA, hp.FLYER_INSPECT_SCHEMA, hp.FLYER_REVIEW_SCHEMA, hp.FLYER_FINAL_SCHEMA] if hasattr(hp, "FLYER_INSPECT_SCHEMA") else []
forbidden = {"url", "path", "api_key", "model", "run_id", "attempt", "attempt_no", "allowance", "max_attempts", "image_size"}
check("R12 the new tools are eligible only for social_media, granted only when requested, refused to an ungranted specialist, the analyst, an unregistered agent and a call outside a "
      "manual request; their schemas expose no URL/path/credential/model/run/attempt argument",
      set(NEW_TOOLS) <= set(el) and not (set(NEW_TOOLS) & set(ana_el)) and set(NEW_TOOLS) <= set(core.FLYER_TOOLS) and e is None and set(NEW_TOOLS) <= set(okc["tools"])
      and e2 and e2["code"] == "tool_not_permitted"
      and all(v == ("not_granted", "not_permitted_for_role", "unknown_agent") for v in tools_try.values()) and no_req == "no_manual_request"
      and len(schemas) == 5 and not any(forbidden & set(s["parameters"]["properties"]) for s in schemas) and all(s["parameters"]["additionalProperties"] is False for s in schemas)
      and set(hp.FLYER_GEN_SCHEMA["parameters"]["properties"]) == flyer.ARGS["generate_flyer"], (tools_try, no_req, e, e2))

# ---------------- R13: delivery-bound verification (P1): a review counts only after the pixels were in a model REQUEST and a model RESPONSE followed ----------------

# R13a: inspection and review in ONE assistant tool batch (no model request in between): refused, nothing stored, cannot authorise a correction or a pass
g13 = start("r13a", [RED, GREEN])
c13, s13 = g13["candidate_id"], sha_of(g13)
v13 = INSP(c13, send=False)
same = flyer.review("soc", REV(c13, s13))                                   # fabricated "all pass" in the same batch
sc_early = flyer.get_flyer(g13["flyer_id"])
cor_early = G(CORR(c13, 1))
check("R13a inspect_flyer + review_flyer in the same assistant batch: the review is refused with a corrective error, NOTHING is stored (no immutable premature review), the status "
      "stays unchecked and the refused review cannot authorise a correction",
      same.get("ok") is False and same.get("code") == "image_not_yet_delivered" and n_reviews(c13) == 0 and sc_early["status"] == "unchecked"
      and cor_early.get("code") == "review_required" and gem_n() == 1, (code(same), code(cor_early), sc_early.get("status"), gem_n()))

# R13b: the refused premature review does not prevent the legitimate later one: request carrying the pixels -> model response -> review
HOP(v13)
rv13 = flyer.review("soc", REV(c13, s13, res=("pass", "fail", "pass"), defects=[DEF()]))
cor13 = G(CORR(c13, 1))
check("R13b inspection -> actual image-bearing model request -> subsequent response -> review succeeds as VERIFIED (after the earlier premature refusal), records the defect and the "
      "normal one-correction path then works",
      rv13.get("ok") and rv13["verified"] is True and rv13["verdict"] == "defects_found" and n_reviews(c13) == 1 and cor13.get("ok") and gem_n() == 2,
      (code(rv13), rv13.get("verdict"), code(cor13)))

# R13c: failed dispatch / text fallback / no response cannot count
g13c = start("r13c", [GREEN])
c13c, s13c = g13c["candidate_id"], sha_of(g13c)
v13c = INSP(c13c, send=False)
HOP(v13c, respond=False)                                                     # request with the pixels, but it FAILED: no response boundary
no_resp = flyer.review("soc", REV(c13c, s13c))
HOP(v13c, image=False)                                                       # Hermes sent the text summary instead (fallback / stripped parts), a response followed
txt = flyer.review("soc", REV(c13c, s13c, res=("pass", "fail", "pass"), defects=[DEF()]))
f13c = flyer.get_flyer(g13c["flyer_id"])
cor_c = G(CORR(c13c, 1))
check("R13c a request that failed (no response) cannot verify; a text-fallback request followed by a response stores the review UNVERIFIED: no defects exposed as verified, no "
      "correction possible, the status stays unchecked",
      no_resp.get("code") == "image_not_yet_delivered" and txt.get("ok") and txt["verified"] is False and txt["verdict"] == "unverified" and txt["delivery"] == "unknown"
      and f13c["status"] == "unchecked" and cor_c.get("code") == "review_not_verified" and gem_n() == 1,
      (code(no_resp), txt.get("verified"), f13c.get("status"), code(cor_c)))

# R13d: a confirmation covers only its own inspection
g13d = start("r13d", [GREEN])
c13d, s13d = g13d["candidate_id"], sha_of(g13d)
vd = INSP(c13d, send=False)
HOP(vd, only_candidate=True)                                                 # candidate pixels but NOT the merchant photographs that are part of the review material
part = flyer.review("soc", REV(c13d, s13d))
g13e = start("r13e", [GREEN])
c13e, s13e = g13e["candidate_id"], sha_of(g13e)
INSP(c13e, send=False)
other = flyer.review("soc", REV(c13e, s13e))                                  # this request's candidate, no round trip yet (r13d's delivery is irrelevant)
req("r13d")                                                                   # another request id asking for the r13e candidate: not owned, never confirmed
cross = flyer.review("soc", REV(c13e, s13e))
check("R13d a confirmation covers only its own inspection: a request that carried only the candidate (not the review material) stores UNVERIFIED; another candidate/request cannot "
      "reuse an earlier delivery",
      part.get("ok") and part["verified"] is False and other.get("code") == "image_not_yet_delivered" and cross.get("ok") is False and cross.get("code") == "candidate_not_in_request",
      (code(part), part.get("verified"), code(other), code(cross)))

# R13e: restart: a pending (unconfirmed) inspection does not survive it; a confirmed delivery does
g13g = start("r13g", [GREEN])
c13g, s13g = g13g["candidate_id"], sha_of(g13g)
INSP(c13g, send=False)
turn_state.pending_images.clear()                                             # the worker process restarted before any model round trip
lost = flyer.review("soc", REV(c13g, s13g))
flyer.note_response("api-after-restart")                                      # a stale response arriving after the restart finds nothing to confirm
lost2 = flyer.review("soc", REV(c13g, s13g))
INSP(c13g, send=True)                                                         # re-inspection + a real round trip
ok_g = flyer.review("soc", REV(c13g, s13g))
g13h = start("r13h", [GREEN])
INSP(g13h["candidate_id"], send=True)                                         # confirmed, then the process restarts
turn_state.pending_images.clear()
ok_h = flyer.review("soc", REV(g13h["candidate_id"], sha_of(g13h)))
check("R13e after a restart an UNCONFIRMED inspection cannot be completed by a stale response (refused until the candidate is inspected again); a CONFIRMED delivery persists and "
      "its review is verified",
      lost.get("code") == "image_not_yet_delivered" and lost2.get("code") == "image_not_yet_delivered" and ok_g.get("ok") and ok_g["verified"] is True
      and ok_h.get("ok") and ok_h["verified"] is True, (code(lost), code(lost2), code(ok_g), code(ok_h)))

# ---------------- R14: P2 corrections: coherent cached replies; selection state follows REAL artifact validity ----------------
def two_candidates(rid):
    """request with a defective first candidate (RED) and a corrected, passing second one (GREEN); both reviewed (verified), NO final selection yet."""
    g = start(rid, [RED, GREEN])
    c1, s1 = g["candidate_id"], sha_of(g)
    INSP(c1)
    flyer.review("soc", REV(c1, s1, res=("pass", "fail", "pass"), defects=[DEF()]))
    cor = G(CORR(c1, 1))
    c2, s2 = cor["candidate_id"], sha_of(cor)
    INSP(c2)
    flyer.review("soc", REV(c2, s2))
    return g["flyer_id"], c1, s1, c2, s2


def pick(cid, why="Selected by the scripted specialist after comparing both reviews; reviews are fallible."):
    return flyer.finalize("soc", {"candidate_id": cid, "rationale": why})


def stored(fid):
    with core.db() as d:
        return d.execute("SELECT final_candidate_id FROM flyer_runs WHERE run_id=?", (fid,)).fetchone()[0]


# R14a: cached replies describe ONE thing: the attempt they return; the final selection travels separately
fa, a1, as1, a2, as2 = two_candidates("r14a")
n0, u0, g0 = n_attempts(fa), scope_used("r-main"), gem_n()
pre = [G(BASE), G(CORR(a1, 1))]
f_pre = flyer.get_flyer(fa)
fin_a = pick(a1)
post = [G(BASE), G(CORR(a1, 1))]
f_post = flyer.get_flyer(fa)
img_a2 = flyer.image_state(a2)
img_a1 = flyer.image_state(fa)


def coherent(r, cid, sha, status, flyer_status, final_cid):
    return (r.get("ok") is True and r.get("cached") is True and r["candidate_id"] == cid and r["image"]["sha256"] == sha and r["status"] == status
            and r["flyer_status"] == flyer_status and r["final"]["candidate_id"] == final_cid and r["review"]["candidate_id"] == cid and r["unresolved_issues"] == []
            and "Agent review passed" in r["note"] and "UNAPPROVED" not in r["note"])


check("R14a repeated generate/correct calls return ONE coherent attempt result: before any selection (candidate, image hash, review, status, note all of the latest attempt; the flyer "
      "state 'awaiting_selection' is a separate field) and after the specialist selected the OLDER defective candidate (still the attempt's own passed status, with the flyer's final "
      "and 'unresolved_issues' separate); no provider call, attempt or allowance change",
      all(coherent(r, a2, as2, "agent_review_passed", "awaiting_selection", None) for r in pre) and fin_a.get("ok")
      and all(coherent(r, a2, as2, "agent_review_passed", "unresolved_issues", a1) for r in post) and post[0]["final"]["selected"] is True
      and f_post["status"] == "unresolved_issues" and f_post["candidate_id"] == a1 and f_post["image"]["sha256"] == as1 and f_post["unresolved_issues"]
      and f_pre["status"] == "awaiting_selection" and img_a2[0] == "ok" and hashlib.sha256(img_a2[1]).hexdigest() == as2
      and img_a1[0] == "ok" and hashlib.sha256(img_a1[1]).hexdigest() == as1
      and gem_n() == g0 and n_attempts(fa) == n0 == 2 and scope_used("r-main") == u0,
      ([(r.get("candidate_id"), r.get("status"), r.get("flyer_status"), code(r)) for r in pre + post], f_post.get("status"), gem_n() - g0))

# R14b: no selection: validity comes from the FILES (shared artifact check), on every read surface
fb_, b1, bs1, b2, bs2 = two_candidates("r14b")
p1_, p2_ = art(fb_, b1), art(fb_, b2)
raw1, raw2 = p1_.read_bytes(), p2_.read_bytes()
base_b = flyer.get_flyer(fb_)
n0, u0, g0 = n_attempts(fb_), scope_used("r-main"), gem_n()


def surfaces(fid):
    """every stored-data read surface for one flyer: detail, list, specialist read, flyer/candidate image state, cached replies."""
    det = flyer.get_flyer(fid)
    lst = next((x for x in flyer.list_flyers("soc") if x["flyer_id"] == fid), None)
    rd = flyer.read_flyer("soc", {"flyer_id": fid})
    return det, lst, rd


p1_.write_bytes(raw1[: len(raw1) // 2])     # first candidate truncated
p2_.unlink()                                 # second candidate missing
det_x, lst_x, rd_x = surfaces(fb_)
rep_x = [G(BASE), G(CORR(b1, 1))]
check("R14b two successful attempts, no selection, BOTH files bad (truncated / missing): every surface says storage_failure with no usable image reference and each candidate's own "
      "integrity failure; no 'awaiting selection', nothing selected, no generation or attempt change, both reviews preserved",
      det_x["status"] == "storage_failure" and lst_x["status"] == "storage_failure" and rd_x["flyer"]["status"] == "storage_failure"
      and det_x["image"] is None and lst_x["image"] is None and det_x["integrity"]["state"] == "failed" and "awaiting" not in json.dumps([det_x["note"], det_x["error"]]).lower()
      and [c["integrity"]["state"] for c in det_x["candidates"]] == ["failed", "failed"] and all(c["image"] is None and c["review"] for c in det_x["candidates"])
      and flyer.image_state(fb_)[0] == "integrity" and flyer.image_state(b1)[0] == "integrity" and flyer.image_state(b2)[0] == "integrity"
      and flyer.image_file(fb_) is None and stored(fb_) is None and all(r.get("ok") is False and r.get("code") == "artifact_integrity_failed" for r in rep_x)
      and gem_n() == g0 and n_attempts(fb_) == n0 and scope_used("r-main") == u0,
      (det_x["status"], lst_x["status"], det_x["image"], [code(r) for r in rep_x]))

p2_.write_bytes(raw2)                       # the second one is restored: it is the only valid candidate
det_s, lst_s, rd_s = surfaces(fb_)
st_s, bytes_s, _ = flyer.image_state(fb_)
sel_try = pick(b1)
check("R14b2 one valid + one damaged, no selection: the surviving candidate is exposed with its own review status and image (no final is recorded), the damaged candidate's integrity "
      "failure is stated, selecting the damaged one is refused",
      det_s["candidate_id"] == b2 and det_s["status"] == "agent_review_passed" and det_s["final"]["selected"] is False and stored(fb_) is None
      and det_s["image"] and det_s["image"]["sha256"] == bs2 and st_s == "ok" and hashlib.sha256(bytes_s).hexdigest() == bs2
      and lst_s["candidate_id"] == b2 and rd_s["flyer"]["candidate_id"] == b2
      and [d["candidate_id"] for d in det_s["damaged_candidates"]] == [b1] and b1 in det_s["note"]
      and [c["integrity"]["state"] for c in det_s["candidates"]] == ["failed", "valid"] and sel_try.get("code") == "artifact_integrity_failed" and stored(fb_) is None,
      (det_s["status"], det_s["candidate_id"], det_s.get("damaged_candidates"), code(sel_try)))

p1_.write_bytes(raw1)                       # both restored: back to the original two-valid state
det_r = flyer.get_flyer(fb_)
check("R14b3 original bytes restored: two valid candidates and no selection is 'awaiting_selection' again, identical to before the damage (no stored state was changed by the reads)",
      det_r["status"] == "awaiting_selection" and det_r["candidate_id"] is None and det_r["image"] is None and stored(fb_) is None
      and det_r["status"] == base_b["status"] and [c["review"]["verdict"] for c in det_r["candidates"]] == ["defects_found", "passed"]
      and flyer.image_state(fb_)[0] == "unselected", (det_r["status"], det_r["candidate_id"]))

# R14c: a SELECTED damaged candidate stays an explicit failure (never silently the other one); a damaged SUPERSEDED candidate does not spoil a valid selected flyer
fc, c1c, cs1, c2c, cs2 = two_candidates("r14c")
pick(c1c)
art(fc, c1c).write_bytes(b"not an image")
det_c = flyer.get_flyer(fc)
fd, c1d, ds1, c2d, ds2 = two_candidates("r14d")
pick(c2d)
d1_ = art(fd, c1d)
d1_raw = d1_.read_bytes()
d1_.unlink()
det_d = flyer.get_flyer(fd)
rep_d = G(BASE)
check("R14c the selected candidate is damaged: storage_failure for that candidate, never the other (valid) one, no image reference; "
      "R14d the superseded candidate is damaged while the valid selected final stands: the flyer stays served with its own status and bytes",
      det_c["status"] == "storage_failure" and det_c["candidate_id"] == c1c and det_c["image"] is None and flyer.image_state(fc)[0] == "integrity"
      and det_c["final"]["candidate_id"] == c1c and stored(fc) == c1c and flyer.image_state(c2c)[0] == "ok"
      and det_d["status"] == "agent_review_passed" and det_d["candidate_id"] == c2d and det_d["image"]["sha256"] == ds2 and flyer.image_state(fd)[0] == "ok"
      and hashlib.sha256(flyer.image_state(fd)[1]).hexdigest() == ds2 and det_d["final"]["candidate_id"] == c2d and rep_d.get("ok") and rep_d["candidate_id"] == c2d
      and rep_d["flyer_status"] == "agent_review_passed", (det_c["status"], det_c["candidate_id"], det_d["status"], code(rep_d)))

procs[0].terminate()      # Part A's Gemini stand-in; Part B starts its own on the same port
procs[0].wait()
shutil.rmtree(TMP, ignore_errors=True)
if os.environ.get("REVIEW_PART_A_ONLY") == "1":
    print(f"\nPART A only: {sum(results)}/{len(results)}", flush=True)
    sys.exit(0 if results and all(results) else 1)
print(f"\nPART A done: {sum(results)}/{len(results)}", flush=True)

# ================= B. real server + workers + scripted model + scripted Gemini + scripted ad provider =================
print("PART B: real server, HTTP chat API and Hermes workers (scripted model, Gemini and ad provider stand-ins; placeholder images)", flush=True)
BD = Path(tempfile.mkdtemp(prefix="reviewB_"))
BIMGS = BD / "images"
BIMGS.mkdir()
make_image("hw-front", (200, 120, 60), folder=BIMGS)
make_image("hw-detail", (60, 130, 190), fmt="JPEG", folder=BIMGS)
BCAT = BD / "catalogue.json"
BCAT.write_text(json.dumps({**CAT, "products": [{**CAT["products"][0], "images": [CAT["products"][0]["images"][0], CAT["products"][0]["images"][1]]}]}), encoding="utf-8")
GHOST = BD / "catalogue-ghost.json"
GHOST.write_text(json.dumps({**CAT, "products": [{**CAT["products"][0], "images": [{"image_id": "hw-ghost", "kind": "test placeholder image (synthetic)"}]}]}), encoding="utf-8")
ENV = {**os.environ, "PYTHONUTF8": "1", "ECOM_CLASSIFIER": "off", "ECOM_VISION_MODELS": "nebius-token-factory:mock-model", "ECOM_CATALOGUE_FILE": str(BCAT),
       "ECOM_IMAGE_DIRS": str(BIMGS), "ECOM_FLYER_ALLOW_SYNTHETIC": "1", "ECOM_FLYER_SCOPE": "b-main", "ECOM_FLYER_MAX_ATTEMPTS": "40", "GEMINI_API_KEY": KEY,
       "ECOM_SCRAPECREATORS_URL": f"http://127.0.0.1:{FB}", "ECOM_PHOTO_HOSTS": "127.0.0.1", "SCRAPECREATORS_API_KEY": "TEST-SCRAPE-KEY-SENTINEL",
       "ECOM_ADS_SCOPE": "b-ads", "ECOM_ADS_API_MAX": "120", "ECOM_ADS_IMAGE_MAX": "40"}
for k in ("LLM_PROVIDER", "LLM_MODEL", "NEBIUS_API_KEY", "NEBIUS_BASE_URL", "NEBIUS_MODEL", "ECOM_APP_ROOT", "HERMES_HOME", "ECOM_RESEARCH_SCOPE"):
    ENV.pop(k, None)
os.environ.pop("ECOM_APP_ROOT", None)
os.environ.pop("HERMES_HOME", None)
FLY_RE = re.compile(r"Flyer (fly-[0-9a-f]{10}) status (\w+) candidate (cand-[0-9a-f]{10})", re.I)


def fb_ctl(**kw):
    return http(FB, "/control", {"reset": True, **kw})[1]


def fb_n():
    return http(FB, "/stats")[1]["total"]


def chat(agent, message, rid=None, timeout=900):
    body = {"message": message}
    if rid:
        body["request_id"] = rid
    for attempt in range(6):
        try:
            return http(APP, f"/api/chat/{agent}", body, timeout=timeout)[:2]
        except (ConnectionResetError, http_client.IncompleteRead) as e:
            # An intermittent Windows loopback reset of a LONG response (the app server stays up and has already stored the finished turn; cause undiagnosed, also seen
            # before this ticket). Replaying the same request_id returns the stored completed result and runs nothing (checked by B7), so retrying is safe and not a mask.
            if not rid or attempt == 5:
                raise
            print(f"NOTE transport reset reading the response of request {rid} ({type(e).__name__}); replaying the same request id", flush=True)
            time.sleep(2)


def tool(agent, name, a):
    with role_hold.second_of_role(ROOT, (a or {}).get('role') if name == 'create_agent' else None):   # older suite: build a second agent of one role (test-only hold)
        st_, r = chat(agent, "CALL_TOOL:" + json.dumps({"name": name, "args": a}))
    outs = [json.loads(t["output"]) for t in r.get("tools", []) if t.get("name") == name and t.get("output")]
    return (outs[0] if outs else None), r


def start_server(extra=None, drop=()):
    env = {k: v for k, v in {**ENV, **(extra or {})}.items() if k not in drop}
    log = open(os.environ["REVIEW_SERVER_LOG"], "ab") if os.environ.get("REVIEW_SERVER_LOG") else subprocess.DEVNULL   # optional diagnostics (ignored scratch path)
    p = subprocess.Popen([sys.executable, "-m", "app.server", str(APP)], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=log)
    procs.append(p)
    for _ in range(80):
        try:
            http(APP, "/api/status", timeout=5)
            http(APP, "/api/flyers", timeout=10)
            return p
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("server did not start")


def stop(p):
    p.terminate()
    p.wait()
    time.sleep(2)


def acts(r):
    return [a["tool"] for a in r.get("activity", [])]


def act_out(r, name):
    return [json.loads(a["output"]) for a in r.get("activity", []) if a["tool"] == name and a.get("output") and a["output"].lstrip().startswith("{")]


def flyer_of(r):
    m = FLY_RE.search(r.get("text") or "")
    return (m.group(1), m.group(2), m.group(3)) if m else (None, None, None)


def llm_images():
    return http(MOCK, "/stats")[1]["image_log"]


EVID = {}
try:
    shutil.rmtree(ROOT / "runtime", ignore_errors=True)
    (ROOT / "secrets").mkdir(exist_ok=True)
    (ROOT / "secrets" / "local.env").write_text(f"LLM_PROVIDER=nebius-token-factory\nLLM_MODEL=mock-model\nNEBIUS_API_KEY=mock-key\nNEBIUS_BASE_URL=http://127.0.0.1:{MOCK}/v1\n", encoding="utf-8")
    subprocess.run([sys.executable, "scripts/setup.py"], cwd=ROOT, env=ENV, check=True, capture_output=True)
    spawn(["tests/mock_llm.py", str(MOCK)], env=ENV)
    gp_ = spawn(["tests/mock_gemini.py", str(GEM)])
    spawn(["tests/mock_fb_ads.py", str(FB)])
    wait_up(MOCK, "/stats")
    wait_up(GEM)
    wait_up(FB)
    gem_ctl()
    fb_ctl(first="relevant", reach="absent")
    srv = start_server()
    http(APP, "/api/company", {"fields": {"name": "Harbor Textiles", "products": "Wool throws and linen bedding (fictional test data)", "customers": "Home buyers (fictional)",
                                          "goal": "Present our textiles clearly and accurately", "brand": "Calm, natural, plain-spoken"}})
    SK = [{"name": "flyer-routine", "content": "# Flyer routine\n1. Research ads, inspect the images you rely on.\n2. Generate one flyer, inspect its pixels, review it.\n3. Correct once if needed and select one final candidate."}]
    spec, _ = tool("main", "create_agent", {"role": "social_media", "name": "Harbor Reviewing Specialist", "company_context_refs": [], "skills": SK,
                                            "objective": "Research US Facebook image ads, generate one accurate promotional flyer from Harbor's own photographs, review its actual pixels and correct it at most once.",
                                            "instructions": "You work for Harbor Textiles (fictional test merchant). Use only supplied product facts, select the merchant's own photographs, report "
                                                            "review results as fallible agent reviews and never call a flyer approved.",
                                            "requested_tools": TOOLS + list(core.AD_TOOLS) + ["inspect_image", "read_catalogue"]})
    check("B1 main creates a social specialist WITH the review/correction tools (grants = requested + foundation) through the real create_agent tool; its SOUL describes the "
          "one-correction rule and fallible agent review",
          spec and spec.get("ok") and set(TOOLS) <= set(spec["granted_tools"]) and set(NEW_TOOLS) <= set(spec["granted_tools"]), spec)
    S = spec["agent_id"]
    soul = (ROOT / "runtime" / "hermes_home" / "profiles" / S / "SOUL.md").read_text(encoding="utf-8")
    grants_before = {a["agent_id"]: a["granted_tools"] for a in http(APP, "/api/agents")[1]}
    check("B1b the saved SOUL explains: inspect the actual candidate pixels, review three checks, at most ONE correction, explicit final selection, 'agent review passed' (never approved)",
          "inspect_flyer" in soul and "review_flyer" in soul and "finalize_flyer" in soul and "ONE correction" in soul and "agent review passed" in soul.lower(), soul[-900:])

    # ---- scenario 1: acceptable first candidate (one generation, one review, finalize)
    def run_flow(rid, colors, opts="", ctl_mode=None, fb=None):
        gem_ctl(colors=colors, mode=ctl_mode or "ok")
        fb_ctl(**(fb or {"first": "relevant", "reach": "absent"}))
        n_img = len(llm_images())
        st_, r = chat(S, f"REVIEW_AGENT Make one reviewed promotional flyer for our wool throw using the best Facebook ad references. {opts}", rid=rid)
        return r, llm_images()[n_img:]

    r1, im1 = run_flow("b-1", [GREEN])
    fid_b1, st_b1, cand_b1 = flyer_of(r1)
    seq1 = acts(r1)
    det1 = http(APP, f"/api/flyers/{fid_b1}")[1] if fid_b1 else {}
    check("B2 acceptable first candidate through the real chat API: the specialist researched ads, inspected the merchant photographs, generated ONCE, inspected the candidate pixels, "
          "reviewed and finalised; ONE Gemini request in total; the API reports 'agent_review_passed' with the ad research link and the review bound to the candidate hash",
          r1["ok"] and gem_n() == 1 and seq1.count("generate_flyer") == 1 and seq1.index("inspect_flyer") > seq1.index("generate_flyer") and seq1.index("review_flyer") > seq1.index("inspect_flyer")
          and seq1[-1] == "finalize_flyer" and st_b1 == "agent_review_passed" and det1.get("status") == "agent_review_passed" and det1["final"]["candidate_id"] == cand_b1
          and det1["research"]["ad_package_id"] and det1["research"]["reach_gate"] and det1["review"]["sha256"] == det1["candidates"][0]["output"]["sha256"]
          and det1["review"]["verified"] is True and det1["attempts"]["used"] == 1, (seq1, r1.get("text", "")[:240], gem_n(), det1.get("status")))
    candidate_pixels = [i for rec in im1 for i in rec["images"]]
    check("B3 image bytes really reached the scripted reasoning model: the request after inspect_flyer carries the candidate's pixels (mean colour = the control colour) followed by the "
          "merchant photographs (their mean colours), and a red/green control changes the decision",
          any(close(i.get("mean", []), GREEN, 14) for i in candidate_pixels) and any(close(i.get("mean", []), mean_of(BIMGS.joinpath("hw-front.png").read_bytes()), 14) for i in candidate_pixels),
          [i.get("mean") for i in candidate_pixels][:8])
    EVID["b1"] = {"reply": r1.get("text"), "activity": [(a["tool"], a["status"]) for a in r1["activity"]], "detail": det1}

    # ---- scenario 2: defective first -> ONE correction -> passed second
    r2_, im2 = run_flow("b-2", [RED, GREEN])
    fid_b2, st_b2, cand_b2 = flyer_of(r2_)
    seq2 = acts(r2_)
    det2 = http(APP, f"/api/flyers/{fid_b2}")[1] if fid_b2 else {}
    greq = gem_stats()["requests"]
    c_first = (det2.get("candidates") or [{}])[0]
    check("B4 defective first candidate through the real app: ONE specific correction naming the recorded defect, a second inspection and review, ONE final selection (the corrected "
          "candidate); exactly TWO Gemini requests; the correction request carried the original photographs then the previous draft's bytes; both candidates, prompts and reviews "
          "are in the detail",
          r2_["ok"] and len(greq) == 2 and seq2.count("generate_flyer") == 2 and seq2.count("inspect_flyer") == 2 and seq2.count("review_flyer") == 2 and seq2[-1] == "finalize_flyer"
          and det2.get("status") == "agent_review_passed" and det2["final"]["candidate_id"] == cand_b2 and det2["attempts"]["used"] == 2
          and [i["sha256"] for i in greq[1]["images"]] == [sha(BIMGS / "hw-front.png"), sha(BIMGS / "hw-detail.jpg"), c_first["output"]["sha256"]]
          and c_first["review"]["verdict"] == "defects_found" and det2["candidates"][1]["review"]["verdict"] == "passed" and det2["candidates"][1]["corrections"]
          and det2["candidates"][1]["predecessor_id"] == c_first["candidate_id"], (seq2, len(greq), det2.get("status")))
    imgs2 = [i for rec in im2 for i in rec["images"]]
    check("B5 the scripted reviewer's two different decisions followed the two different candidate pixels it was shown (first mean ~ red control, second ~ green control)",
          any(close(i.get("mean", []), RED, 14) for i in imgs2) and any(close(i.get("mean", []), GREEN, 14) for i in imgs2), [i.get("mean") for i in imgs2][:10])
    EVID["b2"] = {"reply": r2_.get("text"), "activity": [(a["tool"], a["status"]) for a in r2_["activity"]], "detail": det2, "gemini_requests": [
        {k: v for k, v in q.items() if k in ("text", "images", "n_input", "store")} for q in greq], "model_pixel_means": [i.get("mean") for i in imgs2]}

    # ---- scenario 3: defective second -> no third generation; unresolved issues visible
    r3_, im3 = run_flow("b-3", [RED, RED], "TRY_THIRD")
    fid_b3, st_b3, cand_b3 = flyer_of(r3_)
    det3 = http(APP, f"/api/flyers/{fid_b3}")[1] if fid_b3 else {}
    gens3 = act_out(r3_, "generate_flyer")
    stc3, img3, ct3 = http(APP, f"/api/flyers/images/{fid_b3}", raw=True)
    check("B6 defective second candidate through the real app: a third attempt is refused (correction_limit_reached), exactly TWO Gemini requests, the final draft is file-valid and "
          "flagged 'unresolved_issues' with the defect text in the API, and its image is served",
          gem_n() == 2 and any(g.get("code") == "correction_limit_reached" for g in gens3) and det3.get("status") == "unresolved_issues" and det3["unresolved_issues"]
          and stc3 == 200 and ct3 == "image/jpeg" and "unapproved" in json.dumps(det3).lower(), (gem_n(), [g.get("code") for g in gens3], det3.get("status")))
    EVID["b3"] = {"reply": r3_.get("text"), "detail": det3}

    # ---- scenario 4: explicit selection is not 'newest'
    r4_, _ = run_flow("b-4", [RED, RED], "PICK_FIRST")
    fid_b4, _, cand_b4 = flyer_of(r4_)
    det4 = http(APP, f"/api/flyers/{fid_b4}")[1] if fid_b4 else {}
    stc4, img4, _ = http(APP, f"/api/flyers/images/{fid_b4}", raw=True)
    check("B7 the specialist's explicit choice of the FIRST candidate is what the flyer serves (not the newest): final candidate = first, image bytes = first candidate's file",
          det4.get("final", {}).get("candidate_id") == det4["candidates"][0]["candidate_id"] != det4["candidates"][1]["candidate_id"] and stc4 == 200
          and hashlib.sha256(img4).hexdigest() == det4["candidates"][0]["output"]["sha256"], (det4.get("final"), stc4))

    # ---- scenario 4b (P1): inspection and a fabricated review in ONE assistant tool-call batch, through the real Hermes loop
    r14, im14 = run_flow("b-14", [RED, GREEN], "BATCH_REVIEW")
    fid_b14, st_b14, cand_b14 = flyer_of(r14)
    det14 = http(APP, f"/api/flyers/{fid_b14}")[1] if fid_b14 else {}
    seq14 = acts(r14)
    revs14 = act_out(r14, "review_flyer")
    batches = http(MOCK, "/stats")[1]["batches"]
    c14 = det14.get("candidates") or [{}, {}]
    check("B14 a scripted model that submits inspect_flyer and review_flyer in ONE assistant batch: the same-batch review is refused (image_not_yet_delivered) and stores nothing; the "
          "specialist then looks at the pixels in a later response, finds the (red-control) defect, the ONE correction happens and the final passes on the corrected candidate's own "
          "verified review. The blind 'pass' never became the first candidate's review",
          r14["ok"] and ["inspect_flyer", "review_flyer"] in batches and revs14 and revs14[0].get("code") == "image_not_yet_delivered"
          and seq14.count("generate_flyer") == 2 and gem_n() == 2 and c14[0].get("review", {}).get("verdict") == "defects_found" and c14[0]["review"]["verified"] is True
          and c14[1].get("review", {}).get("verdict") == "passed" and det14.get("status") == "agent_review_passed" and det14["final"]["candidate_id"] == cand_b14
          and "Fabricated in the same batch" not in json.dumps(det14), (seq14, batches, [r.get("code") or r.get("verdict") for r in revs14], gem_n(), det14.get("status")))
    EVID["b14"] = {"reply": r14.get("text"), "activity": [(a["tool"], a["status"]) for a in r14["activity"]], "tool_batches_seen_by_model": batches,
                   "review_results": [{k: v for k, v in r.items() if k in ("ok", "code", "verdict", "verified", "error")} for r in revs14], "detail_status": det14.get("status")}

    # ---- scenario 5: no relevant ads -> honest blocker, no generation
    n_runs0 = len(http(APP, "/api/flyers")[1])
    r5_, _ = run_flow("b-5", [GREEN], fb={"first": "empty", "never_relevant": True, "reach": "absent"})
    check("B8 no relevant ads: the specialist reports an honest blocker, no flyer record exists for the request and Gemini was never called",
          "BLOCKED" in r5_["text"] and "Flyer NOT generated" in r5_["text"] and gem_n() == 0 and len(http(APP, "/api/flyers")[1]) == n_runs0 and "generate_flyer" not in acts(r5_),
          (r5_["text"][:200], gem_n()))

    # ---- scenario 6: missing merchant asset -> blocker, no review is invented
    stop(srv)
    srv = start_server({"ECOM_CATALOGUE_FILE": str(GHOST)})
    r6_, _ = run_flow("b-6", [GREEN], "SKIP_ADS")
    check("B9 a catalogue photograph that is not available is an honest setup blocker (merchant_image_missing): no generation, no inspection, no review",
          "merchant_image_missing" in r6_["text"] and gem_n() == 0 and "review_flyer" not in acts(r6_) and "inspect_flyer" not in acts(r6_), (r6_["text"][:240], acts(r6_)))
    stop(srv)
    srv = start_server()

    # ---- scenario 7: delivery unavailable -> explicit UNCHECKED (a specialist created while no vision model is declared; its profile never carries the declaration)
    stop(srv)
    srv = start_server({"ECOM_VISION_MODELS": ""})
    spec2, _ = tool("main", "create_agent", {"role": "social_media", "name": "Harbor Text Only Reviewer", "company_context_refs": [], "skills": SK,
                                             "objective": "Generate one flyer from Harbor's own photographs and report honestly when its pixels could not be reviewed.",
                                             "instructions": "You work for Harbor Textiles (fictional test merchant). Use only supplied facts; report review limits plainly.",
                                             "requested_tools": TOOLS + ["inspect_image", "read_catalogue"]})
    S2 = (spec2 or {}).get("agent_id")
    gem_ctl(colors=[RED, GREEN])
    st7, r7_ = chat(S2, "REVIEW_AGENT Make one reviewed promotional flyer for our wool throw. SKIP_ADS", rid="b-7") if S2 else (0, {"text": ""})
    fid_b7, st_b7, cand_b7 = flyer_of(r7_)
    det7 = http(APP, f"/api/flyers/{fid_b7}")[1] if fid_b7 else {}
    check("B10 when the model/provider cannot receive images the review is stored UNVERIFIED and the result is explicitly 'unchecked': no correction is possible and no pass is claimed",
          det7.get("status") == "unchecked" and (det7.get("review") or {}).get("verified") is False and det7["review"]["delivery"] in ("text_fallback", "unknown")
          and det7["attempts"]["used"] == 1 and gem_n() == 1, (det7.get("status"), (det7.get("review") or {}).get("delivery"), gem_n(), r7_.get("text", "")[:200]))
    stop(srv)
    srv = start_server()

    # ---- scenario 8: restart, provider replaced, no key: everything retrievable unchanged without any provider request
    before = {x["flyer_id"]: x for x in http(APP, "/api/flyers")[1]}
    dets_before = {f: http(APP, f"/api/flyers/{f}")[1] for f in before}
    imgs_before = {f: http(APP, f"/api/flyers/images/{f}", raw=True)[:2] for f in before}
    stop(srv)
    stop(gp_)
    gp_ = spawn(["tests/mock_gemini.py", str(GEM)])
    wait_up(GEM)
    fb0 = fb_n()
    srv = start_server(drop=("GEMINI_API_KEY", "SCRAPECREATORS_API_KEY"))
    after = {x["flyer_id"]: x for x in http(APP, "/api/flyers")[1]}
    dets_after = {f: http(APP, f"/api/flyers/{f}")[1] for f in after}
    imgs_after = {f: http(APP, f"/api/flyers/images/{f}", raw=True)[:2] for f in after}
    _, rd_r = chat(S, "CALL_TOOL:" + json.dumps({"name": "read_flyer", "args": {"flyer_id": fid_b2}}))   # (stored Activity output is cut at 3000 chars: the head is enough)
    rd = next((a for a in rd_r.get("activity", []) if a["tool"] == "read_flyer" and a["status"] == "ok" and '"ok": true' in a["output"][:30] and fid_b2 in a["output"]), None)
    check("B11 after an app restart with the provider stand-in replaced and NO keys, the list, every flyer's detail (candidates, reviews, prompts, final selection, research link) and every "
          "image are identical, and the specialist's read_flyer works: ZERO Gemini and ZERO ad-provider requests",
          after == before and dets_after == dets_before and imgs_after == imgs_before and rd is not None and gem_n() == 0 and fb_n() == fb0
          and http(APP, "/api/status")[1]["image_generation_configured"] is False, (len(after), gem_n(), fb_n()))
    page = http(APP, "/", raw=True)[1].decode("utf-8")
    check("B12 the existing saved-flyer card has minimal renderings for the new states (final selection, agent review passed / unresolved issues / unchecked, candidate count, unresolved "
          "issues) from backend data",
          all(s in page for s in ("cardHTML", "rc-issues", "unresolved_issues", "awaiting_selection")), [s for s in ("cardHTML", "rc-issues", "unresolved_issues", "awaiting_selection") if s not in page])
    check("B13 no stored grant or saved SOUL was widened or rewritten by any of this",
          (lambda now: all(now.get(k) == v for k, v in grants_before.items()))({a["agent_id"]: a["granted_tools"] for a in http(APP, "/api/agents")[1]})
          and (ROOT / "runtime" / "hermes_home" / "profiles" / S / "SOUL.md").read_text(encoding="utf-8") == soul)
    # ---- scenario 16 (P2): two candidates and NO selection; their files are damaged / restored through the real app, restart included
    stop(srv)
    srv = start_server()   # normal env again (the restart scenario above ran without the image key)
    r16, _ = run_flow("b-16", [RED, GREEN], "NO_FINALIZE")
    fid16, _, _ = flyer_of(r16)
    det16 = http(APP, f"/api/flyers/{fid16}")[1] if fid16 else {}
    cids = [c["candidate_id"] for c in det16.get("candidates") or []]
    fdir = ROOT / "runtime" / "flyers" / (fid16 or "none")
    files = [next(fdir.glob(c + ".*")) for c in cids] if len(cids) == 2 else []
    originals = [f_.read_bytes() for f_ in files]
    g16 = gem_n()

    def api16():
        lst = next((x for x in http(APP, "/api/flyers")[1] if x["flyer_id"] == fid16), {})
        d_ = http(APP, f"/api/flyers/{fid16}")[1]
        im = http(APP, f"/api/flyers/images/{fid16}", raw=True)
        _, rd = chat(S, "CALL_TOOL:" + json.dumps({"name": "read_flyer", "args": {"flyer_id": fid16}}))
        rdo = next((a["output"][:400] for a in rd.get("activity", []) if a["tool"] == "read_flyer" and a.get("output")), "")
        return lst, d_, im, rdo

    base16 = api16()
    files[0].write_bytes(originals[0][: len(originals[0]) // 2])
    files[1].unlink()
    both = api16()
    stop(srv)
    srv = start_server()
    both_restart = api16()
    files[1].write_bytes(originals[1])
    one = api16()
    one_cand = http(APP, f"/api/flyers/images/{cids[0]}", raw=True)[0]
    files[0].write_bytes(originals[0])
    back = api16()
    check("B16 two successful candidates and NO selection (real app): awaiting_selection with no image while both files are valid; BOTH damaged: list, detail, image endpoint (409 "
          "artifact_integrity_failed) and the specialist's read_flyer all say storage failure, before and after an app restart; ONE restored: the surviving candidate is served "
          "with its own status and the damaged one stays an integrity failure; all restored: awaiting_selection again; no final recorded, no provider request, attempts unchanged",
          len(cids) == 2 and base16[1]["status"] == "awaiting_selection" and base16[0]["status"] == "awaiting_selection" and base16[2][0] == 409
          and both[0]["status"] == "storage_failure" and both[1]["status"] == "storage_failure" and both[1]["image"] is None and both[2][0] == 409
          and json.loads(both[2][1]).get("code") == "artifact_integrity_failed"
          and '"status": "storage_failure"' in both[3]
          and both_restart[1]["status"] == "storage_failure" and both_restart[0]["status"] == "storage_failure" and both_restart[2][0] == 409
          and one[1]["status"] == "agent_review_passed" and one[1]["candidate_id"] == cids[1] and one[2][0] == 200
          and hashlib.sha256(one[2][1]).hexdigest() == det16["candidates"][1]["output"]["sha256"] and one_cand == 409
          and [c["integrity"]["state"] for c in one[1]["candidates"]] == ["failed", "valid"] and one[1]["final"]["selected"] is False
          and back[1]["status"] == "awaiting_selection" and back[2][0] == 409
          and gem_n() == g16 and http(APP, f"/api/flyers/{fid16}")[1]["attempts"]["used"] == 2 and not http(APP, f"/api/flyers/{fid16}")[1]["final"]["selected"],
          (base16[1].get("status"), both[1].get("status"), both_restart[1].get("status"), one[1].get("status"), back[1].get("status"), gem_n() - g16))

    # ---- scenario 4c (P1): the provider rejects image-bearing tool results; Hermes downgrades to text; no verified review may result
    stop(srv)
    srv = start_server()   # a fresh worker: a rejected image-bearing request makes Hermes remember the provider/model as text-only for its session
    rej0 = http(MOCK, "/stats")[1]["rejected_image_requests"]
    r15, im15 = run_flow("b-15", [RED], "REJECT_IMAGES")
    fid_b15, st_b15, cand_b15 = flyer_of(r15)
    det15 = http(APP, f"/api/flyers/{fid_b15}")[1] if fid_b15 else {}
    rej1 = http(MOCK, "/stats")[1]["rejected_image_requests"]
    seq15 = acts(r15)
    saves15 = [x for x in r15.get("activity", []) if x.get("tool") == "save_ad_research"]
    check("B15 failed image delivery through the real loop: the provider 400s the image-bearing request and Hermes retries with text only, so the competitor images were NEVER confirmed "
          "delivered: save_ad_research is refused (image_not_delivered), the specialist stops BEFORE any Gemini request (no unresearched flyer, no pass claimed, nothing to correct)",
          rej1 > rej0 and gem_n() == 0 and not fid_b15 and "generate_flyer" not in seq15 and saves15
          and all("image_not_delivered" in str(x.get("output")) for x in saves15) and "agent_review_passed" not in json.dumps(r15.get("text", "")),
          (rej1 - rej0, gem_n(), seq15, [str(x.get("output"))[:160] for x in saves15], str(r15.get("text", ""))[:200]))

    if os.environ.get("REVIEW_EVIDENCE_DIR"):
        ev = Path(os.environ["REVIEW_EVIDENCE_DIR"])
        ev.mkdir(parents=True, exist_ok=True)
        (ev / "full-trace-scripted.json").write_text(json.dumps({"note": "SCRIPTED: stand-in Gemini (solid control colours), rule-based specialist, invented ads. Proves wiring, binding "
                                                                 "and bounds; NOT real Gemini output or real visual-review accuracy.", **EVID}, indent=1, default=str), encoding="utf-8")
        (ev / "final-candidate-one-correction.jpg").write_bytes(http(APP, f"/api/flyers/images/{fid_b2}", raw=True)[1])
        (ev / "first-candidate-defective.jpg").write_bytes(http(APP, f"/api/flyers/images/{(det2.get('candidates') or [{}])[0].get('candidate_id')}", raw=True)[1])
finally:
    for p in procs:
        try:
            p.terminate()
        except Exception:
            pass
    shutil.rmtree(BD, ignore_errors=True)
print(f"\n{sum(results)}/{len(results)} checks passed (scripted Gemini + scripted model + placeholder images: wiring/enforcement only, NOT real Gemini output or visual-review accuracy)")
sys.exit(0 if results and all(results) else 1)
