"""UI-02 tests: the saved-results API (app/results.py, GET /api/results) and the presentation instructions. No model, provider, credential or runtime: a TEMPORARY app root, rows written with SQL
in the exact shapes the real tools store, and the real modules reading them. Seams: results.cards(agent_id) (association by backend-owned agent + message/request identity, legacy fallback,
partial work + failure, safe links, hidden internals) and core.refresh_soul / build_soul + scripts/setup.py (concise-output rule reaches new and existing profiles without losing anything).
  venv-python tests/results_test.py"""
import hashlib, json, os, re, shutil, sys, tempfile, time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="results-test-"))
os.environ["ECOM_APP_ROOT"] = str(TMP)
os.environ.pop("HERMES_HOME", None)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import core  # noqa: E402
from app import flyer as flyer_mod  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{str(detail)[:600]}]"), flush=True)


try:
    from app import results as R
except ImportError as e:
    R = None
    check("app/results.py exists", False, e)

now = time.time()
SHA = "a" * 64
d = core.db()


def msg(agent, who, content, ts):
    cur = d.execute("INSERT INTO messages(agent_id,who,content,tools,ts) VALUES(?,?,?,?,?)", (agent, who, content, "[]", ts))
    return cur.lastrowid


for aid, role in (("analyst", "market_analysis"), ("social", "social_media"), ("other", "social_media")):
    d.execute("INSERT INTO agents VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (aid, aid.title(), role, "default", "obj", "ins", "[]", "[]", "[]", "[]", "conv-" + aid, "idle", now))
# analyst: two requests (X then Y), a legacy draft without any association
u1, a1 = msg("analyst", "user", "first task", now), None
a1 = msg("analyst", "agent", "first reply", now + 1)
u2 = msg("analyst", "user", "second task", now + 2)
a2 = msg("analyst", "agent", "second reply", now + 3)
# social: a request with an ad package AND a failed flyer (partial work + failure), a request with a good flyer, an in-flight request with a draft-less run
u3 = msg("social", "user", "research and flyer, the flyer fails", now + 4)
a3 = msg("social", "error", "[error] the flyer attempt failed", now + 5)
u4 = msg("social", "user", "make the flyer", now + 6)
a4 = msg("social", "agent", "done", now + 7)
u_other = msg("other", "user", "someone else's task", now + 8)

listing_ev = [{"listing_id": "111", "title": "Antique quilt <script>alert(1)</script>", "price": {"amount": 75, "currency": "USD", "formatted": "$75"}, "condition": "used_good", "location": "Dallas, TX",
               "detail_level": "detailed", "source_url": "https://www.facebook.com/marketplace/item/111/", "seller_ref": "seller_1", "supporting": {"description": "text"}, "evidence_sha256": SHA},
              {"listing_id": "222", "title": "Evil", "price": None, "condition": None, "location": None, "detail_level": "search_only", "source_url": "javascript:alert(document.cookie)", "seller_ref": "seller_2"},
              {"listing_id": "333", "title": "Data", "price": None, "condition": None, "location": None, "detail_level": "search_only", "source_url": "data:text/html;base64,PHNjcmlwdD4=", "seller_ref": "seller_3"}]
img_ev = [{"image_id": "111", "kind": "live_listing_photo", "listing_id": "111", "sha256": SHA, "model_observations": "A quilt on a bed with appliqued figures.", "model_uncertainties": "Condition unverified.",
           "counts_as_verified_evidence": True}]


def draft(did, agent, title, run_id=None, req=None, mid=None, status="complete", missing=(), snap=None):
    d.execute("INSERT INTO listing_drafts(draft_id, agent_id, conversation_id, product_id, status, title, description, visual_brief, rationale, limitations, missing, merchant_snapshot, product_snapshot, "
              "listing_evidence, image_evidence, created_at, evidence_source, research_run_id, request_id, message_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (did, agent, "conv-" + agent, "quilt", status, title, "Plain description of the product.", "Lead with the full view.", json.dumps([{"claim": "Comparable listings lead with a full view.", "listing_ids": ["111"], "image_ids": ["111"]}]),
               "Asking prices only; one search area.", json.dumps(list(missing)), json.dumps(snap or {"merchant": {"name": "Acme"}, "notice": "Demonstration only"}),
               json.dumps({"name": "Quilt", "price": {"amount": 79, "currency": "USD"}, "source_url": "https://www.metmuseum.org/art/collection/search/854568"}),
               json.dumps(listing_ev), json.dumps(img_ev), now, "live_research" if run_id else "recorded_sample", run_id, req, mid))


for rid, agent, req, mid in (("run-X", "analyst", "req-x", u1), ("run-Y", "analyst", "req-y", u2)):
    d.execute("INSERT INTO research_runs(run_id, agent_id, conversation_id, request_id, message_id, scope, api_max, image_max, created_at) VALUES(?,?,?,?,?,?,?,?,?)", (rid, agent, "conv-" + agent, req, mid, "s", 4, 2, now))
draft("draft-x", "analyst", "Draft for the first task", run_id="run-X")                          # associated through its research run (legacy shape: no request/message columns set)
draft("draft-y", "analyst", "Draft for the second task", req="req-y", mid=u2)                    # associated directly (new shape)
draft("draft-legacy", "analyst", "Old draft with no identity")                                    # recorded sample, nothing to associate with
draft("draft-foreign", "analyst", "Draft that points at another agent's message", req="req-z", mid=u_other)   # message belongs to a different agent -> never attached

d.execute("INSERT INTO ad_runs(run_id, agent_id, company_id, company_name, conversation_id, request_id, message_id, scope, api_max, image_max, media_type, country, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
          ("adrun-3", "social", "default", "Acme", "conv-social", "req-3", u3, "s", 8, 3, "IMAGE_AND_MEME", "US", now))
refs = {"references": [{"ad_no": 2, "source_ad_id": "9", "source_url": "https://www.facebook.com/ads/library?id=9", "image_id": "ad-9-1", "sha256": SHA, "why_relevant": "Quilt shown large and calm.", "visual_features": "Centered product; quiet palette.",
                        "inspected_at": "t", "delivery": "image_part_sent"}],
        "cited_ads": [{"ad_no": 2, "source_ad_id": "9", "source_url": "https://www.facebook.com/ads/library?id=9", "advertiser": {"name": "Deerly's <b>Quilts</b>", "page_id": "1"}, "active": True, "card_count": 1,
                       "campaign": {"campaign_id": None}, "image_count": 1}]}
gate = {"state": "disabled_reach_unavailable", "ranking_enabled": False, "metric": None, "geography": None, "period": None, "ads_recorded": 30, "ads_with_reported_reach": 0, "reason": "No ad carries a reach value."}
d.execute("INSERT INTO ad_packages VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ("adpkg-3", "adrun-3", "social", "default", "conv-social", "req-3", "complete", "Two relevant ads were inspected.", "relevance_only", None,
          "Reach unknown; chosen by relevance.", json.dumps(gate), json.dumps(refs), json.dumps([{"ad_no": 2}]), json.dumps({"scraper_attempts": 5}), json.dumps({"request_id": "req-3"}), now))


def flyer(fid, agent, req, mid, status="ok", error=None, review=None, final=True):
    d.execute("INSERT INTO flyer_runs(run_id, agent_id, company_id, company_name, conversation_id, request_id, message_id, product_id, scope, attempts_final_max, final_candidate_id, created_at, selection_rationale, selected_at, research_json) "
              "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (fid, agent, "default", "Acme", "conv-" + agent, req, mid, "quilt", "s", 2, ("cand-" + fid[4:]) if (final and status == "ok") else None, now,
                                                         "The only valid candidate.", "t", None))
    cand = "cand-" + fid[4:]
    ok = status == "ok"
    sha, nbytes = None, None
    if ok:   # a REAL saved image: the page serves it only after the integrity check (size, hash, decode, dimensions) passes
        from PIL import Image
        folder = core.RUNTIME / "flyers" / fid
        folder.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (80, 100), (190, 120, 90)).save(folder / (cand + ".jpg"), "JPEG")
        raw = (folder / (cand + ".jpg")).read_bytes()
        sha, nbytes = hashlib.sha256(raw).hexdigest(), len(raw)
    d.execute("INSERT INTO flyer_attempts(candidate_id, run_id, attempt_no, status, outcome, prompt, context_text, product_json, inputs_json, references_json, provider, model, request_json, inputs_synthetic, http_status, error, "
              "usage, interaction_id, ms, out_path, out_sha256, out_bytes, out_width, out_height, out_mime, created_at, dispatched_at, finished_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (cand, fid, 1, "done", "ok" if ok else "provider_error", "p", "c", "{}", "[]", "[]", "gemini", "m", "{}", 0, 200 if ok else 500, error, None, None, 1000, (cand + ".jpg") if ok else None,
               sha, nbytes, 80 if ok else None, 100 if ok else None, "image/jpeg" if ok else None, now, now, now))
    if review:
        d.execute("INSERT INTO flyer_reviews(review_id, candidate_id, run_id, agent_id, request_id, sha256, width, height, inspection_id, delivery, verified, verdict, checks_json, defects_json, uncertainties, summary, refs_json, created_at) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ("rev-" + fid[4:], cand, fid, agent, req, SHA, 800, 1000, 1, "image_part_sent", 1, review["verdict"], json.dumps(review["checks"]),
                                                                  json.dumps(review["defects"]), "Limited to the delivered pixels.", "Summary.", "[]", now))


PASS = {"product_appearance": {"result": "pass", "observation": "The quilt matches the photo."}, "required_text_price": {"result": "pass", "observation": "Name and USD 79.00 visible."},
        "layout_readability": {"result": "pass", "observation": "Clear order."}}
flyer("fly-fa11ed0001", "social", "req-3", u3, status="failed", error="provider_error: HTTP 500")                 # same request as the ad package: partial work + failure
flyer("fly-600d000001", "social", "req-4", u4, review={"verdict": "passed", "checks": PASS, "defects": []})
flyer("fly-1e6ac90001", "social", None, None, review={"verdict": "passed", "checks": PASS, "defects": []})      # legacy: no identity at all
d.commit()
d.close()

if R:
    cards = R.cards("analyst")
    by = {c["key"]: c for c in cards}
    check("RS-1 two requests from one agent: each draft carries ITS request's message id (run association and direct association agree), never the other's",
          by["listing_draft:draft-x"]["message_id"] == u1 and by["listing_draft:draft-x"]["request_id"] == "req-x" and by["listing_draft:draft-y"]["message_id"] == u2 and by["listing_draft:draft-y"]["request_id"] == "req-y", {k: (c["message_id"], c["request_id"]) for k, c in by.items()})
    check("RS-2 a draft with no identity (legacy) and one pointing at another agent's message are NOT attached to any message (message_id None, associated False)",
          by["listing_draft:draft-legacy"]["message_id"] is None and not by["listing_draft:draft-legacy"]["associated"] and by["listing_draft:draft-foreign"]["message_id"] is None and not by["listing_draft:draft-foreign"]["associated"],
          (by["listing_draft:draft-legacy"], by["listing_draft:draft-foreign"]["message_id"]))
    check("RS-3 results are per agent: the analyst's list holds only its own drafts", {c["agent_id"] for c in cards} == {"analyst"} and len(cards) == 4, [c["key"] for c in cards])
    sc = R.cards("social")
    sb = {c["key"]: c for c in sc}
    check("RS-4 one request with saved research AND a failed flyer yields BOTH cards on that request's message (partial work plus the failure), and another request's flyer stays on its own message",
          sb["ad_research:adpkg-3"]["message_id"] == u3 and sb["flyer:fly-fa11ed0001"]["message_id"] == u3 and sb["flyer:fly-600d000001"]["message_id"] == u4 and not sb["flyer:fly-1e6ac90001"]["associated"], {k: c["message_id"] for k, c in sb.items()})
    ff = sb["flyer:fly-fa11ed0001"]
    check("RS-5 a failed flyer shows its actual status and error, no image and no invented review", ff["image"] is None and "failed" in ff["status_text"].lower() and "HTTP 500" in (ff["error"] or "") and not any("passed" in x.lower() for x in [ff["status_text"]]), ff)
    fg = sb["flyer:fly-600d000001"]
    check("RS-6 a flyer with a passing agent review is labelled 'Generated flyer', links its saved image, says the review is automated and not human approval, and never says approved or defect-free",
          fg["heading"] == "Generated flyer" and fg["image"] and fg["image"]["url"] == "/api/flyers/images/fly-600d000001" and "not human approval" in fg["status_text"] and "approved" not in json.dumps(fg).lower().replace("not human approval", "")
          and "no defects" not in json.dumps(fg).lower(), fg)
    ap = sb["ad_research:adpkg-3"]
    check("RS-7 the ad-research card explains the selection in plain words (relevance, reach unavailable) and links the ad in the Facebook Ad Library as a source", "relevance" in json.dumps(ap).lower() and any(s["url"].startswith("https://www.facebook.com/ads/library") for s in ap["sources"]), ap["sources"])
    dr = by["listing_draft:draft-x"]
    urls = [s["url"] for s in dr["sources"]]
    check("RS-8 only http(s) source links are offered: the javascript: and data: URLs are dropped, the real listing and the catalogue source stay", all(u.startswith(("https://", "http://")) for u in urls) and any("marketplace/item/111" in u for u in urls)
          and not any("javascript" in json.dumps(s) or "data:text" in json.dumps(s) for s in dr["sources"]), dr["sources"])
    allc = json.dumps(cards + sc)
    check("RS-9 the card fields carry no hashes, tool/identity payloads or internal run/candidate/package ids for display (only the internal key and the image URL contain an id)",
          not re.search(r"[0-9a-f]{64}", allc) and not any(k in allc for k in ("evidence_sha256", "seller_ref", "inspection_run_id", "call_accounting", "scraper_attempts")), re.findall(r"[0-9a-f]{64}", allc)[:1])
    check("RS-10 markup in stored text is returned as plain text, unmodified (the page escapes it; nothing is executed or silently rewritten here)",
          "<script>" in json.dumps(dr["sources"]) or "<script>" in json.dumps(dr), None)
    check("RS-11 cards come in chronological order and the sources/details sections are present for a research-backed draft", [c["created_at"] for c in cards] == sorted(c["created_at"] for c in cards) and dr["details"] and dr["sources"], None)
    from app import listing, turn_state
    turn_state.request_id = "req-t"
    ident = listing._identity("analyst")
    turn_state.request_id = None
    check("RS-12 the identity the real save path stamps on a new draft is the backend's request id plus the agent's latest user message id (never model-supplied)", ident == ("req-t", u2), ident)

# ---- presentation instructions: new profiles, existing profiles, main
from app import roles  # noqa: E402
rule_marker = getattr(roles, "REPLY_STYLE", None)
check("RS-20 the concise-output rule exists once in roles.py", bool(rule_marker) and "result" in rule_marker.lower(), rule_marker)
core_soul = core.build_soul({"name": "Acme Analyst", "role": "market_analysis", "objective": "Compare listings for Acme quilts and draft one evidence-backed listing.", "instructions": "Use only supplied facts and retrieved evidence.", "tools": ["read_company_context", "memory", "skills"]}, "Acme")
check("RS-21 a newly built specialist SOUL contains the concise-output rule (analyst and social)", bool(rule_marker) and rule_marker.strip()[:60] in core_soul
      and rule_marker.strip()[:60] in core.build_soul({"name": "S", "role": "social_media", "objective": "Make one labelled flyer for Acme quilts from supplied photos.", "instructions": "Use only supplied facts.", "tools": ["read_company_context"]}, "Acme"), core_soul[-400:])
# ---- existing profiles receive the rule through the normal refresh, and nothing else of theirs changes
prof = core.HERMES_ROOT / "profiles" / "analyst"
(prof / "memories").mkdir(parents=True)
(prof / "skills" / "my-custom-skill").mkdir(parents=True)
(prof / "sessions").mkdir()
(prof / "SOUL.md").write_text("# Old soul without the reply rule\n", encoding="utf-8")
(prof / "skills" / "my-custom-skill" / "SKILL.md").write_text("---\nname: my-custom-skill\n---\n\nkeep me\n", encoding="utf-8")
(prof / "memories" / "MEMORY.md").write_text("durable note\n", encoding="utf-8")
(prof / "sessions" / "s1.json").write_text("{}", encoding="utf-8")
(prof / "state.db").write_bytes(b"history")
d = core.db()
d.execute("UPDATE agents SET objective=?, instructions=?, granted_tools=?, role=? WHERE agent_id='analyst'", ("Company-specific objective that was customized by the operator.", "Customized instructions that must survive the refresh.", json.dumps(["read_company_context", "memory", "skills"]), "market_analysis"))
d.commit()
d.close()
before = {f.relative_to(prof).as_posix(): hashlib.sha256(f.read_bytes()).hexdigest() for f in prof.rglob("*") if f.is_file() and f.name != "SOUL.md"}
refreshed = core.refresh_specialist_souls() if hasattr(core, "refresh_specialist_souls") else None
soul = (prof / "SOUL.md").read_text(encoding="utf-8") if (prof / "SOUL.md").exists() else ""
after = {f.relative_to(prof).as_posix(): hashlib.sha256(f.read_bytes()).hexdigest() for f in prof.rglob("*") if f.is_file() and f.name != "SOUL.md"}
check("RS-22 an EXISTING specialist's SOUL.md is rebuilt from its registry row: it gains the concise-output rule and keeps the customized objective and instructions", refreshed == ["analyst"] and bool(rule_marker) and rule_marker.strip()[:60] in soul
      and "Company-specific objective that was customized by the operator." in soul and "Customized instructions that must survive the refresh." in soul, (refreshed, soul[:200]))
check("RS-23 nothing else in the profile changes: custom skill, memory, sessions and history database are byte-identical", before == after, (before, after))
again = core.refresh_specialist_souls() if hasattr(core, "refresh_specialist_souls") else None
check("RS-24 the refresh is idempotent (a second run rewrites nothing)", again == [], again)
check("RS-25 the refresh never creates a profile for a registry row that has none (no directory, no file)", not (core.HERMES_ROOT / "profiles" / "social").exists() and not (core.HERMES_ROOT / "profiles" / "other").exists(), None)

# ---- UI-02 correction round: (1) stored demonstration labels, (2) integrity warnings of a damaged OTHER flyer candidate, (4) profile refresh vs. Customize
import sqlite3, threading  # noqa: E402
d = core.db()
for aid, role in (("demoag", "market_analysis"), ("social2", "social_media")):
    d.execute("INSERT INTO agents VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (aid, aid.title(), role, "default", "obj", "ins", "[]", "[]", "[]", "[]", "conv-" + aid, "idle", now))
NOTICE = "Demonstration only: a public-domain museum object, not a retail offer."
draft("draft-demo-note", "demoag", "Demo draft with a notice", snap={"merchant": {"name": "Acme"}, "demo": True, "notice": NOTICE, "catalogue_file": "x", "catalogue_sha256": SHA})
draft("draft-demo-flag", "demoag", "Demo draft flagged without notice text", snap={"merchant": {"name": "Acme"}, "demo": True, "notice": None})
draft("draft-plain", "demoag", "Ordinary draft", snap={"merchant": {"name": "Acme"}, "demo": False, "notice": None})
DAMAGED = "cand-d0a0000002"


def damaged_second(fid):   # a second saved candidate whose image file is missing: its generation succeeded (attempt consumed) but the stored file fails the integrity check
    d.execute("INSERT INTO flyer_attempts(candidate_id, run_id, attempt_no, status, outcome, prompt, context_text, product_json, inputs_json, references_json, provider, model, request_json, inputs_synthetic, http_status, error, "
              "usage, interaction_id, ms, out_path, out_sha256, out_bytes, out_width, out_height, out_mime, created_at, dispatched_at, finished_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (DAMAGED, fid, 2, "done", "ok", "p", "c", "{}", "[]", "[]", "gemini", "m", "{}", 0, 200, None, None, None, 1000, DAMAGED + ".jpg", SHA, 1000, 80, 100, "image/jpeg", now + 1, now + 1, now + 1))


flyer("fly-d0a0000001", "social2", "req-d1", None, review={"verdict": "passed", "checks": PASS, "defects": []}, final=False)   # valid + reviewed, never explicitly selected
damaged_second("fly-d0a0000001")
flyer("fly-d0b0000001", "social2", "req-d2", None, final=False)                                                             # valid but never reviewed
d.execute("INSERT INTO flyer_attempts(candidate_id, run_id, attempt_no, status, outcome, prompt, context_text, product_json, inputs_json, references_json, provider, model, request_json, inputs_synthetic, http_status, error, usage, interaction_id, ms, out_path, out_sha256, out_bytes, out_width, out_height, out_mime, created_at, dispatched_at, finished_at) SELECT 'cand-d0b0000002', run_id, 2, status, outcome, prompt, context_text, product_json, inputs_json, references_json, provider, model, request_json, inputs_synthetic, http_status, "
          "error, usage, interaction_id, ms, 'cand-d0b0000002.jpg', out_sha256, out_bytes, out_width, out_height, out_mime, created_at, dispatched_at, finished_at FROM flyer_attempts WHERE candidate_id='cand-d0b0000001'")
d.commit()
d.close()
if R:
    def shown(c):
        return json.dumps({k: v for k, v in c.items() if k not in ("key", "image", "agent_id")})
    dc = {c["key"]: c for c in R.cards("demoag")}
    note, flag, plain = dc["listing_draft:draft-demo-note"], dc["listing_draft:draft-demo-flag"], dc["listing_draft:draft-plain"]
    check("RS-30 a draft saved from a demonstration catalogue shows the STORED notice in the visible part of its card (not in collapsed details), whatever the model wrote in the description",
          any(NOTICE in f["text"] for f in note["fields"]) and NOTICE not in "Plain description of the product.", note["fields"])
    check("RS-31 a demonstration draft whose snapshot has the flag but no notice text still says it is a demonstration; nothing else is invented", any("demonstration" in f["text"].lower() for f in flag["fields"]), flag["fields"])
    check("RS-32 an ordinary (non-demo) draft acquires no demonstration label anywhere in its card", "demonstration" not in shown(plain).lower() and "demo" not in shown(plain).lower(), shown(plain))
    check("RS-33 the stored notice carries no hash or internal file reference", not re.search(r"[0-9a-f]{64}", shown(note)) and "catalogue_file" not in shown(note), shown(note))
    fc = {c["key"]: c for c in R.cards("social2")}
    ok1, ok2 = fc["flyer:fly-d0a0000001"], fc["flyer:fly-d0b0000001"]
    check("RS-34 a reviewed flyer whose OTHER candidate is damaged keeps its reviewed status and image and ALSO states the integrity problem as a known issue",
          ok1["status"] == "agent_review_passed" and ok1["image"] and any("integrity" in i.lower() and "missing" in i.lower() for i in ok1["issues"]), (ok1["status"], ok1["issues"]))
    check("RS-35 that warning shows no candidate id or hash, says nothing was regenerated or selected, and does not repeat the generic review note",
          "cand-" not in shown(ok1) and not re.search(r"[0-9a-f]{64}", shown(ok1)) and any("not generated again" in i for i in ok1["issues"]) and flyer_mod.PASSED_NOTE not in shown(ok1) and "not human approval" in ok1["status_text"], shown(ok1))
    check("RS-36 an unreviewed flyer with a damaged other candidate states the problem exactly once and exposes no candidate id", shown(ok2).count("integrity check") == 1 and "cand-" not in shown(ok2), shown(ok2))
    check("RS-37 a flyer with no damaged candidate gains no integrity warning", "integrity" not in shown(fg).lower(), shown(fg))
    con = sqlite3.connect(core.DB_PATH, timeout=30)
    sel_before = con.execute("SELECT final_candidate_id FROM flyer_runs WHERE run_id='fly-d0a0000001'").fetchone()[0]
    n_before = con.execute("SELECT COUNT(*) FROM flyer_attempts").fetchone()[0]
    con.close()
    R.cards("social2")
    con = sqlite3.connect(core.DB_PATH, timeout=30)
    check("RS-38 building the cards changes no selection and creates no attempt (no regeneration, accounting untouched)",
          sel_before is None and con.execute("SELECT final_candidate_id FROM flyer_runs WHERE run_id='fly-d0a0000001'").fetchone()[0] is None and con.execute("SELECT COUNT(*) FROM flyer_attempts").fetchone()[0] == n_before, None)
    con.close()

# (4) the refresh holds the registry write lock from its read until its last file write, so a Customize that commits in between is never overwritten by a stale snapshot
OLD_OBJ, NEW_OBJ = "Company-specific objective that was customized by the operator.", "A brand new objective written by the later Customize call for Acme quilts."
(prof / "SOUL.md").write_text("# stale soul that forces the refresh to write\n", encoding="utf-8")
real_build, race = core.build_soul, {"thread": None, "locked": None, "result": None}


def paused_build(c, company):
    out = real_build(c, company)   # the OLD registry snapshot is already read and its soul built
    if threading.current_thread() is threading.main_thread() and race["thread"] is None:
        probe = sqlite3.connect(core.DB_PATH, timeout=0)
        try:
            probe.execute("BEGIN IMMEDIATE")   # succeeds only if nobody holds the registry write lock
            race["locked"] = False
            probe.rollback()
        except sqlite3.OperationalError:
            race["locked"] = True
        finally:
            probe.close()
        race["thread"] = threading.Thread(target=lambda: race.update(result=core.customize_agent("analyst", {"objective": NEW_OBJ})))
        race["thread"].start()
        if not race["locked"]:
            race["thread"].join()   # without serialization the customization commits right here, in the middle of the refresh
    return out


core.build_soul = paused_build
err_refresh = None
try:
    core.refresh_specialist_souls()
except Exception as e:  # noqa: BLE001
    err_refresh = e
finally:
    core.build_soul = real_build
race["thread"].join()
con = sqlite3.connect(core.DB_PATH, timeout=30)
reg_obj = con.execute("SELECT objective FROM agents WHERE agent_id='analyst'").fetchone()[0]
con.close()
soul_now = (prof / "SOUL.md").read_text(encoding="utf-8")
after2 = {f.relative_to(prof).as_posix(): hashlib.sha256(f.read_bytes()).hexdigest() for f in prof.rglob("*") if f.is_file() and f.name != "SOUL.md" and ".customize-staging" not in f.parts}
check("RS-40 while the refresh sits between its registry read and its file write, the registry write lock is held (a Customize cannot commit in between)", race["locked"] is True, race)
check("RS-41 a Customize racing a refresh succeeds and its objective survives in BOTH the registry and the SOUL.md (the refresh's older snapshot never overwrites it)",
      err_refresh is None and race["result"] and race["result"].get("ok") and reg_obj == NEW_OBJ and NEW_OBJ in soul_now and OLD_OBJ not in soul_now, (err_refresh, race["result"], reg_obj[:40], soul_now[:160]))
check("RS-42 afterwards the profile is consistent: a further refresh finds nothing to rewrite, and the custom skill, memory and history are untouched", core.refresh_specialist_souls() == [] and before == after2, (before, after2))
shutil.rmtree(TMP, ignore_errors=True)
print(f"{sum(results)}/{len(results)} passed")
sys.exit(0 if results and all(results) else 1)
