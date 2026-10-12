"""Ticket 04 focused tests: catalogue + RECORDED evidence tools, the inspection log, the validated save, and the read API.
Part A/B: pure backend (temp root, no Hermes, no model). Part C: SCRIPTED model through the real server and Hermes workers (tool provisioning,
isolation, end-to-end tool flow, restart, read API makes no model/scraper call). Nothing here is a vision or reasoning test; the live
demonstration is tests/listing_live_check.py. Wipes the copy's runtime/ in part C - run ONLY from a COPY:
  LISTING_I_AM_A_COPY=1 venv-python tests/listing_draft_test.py"""
import copy, hashlib, json, os, shutil, sqlite3, subprocess, sys, tempfile, time, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if os.environ.get("LISTING_I_AM_A_COPY") != "1":
    sys.exit("Refusing to run: set LISTING_I_AM_A_COPY=1 and run from a COPY of the project.")
FIX = ROOT / "tests" / "fixtures"
os.environ["HERMES_HOME"] = str(ROOT / "runtime" / "hermes_home" / "profiles" / "main")   # project-local, set before ANY profile operation; core refuses profile creation elsewhere
TMP = Path(tempfile.mkdtemp(prefix="lst_"))
os.environ["ECOM_APP_ROOT"] = str(TMP)                       # parts A/B write their app.db here, never to the copy's runtime
EV_REAL = FIX / "marketplace_sample.json"                     # carries the REAL recorded photo hashes: the synthetic stand-ins below deliberately do NOT match them
os.environ["ECOM_CATALOGUE_FILE"] = str(FIX / "demo_catalogue.json")
os.environ["ECOM_EVIDENCE_FILE"] = str(EV_REAL)
IMGS = TMP / "imgs"
IMGS.mkdir()
os.environ["ECOM_IMAGE_DIRS"] = str(IMGS)
sys.path.insert(0, str(ROOT))
from PIL import Image
from app import core, listing, hermes_plugin as hp
# the catalogue is only supplied to the company it belongs to (ticket 05): this isolated company matches the demo catalogue's merchant
core.update_company({"name": "Acme Linens", "products": "Cotton bedding", "customers": "Home buyers in the US", "goal": "Better listing photos"}, source="form")

results, procs = [], []
MOCK, APP = 8774, 8823


def check(name, ok, detail=""):
    ok = bool(ok); results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{str(detail)[:500]}]"), flush=True)


# synthetic stand-ins for the cached photos, named by listing ID (the tests need files, not the private real photos)
for lid, col in (("1638806271151287", (200, 90, 60)), ("918521891138262", (60, 60, 70)), ("demo-quilt-front", (222, 209, 186))):
    Image.new("RGB", (200, 160), col).save(IMGS / f"{lid}.png")
A, B = "spec-a", "spec-b"
PID = "acme-cloud-quilt-queen"


def truthful_evidence(name, imgs, drop=()):
    """Copy of the recorded sample whose image_checks carry the TRUE sha256 of the synthetic stand-in files (the stand-ins are what this suite
    inspects, so their hashes are the truthful ones); `drop` removes a listing's recorded check (-> no recorded hash to compare)."""
    ev = json.loads(EV_REAL.read_text(encoding="utf-8"))
    for chk in ev["image_checks"]:
        f = next((p for p in imgs.glob(chk["listing_id"] + ".*")), None)
        if f is not None:
            chk["sha256"] = hashlib.sha256(f.read_bytes()).hexdigest()
    ev["image_checks"] = [c for c in ev["image_checks"] if c["listing_id"] not in drop]
    (TMP / name).write_text(json.dumps(ev), encoding="utf-8")
    return TMP / name


EV_TRUE = truthful_evidence("ev_truthful.json", IMGS)
EV_NOHASH = truthful_evidence("ev_nohash.json", IMGS, drop=("1638806271151287",))   # no recorded hash for that photo at all
os.environ["ECOM_EVIDENCE_FILE"] = str(EV_TRUE)


def register(agent_id, tools=("save_listing_draft",)):
    with core.db() as d:
        d.execute("INSERT OR REPLACE INTO agents VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (agent_id, agent_id, "market_analysis", "default", "o", "i", "[]", "[]", json.dumps(list(tools)), "[]", f"conv-{agent_id}", "idle", time.time()))


def inspect(agent, iid, delivery="image_part_sent"):
    r = core.prepare_image(iid)
    assert r["ok"], r
    listing.record_inspection(agent, r, delivery=delivery)
    return r


def draft(**over):
    d = {"product_id": PID, "title": "Cloud Weave Quilted Coverlet, Queen, Oatmeal",
         "description": "A queen-size quilted coverlet in oatmeal with a 100% cotton shell and polyester fill. Machine washable. Supplied as a single coverlet, new.",
         "visual_brief": "Shoot the coverlet fully made up on a queen bed against a plain light wall, daylight from the left, one close-up of the diamond quilting, "
                         "and a folded stack showing the oatmeal colour. Keep the frame uncluttered so the product is the focus.",
         "rationale": [{"claim": "A comparable new comforter set is listed at a low asking price with a sealed-bag photo.", "listing_ids": ["1638806271151287"],
                        "image_ids": ["1638806271151287"]}],
         "image_observations": [{"image_id": "1638806271151287", "observations": "Sealed clear bag with a coral and beige comforter and a printed insert.",
                                 "uncertainties": "Fine print not readable."}],
         "limitations": "Asking prices only; no sales data."}
    d.update(over)
    return d


def err_code(r):
    return r.get("code") if isinstance(r, dict) and r.get("ok") is False else ("OK" if isinstance(r, dict) and r.get("ok") else r)


register(A); register(B); register("env-agent"); register("no-grant", tools=("memory",))


# ================= A. catalogue + recorded evidence =================
c = listing.read_catalogue()
p0 = c["products"][0]
check("A1 catalogue: fictional demo is labelled, product facts supplied, nothing missing, product image inspectable",
      c["ok"] and c["demo"] and "FICTIONAL" in c["notice"] and p0["product_id"] == PID and p0["price"] == {"amount": 89.0, "currency": "USD"}
      and p0["missing_facts"] == [] and p0["image_inspectable"] and "synthetic illustration" in p0["image"]["kind"], c)
check("A2 unknown product -> unknown_product listing the allowed IDs", err_code(listing.read_catalogue("nope")) == "unknown_product" and listing.read_catalogue("nope")["allowed_values"] == [PID])
r = listing.read_recorded_evidence(limit=40)
blob = json.dumps(r)
check("A3 recorded evidence: 59 recorded, detailed vs search-only distinguished, no manual verdicts or manual visual notes leak",
      r["total_recorded"] == 59 and {x["detail_level"] for x in r["listings"]} == {"detailed", "search_only"} and "manual_review" not in blob
      and "manual_visual" not in blob and "codex" not in blob.lower(), blob[:300])
cached = listing.read_recorded_evidence(cached_images_only=True)
check("A4 image_cached is derived from files actually present (2 of the recorded listings here), not from the fixture",
      sorted(x["listing_id"] for x in cached["listings"]) == ["1638806271151287", "918521891138262"], cached["listings"])
d1 = listing.read_recorded_evidence(listing_id="1638806271151287")["listing"]
check("A5 listing detail carries source URL, retrieval time, price/currency, seller pseudonym only",
      d1["source_url"].startswith("https://www.facebook.com/marketplace/item/") and d1["retrieved_at"] and d1["price"]["currency"] == "USD"
      and d1["seller_ref"].startswith("seller_") and d1["detail_level"] == "detailed", d1)
check("A6 unknown listing id rejected; text filter and detailed filter work",
      err_code(listing.read_recorded_evidence(listing_id="1")) == "unknown_listing"
      and listing.read_recorded_evidence(query="zzz-no-such-text")["matches"] == 0 and listing.read_recorded_evidence(query="comforter")["matches"] > 0
      and listing.read_recorded_evidence(detailed_only=True)["matches"] == 12)
miss = copy.deepcopy(json.loads((FIX / "demo_catalogue.json").read_text(encoding="utf-8")))
del miss["products"][0]["price"]
(TMP / "cat_missing.json").write_text(json.dumps(miss), encoding="utf-8")
os.environ["ECOM_CATALOGUE_FILE"] = str(TMP / "cat_missing.json")
check("A7 a catalogue product with missing facts is reported (missing_facts) and a draft for it is refused, not guessed",
      listing.read_catalogue(PID)["products"][0]["missing_facts"] == ["price.amount", "price.currency"]
      and err_code(listing.save_draft(A, draft())) == "product_facts_missing")
os.environ["ECOM_CATALOGUE_FILE"] = str(FIX / "demo_catalogue.json")
os.environ["ECOM_EVIDENCE_FILE"] = str(TMP / "nope.json")
check("A8 missing evidence file -> explicit evidence_missing for reads and for saves",
      err_code(listing.read_recorded_evidence()) == "evidence_missing" and err_code(listing.save_draft(A, draft())) == "evidence_missing")
os.environ["ECOM_EVIDENCE_FILE"] = str(EV_TRUE)

# ================= B. validated save =================
inspect(A, "1638806271151287")
check("B0 saving needs a registered specialist that holds save_listing_draft (defence in depth behind tool exposure)",
      err_code(listing.save_draft("ghost", draft())) == "unknown_agent" and err_code(listing.save_draft("no-grant", draft())) == "not_granted"
      and err_code(listing.save_draft("", draft())) == "unknown_agent")
bad = [("unknown product", draft(product_id="x"), "unknown_product"),
       ("title too short", draft(title="Quilt"), "too_short"),
       ("discount claim", draft(description=draft()["description"] + " Now 20% off for a limited time."), "unsupported_claim"),
       ("shipping promise", draft(description=draft()["description"] + " Free shipping included."), "unsupported_claim"),
       ("pick-up promise", draft(description=draft()["description"] + " Available for pick up in Dallas."), "unsupported_claim"),
       ("popularity claim", draft(description=draft()["description"] + " A bestselling favourite."), "unsupported_claim"),
       ("certification claim", draft(description=draft()["description"] + " Organic and hypoallergenic."), "unsupported_claim"),
       ("wrong price", draft(description=draft()["description"] + " Only $79."), "unsupported_claim"),
       ("wrong size", draft(title="Cloud Weave Quilted Coverlet, King, Oatmeal"), "unsupported_claim"),
       ("unsupplied material", draft(description=draft()["description"] + " Soft linen blend."), "unsupported_claim"),
       ("no rationale", draft(rationale=[]), "bad_rationale"),
       ("rationale without any reference", draft(rationale=[{"claim": "A claim that cites nothing at all."}]), "bad_rationale"),
       ("unknown listing id", draft(rationale=[{"claim": "Cites a listing that was never recorded.", "listing_ids": ["999"]}]), "unknown_listing"),
       ("image cited but not observed", draft(rationale=[{"claim": "Cites an image with no observation entry.", "listing_ids": ["1638806271151287"], "image_ids": ["918521891138262"]}]), "image_not_observed"),
       ("observation for an image never inspected", draft(image_observations=[{"image_id": "918521891138262", "observations": "I think it is dark grey curtains."}]), "image_not_inspected"),
       ("competitor sales claim", draft(rationale=[{"claim": "This listing has sold quickly so demand is high.", "listing_ids": ["1638806271151287"]}]), "unsupported_claim")]
got = {label: err_code(listing.save_draft(A, d)) for label, d, _ in bad}
check("B1 invalid or unsupported drafts are rejected with the right corrective code, and nothing is stored",
      all(got[label] == want for label, _, want in bad) and listing.list_drafts() == [], {k: (v, w) for (k, _, w), v in zip(bad, got.values()) if v != w})
check("B2 the declared price and supplied size/material are accepted when stated correctly",
      err_code(listing.save_draft(A, draft(description=draft()["description"] + " Priced at $89.00."))) == "OK")
listing_count = len(listing.list_drafts())
r = listing.save_draft(A, {**draft(), "agent_id": "evil-agent", "status": "complete", "source_url": "https://evil.example", "merchant_snapshot": {"price": 1}})
dr = listing.get_draft(r["draft_id"])
check("B3 identity and provenance are backend-derived: model-supplied agent_id/status/source_url/snapshot are ignored",
      r["ok"] and r["status"] == "complete" and dr["agent_id"] == A and dr["product_snapshot"]["price"]["amount"] == 89.0 and dr["merchant_snapshot"]["demo"] is True
      and dr["listing_evidence"][0]["source_url"] == d1["source_url"] and "evil" not in json.dumps(dr), dr)
img = dr["image_evidence"][0]
check("B4 evidence stored: listing snapshot (URL, retrieval time, evidence file hash), image hash/size/inspection time/model observations, kind",
      dr["listing_evidence"][0]["retrieved_at"] == d1["retrieved_at"] and len(dr["listing_evidence"][0]["evidence_sha256"]) == 64
      and img["kind"] == "recorded_listing_photo" and img["listing_id"] == "1638806271151287" and img["sha256"] == core.prepare_image("1638806271151287")["sha256"]
      and img["width"] == 200 and img["inspected_at"] and "coral" in img["model_observations"], img)
check("B4b the inspected file's hash equals the hash recorded for that listing's photo -> provenance hash_match, and the recorded hash is kept in the snapshot",
      img["matches_recorded_photo_hash"] is True and img.get("provenance") == "hash_match" and img.get("recorded_sha256") == img["sha256"], img)
check("B5 a second specialist cannot cite the first one's inspections (image_not_inspected)", err_code(listing.save_draft(B, draft())) == "image_not_inspected")
r2 = listing.save_draft(B, draft(rationale=[{"claim": "A search-only listing shows an asking price for a comparable set.", "listing_ids": ["955699870493854"]}], image_observations=[]))
check("B6 only a search-only listing and no inspected photo -> saved as PARTIAL with the reasons, never as complete",
      r2["ok"] and r2["status"] == "partial" and len(r2["missing"]) == 2, r2)
before = json.dumps(listing.get_draft(r["draft_id"]))
cat2 = json.loads((FIX / "demo_catalogue.json").read_text(encoding="utf-8"))
cat2["products"][0]["price"]["amount"] = 99.0
(TMP / "cat_changed.json").write_text(json.dumps(cat2), encoding="utf-8")
os.environ["ECOM_CATALOGUE_FILE"] = str(TMP / "cat_changed.json")
check("B7 saved snapshots do not change when the catalogue changes later", json.dumps(listing.get_draft(r["draft_id"])) == before and listing.get_draft(r["draft_id"])["product_snapshot"]["price"]["amount"] == 89.0)
os.environ["ECOM_CATALOGUE_FILE"] = str(FIX / "demo_catalogue.json")
check("B8 list/get: summaries per agent, unknown id -> None", [x["draft_id"] for x in listing.list_drafts(B)] == [r2["draft_id"]] and listing.get_draft("draft-nope") is None
      and "description" not in listing.list_drafts()[0])
n0 = len(listing.list_drafts())
db_rows = core.db().execute("SELECT COUNT(*) FROM image_inspections").fetchone()[0]
env = hp._inspect_image({"image_id": "918521891138262"})
rows = core.db().execute("SELECT agent_id, image_id, kind, sha256 FROM image_inspections ORDER BY id DESC LIMIT 1").fetchone()
check("B9 the inspect_image tool writes the trusted inspection log (agent from the worker env, hash from the pixels)",
      env["_multimodal"] and core.db().execute("SELECT COUNT(*) FROM image_inspections").fetchone()[0] == db_rows + 1 and rows["image_id"] == "918521891138262"
      and rows["kind"] == "recorded_listing_photo" and rows["sha256"] == core.prepare_image("918521891138262")["sha256"], dict(rows))
os.environ["ECOM_AGENT_ID"] = "env-agent"
out = json.loads(hp._save_draft(draft(image_observations=[{"image_id": "1638806271151287", "observations": "Sealed bag, coral and beige."}])))
check("B10 the save tool takes the agent identity from ECOM_AGENT_ID, not from arguments (env-agent has no inspections -> image_not_inspected)",
      out["code"] == "image_not_inspected", out)
os.environ.pop("ECOM_AGENT_ID")
check("B11 tool handlers return JSON strings and never raise on junk",
      all(isinstance(f(x), str) for f in (hp._read_catalogue, hp._read_evidence, hp._save_draft) for x in (None, {}, "x", {"limit": "abc"}, {"rationale": 5})))

# ================= D. ticket04 review corrections =================
prod = listing.read_catalogue(PID)["products"][0]
n_drafts = lambda: len(listing.list_drafts())

# --- D1/D2: photo provenance
os.environ["ECOM_EVIDENCE_FILE"] = str(EV_REAL)           # the REAL recorded hash (76ccd17f...) for 1638806271151287; the inspected stand-in differs
n0 = n_drafts()
r = listing.save_draft(A, draft())
check("D1 a cited photo whose file hash differs from the hash recorded for that listing is REJECTED with a clear provenance error; nothing is saved",
      err_code(r) == "image_provenance_mismatch" and "1638806271151287" in r.get("error", "") and "76ccd17f" in r.get("error", "") and n_drafts() == n0, r)
r = listing.save_draft(A, draft(rationale=[{"claim": "A search-only listing shows an asking price for a comparable set.", "listing_ids": ["955699870493854"]}], image_observations=[]))
check("D1b a mismatched file is only a problem when it is CITED: a draft that cites no photo still saves (partial)", r.get("ok") and r["status"] == "partial", r)
os.environ["ECOM_EVIDENCE_FILE"] = str(EV_NOHASH)
r = listing.save_draft(A, draft())
im = (listing.get_draft(r["draft_id"])["image_evidence"] or [{}])[0] if r.get("ok") else {}
check("D2 no recorded hash for the cited photo: saved PARTIAL, provenance 'no_recorded_hash', matches_recorded_photo_hash None (distinct from a match, never faked)",
      r.get("ok") and r["status"] == "partial" and im.get("provenance") == "no_recorded_hash" and im.get("matches_recorded_photo_hash") is None
      and any("hash" in m for m in r["missing"]), (r, im))
os.environ["ECOM_EVIDENCE_FILE"] = str(EV_TRUE)
r = listing.save_draft(A, draft())
check("D2b the same draft against the truthful recorded hash is COMPLETE", r.get("ok") and r["status"] == "complete" and r["missing"] == [], r)

# --- D3: honest vision status (preparation is not delivery)
for ag in ("d-text", "d-unknown", "d-old", "d-mix"):
    register(ag)
inspect("d-text", "1638806271151287", delivery="text_fallback")
inspect("d-unknown", "1638806271151287", delivery="unknown")
with core.db() as d:   # a row written before the correction: no delivery column value at all
    d.execute("INSERT INTO image_inspections(agent_id, image_id, kind, sha256, width, height, ts) VALUES(?,?,?,?,?,?,?)",
              ("d-old", "1638806271151287", "recorded_listing_photo", core.prepare_image("1638806271151287")["sha256"], 200, 160, time.time()))
inspect("d-mix", "1638806271151287")
inspect("d-mix", "demo-quilt-front", delivery="text_fallback")
for ag, want in (("d-text", "text_fallback"), ("d-unknown", "unknown"), ("d-old", "unknown")):
    r = listing.save_draft(ag, draft())
    im = (listing.get_draft(r["draft_id"])["image_evidence"] or [{}])[0] if r.get("ok") else {}
    check(f"D3 [{ag}] delivery {want}: observation text is stored but the draft is PARTIAL, names the image, and the snapshot is explicit it is not verified evidence",
          r.get("ok") and r["status"] == "partial" and any("1638806271151287" in m for m in r["missing"]) and im.get("delivery") == want
          and im.get("counts_as_verified_evidence") is False and im.get("model_observations"), (r, im))
r = listing.save_draft("d-mix", draft(rationale=draft()["rationale"] + [{"claim": "The merchant's own illustration shows an oatmeal diamond-grid coverlet.", "image_ids": ["demo-quilt-front"]}],
                                      image_observations=draft()["image_observations"] + [{"image_id": "demo-quilt-front", "observations": "Oatmeal panel with a diamond grid and demo captions."}]))
check("D3b one verified competitor photo does not hide another cited image whose pixels were never delivered: PARTIAL naming demo-quilt-front",
      r.get("ok") and r["status"] == "partial" and any("demo-quilt-front" in m for m in r["missing"]) and not any("1638806271151287" in m for m in r["missing"]), r)
r = listing.save_draft(A, draft())
check("D3c a verified delivery (image_part_sent) with a matching hash still completes the draft (unchanged valid save)", r.get("ok") and r["status"] == "complete", r)
register("d-kind")
os.environ["ECOM_EVIDENCE_FILE"] = str(TMP / "evidence_not_there_yet.json")     # inspected while no evidence file was configured -> logged with kind 'other'
inspect("d-kind", "1638806271151287")
kind_logged = core.db().execute("SELECT kind FROM image_inspections WHERE agent_id='d-kind'").fetchone()["kind"]
os.environ["ECOM_EVIDENCE_FILE"] = str(EV_REAL)
r = listing.save_draft("d-kind", draft())
os.environ["ECOM_EVIDENCE_FILE"] = str(EV_TRUE)
r2 = listing.save_draft("d-kind", draft())
check("D3e the evidence in force at save time decides provenance, not the kind logged at inspection: a listing photo logged as 'other' is still hash-checked",
      kind_logged == "other" and err_code(r) == "image_provenance_mismatch" and r2.get("ok") and r2["status"] == "complete"
      and listing.get_draft(r2["draft_id"])["image_evidence"][0]["kind"] == "recorded_listing_photo", (kind_logged, r, r2))
oldp = TMP / "old.db"
c0 = sqlite3.connect(oldp)
c0.executescript("CREATE TABLE image_inspections(id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id TEXT, image_id TEXT, kind TEXT, sha256 TEXT, width INTEGER, height INTEGER, ts REAL);"
                 "INSERT INTO image_inspections(agent_id,image_id,kind,sha256,width,height,ts) VALUES('old-agent','1638806271151287','recorded_listing_photo','abc',10,10,1.0);")
c0.commit(); c0.close()
real_db = core.DB_PATH
core.DB_PATH = oldp
try:
    dd = core.db()
    cols = [x[1] for x in dd.execute("PRAGMA table_info(image_inspections)")]
    row = dd.execute("SELECT * FROM image_inspections").fetchone()
    dd.close()
    mig = "delivery" in cols and row["image_id"] == "1638806271151287" and row["sha256"] == "abc" and row["delivery"] is None
finally:
    core.DB_PATH = real_db
check("D3d the schema change is additive: an existing database keeps its inspection rows and gains a NULL delivery column (read as unknown)", mig)

# --- D4: price and currency
def cp(text, p=prod, where="description"):
    return listing.copy_problem(text, p, where)


USD_OK = ["Price: $89 USD.", "Price: 89 USD.", "Price: USD 89.00", "Priced at US$89.", "Price: $89.00.", "Price: 89.", "Costs 89 dollars.", "Price: $89 each.", "Only $89.00 for the coverlet."]
USD_BAD = ["Price: 79 USD.", "Price: $89 EUR.", "Price: \u20ac89.", "Price: 89 EUR.", "Price: EUR 89.", "Price: \u00a389.", "Price: 79.", "Price: 79 dollars.",
           "Price: \u20b989.", "Priced at $79.00.", "Price: USD 90.", "Price: $1,089.", "Price: 89 GBP."]
NOT_PRICE = ["Measures 90 x 96 in.", "Comes as 1 coverlet.", "100% cotton shell with polyester fill.", "Supplied with 2 care labels and a 4 inch quilting grid.",
             "Wash at 30 degrees.", "Fits a 15 in deep mattress.", "Made in 2026 in 1 piece, 96 in long."]
bad_ok = [t for t in USD_OK if cp(t)]
bad_bad = [t for t in USD_BAD if not cp(t)]
bad_np = [t for t in NOT_PRICE if cp(t)]
check("D4 USD catalogue (89 USD): correct amount/currency forms are accepted (symbol, code before and after, words, bare 'Price: 89')", not bad_ok, bad_ok)
check("D4b ... wrong amounts and wrong currencies are rejected (79 USD, $89 EUR, EUR 89, 89 GBP, bare 'Price: 79', symbols \u20ac \u00a3 \u20b9)", not bad_bad, bad_bad)
check("D4c ... dimensions, quantities, percentages, temperatures and years are NOT read as prices", not bad_np, [(t, cp(t)) for t in bad_np])
r = listing.save_draft(A, draft(description=draft()["description"] + " Price: 79 USD."))
r2 = listing.save_draft(A, draft(description=draft()["description"] + " Price: $89 EUR."))
check("D4d the two reviewer examples are refused through save_draft with a corrective unsupported_claim error naming the declared price and currency",
      err_code(r) == "unsupported_claim" and err_code(r2) == "unsupported_claim" and "89" in r["error"] and "USD" in r["error"] and "EUR" in r2["error"], (r, r2))

# a DIFFERENT merchant/product with a non-USD currency, supplied only through configuration (no application-code edits)
eur = {"schema": 1, "demo": True, "notice": "FICTIONAL DEMO DATA: invented for tests.",
       "merchant": {"merchant_id": "demo-nordlys", "name": "Nordlys Textil (fictional demo merchant)"},
       "products": [{"product_id": "nordlys-linen-curtain-140", "name": "Nordlys Linen Curtain Panel, 140 x 250 cm", "category": "curtains", "condition": "new",
                     "specifications": {"size": "140 x 250 cm", "colour": "Natural", "material": "100% linen", "care": "Wash at 40 C", "pieces": "1 panel"},
                     "price": {"amount": 49.9, "currency": "EUR"},
                     "image": {"image_id": "nordlys-curtain-front", "kind": "synthetic illustration of the fictional product (not a photograph)"}}]}
(TMP / "cat_eur.json").write_text(json.dumps(eur), encoding="utf-8")
os.environ["ECOM_CATALOGUE_FILE"] = str(TMP / "cat_eur.json")
core.update_company({"name": "Nordlys Textil"}, source="form")     # the other merchant's own company (a catalogue is only supplied to its owner)
EP = "nordlys-linen-curtain-140"
base = ("A natural curtain panel in 100% linen measuring 140 x 250 cm, supplied as a single panel and washable at 40 C.")


def edraft(extra):
    return draft(product_id=EP, title="Nordlys Linen Curtain Panel, 140 x 250 cm", description=base + " " + extra,
                 visual_brief="Hang the panel at full length against a plain wall in daylight, add a close-up of the weave and one shot of the top edge so the heading is visible.")


EUR_OK = ["Price: \u20ac49.90.", "Price: 49,90 \u20ac.", "Price: EUR 49.90.", "Price: 49.90 EUR.", "Price: 49.9 euros.", "Price: 49.90."]
EUR_BAD = ["Price: $49.90.", "Price: 49.90 USD.", "Price: \u20ac59.90.", "Price: 49 EUR.", "Price: 49,90 USD.", "Price: \u00a349.90.", "Price: 89 EUR."]
res_ok = {t: err_code(listing.save_draft(A, edraft(t))) for t in EUR_OK}
res_bad = {t: err_code(listing.save_draft(A, edraft(t))) for t in EUR_BAD}
cat_tool = json.loads(hp._read_catalogue({"product_id": EP}))
check("D4e a second merchant/product (EUR 49.90, other product ID) works from configuration alone: catalogue read and correct price forms save",
      cat_tool["ok"] and cat_tool["merchant"]["merchant_id"] == "demo-nordlys" and cat_tool["products"][0]["price"]["currency"] == "EUR"
      and all(v == "OK" for v in res_ok.values()), (res_ok, cat_tool.get("code")))
check("D4f ... and wrong amount or wrong currency is rejected for it ($49.90, 49.90 USD, \u20ac59.90, 49 EUR, \u00a349.90, 89 EUR)", all(v == "unsupported_claim" for v in res_bad.values()), res_bad)
os.environ["ECOM_CATALOGUE_FILE"] = str(FIX / "demo_catalogue.json")
core.update_company({"name": "Acme Linens"}, source="form")

# --- D5: durable supporting evidence
src = next(l for l in json.loads(EV_REAL.read_text(encoding="utf-8"))["listings"] if l["listing_id"] == "1638806271151287")
exposed = listing.read_recorded_evidence(listing_id="1638806271151287")["listing"]
r = listing.save_draft(A, draft())
saved = listing.get_draft(r["draft_id"])
sup = (saved["listing_evidence"][0].get("supporting") or {}) if saved["listing_evidence"] else {}
photos = sup.get("photos") or []
check("D5 the cited listing's recorded description and photo references are stored with the draft: same content that was exposed to the specialist",
      sup.get("description") == src["description"] and sup.get("description") == exposed.get("description") and sup.get("photo_count") == len(src["photos"])
      and [p.get("photo_id") for p in photos] == [p["id"] for p in src["photos"]] and photos == exposed.get("photos")
      and all(set(p) == {"photo_id", "width", "height", "caption"} for p in photos), (sup, exposed.get("photos")))
blob = json.dumps(saved)
check("D5b ... and no manual review notes, no unrelated raw payload (seller fields, coordinates, attributes) and no secrets are persisted",
      not any(w in blob for w in ("manual_review", "manual_visual", "heuristic_textile_terms", "latitude", "marketplace_user_profile", "profile_picture", "attributes"))
      and "codex" not in blob.lower() and "api_key" not in blob.lower(), blob[:300])
os.environ["ECOM_EVIDENCE_FILE"] = str(TMP / "evidence_removed.json")
check("D5c after the configured evidence input is removed the saved draft (incl. description/photo references) is retrieved unchanged, with no evidence file",
      listing.get_draft(r["draft_id"]) == saved and err_code(listing.read_recorded_evidence()) == "evidence_missing")
chg = json.loads(EV_TRUE.read_text(encoding="utf-8"))
for l in chg["listings"]:
    if l["listing_id"] == "1638806271151287":
        l["description"] = "CHANGED LATER"; l["photos"] = []
(TMP / "ev_changed.json").write_text(json.dumps(chg), encoding="utf-8")
os.environ["ECOM_EVIDENCE_FILE"] = str(TMP / "ev_changed.json")
check("D5d ... and unchanged when the evidence input is replaced by a different one", listing.get_draft(r["draft_id"]) == saved)
os.environ["ECOM_EVIDENCE_FILE"] = str(EV_TRUE)

shutil.rmtree(IMGS, ignore_errors=True)


# ================= C. scripted plumbing through the real server + workers =================
def call(path, body=None, port=APP):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=600); return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def tool(agent, name, args):
    st, r = call(f"/api/chat/{agent}", {"message": "CALL_TOOL:" + json.dumps({"name": name, "args": args})})
    outs = [t for t in r.get("tools", []) if t.get("name") == name and t.get("output")]
    return (outs[0]["output"] if outs else None), r


def start_server(env):
    p = subprocess.Popen([sys.executable, "-m", "app.server", str(APP)], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(p)
    for _ in range(80):
        try: call("/api/status"); return p
        except Exception: time.sleep(0.5)
    raise RuntimeError("server did not start")


try:
    ENV = {**os.environ, "PYTHONUTF8": "1", "ECOM_CLASSIFIER": "off"}
    for k in ("LLM_PROVIDER", "LLM_MODEL", "NEBIUS_API_KEY", "NEBIUS_BASE_URL", "NEBIUS_MODEL", "ECOM_APP_ROOT", "ECOM_CATALOGUE_FILE", "ECOM_EVIDENCE_FILE", "ECOM_IMAGE_DIRS"):
        ENV.pop(k, None)
    shutil.rmtree(ROOT / "runtime", ignore_errors=True)
    IMG = ROOT / "runtime" / "img_controls"
    IMG.mkdir(parents=True)
    ENV["ECOM_IMAGE_DIRS"] = str(IMG)
    Image.new("RGB", (200, 160), (200, 90, 60)).save(IMG / "1638806271151287.png")
    ENV["ECOM_EVIDENCE_FILE"] = str(truthful_evidence("ev_c.json", IMG))      # recorded hash = the control image's true hash
    (ROOT / "secrets").mkdir(exist_ok=True)
    (ROOT / "secrets" / "local.env").write_text(f"LLM_PROVIDER=nebius-token-factory\nLLM_MODEL=mock-model\nNEBIUS_API_KEY=mock-key\nNEBIUS_BASE_URL=http://127.0.0.1:{MOCK}/v1\n", encoding="utf-8")
    subprocess.run([sys.executable, "scripts/setup.py"], cwd=ROOT, env=ENV, check=True, capture_output=True)
    procs.append(subprocess.Popen([sys.executable, "tests/mock_llm.py", str(MOCK)], cwd=ROOT, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(1)
    srv = start_server(ENV)
    stats = lambda: call("/stats", port=MOCK)[1]
    st, r = call("/api/company", {"fields": {"name": "Acme Linens", "products": "Cotton bedding", "customers": "Home buyers in the US", "goal": "Better listing photos"}})
    BASE = {"role": "market_analysis", "objective": "Help Acme Linens turn recorded Marketplace evidence into one accurate, source-linked listing draft per product.",
            "instructions": "You write listing drafts for Acme Linens from catalogue facts and recorded evidence. Never invent specifications, discounts or delivery terms.",
            "skills": [{"name": "listing-draft-review", "content": "# Listing draft review\n1. Read the catalogue.\n2. Choose comparable listings yourself.\n3. Inspect photos and cite only what you used."}]}
    LISTING = ["inspect_image", "read_catalogue", "read_recorded_evidence", "save_listing_draft"]
    out, r = tool("main", "create_agent", {**BASE, "name": "Draft Analyst", "requested_tools": LISTING})
    o = json.loads(out)
    aid = o["agent_id"]
    check("C1 main provisions the four listing tools through requested_tools; response and registry agree and mandatory tools remain",
          o["ok"] and sorted(o["granted_tools"]) == sorted(LISTING + ["memory", "read_company_context", "skills"])
          and sorted(call(f"/api/agents/{aid}")[1]["granted_tools"]) == sorted(o["granted_tools"]), o)
    out2, r2 = tool("main", "create_agent", {**BASE, "name": "Plain Analyst", "requested_tools": []})
    pid = json.loads(out2)["agent_id"]
    outs = [tool(pid, n, {})[1]["text"] for n in ("read_catalogue", "read_recorded_evidence", "save_listing_draft")]
    check("C2 a specialist WITHOUT the grants cannot see or call any listing tool", all("not available" in t for t in outs), outs)
    check("C3 main has none of the listing tools", all("not available" in tool("main", n, {})[1]["text"] for n in ("read_catalogue", "read_recorded_evidence", "save_listing_draft")))
    st, r = call(f"/api/chat/{aid}", {"message": "hi"})
    check("C4 the granted specialist still cannot create agents or update the company", all(n not in r["text"] for n in ("create_agent", "update_company")) and "save_listing_draft" in r["text"], r["text"])
    o_cat, _ = tool(aid, "read_catalogue", {"product_id": PID})
    o_ev, _ = tool(aid, "read_recorded_evidence", {"cached_images_only": True})
    check("C5 catalogue and recorded-evidence tools work through the worker with the demo files",
          json.loads(o_cat)["products"][0]["price"]["amount"] == 89.0 and [x["listing_id"] for x in json.loads(o_ev)["listings"]] == ["1638806271151287"], (o_cat[:200], o_ev[:200]))
    o_s, _ = tool(aid, "save_listing_draft", draft())
    check("C6 saving before inspecting the photo is refused with image_not_inspected (no draft)", json.loads(o_s)["code"] == "image_not_inspected" and call("/api/drafts")[1] == [])
    def sdb(q, *a):   # the isolated app's own database (read-only use)
        c = sqlite3.connect(ROOT / "runtime" / "app.db")
        c.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in c.execute(q, a)]
        finally:
            c.close()
    # --- phase 1: the model is NOT declared vision-capable -> Hermes sends a text summary only
    o_i, ri = tool(aid, "inspect_image", {"image_id": "1638806271151287"})
    rows = [r for r in sdb("SELECT * FROM image_inspections WHERE agent_id=? ORDER BY id", aid)]
    o_s, rs = tool(aid, "save_listing_draft", draft())
    sv1 = json.loads(o_s)
    check("C7 text fallback (model not declared vision-capable): no image reaches the model, the inspection is logged text_fallback and a draft built on it is PARTIAL",
          "images_in_request=0" in ri["text"] and stats()["image_requests"] == 0 and rows and rows[-1]["delivery"] == "text_fallback"
          and sv1["ok"] and sv1["status"] == "partial" and any("1638806271151287" in m for m in sv1["missing"]), (ri["text"][:200], rows, sv1))
    # --- phase 2: the per-model vision declaration (what profile_config() writes for a verified model): supported path
    srv.terminate(); srv.wait()
    srv = start_server({**ENV, "ECOM_VISION_MODELS": "nebius-token-factory:mock-model"})
    o_i, ri = tool(aid, "inspect_image", {"image_id": "1638806271151287"})
    ims = stats()["last_images"]
    rows = sdb("SELECT * FROM image_inspections WHERE agent_id=? ORDER BY id", aid)
    o_s, rs = tool(aid, "save_listing_draft", draft())
    saved = json.loads(o_s)
    check("C7b supported path: the image part reaches the model request, the inspection is logged image_part_sent and the draft is COMPLETE; identity from the worker",
          "images_in_request=1" in ri["text"] and ims and rows[-1]["delivery"] == "image_part_sent" and saved["ok"] and saved["status"] == "complete"
          and saved["draft_id"].startswith("draft-"), (ri["text"][:200], rows[-1], saved))
    did = saved["draft_id"]
    st, full = call(f"/api/drafts/{did}")
    check("C8 read API returns the draft with snapshots, supporting evidence and delivery status; list filters by agent",
          st == 200 and full["agent_id"] == aid and full["product_snapshot"]["price"]["currency"] == "USD" and full["listing_evidence"][0]["source_url"]
          and full["listing_evidence"][0]["supporting"]["description"] and full["image_evidence"][0]["sha256"] and full["image_evidence"][0]["delivery"] == "image_part_sent"
          and [x["draft_id"] for x in call(f"/api/drafts?agent_id={aid}")[1]] == [sv1["draft_id"], did] and call(f"/api/drafts?agent_id={pid}")[1] == [], full)
    ct = [a for a in call(f"/api/chat/{aid}")[1] if a.get("activity")]
    labels = {x["label"] for a in ct for x in a["activity"]}
    check("C9 existing Activity rendering gets readable labels for the new tools", {"Reading the catalogue", "Saving a listing draft", "Looking at an image"} <= labels, labels)
    mem = "".join(f.read_text(encoding="utf-8") for f in (ROOT / "runtime" / "hermes_home" / "profiles" / aid / "memories").glob("*.md")) if (ROOT / "runtime" / "hermes_home" / "profiles" / aid / "memories").exists() else ""
    check("C10 research records are in app.db, not in the specialist's memory", did not in mem and "1638806271151287" not in mem)
    # --- phase 3: the recorded evidence is the REAL sample, whose photo hash is not the cached file's: provenance mismatch through the tool
    srv.terminate(); srv.wait()
    srv = start_server({**ENV, "ECOM_VISION_MODELS": "nebius-token-factory:mock-model", "ECOM_EVIDENCE_FILE": str(EV_REAL)})
    tool(aid, "inspect_image", {"image_id": "1638806271151287"})
    o_s, _ = tool(aid, "save_listing_draft", draft())
    bad = json.loads(o_s)
    check("C13 through the worker tool: a cached file that is not the recorded photo is refused with image_provenance_mismatch and nothing is saved",
          bad["code"] == "image_provenance_mismatch" and len(call("/api/drafts")[1]) == 2, bad)
    # --- phase 4: the configured evidence input is REMOVED and the app restarted
    srv.terminate(); srv.wait()
    srv = start_server({**ENV, "ECOM_VISION_MODELS": "nebius-token-factory:mock-model", "ECOM_EVIDENCE_FILE": str(TMP / "evidence_removed.json")})
    time.sleep(4)                                   # let any background model request from the last turn (Hermes bookkeeping) land first
    n_req = stats()["requests"]
    st, again = call(f"/api/drafts/{did}")
    lst = call("/api/drafts")[1]
    lst2 = call(f"/api/drafts?agent_id={aid}")[1]
    check("C11 after a restart WITHOUT the evidence file the draft, its supporting description/photo references and the list are retrieved unchanged; ZERO model requests (no scraper exists in this path)",
          st == 200 and again == full and again["listing_evidence"][0]["supporting"]["description"] and [x["draft_id"] for x in lst] == [sv1["draft_id"], did]
          and [x["draft_id"] for x in lst2] == [sv1["draft_id"], did] and stats()["requests"] == n_req, (st, stats()["requests"], n_req))
    o_ev, _ = tool(aid, "read_recorded_evidence", {})
    check("C11b ... while the tool itself reports the missing input explicitly (evidence_missing), so the retrieval above really did not depend on it", json.loads(o_ev)["code"] == "evidence_missing", o_ev[:200])
    check("C12 unknown draft -> 404 with a structured error", call("/api/drafts/draft-nope")[0] == 404)
finally:
    for p in procs:
        p.terminate()
    shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{sum(results)}/{len(results)} checks passed (parts A/B pure backend; part C scripted plumbing, NOT a vision or reasoning test)")
sys.exit(0 if results and all(results) else 1)
