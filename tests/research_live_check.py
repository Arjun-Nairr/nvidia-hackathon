"""LIVE demonstration harness for ticket 05: ONE manual chat request through the existing specialist chat endpoint of a real server and a real Hermes
worker. The specialist (subscription provider openai-codex) reads the fictional demo catalogue, chooses its own Facebook Marketplace searches through
the backend research tools (REAL ScrapeCreators requests and CDN photo downloads), inspects photos with inspect_image and saves one draft. Then the
server is restarted with the scraper unreachable and the draft/run are read back with no model request and no scraping. No Nebius.

Hard bounds (enforced by the backend, persisted in this copy's app.db under a SEPARATE scope; nothing is reset or retried):
  <= 10 ScrapeCreators attempts (failures included), <= 3 CDN photo downloads, 1 manual request, max 14 agent iterations (+1 summary request).

ARCHIVE RULE: the archive file (research_live_result.json) is written as soon as the chat answer exists, BEFORE any restart check or other follow-up,
then rewritten after each later stage; any exception (or an injected one in scripted mode) is recorded in it ("failure") together with whatever draft,
run record, usage and error evidence could still be collected, and the server is always stopped afterwards. Written atomically and sanitized (API key and
URL query strings removed). scripts/research_live_launch.py copies it out of the throwaway copy BEFORE that copy is deleted.

Run via scripts/research_live_launch.py (isolated copy + archive). Direct use needs RESEARCH_LIVE_I_AM_A_COPY=1 in a copy whose secrets/local.env holds
LLM_PROVIDER/LLM_MODEL and SCRAPECREATORS_API_KEY and whose runtime/hermes_home has the copied login with >= 20 minutes of token life.
RESEARCH_LIVE_SCRIPTED=1 (never with openai-codex) runs the same code against scripted local services to test the archive behaviour; its archive says
mode=scripted and is never live evidence. RESEARCH_LIVE_INJECT_FAIL = hard_exit | before_archive | after_archive | no_research_tools (scripted only; the last makes the stand-in main create a
specialist WITHOUT the research tools, i.e. the creation-failure path).

RESEARCH_LIVE_VIA_MAIN=1 (V1 clean demonstration): the fictional demo company is saved through the backend form path (no model), then the specialist is
created by the REAL main agent from ONE natural-language request (Laya routing + main's create_agent), and only then gets the one research request. Model
requests across BOTH turns stay inside 16 because the live server runs with ECOM_CHAT_MAX_ITERATIONS=4 and ECOM_RESEARCH_MAX_ITERATIONS=10 (each turn is
iterations + at most one summary request: (4+1) + (10+1) = 16). The first live run used 10 requests for the research turn alone. There is no fallback: if main does not create a suitable specialist, nothing is researched and
the archive says so. RESEARCH_LIVE_SCOPE names the persisted allowance scope (fresh copy = fresh scope; never reused)."""
import base64, json, os, re, subprocess, sys, time, traceback, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if os.environ.get("RESEARCH_LIVE_I_AM_A_COPY") != "1":
    sys.exit("Refusing to run: copy of the project only (RESEARCH_LIVE_I_AM_A_COPY=1).")
SCRIPTED = os.environ.get("RESEARCH_LIVE_SCRIPTED") == "1"
INJECT = os.environ.get("RESEARCH_LIVE_INJECT_FAIL") if SCRIPTED else None
VIA_MAIN = os.environ.get("RESEARCH_LIVE_VIA_MAIN") == "1"
if VIA_MAIN:   # assigned (not defaulted): ambient environment cannot loosen the combined 16-request bound
    # live: (4+1) + (10+1) = 16. The scripted stand-in model makes one tool call per request (the real model batches them), so it gets a larger research cap.
    os.environ["ECOM_CHAT_MAX_ITERATIONS"], os.environ["ECOM_RESEARCH_MAX_ITERATIONS"] = ("4", "12") if SCRIPTED else ("4", "10")
sys.path.insert(0, str(ROOT))
os.environ["HERMES_HOME"] = str(ROOT / "runtime" / "hermes_home" / "profiles" / "main")   # Hermes resolves profile locations from this: project-local
os.environ["ECOM_TIMING"] = "1"
if SCRIPTED:
    os.environ.setdefault("ECOM_RESEARCH_SCOPE", "scripted-demo")
    os.environ.setdefault("ECOM_RESEARCH_API_MAX", "10")
    os.environ.setdefault("ECOM_RESEARCH_IMAGE_MAX", "3")
else:
    os.environ.update({"ECOM_RESEARCH_SCOPE": os.environ.get("RESEARCH_LIVE_SCOPE") or "ticket05-demo", "ECOM_RESEARCH_API_MAX": "10", "ECOM_RESEARCH_IMAGE_MAX": "3"})
    os.environ.pop("SSLKEYLOGFILE", None)                     # an inaccessible key-log device breaks TLS construction; verification stays ON
    for k in ("ECOM_SCRAPECREATORS_URL", "ECOM_PHOTO_HOSTS", "ECOM_CATALOGUE_FILE", "ECOM_EVIDENCE_FILE", "ECOM_IMAGE_DIRS"):
        os.environ.pop(k, None)                               # real endpoints, real CDN allow-list, default demo catalogue
from app import core, research
assert str(core.HERMES_ROOT).startswith(str(ROOT)), "isolated copy required"

PORT = int(os.environ.get("RESEARCH_LIVE_PORT") or 8832)
OUT = ROOT / "research_live_result.json"
KEY = research.diag().get_key() or ""
CHECKS = []
rec = {"mode": "scripted" if SCRIPTED else "live", "via_main": VIA_MAIN, "stage": "start", "failure": None, "checks": CHECKS, "outcome": None,
       "started_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
srv = None


def scrub(x):
    s = json.dumps(x)
    if KEY:
        s = s.replace(KEY, "***")
    s = re.sub(r"(https?://[^\s\"\\?]+)\?[^\s\"\\]*", r"\1", s)    # signed query strings never reach the archive
    return json.loads(s)


def archive():
    """Atomic, sanitized, idempotent: callable at every stage and from the failure handler."""
    rec["checks_passed"] = sum(1 for c in CHECKS if c["ok"])
    rec["checks_total"] = len(CHECKS)
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(scrub(rec), indent=1), encoding="utf-8")
    os.replace(tmp, OUT)


def check(name, ok, detail=""):
    ok = bool(ok)
    CHECKS.append({"name": name, "ok": ok, "detail": None if ok else str(detail)[:500]})
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


def api(path, body=None, timeout=1500):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def start(extra=None):
    p = subprocess.Popen([sys.executable, "-m", "app.server", str(PORT)], cwd=ROOT, env={**os.environ, "PYTHONUTF8": "1", **(extra or {})},
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(120):
        try:
            api("/api/status", timeout=5); return p
        except Exception:
            time.sleep(0.5)
    p.terminate()
    raise RuntimeError("server did not start")


def timing_chat():
    f = ROOT / "runtime" / "timing.jsonl"
    rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()] if f.exists() else []
    return [x for x in rows if x.get("kind") == "chat"]


def _j(x):
    try:
        v = json.loads(x)
        return v if isinstance(v, dict) else {}
    except (TypeError, ValueError):
        return {}


def collect(aid, resp):
    """Gather everything that exists NOW into rec; every part is independent, so one failing read cannot erase the others."""
    errs = rec.setdefault("collect_errors", [])

    def part(name, fn):
        try:
            return fn()
        except BaseException as e:
            errs.append(f"{name}: {type(e).__name__}: {str(e)[:200]}")
            return None
    acts = (resp or {}).get("activity") or []
    steps = []
    for a in acts:
        args = _j(a.get("input")) if isinstance(a.get("input"), str) else (a.get("input") or {})
        steps.append({"tool": a.get("tool"), "status": a.get("status"), "args": {k: v for k, v in args.items() if k not in ("description", "visual_brief", "rationale", "image_observations")}})
    rec["steps"] = steps
    rec["activity"] = [{"tool": a.get("tool"), "status": a.get("status"), "output": (a.get("output") or "")[:2000]} for a in acts]
    rec["save_errors"] = [_j(a.get("output")) for a in acts if a.get("tool") == "save_listing_draft" and _j(a.get("output")).get("ok") is False]
    rec["reply"] = (resp or {}).get("text")
    who = {aid, "main"} if VIA_MAIN else {aid}   # via main: creation AND research count against the same 16
    chat_t = [x for x in (part("timing", timing_chat) or []) if x.get("agent") in who]
    rec["model_requests_api_end"] = sum(x.get("api_calls", 0) for x in chat_t)
    rec["model_requests_api_start"] = sum(sum(1 for e in x.get("events", []) if e.get("stage") == "api_start") for x in chat_t)
    rec["model_requests_by_agent"] = {w: sum(sum(1 for e in x.get("events", []) if e.get("stage") == "api_start") for x in chat_t if x.get("agent") == w) for w in sorted(w for w in who if w)}
    rec["model_calls"] = [{"agent": x.get("agent"), "n": e.get("n"), "ms": e.get("ms"), "finish": e.get("finish"), "tool_calls": e.get("tool_calls"), "usage": e.get("usage")}
                          for x in chat_t for e in x.get("events", []) if e.get("stage") == "api_end"]
    runs = part("runs", lambda: api(f"/api/research/runs?agent_id={aid}")[1]) or []
    rec["run"] = part("run", lambda: api(f"/api/research/runs/{runs[0]['run_id']}")[1]) if runs else None
    rec["scraper_attempts"] = rec["run"]["allowance"]["run_api_attempts"] if rec.get("run") else None
    rec["photo_downloads"] = rec["run"]["allowance"]["run_photo_downloads"] if rec.get("run") else None
    saved = [o for o in (_j(a.get("output")) for a in acts if a.get("tool") == "save_listing_draft") if o.get("ok") is True]
    rec["draft"] = part("draft", lambda: api(f"/api/drafts/{saved[-1]['draft_id']}")[1]) if saved else None
    rec["allowance"] = part("allowance", lambda: api("/api/research/allowance")[1])
    d = rec.get("draft")
    complete = bool(d and d.get("status") == "complete" and any(i.get("counts_as_verified_evidence") and i.get("kind") == "live_listing_photo" for i in d.get("image_evidence", [])))
    rec["outcome"] = "complete" if complete else ("partial" if d else "blocked")


CREATE_MSG = ("Please create a market-analysis specialist for our company. It should research comparable products on Facebook Marketplace near Dallas: look up "
              "the location, search listings, read listing details and download listing photos. It should look at the photos it relies on, read our product "
              "catalogue and save one source-backed listing draft. Use live Marketplace research only, not any recorded sample data.")
RESEARCH_MSG = ("Please research comparable products for our product on Facebook Marketplace near Dallas and save one grounded listing draft. Choose the searches and "
                "the most comparable listings yourself, look at their photos, and tell me the draft ID and anything you could not verify.")
WANT_TOOLS = {"marketplace_locate", "marketplace_search", "marketplace_item", "marketplace_photo", "inspect_image", "read_catalogue", "save_listing_draft"}


def create_via_main():
    """Save the fictional demo company (backend form path, no model), start the server, and let the REAL main agent create the specialist from one
    natural-language request. Returns the new agent id or None; the outcome is recorded either way. No fallback creation."""
    global srv
    core.update_company({"name": "Acme Linens (fictional demo merchant)",
                         "products": "Quilted coverlets and cotton bedding for the bedroom (fictional demo product line)",
                         "customers": "Home buyers in the US furnishing a bedroom (fictional demo)",
                         "goal": "Understand how comparable bedding is presented on Facebook Marketplace near Dallas and draft an accurate listing for our quilted coverlet"},
                        source="form")
    rec["company"] = core.load_company()
    srv = start()
    rec["stage"] = "create_via_main"
    t0 = time.time()
    st, r = api("/api/chat/main", {"message": ("DEMO_CREATE_RESEARCH: " if SCRIPTED and INJECT != "no_research_tools" else "") + CREATE_MSG, "request_id": "demo-create-1"})
    acts = r.get("activity") or []
    rec["creation"] = {"wall_s": round(time.time() - t0, 1), "http": st, "ok": r.get("ok"), "error": r.get("error"), "route": r.get("route"), "reply": r.get("text"),
                       "tools": [{"tool": a.get("tool"), "status": a.get("status"), "input": a.get("input"), "output": (a.get("output") or "")[:2500]} for a in acts]}
    made = [_j(a.get("output")) for a in acts if a.get("tool") == "create_agent"]
    ok_made = [o for o in made if o.get("ok") is True]
    agents = api("/api/agents")[1]
    check("creation request routed to main as create_market_agent", (r.get("route") or {}).get("outcome") in ("create_market_agent", "classifier_off_test_only"), r.get("route"))
    check("main made a real create_agent call that succeeded", bool(ok_made), made)
    aid = ok_made[-1].get("agent_id") if ok_made else None
    detail = api(f"/api/agents/{aid}")[1] if aid else None
    granted = set((detail or {}).get("granted_tools") or [])
    rec["specialist"] = {"agent_id": aid, "agents_after_creation": [a.get("agent_id") for a in agents],
                         "name": (detail or {}).get("name"), "objective": (detail or {}).get("objective"), "granted_tools": sorted(granted),
                         "skills": [s.get("name") if isinstance(s, dict) else s for s in (detail or {}).get("skills", [])],
                         "soul": (core.HERMES_ROOT / "profiles" / aid / "SOUL.md").read_text(encoding="utf-8") if aid else None}
    check("exactly one specialist exists with the research, image-inspection, catalogue and draft tools, and WITHOUT the recorded-evidence tool",
          aid is not None and len(agents) == 1 and WANT_TOOLS <= granted and "read_recorded_evidence" not in granted, (rec["specialist"]["agents_after_creation"], sorted(granted)))
    archive()
    return aid if aid and len(agents) == 1 and WANT_TOOLS <= granted and "read_recorded_evidence" not in granted else None


def main():
    global srv
    cfg, problem = core.llm_config(), core.llm_problem()
    rec.update(provider=cfg["provider"], model=cfg["model"])
    if SCRIPTED:
        life = None
        if cfg["provider"] == "openai-codex":
            sys.exit("NOT RUN: scripted mode is never allowed with the subscription provider")
        if not (os.environ.get("ECOM_SCRAPECREATORS_URL") or "").startswith(("http://127.0.0.1", "http://localhost")):
            sys.exit("NOT RUN: scripted mode needs ECOM_SCRAPECREATORS_URL pointing at a local stand-in")
        gate_ok = not problem
    else:
        life = token_life_seconds()
        gate_ok = not (problem or life is None or life < 20 * 60 or cfg["provider"] != "openai-codex" or not KEY)
    print(f"mode {rec['mode']} | provider {cfg['provider']} model {cfg['model']} | login token life: {None if life is None else round(life / 60)} min | problem: {problem} | "
          f"ScrapeCreators key: {'configured' if KEY else 'MISSING'}", flush=True)
    if not gate_ok:
        rec["outcome"] = "not_run"
        rec["failure"] = {"stage": "gate", "message": problem or "login token life too short/unknown, provider is not the subscription provider, or the ScrapeCreators key is missing"}
        archive()
        sys.exit("NOT RUN: " + rec["failure"]["message"])

    rec["stage"] = "setup"
    aid, resp = None, None
    try:
        if VIA_MAIN:
            aid = create_via_main()
            if aid is None:   # no silent fallback to a backend-created specialist: nothing is researched, the archive says why
                rec["outcome"] = "creation_failed"
                rec["stage"] = "done"
                archive()
                return
        else:
            core.update_company({"name": "Acme Linens (fictional demo)", "products": "Cotton bedding and curtains", "customers": "Home buyers in the US",
                                 "goal": "Understand how competing bedding listings are presented and draft better listings"}, source="form")
        tools = ["inspect_image", "read_catalogue", "save_listing_draft", *core.MARKETPLACE_TOOLS]
        r = {} if VIA_MAIN else core.create_agent({"role": "market_analysis", "name": "Live Listing Researcher",
                               "objective": "Research comparable new bedding on Facebook Marketplace for the merchant's product and turn it into one accurate, source-linked listing draft.",
                               "instructions": "You write listing drafts for Acme Linens (a fictional demo merchant). Research Facebook Marketplace within your backend allowance, choose the "
                                               "comparables and photos yourself, and use only supplied product facts: never invent specifications, discounts, delivery terms, performance "
                                               "or competitor-sales claims. Say what you could not verify.",
                               "skills": [{"name": "live-listing-research", "content":
                                           "# Live listing research routine\n1. Read the catalogue product, its supplied facts and the merchant's market.\n"
                                           "2. Locate that market, then choose and refine your own searches; judge relevance yourself and change approach after weak or empty results.\n"
                                           "3. Request details and photos only for comparables worth the allowance; inspect the photos you rely on.\n"
                                           "4. Draft from supplied product facts only, save with save_listing_draft, and report limits and anything unverified."}],
                               "requested_tools": tools})
        if not VIA_MAIN:
            check("specialist created; research and listing tools granted with the mandatory tools", r.get("ok") and set(tools) <= set(r["granted_tools"]), r)
            aid = r["agent_id"]
            srv = start()
        msg = RESEARCH_MSG if VIA_MAIN else ("Please research Facebook Marketplace for comparable new bedding near our market and create one listing draft for our product "
                                              "acme-cloud-quilt-queen. Pick the most comparable listings yourself, look at their photos, and save the draft. Tell me the "
                                              "draft ID and anything you could not verify.")
        if SCRIPTED:
            msg = "RESEARCH_AGENT: " + msg                 # the scripted stand-in model's marker (tests/mock_llm.py)
        rec["stage"] = "chat"
        t0 = time.time()
        st, resp = api(f"/api/chat/{aid}", {"message": msg, "request_id": "live-req-1"})
        rec["wall_s"] = round(time.time() - t0, 1)
        if INJECT == "hard_exit":
            srv.terminate()                                # (test hygiene: a real crash would orphan the server)
            os._exit(9)                                    # simulates the original failure: the process vanishes before anything is archived
        print(f"\n--- chat reply ({rec['wall_s']}s, ok={resp.get('ok')}) ---\n{resp.get('text')}\n", flush=True)
        rec["stage"] = "collect"
        if INJECT == "before_archive":
            raise RuntimeError("injected failure before the first archive write")
        collect(aid, resp)
        run, draft = rec.get("run"), rec.get("draft")
        archive()                                          # FIRST archive: the result exists before any follow-up check can fail
        print("decisions:", [(s["tool"], s["args"].get("query") or s["args"].get("listing_id") or s["args"].get("image_id") or s["args"].get("location_no"), s["status"])
                             for s in rec["steps"]], flush=True)
        if INJECT == "after_archive":
            raise RuntimeError("injected failure after the archive write")
        rec["stage"] = "checks"
        check("chat request succeeded through the existing specialist chat endpoint", st == 200 and resp.get("ok"), (st, resp.get("error")))
        check("a backend-owned research run exists for this one request", run is not None and run["request_id"] == "live-req-1", run)
        check("ScrapeCreators attempts (failures included) stayed within 10", rec["scraper_attempts"] is not None and rec["scraper_attempts"] <= 10, rec["scraper_attempts"])
        check("CDN photo downloads stayed within 3", rec["photo_downloads"] is not None and rec["photo_downloads"] <= 3, rec["photo_downloads"])
        n_req = max(rec["model_requests_api_start"], rec["model_requests_api_end"])
        check("live model requests stayed within 16", 0 < n_req <= 16, (rec["model_requests_api_start"], rec["model_requests_api_end"]))
        check("the specialist chose its own searches (research tools called from observations, not a script)", any(s["tool"] == "marketplace_search" for s in rec["steps"]), rec["steps"])
        archive()
        if draft:
            print("\n=== SAVED DRAFT", draft["draft_id"], "status", draft["status"], "evidence", draft["evidence_source"], "===", flush=True)
            print("TITLE:", draft["title"], "\nDESCRIPTION:", draft["description"], "\nVISUAL BRIEF:", draft["visual_brief"], flush=True)
            for x in draft["rationale"]:
                print("RATIONALE:", x["claim"], "| listings", x["listing_ids"], "| images", x["image_ids"], flush=True)
            for i in draft["image_evidence"]:
                print("IMAGE", i["image_id"], i["kind"], i["sha256"][:12], i["delivery"], i["provenance"], "|", i["model_observations"], "| unsure:", i["model_uncertainties"], flush=True)
            print("LIMITATIONS:", draft["limitations"], "| MISSING:", draft["missing"], flush=True)
            check("the saved draft is retrievable through the read API with live provenance, a run id, snapshots and supporting evidence",
                  draft["evidence_source"] == "live_research" and draft["research_run_id"] == run["run_id"] and draft["listing_evidence"]
                  and all(l["evidence_file"].startswith("live-run:") and l.get("retrieved_at") and "facebook.com/marketplace/item/" in (l.get("source_url") or "")
                          for l in draft["listing_evidence"]), draft["listing_evidence"])
            archive()
            rec["stage"] = "restart_check"
            srv.terminate(); srv.wait(); time.sleep(2)
            n_calls = len(run["calls"])
            srv = start({"ECOM_SCRAPECREATORS_URL": "http://127.0.0.1:9"})          # scraper unreachable: a retrieval that scraped would fail
            n_before = sum(x.get("api_calls", 0) for x in timing_chat())
            again = api(f"/api/drafts/{draft['draft_id']}")[1]
            run2 = api(f"/api/research/runs/{run['run_id']}")[1]
            n_after = sum(x.get("api_calls", 0) for x in timing_chat())
            check("after a server restart the draft and its research run are retrieved unchanged with no model request and no scraper request",
                  again == draft and run2["calls"] == run["calls"] and len(run2["calls"]) == n_calls and n_before == n_after, (again == draft, n_before, n_after))
            if VIA_MAIN:
                ag2 = api("/api/agents")[1]
                check("after the restart the registry still holds exactly the one demo specialist (the sidebar shows main plus this analyst)",
                      [a.get("agent_id") for a in ag2] == [aid] and api("/api/company")[1]["company"]["name"] == rec["company"]["name"], [a.get("agent_id") for a in ag2])
        rec["stage"] = "done"
    except BaseException as e:                              # the archive written above is kept; the failure is added to it
        rec["failure"] = {"stage": rec.get("stage"), "type": type(e).__name__, "message": str(e)[:500], "traceback": traceback.format_exc()[-1500:]}
        if not rec.get("run") and not rec.get("draft") and aid:   # failed before collection: collect what exists now (best effort, each part independent)
            try:
                collect(aid, resp)
            except BaseException as e2:
                rec.setdefault("collect_errors", []).append(f"late collect: {type(e2).__name__}: {str(e2)[:200]}")
        archive()
        raise
    finally:
        if srv is not None:
            try:
                srv.terminate()
            except Exception:
                pass


if __name__ == "__main__":
    main()
    archive()
    print(f"\nRESULT mode={rec['mode']} outcome={rec['outcome']} | {rec['checks_passed']}/{rec['checks_total']} checks passed | scraper attempts {rec['scraper_attempts']}/10, "
          f"photos {rec['photo_downloads']}/3, model requests {max(rec['model_requests_api_start'], rec['model_requests_api_end'])}/16, wall {rec.get('wall_s')} s | "
          f"archive {OUT.name}", flush=True)
    sys.exit(0 if CHECKS and all(c["ok"] for c in CHECKS) else 1)
