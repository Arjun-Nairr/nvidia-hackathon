"""Onboarding + semi-prebuilt analyst, end to end through the real backend/Hermes workers with a SCRIPTED model (tests/mock_llm.py,
CALL_TOOL markers make main call tools with exact arguments). Wiring and enforcement only; NOT a model-quality test. Classifier is off
here (routing is covered by tests/routing_e2e_mock.py). Run ONLY from a COPY of the project (wipes the copy's runtime/):
  ONBOARDING_I_AM_A_COPY=1 venv-python tests/onboarding_mock.py"""
import hashlib, json, os, shutil, subprocess, sys, time, urllib.request, urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if os.environ.get("ONBOARDING_I_AM_A_COPY") != "1":
    sys.exit("Refusing to run: set ONBOARDING_I_AM_A_COPY=1 and run from a COPY of the project.")
sys.path.insert(0, str(ROOT))
MOCK, APP = 8771, 8820
ENV = {**os.environ, "PYTHONUTF8": "1", "ECOM_CLASSIFIER": "off"}
for k in ("LLM_PROVIDER", "LLM_MODEL", "NEBIUS_API_KEY", "NEBIUS_BASE_URL", "NEBIUS_MODEL"):
    ENV.pop(k, None)
procs, results = [], []


def check(name, ok, detail=""):
    ok = bool(ok); results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{str(detail)[:500]}]"), flush=True)


def call(path, body=None, port=APP):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=600); return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def tool(agent, name, args):
    """Make `agent` (scripted model) call a tool with exact args; returns (parsed tool output or None, whole response)."""
    st, r = call(f"/api/chat/{agent}", {"message": "CALL_TOOL:" + json.dumps({"name": name, "args": args})})
    outs = [json.loads(t["output"]) for t in r.get("tools", []) if t.get("name") == name and t.get("output")]
    return (outs[0] if outs else None), r


def start_server():
    p = subprocess.Popen([sys.executable, "-m", "app.server", str(APP)], cwd=ROOT, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(p)
    for _ in range(80):
        try: call("/api/status"); return p
        except Exception: time.sleep(0.5)
    raise RuntimeError("server did not start")


def tree_text(p):
    return "".join(f.read_text(encoding="utf-8", errors="ignore") for f in Path(p).rglob("*") if f.is_file() and f.suffix in (".md", ".yaml", ".json", ".txt"))


try:
    shutil.rmtree(ROOT / "runtime", ignore_errors=True)
    shutil.rmtree(ROOT / "data", ignore_errors=True)   # the demo fixture must not exist anywhere in production paths
    (ROOT / "secrets").mkdir(exist_ok=True)
    (ROOT / "secrets" / "local.env").write_text(f"LLM_PROVIDER=nebius-token-factory\nLLM_MODEL=mock-model\nNEBIUS_API_KEY=mock-key\nNEBIUS_BASE_URL=http://127.0.0.1:{MOCK}/v1\n", encoding="utf-8")
    subprocess.run([sys.executable, "scripts/setup.py"], cwd=ROOT, env=ENV, check=True, capture_output=True)
    procs.append(subprocess.Popen([sys.executable, "tests/mock_llm.py", str(MOCK)], cwd=ROOT, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(1)
    srv = start_server()
    main_dir = ROOT / "runtime" / "hermes_home" / "profiles" / "main"

    # ---- blank startup
    st, c = call("/api/company")
    check("blank start: company empty, four essentials missing, no agents, no company file", c["status"]["missing"] == ["name", "products", "customers", "goal"]
          and all(v == "" for v in c["company"].values()) and call("/api/agents")[1] == [] and not (ROOT / "runtime" / "company.json").exists(), c)
    check("no demo/Northloom/fictional text in the fresh main profile or sidebar data", not any(w in tree_text(main_dir) + json.dumps(c) for w in ("Northloom", "FICTIONAL", "fictional")))
    srv.terminate(); srv.wait(); srv = start_server()
    check("blank stays blank after restart (startup never restores a fixture)", not (ROOT / "runtime" / "company.json").exists() and call("/api/company")[1]["status"]["complete"] is False)

    # ---- missing essentials prevent creation (backend), with a corrective error
    ARGS = {"role": "market_analysis", "name": "Acme Candle Analyst",
            "objective": "Help Acme Candles understand how competing candle brands price and position themselves so the owner can set gift-set prices with evidence.",
            "instructions": "You analyse competitors for Acme Candles, which sells hand-poured soy candles to gift buyers. Use only the company context and what the owner tells you; label assumptions; never invent prices.",
            "skills": [{"name": "gift-set-price-review", "content": "# Gift-set price review\n1. Read the company context.\n2. Ask the owner which gift sets and competitors to compare.\n3. Compare only evidenced prices; list unknowns; end with two concrete actions."}],
            "requested_tools": ["read_company_context", "memory", "skills"], "company_context_refs": ["brand"]}
    out, r = tool("main", "create_agent", ARGS)
    check("create_agent on a blank company -> corrective company_incomplete error naming what is missing, nothing created",
          out and out["code"] == "company_incomplete" and "company name" in out["error"] and "target customers" in out["error"] and call("/api/agents")[1] == [], out)

    # ---- form edits (backend validation shared with main's tool)
    st, r = call("/api/company", {"fields": {"name": "Acme Candles", "products": "Hand-poured soy candles and gift sets"}})
    check("form save persists partial details and reports what is still missing", st == 200 and r["missing"] == ["customers", "goal"] and r["changed"] == ["name", "products"], r)
    for label, fields, code in [("placeholder rejected", {"customers": "unknown"}, "placeholder_value"), ("unknown field rejected", {"favourite_colour": "red"}, "unknown_field"),
                                ("bad website rejected", {"website": "not a url"}, "bad_website"), ("required field cannot be cleared", {"name": ""}, "required_field_empty")]:
        st, r = call("/api/company", {"fields": fields})
        check(f"form validation: {label}", st == 400 and r["code"] == code, (st, r))
    out, r = tool("main", "create_agent", ARGS)
    check("still incomplete (customers, goal): creation refused with exactly those missing", out and out["code"] == "company_incomplete" and out["allowed_values"] == ["customers", "goal"], out)

    # ---- conversational update through main's tool: same validation + storage
    out, r = tool("main", "update_company", {"customers": "unknown"})
    check("main's update_company rejects placeholders (does not store 'unknown')", out and out["code"] == "placeholder_value" and call("/api/company")[1]["company"]["customers"] == "", out)
    out, r = tool("main", "update_company", {"customers": "Gift buyers aged 25-45 in the UK", "goal": "Understand how rival candle brands price gift sets"})
    st, c = call("/api/company")
    check("main's update_company saved the stated answers; company now complete", out and out["ok"] and out["complete"] and c["status"]["complete"]
          and c["company"]["customers"].startswith("Gift buyers") and c["updated_by"] == "main", (out, c))
    out, r = tool("main", "update_company", {"competitors": "Wick & Co"})
    check("optional competitors stored only as given; other optionals stay unknown", out["ok"] and call("/api/company")[1]["company"]["brand"] == "" and call("/api/company")[1]["company"]["website"] == "")
    srv.terminate(); srv.wait(); srv = start_server()
    check("company details persist across restart", call("/api/company")[1]["company"]["name"] == "Acme Candles" and call("/api/company")[1]["status"]["complete"])

    # ---- semi-prebuilt analyst: baseline + custom, backend-owned tools
    out, r = tool("main", "create_agent", {**ARGS, "skills": [{"name": "competitor-analysis-baseline", "content": "x" * 60}]})
    check("main cannot supply the baseline skill again (duplicate rejected)", out and out["code"] == "duplicate_baseline_skill", out)
    out, r = tool("main", "create_agent", {**ARGS, "requested_tools": ["web_search"]})
    check("main cannot request a tool outside the role's eligible set", out and out["code"] == "tool_not_permitted" and call("/api/agents")[1] == [], out)
    out, r = tool("main", "create_agent", ARGS)
    aid = out and out.get("agent_id")
    check("analyst created; reports baseline + custom skills and backend-granted tools", out and out["ok"] and out["skills"] == ["competitor-analysis-baseline", "gift-set-price-review"]
          and sorted(out["granted_tools"]) == ["memory", "read_company_context", "skills"] and set(out["context_refs"]) >= {"profile", "products", "customers", "goal", "brand"}, out)
    pdir = ROOT / "runtime" / "hermes_home" / "profiles" / aid
    soul = (pdir / "SOUL.md").read_text(encoding="utf-8")
    check("profile has baseline skill file + custom skill file + responsibilities + company-specific text, no demo labels",
          (pdir / "skills" / "competitor-analysis-baseline" / "SKILL.md").exists() and (pdir / "skills" / "gift-set-price-review" / "SKILL.md").exists()
          and "Core responsibilities" in soul and "Acme Candles" in soul and "gift buyers" in soul and not any(w in tree_text(pdir) for w in ("Northloom", "fictional", "FICTIONAL")), soul[:300])
    check("baseline skill text contains the required topics",
          all(w in (pdir / "skills" / "competitor-analysis-baseline" / "SKILL.md").read_text(encoding="utf-8") for w in ("Evidence", "Assumption", "Unknown", "Missing information", "Recommended actions")))
    out2, r = tool("main", "create_agent", ARGS)
    check("same name again is refused (no silent regeneration/duplicate)", out2 and out2["code"] == "name_taken", out2)

    # ---- specialist chat, tool isolation, memory isolation, restart persistence
    st, r = call(f"/api/chat/{aid}", {"message": "hi"})
    names = r["text"].split("tools ")[-1]
    check("specialist chats directly and has NO create_agent / update_company tool", r["ok"] and "create_agent" not in names and "update_company" not in names and "read_company_context" in names, r["text"])
    o3, r3 = tool(aid, "create_agent", ARGS)
    check("specialist cannot call create_agent (not available)", o3 is None and "not available" in r3["text"], r3["text"])
    st, r = call(f"/api/chat/{aid}", {"message": "remember: always sign reports with PURPLE-OTTER"})
    mem = "".join(f.read_text(encoding="utf-8") for f in (pdir / "memories").glob("*.md"))
    check("preference saved to the specialist's own memory only", "PURPLE-OTTER" in mem and "PURPLE-OTTER" not in tree_text(main_dir), mem)
    soul_hash = hashlib.sha256(soul.encode()).hexdigest()
    st, r = call("/api/company", {"fields": {"goal": "Track gift-set price changes by three named rivals each month"}})
    soul_after = (pdir / "SOUL.md").read_text(encoding="utf-8")
    ctx, rr = tool(aid, "read_company_context", {})
    check("editing the company does not silently rewrite the specialist, which reads the new goal live",
          hashlib.sha256(soul_after.encode()).hexdigest() == soul_hash and ctx and "three named rivals" in json.dumps(ctx), ctx)
    n_rows = len(call(f"/api/chat/{aid}")[1])
    srv.terminate(); srv.wait(); srv = start_server()
    ags = call("/api/agents")[1]
    check("agent, its transcript, company and memory file survive restart", len(ags) == 1 and ags[0]["agent_id"] == aid and len(call(f"/api/chat/{aid}")[1]) == n_rows
          and "PURPLE-OTTER" in "".join(f.read_text(encoding="utf-8") for f in (pdir / "memories").glob("*.md")) and call("/api/company")[1]["company"]["name"] == "Acme Candles")
    st, r = call(f"/api/chat/{aid}", {"message": "count"})
    check("specialist conversation continues after restart", r["ok"] and int(r["text"].split("I can see ")[1].split(" messages")[0]) > 4, r["text"])
finally:
    for p in procs:
        p.terminate()
print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if results and all(results) else 1)
