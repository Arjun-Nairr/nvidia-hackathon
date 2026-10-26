"""Plumbing test through REAL Hermes (profiles, plugin tool, memory, sessions) with a SCRIPTED model (tests/mock_llm.py).
This proves wiring only. It is NOT a Nebius/NVIDIA inference test. Destroys and recreates ./runtime.
Run: python tests/e2e_mock.py"""
import json, os, shutil, subprocess, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
MOCK_PORT, APP_PORT = 8766, 8801
ENV = {**os.environ, "NEBIUS_API_KEY": "mock-key", "NEBIUS_BASE_URL": f"http://127.0.0.1:{MOCK_PORT}/v1",
       "NEBIUS_MODEL": "mock-model", "LLM_PROVIDER": "nebius-token-factory", "LLM_MODEL": "mock-model", "PYTHONUTF8": "1", "ECOM_CLASSIFIER": "off"}
os.environ.update({k: ENV[k] for k in ("NEBIUS_API_KEY", "NEBIUS_BASE_URL", "NEBIUS_MODEL", "LLM_PROVIDER", "LLM_MODEL")})
procs, results = [], []


def check(name, ok, detail=""):
    ok = bool(ok); results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""), flush=True)


def api(path, body=None):
    req = urllib.request.Request(f"http://127.0.0.1:{APP_PORT}{path}", data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=300).read())


def start_server():
    p = subprocess.Popen([sys.executable, "-m", "app.server", str(APP_PORT)], cwd=ROOT, env=ENV,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(p)
    for _ in range(40):
        try:
            api("/api/status"); return p
        except Exception:
            time.sleep(0.25)
    raise RuntimeError("server did not start")


try:
    shutil.rmtree(ROOT / "runtime", ignore_errors=True)
    subprocess.run([sys.executable, "scripts/setup.py"], cwd=ROOT, env=ENV, check=True, capture_output=True)
    import shutil as _sh
    (ROOT / "runtime").mkdir(exist_ok=True); _sh.copy(ROOT / "tests" / "fixtures" / "company_example.json", ROOT / "runtime" / "company.json")  # test company (production starts blank)
    procs.append(subprocess.Popen([sys.executable, "tests/mock_llm.py", str(MOCK_PORT)], cwd=ROOT,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(1)
    srv = start_server()

    # unit-level validation (no model involved)
    from app import core
    base = json.loads(json.dumps(__import__("tests.mock_llm", fromlist=["x"]).AGENT_ARGS))
    for label, patch, code in [("unsupported role", {"role": "seo_expert"}, "unsupported_role"),
                               ("web_search tool", {"requested_tools": ["web_search"]}, "tool_not_permitted"),
                               ("unknown tool", {"requested_tools": ["terminal"]}, "tool_not_permitted"),
                               ("bad context ref", {"company_context_refs": ["secrets"]}, "bad_context_refs"),
                               ("too many skills", {"skills": [{"name": f"extra-skill-{i}", "content": "x" * 50} for i in range(4)]}, "bad_skills"),
                               ("short instructions", {"instructions": "be good"}, "too_short")]:
        r = core.create_agent({**base, **patch})
        check(f"validation: {label} -> {code}", r.get("ok") is False and r.get("code") == code and isinstance(r.get("error"), str), r)
    check("validation: invalid requests created nothing", api("/api/agents") == [])

    # model-driven: invalid requests come back as structured errors through the real tool call
    for tag, code in [("BAD_ROLE", "unsupported_role"), ("BAD_TOOL", "tool_not_permitted")]:
        r = api("/api/chat/main", {"message": f"{tag} create a market analysis agent"})
        outs = [t.get("output", "") for t in r["tools"] if t.get("output")]
        check(f"main agent tool call with {tag} returns {code}", any(code in o for o in outs), r["tools"])

    # natural-language request -> create_agent
    r = api("/api/chat/main", {"message": "Please create a market analysis specialist for our company"})
    calls = [t for t in r["tools"] if t.get("name") == "create_agent" and t.get("input")]
    out = next((json.loads(t["output"]) for t in r["tools"] if t.get("name") == "create_agent" and t.get("output")), {})
    check("main agent called create_agent", len(calls) == 1, r)
    check("create_agent result shape", out.get("ok") and out.get("agent_id") and out.get("conversation_id") and out.get("state") == "idle"
          and sorted(out.get("granted_tools", [])) == ["memory", "read_company_context", "skills"] and out.get("approval_requirements"), out)
    aid = out["agent_id"]
    d = api(f"/api/agents/{aid}")
    check("agent registered with company-specific instructions + skill", "Northloom" in d["instructions"] and len(d["skills"]) == 1, d)
    pdir = ROOT / "runtime/hermes_home/profiles" / aid
    check("separate profile on disk (SOUL + skill)", "Northloom" in (pdir / "SOUL.md").read_text(encoding="utf-8")
          and (pdir / "skills/competitor-review/SKILL.md").exists())
    check("profile is separate from main", (ROOT / "runtime/hermes_home/profiles/main") != pdir and not (pdir / "memories/MEMORY.md").exists())
    # section grant enforcement
    with core.db() as c:
        c.execute("UPDATE agents SET context_refs=? WHERE agent_id=?", (json.dumps(["brand"]), aid))
    check("read_company_context enforces grants", core.read_company_context("products", aid).get("code") == "section_not_granted"
          and core.read_company_context("brand", aid).get("ok"))
    with core.db() as c:
        c.execute("UPDATE agents SET context_refs=? WHERE agent_id=?", (json.dumps(d["context_refs"]), aid))

    # direct specialist chat + memory
    r = api(f"/api/chat/{aid}", {"message": "hi"})
    check("direct specialist chat works", r["text"].startswith("[MOCK LLM]") and not r["error"], r)
    tools_seen = r["text"]
    check("specialist toolset includes skill_manage + memory, excludes create_agent", "skill_manage" in tools_seen and "memory" in tools_seen
          and "create_agent" not in tools_seen, tools_seen)
    api(f"/api/chat/{aid}", {"message": "remember: always sign reports with PURPLE-OTTER"})
    mem = (pdir / "memories/USER.md")
    check("preference saved to specialist memory file", mem.exists() and "PURPLE-OTTER" in mem.read_text(encoding="utf-8"))
    check("main profile memory untouched", "PURPLE-OTTER" not in "".join(p.read_text(encoding="utf-8") for p in (ROOT / "runtime/hermes_home/profiles/main/memories").glob("*.md")))
    n_before = len(api(f"/api/chat/{aid}"))

    # restart everything
    srv.terminate(); srv.wait()
    start_server()
    agents = api("/api/agents")
    check("agent identity survives restart", len(agents) == 1 and agents[0]["agent_id"] == aid and agents[0]["state"] == "idle", agents)
    check("app transcript survives restart", len(api(f"/api/chat/{aid}")) == n_before and n_before >= 4)
    r = api(f"/api/chat/{aid}", {"message": "still there?"})
    seen = int(r["text"].split("I can see ")[1].split(" messages")[0])
    check("Hermes conversation resumes after restart (model sees prior turns)", seen > 6, r["text"])
    r = core.run_turn(aid, "what do I like?", conv_override="fresh-session-check")
    check("memory preference available to a new session after restart", "PURPLE-OTTER" in r["text"], r)

    # missing key must be reported, never mocked
    saved = {k: os.environ.pop(k) for k in ("NEBIUS_API_KEY", "NEBIUS_BASE_URL")}
    sec_file = ROOT / "secrets/local.env"
    r = core.run_turn("main", "hello")
    os.environ.update(saved)
    check("missing key -> explicit error naming secrets/local.env", "secrets/local.env" in (r.get("error") or "") and not r["text"], r)
finally:
    for p in procs:
        p.terminate()
print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
