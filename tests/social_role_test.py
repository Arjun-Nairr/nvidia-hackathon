"""V2-01 tests: main can create an independent social_media specialist beside the market analyst. SCRIPTED reasoning model (tests/mock_llm.py;
CALL_TOOL markers make main call tools with exact arguments) and the REAL backend, HTTP API and Hermes workers; the classifier is off here (real-Laya
routing is covered by tests/route_table.py and tests/routing_e2e_mock.py). Wiring, grants, isolation and enforcement only: this is NOT evidence of model
quality, and nothing here calls a subscription model, scraper, Gemini or Nebius.
Part A (pure/in-process): role registry, validation, per-role baseline, creation-role guard, routing decision rules.
Part B (real server + workers): creation through main, profile files, grants, direct chats, memory isolation, restart, main-only authority.
Wipes the copy's runtime/ - run ONLY from a COPY of the project:
  SOCIAL_I_AM_A_COPY=1 venv-python tests/social_role_test.py"""
import hashlib, json, os, re, shutil, subprocess, sys, time, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if os.environ.get("SOCIAL_I_AM_A_COPY") != "1":
    sys.exit("Refusing to run: set SOCIAL_I_AM_A_COPY=1 and run from a COPY of the project.")
sys.path.insert(0, str(ROOT))
MOCK, APP = 8777, 8826
ENV = {**os.environ, "PYTHONUTF8": "1", "ECOM_CLASSIFIER": "off"}
for k in ("LLM_PROVIDER", "LLM_MODEL", "NEBIUS_API_KEY", "NEBIUS_BASE_URL", "NEBIUS_MODEL", "ECOM_APP_ROOT", "HERMES_HOME"):
    ENV.pop(k, None)
procs, results = [], []


def check(name, ok, detail=""):
    ok = bool(ok); results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{str(detail)[:700]}]"), flush=True)


# ---------------------------------------------------------------- Part A: pure checks (no server, no model)
os.environ["ECOM_APP_ROOT"] = str(ROOT)
os.environ["HERMES_HOME"] = str(ROOT / "runtime" / "hermes_home" / "profiles" / "main")
from app import core, roles, routing, turn_state, hermes_plugin as hp

SOC_TOOLS = ["inspect_image", "memory", "read_catalogue", "read_company_context", "skills"]
MA_FULL = ["marketplace_locate", "marketplace_search", "marketplace_item", "marketplace_photo", "inspect_image", "read_catalogue", "save_listing_draft"]
GOOD_SKILL = [{"name": "feed-flyer-checklist", "content": "# Feed flyer checklist\n1. Confirm product facts and the declared price from the catalogue.\n2. One message, one lead photo.\n3. Two copy options."}]


def args(role="social_media", **kw):
    base = {"role": role, "name": "Acme Social Media Specialist" if role == "social_media" else "Acme Competitor Analyst",
            "objective": "Turn Acme Linens' supplied product facts into accurate promotional briefs and copy for its bedding range.",
            "instructions": "You work for Acme Linens (fictional). Use only supplied product facts and declared prices; say plainly what you cannot do.",
            "company_context_refs": [], "skills": GOOD_SKILL, "requested_tools": ["inspect_image", "read_catalogue"]}
    base.update(kw)
    return base


c, e = core.validate_create_agent(args())
check("A1 social_media validates: requested tools plus the mandatory foundation (read_company_context, memory, skills), nothing else",
      e is None and c["tools"] == SOC_TOOLS and c["role"] == "social_media", (e, c and c["tools"]))
ok_ma, e = core.validate_create_agent(args("market_analysis", requested_tools=MA_FULL))
check("A2 market_analysis behaviour is unchanged: all seven eligible tools plus the foundation validate",
      e is None and ok_ma["tools"] == sorted(set(MA_FULL) | {"read_company_context", "memory", "skills"}), (e, ok_ma and ok_ma["tools"]))
for bad in (["marketplace_search"], ["save_listing_draft"], ["read_recorded_evidence"], ["facebook_ad_research"], ["image_generation"], ["web_search"]):
    c, e = core.validate_create_agent(args(requested_tools=bad))
    check(f"A3 social_media cannot be granted {bad[0]} (not implemented for / not connected to this role): tool_not_permitted lists only its own tools",
          e and e["code"] == "tool_not_permitted" and set(e["allowed_values"]) == set(SOC_TOOLS) | set(core.AD_TOOLS) | set(core.FLYER_TOOLS), e)   # V2-03 added the fb_* tools, V2-04 the flyer tools
c, e = core.validate_create_agent(args("email"))
check("A4 unknown/email roles stay unsupported and the corrective error names the two supported roles",
      e and e["code"] == "unsupported_role" and e["allowed_values"] == ["market_analysis", "social_media"], e)
c, e = core.validate_create_agent(args(skills=[{"name": roles.SOCIAL_BASELINE_SKILL_NAME, "content": GOOD_SKILL[0]["content"]}]))
check("A5 a social custom skill named like ITS baseline is rejected", e and e["code"] == "duplicate_baseline_skill", e)
c, e = core.validate_create_agent(args(skills=[{"name": "my-copy", "content": roles.SOCIAL_BASELINE_SKILL}]))
check("A5b a social custom skill that copies ITS baseline text is rejected", e and e["code"] == "duplicate_baseline_skill", e)
c, e = core.validate_create_agent(args("market_analysis", skills=[{"name": "my-copy", "content": roles.BASELINE_SKILL}], requested_tools=[]))
check("A5c the analyst's duplicate-baseline rule is unchanged", e and e["code"] == "duplicate_baseline_skill", e)
check("A6 the two roles share no foundation text: different baseline names, responsibilities and skill bodies; no analyst text in the social baseline",
      roles.FOUNDATIONS["social_media"]["baseline_name"] != roles.FOUNDATIONS["market_analysis"]["baseline_name"]
      and core._similar(roles.SOCIAL_BASELINE_SKILL, roles.BASELINE_SKILL) < 0.5 and roles.SOCIAL_RESPONSIBILITIES != roles.RESPONSIBILITIES
      and "competitor-analysis-baseline" not in roles.SOCIAL_BASELINE_SKILL + roles.SOCIAL_RESPONSIBILITIES
      and "market-analysis" not in roles.SOCIAL_BASELINE_SKILL.lower() + roles.SOCIAL_RESPONSIBILITIES.lower())
check("A6b eligible social tools are the implemented ones only (V2-03 six fb_* ad-research tools, V2-04 generate_flyer/read_flyer; Marketplace tools stay out; posting stays not connected)",
      set(core.ROLES["social_media"]["eligible_tools"]) == {"read_company_context", "memory", "skills", "inspect_image", "read_catalogue", *core.AD_TOOLS, *core.FLYER_TOOLS}
      and not any(k.startswith("marketplace_") for k in core.ROLES["social_media"]["eligible_tools"])
      and "social_posting" in core.ROLES["social_media"]["not_connected"] and "image_generation" not in core.ROLES["social_media"]["not_connected"]
      and "facebook_ad_research" not in core.ROLES["social_media"]["not_connected"])

# the creation guard: classification only guides; the role the backend classified is the only role that may be created
turn_state.route = None
g0 = turn_state.create_allowed() is False and turn_state.create_allowed("social_media") is False
turn_state.route = {"outcome": "create_social_agent", "allow_create_agent": True, "role": "social_media"}
g1 = (turn_state.create_allowed(), turn_state.create_allowed("social_media"), turn_state.create_allowed("market_analysis"))
turn_state.route = {"outcome": "create_market_agent", "allow_create_agent": True, "role": "market_analysis"}
g2 = (turn_state.create_allowed("market_analysis"), turn_state.create_allowed("social_media"))
turn_state.route = {"outcome": "business_query", "allow_create_agent": False, "role": None}
g3 = turn_state.create_allowed("social_media")
turn_state.route = {"outcome": "classifier_off_test_only", "allow_create_agent": True}
g4 = (turn_state.create_allowed("social_media"), turn_state.create_allowed("market_analysis"))
check("A7 create_allowed: fail-closed without a route; a creation route allows ONLY its classified role; business_query allows none; the test seam allows any supported role",
      g0 and g1 == (True, True, False) and g2 == (True, False) and g3 is False and g4 == (True, True), (g0, g1, g2, g3, g4))
turn_state.route = {"outcome": "create_social_agent", "allow_create_agent": True, "role": "social_media"}
blocked = hp._block_create_unless_allowed(tool_name="create_agent", args={"role": "market_analysis"})
passed = hp._block_create_unless_allowed(tool_name="create_agent", args={"role": "social_media"})
tool_refusal = json.loads(hp._guarded_create({"role": "market_analysis"}))
turn_state.route = {"outcome": "business_query", "allow_create_agent": False, "role": None}
blocked2 = hp._block_create_unless_allowed(tool_name="create_agent", args={"role": "social_media"})
turn_state.route = None
check("A8 plugin hook and tool body both refuse a role other than the routed one, and any role on a non-creation route",
      blocked and blocked["action"] == "block" and passed is None and tool_refusal.get("code") == "role_not_permitted_for_request"
      and blocked2 and blocked2["action"] == "block", (blocked, passed, tool_refusal, blocked2))
desc = hp.CREATE_SCHEMA["description"]
check("A9 the create_agent description covers BOTH roles with their own guidance, names the ad tools and the flyer tool for the social role",
      "ROLE market_analysis" in desc and "ROLE social_media" in desc and "fb_ads_search" in desc and "generate_flyer" in desc
      and "market_analysis or social_media" in hp.CREATE_SCHEMA["parameters"]["properties"]["role"]["description"])

# routing decision rules (pure; the real Laya's probabilities are covered by tests/route_table.py)
ro = routing._role_outcome
check("A10 role decision: social wins only with a clear margin; a close call, an unsupported role and a weak signal never create",
      ro({"social_media": 0.70, "market_analysis": 0.20, "email": 0.05, "other_role": 0.05})[0] == "create_social_agent"
      and ro({"social_media": 0.45, "market_analysis": 0.40, "email": 0.1, "other_role": 0.05})[0] == "clarification"
      and ro({"social_media": 0.50, "market_analysis": 0.30, "email": 0.1, "other_role": 0.1})[0] == "clarification"
      and ro({"social_media": 0.62, "market_analysis": 0.22, "email": 0.1, "other_role": 0.06})[0] == "create_social_agent"
      and ro({"social_media": 0.55, "market_analysis": 0.50, "email": 0.0, "other_role": 0.0})[0] == "clarification"
      and ro({"market_analysis": 0.60, "social_media": 0.2, "email": 0.1, "other_role": 0.1})[0] == "create_market_agent"
      and ro({"email": 0.75, "social_media": 0.1, "market_analysis": 0.1, "other_role": 0.05})[0] == "unsupported_role"
      and ro({"social_media": 0.30, "market_analysis": 0.25, "email": 0.25, "other_role": 0.2})[0] == "clarification")
res = [routing._result(o, "", r, None, {}, [{"model_ms": 0}], 0, [{"agent_id": "x-analyst", "name": "X Analyst", "role": "market_analysis"}], {"name": "Acme"},
                       {"complete": True, "missing_labels": []}) for o, r in (("create_social_agent", "social_media"), ("create_market_agent", "market_analysis"),
                                                                           ("business_query", None), ("unsupported_role", "email"))]
check("A11 allow_create_agent is true only for the two creation outcomes; the social context names the role, lists existing specialists with their roles and "
      "says to point to an existing one unless another is explicitly requested; the unsupported reply offers both supported roles",
      [r["allow_create_agent"] for r in res] == [True, True, False, False] and "only for role social_media" in res[0]["context"]
      and "x-analyst, role market_analysis" in res[0]["context"] and "explicitly asks for another" in res[0]["context"]
      and "only for role market_analysis" in res[1]["context"] and "social-media specialist" in res[3]["reply"] and "market-analysis specialist" in res[3]["reply"])
os.environ.pop("HERMES_HOME", None)


# ---------------------------------------------------------------- Part B: real server + workers + scripted model
def call(path, body=None, port=APP):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=600); return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def tool(agent, name, a):
    st, r = call(f"/api/chat/{agent}", {"message": "CALL_TOOL:" + json.dumps({"name": name, "args": a})})
    outs = [json.loads(t["output"]) for t in r.get("tools", []) if t.get("name") == name and t.get("output")]
    return (outs[0] if outs else None), r


def start_server():
    p = subprocess.Popen([sys.executable, "-m", "app.server", str(APP)], cwd=ROOT, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(p)
    for _ in range(80):
        try: call("/api/status"); return p
        except Exception: time.sleep(0.5)
    raise RuntimeError("server did not start")


def stop(p):
    p.terminate(); p.wait(); time.sleep(2)


def tree_text(p):
    return "".join(f.read_text(encoding="utf-8", errors="ignore") for f in Path(p).rglob("*") if f.is_file() and f.suffix in (".md", ".yaml", ".json", ".txt"))


def tools_seen(reply):
    m = re.search(r"tools \[(.*)\]", reply or "")
    return sorted(x.strip(" '\"") for x in m.group(1).split(",")) if m else []


def mem_text(aid):
    d = ROOT / "runtime" / "hermes_home" / "profiles" / aid / "memories"
    return "".join(f.read_text(encoding="utf-8", errors="ignore") for f in d.glob("*.md")) if d.exists() else ""


try:
    shutil.rmtree(ROOT / "runtime", ignore_errors=True)
    (ROOT / "secrets").mkdir(exist_ok=True)
    (ROOT / "secrets" / "local.env").write_text(f"LLM_PROVIDER=nebius-token-factory\nLLM_MODEL=mock-model\nNEBIUS_API_KEY=mock-key\nNEBIUS_BASE_URL=http://127.0.0.1:{MOCK}/v1\n", encoding="utf-8")
    subprocess.run([sys.executable, "scripts/setup.py"], cwd=ROOT, env=ENV, check=True, capture_output=True)
    procs.append(subprocess.Popen([sys.executable, "tests/mock_llm.py", str(MOCK)], cwd=ROOT, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(1)
    srv = start_server()
    main_soul = (ROOT / "runtime" / "hermes_home" / "profiles" / "main" / "SOUL.md").read_text(encoding="utf-8")
    check("B1 main's setup instructions name both roles, separate main's own capabilities from specialists', and no longer say that research is blanket not connected",
          "market_analysis" in main_soul and "social_media" in main_soul and "NO research, scraping, image, posting or email tools" in main_soul
          and "Facebook Marketplace research exists only for a market_analysis specialist" in main_soul
          and "Live market research, web access, scraping, email and posting are NOT connected yet" not in main_soul
          and "Specialists are independent" in main_soul, main_soul[:300])

    # ---- creation refused until the company exists (backend authority), then the company is saved
    out, r = tool("main", "create_agent", args())
    check("B2 creation of a social specialist is refused with company_incomplete on a blank company; nothing created",
          out and out.get("code") == "company_incomplete" and call("/api/agents")[1] == [], out)
    st, co = call("/api/company", {"fields": {"name": "Acme Linens (fictional demo merchant)", "products": "Quilted coverlets and cotton bedding (fictional demo)",
                                              "customers": "Home buyers in the US (fictional demo)", "goal": "Present our bedding clearly and accurately to shoppers"}})
    check("B3 company saved through the form path", st == 200 and call("/api/company")[1]["status"]["complete"], co)

    # ---- analyst first (existing behaviour), then the social specialist, both through main's real create_agent tool
    ma, r = tool("main", "create_agent", args("market_analysis", requested_tools=MA_FULL,
                                              skills=[{"name": "price-tier-review", "content": "# Price tier review\n1. List the merchant's price tiers.\n2. Compare each to what was found.\n3. Mark unknowns."}]))
    check("B4 main creates the market analyst: baseline competitor-analysis-baseline + custom skill, all seven requested tools plus the foundation granted",
          ma and ma.get("ok") and ma["skills"] == ["competitor-analysis-baseline", "price-tier-review"] and ma["granted_tools"] == sorted(set(MA_FULL) | {"read_company_context", "memory", "skills"}), ma)
    so, r = tool("main", "create_agent", args())
    print("   ACTUAL scripted creation response (social_media):", json.dumps(so))
    check("B5 main creates the social-media specialist: baseline social-media-flyer-baseline + custom skill; granted tools = requested + foundation; no ad/generation tool",
          so and so.get("ok") and so["skills"] == ["social-media-flyer-baseline", "feed-flyer-checklist"] and so["granted_tools"] == SOC_TOOLS
          and so["approval_requirements"][-1]["requirement"].startswith("only with the granted generate_flyer"), so)
    aid_ma, aid_so = ma["agent_id"], so["agent_id"]
    agents = call("/api/agents")[1]
    check("B6 both agents are registered side by side with their own roles; creating the second did not touch the first (no paired creation, no deletion)",
          [(a["agent_id"], a["role"]) for a in agents] == [(aid_ma, "market_analysis"), (aid_so, "social_media")], agents)

    # ---- profile files
    pm, ps = ROOT / "runtime" / "hermes_home" / "profiles" / aid_ma, ROOT / "runtime" / "hermes_home" / "profiles" / aid_so
    soul_m, soul_s = (pm / "SOUL.md").read_text(encoding="utf-8"), (ps / "SOUL.md").read_text(encoding="utf-8")
    check("B7 each profile holds only its own baseline skill file plus its own custom skill (no inherited skill)",
          sorted(p.name for p in (pm / "skills").iterdir() if (p / "SKILL.md").exists()) == ["competitor-analysis-baseline", "price-tier-review"]
          and sorted(p.name for p in (ps / "skills").iterdir() if (p / "SKILL.md").exists()) == ["feed-flyer-checklist", "social-media-flyer-baseline"], (list((pm / "skills").iterdir()), list((ps / "skills").iterdir())))
    check("B8 social SOUL: its own role, fixed responsibilities and baseline; states ad research/generation and publishing are NOT connected; no analyst text",
          "social-media specialist" in soul_s and roles.SOCIAL_RESPONSIBILITIES.splitlines()[0] in soul_s and "social-media-flyer-baseline" in soul_s
          and "Facebook ad research and image or flyer generation are NOT connected" in soul_s and "cannot produce or publish" in soul_s
          and "competitor-analysis-baseline" not in soul_s and "market-analysis specialist" not in soul_s and "marketplace_search" not in soul_s, soul_s[:600])
    check("B9 analyst SOUL is unchanged in shape: market-analysis role, its own baseline, Marketplace research paragraph, no social text",
          "market-analysis specialist" in soul_m and "competitor-analysis-baseline" in soul_m and "marketplace_locate" in soul_m and "social-media" not in soul_m, soul_m[:400])

    # ---- direct chats, tool exposure per role, no recursion
    rm, rs = call(f"/api/chat/{aid_ma}", {"message": "hello analyst"})[1], call(f"/api/chat/{aid_so}", {"message": "hello social"})[1]
    tm, ts = tools_seen(rm["text"]), tools_seen(rs["text"])
    check("B10 both specialists chat directly (unrouted); the analyst sees its Marketplace/draft toolsets, the social specialist only company/memory/skills/catalogue/image tools",
          rm["ok"] and rs["ok"] and rm["route"] is None and rs["route"] is None and "marketplace_search" in tm and "save_listing_draft" in tm
          and "read_catalogue" in ts and "inspect_image" in ts and "read_company_context" in ts
          and not any(t.startswith("marketplace_") or t in ("save_listing_draft", "read_recorded_evidence", "create_agent", "update_company") for t in ts), (tm, ts))
    before = call(f"/api/agents/{aid_so}")[1]
    o1, r1 = tool(aid_so, "create_agent", args(name="Recursive Social Child"))
    o2, r2 = tool(aid_so, "update_company", {"name": "Hijacked Name"})
    o3, r3 = tool(aid_ma, "create_agent", args(name="Recursive Analyst Child"))
    after = call(f"/api/agents/{aid_so}")[1]
    check("B11 specialists cannot create agents or edit company facts (the tools do not exist for them); grants unchanged; no agent or company change",
          o1 is None and o2 is None and o3 is None and "not available" in r1["text"] and "not available" in r2["text"] and "not available" in r3["text"]
          and before == after and len(call("/api/agents")[1]) == 2 and call("/api/company")[1]["company"]["name"] == "Acme Linens (fictional demo merchant)", (r1["text"][:120], before == after))
    up, r = tool("main", "update_company", {"brand": "Calm, plain-spoken, no hype (fictional demo)"})
    check("B12 main alone can update company facts (updated_by main); the specialists' saved SOUL is not rewritten by the edit",
          up and up.get("ok") and call("/api/company")[1]["updated_by"] == "main" and (ps / "SOUL.md").read_text(encoding="utf-8") == soul_s, up)

    # ---- memory isolation + persistence across a restart
    call(f"/api/chat/{aid_so}", {"message": "remember: sign every creative brief off with PURPLE-OTTER"})
    call(f"/api/chat/{aid_ma}", {"message": "remember: always end reports with TEAL-HERON"})
    ms, mm, mmain = mem_text(aid_so), mem_text(aid_ma), mem_text("main")
    check("B13 each specialist's own memory holds only its own preference; the other specialist and main do not see it",
          "PURPLE-OTTER" in ms and "TEAL-HERON" not in ms and "TEAL-HERON" in mm and "PURPLE-OTTER" not in mm and "PURPLE-OTTER" not in mmain and "TEAL-HERON" not in mmain, (ms, mm, mmain))
    hist_so, hist_ma = len(call(f"/api/chat/{aid_so}")[1]), len(call(f"/api/chat/{aid_ma}")[1])
    soul_hash = hashlib.sha256((ps / "SOUL.md").read_bytes()).hexdigest()
    stop(srv)
    srv = start_server()
    agents2 = call("/api/agents")[1]
    rs2 = call(f"/api/chat/{aid_so}", {"message": "what do you remember about sign-offs?"})[1]
    rm2 = call(f"/api/chat/{aid_ma}", {"message": "what do you remember about sign-offs?"})[1]
    check("B14 after an app restart: both agents, roles, grants and transcripts persist and both still chat",
          [(a["agent_id"], a["role"], a["granted_tools"]) for a in agents2] == [(aid_ma, "market_analysis", ma["granted_tools"]), (aid_so, "social_media", SOC_TOOLS)]
          and len(call(f"/api/chat/{aid_so}")[1]) >= hist_so and len(call(f"/api/chat/{aid_ma}")[1]) >= hist_ma and rs2["ok"] and rm2["ok"], (agents2, hist_so, hist_ma))
    ts2, tm2 = tools_seen(rs2["text"]), tools_seen(rm2["text"])
    check("B15 after the restart each specialist's own memory is still its own (nothing leaked across), and each worker still derives its toolsets from its OWN role "
          "(analyst: Marketplace and draft tools; social: no Marketplace tool)",
          "PURPLE-OTTER" in mem_text(aid_so) and "TEAL-HERON" not in mem_text(aid_so) and "TEAL-HERON" in mem_text(aid_ma) and "PURPLE-OTTER" not in mem_text(aid_ma)
          and "marketplace_search" in tm2 and "save_listing_draft" in tm2 and "inspect_image" in ts2 and not any(t.startswith("marketplace_") for t in ts2),
          (ts2, tm2))
    check("B16 the social SOUL file is byte-identical after the restart", hashlib.sha256((ps / "SOUL.md").read_bytes()).hexdigest() == soul_hash)
    check("B17 neither specialist profile contains the other's name, skills or memory text",
          "price-tier-review" not in tree_text(ps) and "feed-flyer-checklist" not in tree_text(pm) and "Acme Social Media Specialist" not in tree_text(pm), "")
    page = urllib.request.urlopen(f"http://127.0.0.1:{APP}/", timeout=30).read().decode("utf-8")
    check("B19 the served page no longer claims blanket 'live market research: not connected' and labels the goal role-neutrally (string changes only)",
          "granted per specialist" in page and "Live market research: <b>not connected" not in page and "Competitor-analysis goal" not in page and "Business goal" in page)
    check("B18 creating a second social specialist with the same name is refused (name_taken); duplicate protection is unchanged",
          (tool("main", "create_agent", args())[0] or {}).get("code") == "name_taken")
finally:
    for p in procs:
        try: p.terminate()
        except Exception: pass
print(f"\n{sum(results)}/{len(results)} checks passed (scripted model: wiring/enforcement only, NOT live model behaviour)")
sys.exit(0 if results and all(results) else 1)
