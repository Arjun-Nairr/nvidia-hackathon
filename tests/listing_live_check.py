"""LIVE end-to-end demonstration for ticket 04 on the development subscription provider (openai-codex). ONE manual request through the existing
specialist chat endpoint of a real server + real Hermes worker: the specialist reads the fictional demo catalogue and the RECORDED Marketplace
evidence, chooses comparisons, inspects cached photos with inspect_image and saves one draft. Then the server is restarted and the draft is
read back through the read API with no model request. No scraping, no CDN downloads, no Nebius.
Runs ONLY in an isolated copy (login token life must be >= 20 min so the copy cannot trigger a single-use refresh):
  LISTING_LIVE_I_AM_A_COPY=1 venv-python tests/listing_live_check.py"""
import base64, json, os, subprocess, sys, time, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if os.environ.get("LISTING_LIVE_I_AM_A_COPY") != "1":
    sys.exit("Refusing to run: copy of the project only (LISTING_LIVE_I_AM_A_COPY=1).")
sys.path.insert(0, str(ROOT))
os.environ["ECOM_TIMING"] = "1"
os.environ["HERMES_HOME"] = str(ROOT / "runtime" / "hermes_home" / "profiles" / "main")   # Hermes resolves profile locations from this: keep it project-local
from app import core
assert str(core.HERMES_ROOT).startswith(str(ROOT)), "isolated copy required"

PORT, results = 8831, []
OUT = ROOT / "listing_live_result.json"


def check(name, ok, detail=""):
    ok = bool(ok); results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{str(detail)[:600]}]"), flush=True)


def token_life_seconds():
    best = None

    def walk(o):
        nonlocal best
        if isinstance(o, dict):
            for v in o.values(): walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)
        elif isinstance(o, str) and o.count(".") == 2:
            try:
                pay = json.loads(base64.urlsafe_b64decode(o.split(".")[1] + "=" * (-len(o.split(".")[1]) % 4)))
                if "exp" in pay:
                    life = pay["exp"] - time.time(); best = life if best is None else min(best, life)
            except Exception:
                pass
    walk(json.loads((core.HERMES_ROOT / "auth.json").read_text(encoding="utf-8")))
    return best


def api(path, body=None, timeout=900):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def start():
    p = subprocess.Popen([sys.executable, "-m", "app.server", str(PORT)], cwd=ROOT, env={**os.environ, "PYTHONUTF8": "1"}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(120):
        try:
            api("/api/status", timeout=5); return p
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("server did not start")


cfg, problem, life = core.llm_config(), core.llm_problem(), token_life_seconds()
print(f"provider {cfg['provider']} model {cfg['model']} | login token life: {None if life is None else round(life / 60)} min | problem: {problem}")
if problem or life is None or life < 20 * 60 or cfg["provider"] != "openai-codex":
    sys.exit("NOT RUN: " + (problem or "login token life too short/unknown, or provider is not the subscription provider"))
cached = sorted(p.stem for p in (ROOT / "runtime" / "marketplace_check" / "images").glob("*.jpg"))
print("cached private photos available:", cached)

core.update_company({"name": "Acme Linens (fictional demo)", "products": "Cotton bedding and curtains", "customers": "Home buyers in the US",
                     "goal": "Understand how competing bedding listings are presented and draft better listings"}, source="form")
LISTING = ["inspect_image", "read_catalogue", "read_recorded_evidence", "save_listing_draft"]
r = core.create_agent({"role": "market_analysis", "name": "Listing Draft Analyst",
                       "objective": "Turn the merchant's supplied catalogue facts and recorded Marketplace evidence into one accurate, source-linked listing draft per product.",
                       "instructions": "You write listing drafts for Acme Linens (a fictional demo merchant). Read the catalogue, choose the comparable recorded listings yourself, "
                                       "inspect their photos where cached, and save one draft. Use only supplied product facts; never invent specifications, discounts, delivery "
                                       "terms, performance or competitor-sales claims. Say what you could not verify.",
                       "skills": [{"name": "listing-draft-routine", "content": "# Listing draft routine\n1. Read the catalogue product and note which facts are supplied.\n"
                                                                          "2. Search the recorded evidence; judge relevance yourself (new bedding of similar type).\n"
                                                                          "3. Inspect photos of the comparables you rely on.\n4. Draft title, description, visual brief and a rationale citing listing and image IDs.\n"
                                                                          "5. Save with save_listing_draft and report the draft ID plus limits."}],
                       "requested_tools": LISTING})
check("specialist created; listing tools granted with the mandatory tools", r.get("ok") and set(LISTING) <= set(r["granted_tools"]), r)
aid = r["agent_id"]

srv = start()
t0 = time.time()
MSG = ("Please create one Marketplace listing draft for our product acme-cloud-quilt-queen. Use the recorded Marketplace evidence, pick the most comparable "
       "listings yourself, look at their photos where you can, and save the draft. Tell me the draft ID and anything you could not verify.")
st, resp = api(f"/api/chat/{aid}", {"message": MSG})
wall = round(time.time() - t0, 1)
print(f"\n--- chat reply ({wall}s, ok={resp.get('ok')}) ---\n{resp.get('text')}\n")
acts = resp.get("activity") or []
print("activity:", [(a["tool"], a["status"]) for a in acts])
tl = [json.loads(l) for l in (ROOT / "runtime" / "timing.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()] if (ROOT / "runtime" / "timing.jsonl").exists() else []
chat_t = [x for x in tl if x.get("kind") == "chat" and x.get("agent") == aid]
n_api = sum(x.get("api_calls", 0) for x in chat_t)
saves = [a for a in acts if a["tool"] == "save_listing_draft"]
def _j(x):
    try:
        v = json.loads(x)
        return v if isinstance(v, dict) else {}
    except (TypeError, ValueError):
        return {}


saved_ok = [o for o in (_j(a.get("output")) for a in saves) if o.get("ok") is True]
inspected = [json.loads(a["input"]).get("image_id") if isinstance(a.get("input"), str) else (a.get("input") or {}).get("image_id") for a in acts if a["tool"] == "inspect_image"]
check("chat request succeeded through the existing specialist chat endpoint", st == 200 and resp.get("ok"), (st, resp.get("error")))
check("the specialist saved a draft through save_listing_draft", bool(saved_ok), [a.get("output", "")[:200] for a in saves])
check("it read the catalogue and the recorded evidence itself", {"read_catalogue", "read_recorded_evidence"} <= {a["tool"] for a in acts}, [a["tool"] for a in acts])
check("it inspected at least one cached listing photo with inspect_image (real pixels)", any(i in cached for i in inspected), inspected)
draft = None
if saved_ok:
    did = saved_ok[-1]["draft_id"]
    st2, draft = api(f"/api/drafts/{did}")
    check("saved draft retrievable through the read API with product snapshot and evidence",
          st2 == 200 and draft["product_snapshot"]["price"] == {"amount": 89.0, "currency": "USD"} and draft["listing_evidence"] and draft["image_evidence"], draft)
    check("draft status complete (detailed listing and an inspected competitor photo cited); every cited image was delivered as an image part to a supported vision path",
          draft["status"] == "complete" and all(i.get("delivery") == "image_part_sent" for i in draft["image_evidence"]), draft.get("missing"))
    check("every cited image is a real inspected photo with a hash; every cited listing has a Facebook source URL and retrieval time",
          all(i.get("sha256") and i.get("model_observations") for i in draft["image_evidence"])
          and all("facebook.com/marketplace/item/" in (l.get("source_url") or "") and l.get("retrieved_at") for l in draft["listing_evidence"]), draft["listing_evidence"])
    print("\n=== SAVED DRAFT", did, "===")
    print("TITLE:", draft["title"])
    print("DESCRIPTION:", draft["description"])
    print("VISUAL BRIEF:", draft["visual_brief"])
    for x in draft["rationale"]:
        print("RATIONALE:", x["claim"], "| listings", x["listing_ids"], "| images", x["image_ids"])
    for i in draft["image_evidence"]:
        print("IMAGE", i["image_id"], i["kind"], i["sha256"][:12], "|", i["model_observations"], "| unsure:", i["model_uncertainties"])
    print("LIMITATIONS:", draft["limitations"], "| MISSING:", draft["missing"])
    srv.terminate(); srv.wait(); time.sleep(2)
    srv = start()
    n_before = sum(x.get("api_calls", 0) for x in [json.loads(l) for l in (ROOT / "runtime" / "timing.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()] if x.get("kind") == "chat")
    st3, again = api(f"/api/drafts/{did}")
    lst = api("/api/drafts")[1]
    n_after = sum(x.get("api_calls", 0) for x in [json.loads(l) for l in (ROOT / "runtime" / "timing.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()] if x.get("kind") == "chat")
    check("after a server restart the draft and evidence are retrieved unchanged, with no model request", st3 == 200 and again == draft and any(x["draft_id"] == did for x in lst)
          and n_before == n_after, (st3, n_before, n_after))
srv.terminate()
rec = {"provider": cfg["provider"], "model": cfg["model"], "wall_s": wall, "model_requests": n_api, "activity": [(a["tool"], a["status"]) for a in acts],
       "reply": resp.get("text"), "draft": draft}
OUT.write_text(json.dumps(rec, indent=1), encoding="utf-8")
check(f"model request budget is bounded ({n_api})", 0 < n_api <= 10, n_api)
print(f"\n{sum(results)}/{len(results)} checks passed; model requests {n_api}; wall {wall} s; result in {OUT.name}")
sys.exit(0 if results and all(results) else 1)
