"""Ticket 01 regression: (A) company updates are transactional across PROCESSES and failures are explicit; (B) the same through the real
application paths (form API + main's update_company tool in a real Hermes worker, scripted model); (C) mandatory specialist capabilities.
Scripted model (tests/mock_llm.py): wiring and enforcement only, NOT a provider test. Wipes the copy's runtime/ - run ONLY from a COPY:
  TICKET01_I_AM_A_COPY=1 venv-python tests/ticket01_regression.py
Part A needs no Hermes. Races are provoked, not forced: each loop is repeated until contention is dense; on correct code every
acknowledged update must survive, on the unfixed code lost updates show up within the first rounds."""
import json, os, shutil, subprocess, sys, tempfile, threading, time, urllib.request, urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def writer_main(field, n, start_at):   # child process: own field, sequential updates, verify each acknowledged value is visible
    from app import core
    while time.time() < start_at:
        pass
    lost = rejected = exc = 0
    for i in range(n):
        v = f"{field}-{i}"
        try:
            r = core.update_company({field: v}, source="form")
        except Exception:
            exc += 1; continue
        if not r.get("ok"):
            rejected += 1; continue
        if core.load_company().get(field) != v:
            lost += 1
    print(json.dumps({"field": field, "lost": lost, "rejected": rejected, "exc": exc}))


if len(sys.argv) > 1 and sys.argv[1] == "--writer":
    writer_main(sys.argv[2], int(sys.argv[3]), float(sys.argv[4])); sys.exit(0)
if len(sys.argv) > 1 and sys.argv[1] == "--hold-lock":   # child process that holds the company transaction lock
    from app import core
    with core.company_lock():
        print("locked", flush=True); time.sleep(float(sys.argv[2]))
    sys.exit(0)

if os.environ.get("TICKET01_I_AM_A_COPY") != "1":
    sys.exit("Refusing to run: set TICKET01_I_AM_A_COPY=1 and run from a COPY of the project.")
MOCK, APP = 8772, 8821
ENV = {**os.environ, "PYTHONUTF8": "1", "ECOM_CLASSIFIER": "off"}
for k in ("LLM_PROVIDER", "LLM_MODEL", "NEBIUS_API_KEY", "NEBIUS_BASE_URL", "NEBIUS_MODEL", "ECOM_APP_ROOT"):
    ENV.pop(k, None)
procs, results = [], []


def check(name, ok, detail=""):
    ok = bool(ok); results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{str(detail)[:600]}]"), flush=True)


# ============ A. storage: separate processes, one company file (isolated temp root; no server, no Hermes) ============
TMP = Path(tempfile.mkdtemp(prefix="t01_"))
os.environ["ECOM_APP_ROOT"] = str(TMP)
from app import core
CPATH = core.COMPANY_PATH
CENV = {**ENV, "ECOM_APP_ROOT": str(TMP)}
print(f"-- A. isolated storage {TMP}", flush=True)


def reset_company(**f):
    shutil.rmtree(core.RUNTIME, ignore_errors=True)
    core.RUNTIME.mkdir(parents=True)
    if f:
        CPATH.write_text(json.dumps({**core._blank_company(), **f}), encoding="utf-8")


FIELDS = ["products", "customers", "goal", "brand", "competitors"]
tot = {"lost": 0, "rejected": 0, "exc": 0, "blank_reads": 0, "final_wrong": 0}
for rnd in range(3):
    reset_company(name="Seed Co")
    start = time.time() + 3
    ps = [subprocess.Popen([sys.executable, __file__, "--writer", f, "40", str(start)], env=CENV, stdout=subprocess.PIPE, text=True) for f in FIELDS]
    stop, blank = threading.Event(), [0]

    def reader(stop=stop, blank=blank):
        while not stop.is_set():
            if core.load_company().get("name") != "Seed Co":
                blank[0] += 1
    th = threading.Thread(target=reader); th.start()
    outs = [json.loads(p.communicate()[0].strip().splitlines()[-1]) for p in ps]
    stop.set(); th.join()
    fin = core.load_company()
    wrong = [f for f in FIELDS if fin.get(f) != f"{f}-39"]
    r = {"lost": sum(o["lost"] for o in outs), "rejected": sum(o["rejected"] for o in outs), "exc": sum(o["exc"] for o in outs), "blank_reads": blank[0], "final_wrong": len(wrong)}
    print(f"   round {rnd + 1}: 5 processes x 40 updates -> {r}  final fields missing/stale: {wrong}", flush=True)
    for k in tot: tot[k] += r[k]
check("A1 separate processes updating different fields concurrently: every acknowledged update survives, none errors",
      tot["lost"] == 0 and tot["exc"] == 0 and tot["rejected"] == 0 and tot["final_wrong"] == 0, tot)
check("A2 concurrent readers never see a blank/partial company while writers run", tot["blank_reads"] == 0, tot)

reset_company(name="Seed Co")
tl = {"lost": 0, "exc": 0}


def tw(f):
    for i in range(40):
        v = f"{f}-{i}"
        try:
            ok = core.update_company({f: v}, source="main").get("ok")
        except Exception:
            tl["exc"] += 1; continue
        if not ok or core.load_company().get(f) != v:
            tl["lost"] += 1
ts = [threading.Thread(target=tw, args=(f,)) for f in FIELDS]
[t.start() for t in ts]; [t.join() for t in ts]
check("A3 threads inside one process (server request threads) also lose nothing", tl == {"lost": 0, "exc": 0} and all(core.load_company().get(f) == f"{f}-39" for f in FIELDS), tl)

# ---- explicit failures: nothing is reported saved that was not saved
reset_company(name="Seed Co", products="Soy candles")
before = CPATH.read_bytes()
core.COMPANY_LOCK_TIMEOUT = 0.5
holder = subprocess.Popen([sys.executable, __file__, "--hold-lock", "30"], env=CENV, stdout=subprocess.PIPE, text=True)
got = holder.stdout.readline().strip()   # "locked" once the holder owns the lock; empty if it could not start
t0 = time.time()
try:
    r = core.update_company({"goal": "Learn rival prices"}, source="form")
except Exception as e:
    r = {"ok": "raised", "error": repr(e)}
el = time.time() - t0
check("A4 lock held by another process: explicit storage error within the timeout, nothing written",
      got == "locked" and r.get("ok") is False and r.get("code") == "company_storage_error" and el < 5 and CPATH.read_bytes() == before, (got, r, round(el, 1)))
holder.kill(); holder.wait()
try:
    r = core.update_company({"goal": "Learn rival prices"}, source="form")
except Exception as e:
    r = {"ok": "raised", "error": repr(e)}
check("A5 the lock dies with a hard-killed holder: the next update succeeds immediately", r.get("ok") is True and core.load_company()["goal"] == "Learn rival prices", r)

reset_company(name="Seed Co", products="Soy candles")
before = CPATH.read_bytes()
real_replace = os.replace
def broken_replace(*a, **k): raise OSError(28, "No space left on device")
os.replace = broken_replace
try:
    try:
        r = core.update_company({"goal": "Learn rival prices"}, source="form")
    except Exception as e:
        r = {"ok": "raised", "error": repr(e)}
finally:
    os.replace = real_replace
check("A6 write fails (disk full): explicit storage error, saved data unchanged, no leftover temp file",
      r.get("ok") is False and r.get("code") == "company_storage_error" and CPATH.read_bytes() == before
      and not [p for p in core.RUNTIME.iterdir() if p.suffix == ".tmp" or ".tmp" in p.name], (r, [p.name for p in core.RUNTIME.iterdir()]))

CPATH.write_text("{ this is not json", encoding="utf-8")
try:
    r = core.update_company({"goal": "Learn rival prices"}, source="form")
except Exception as e:
    r = {"ok": "raised", "error": repr(e)}
check("A7 unreadable saved file: explicit error and the file is NOT overwritten (no silent data loss)",
      r.get("ok") is False and r.get("code") == "company_storage_error" and CPATH.read_text(encoding="utf-8") == "{ this is not json", r)
reset_company()
r = core.update_company({"name": "Fresh Co"}, source="form")
check("A8 absent file is still a normal blank start (first save creates it; response shape unchanged)",
      r.get("ok") is True and r["changed"] == ["name"] and set(r) == {"ok", "changed", "company", "complete", "missing", "missing_labels"}
      and core.load_company()["updated_by"] == "form", r)

VA = {"role": "market_analysis", "name": "Acme Analyst", "objective": "Help Acme Candles compare rival gift-set prices using only evidence the owner supplies.",
      "instructions": "You analyse competitors for Acme Candles. Use only the company context and what the owner tells you; label assumptions; never invent prices.",
      "skills": [{"name": "gift-set-price-review", "content": "# Gift-set price review\n1. Read the company context.\n2. Ask which gift sets to compare.\n3. End with two actions."}]}
got = {}
for label, req in [("empty", []), ("memory only", ["memory"]), ("omitted", None), ("web_search", ["web_search"]), ("memory+email", ["memory", "email"]),
                   ("string", "memory")]:
    a = dict(VA) if req is None else {**VA, "requested_tools": req}
    try:
        c, e = core.validate_create_agent(a)
        got[label] = (sorted(c["tools"]), None) if c else (None, e["code"])
    except Exception as ex:
        got[label] = ("raised", repr(ex))
M = ["memory", "read_company_context", "skills"]
check("A9 validation: empty/partial/omitted requests get all mandatory tools; web_search, memory+email and a non-list are rejected BEFORE grants",
      got == {"empty": (M, None), "memory only": (M, None), "omitted": (M, None), "web_search": (None, "tool_not_permitted"),
              "memory+email": (None, "tool_not_permitted"), "string": (None, "bad_tools")}, got)
shutil.rmtree(TMP, ignore_errors=True)

# ============ B/C. real application paths: server + Hermes workers + scripted model ============
os.environ.pop("ECOM_APP_ROOT", None)


def call(path, body=None, port=APP):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=600); return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def tool(agent, name, args):
    st, r = call(f"/api/chat/{agent}", {"message": "CALL_TOOL:" + json.dumps({"name": name, "args": args})})
    outs = []
    for t in r.get("tools", []):
        if t.get("name") == name and t.get("output"):
            try:
                outs.append(json.loads(t["output"]))
            except ValueError:   # the stored activity output is truncated for long results (e.g. a whole skill file)
                outs.append({"_raw": t["output"]})
    return (outs[0] if outs else None), r


def start_server():
    p = subprocess.Popen([sys.executable, "-m", "app.server", str(APP)], cwd=ROOT, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(p)
    for _ in range(80):
        try: call("/api/status"); return p
        except Exception: time.sleep(0.5)
    raise RuntimeError("server did not start")


try:
    print("-- B. real form + main-tool paths", flush=True)
    shutil.rmtree(ROOT / "runtime", ignore_errors=True)
    shutil.rmtree(ROOT / "data", ignore_errors=True)
    (ROOT / "secrets").mkdir(exist_ok=True)
    (ROOT / "secrets" / "local.env").write_text(f"LLM_PROVIDER=nebius-token-factory\nLLM_MODEL=mock-model\nNEBIUS_API_KEY=mock-key\nNEBIUS_BASE_URL=http://127.0.0.1:{MOCK}/v1\n", encoding="utf-8")
    subprocess.run([sys.executable, "scripts/setup.py"], cwd=ROOT, env=ENV, check=True, capture_output=True)
    procs.append(subprocess.Popen([sys.executable, "tests/mock_llm.py", str(MOCK)], cwd=ROOT, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(1)
    srv = start_server()
    st, r = call("/api/company", {"fields": {"name": "Acme Candles"}})
    assert st == 200, r

    # B1. form threads (3 fields) hammer POST /api/company while main's real worker saves `products` through its tool, 30 turns
    stop, lost, errs, acks = threading.Event(), [0], [0], {"customers": None, "brand": None, "competitors": None}

    def form_thread(f):
        i = 0
        while not stop.is_set():
            i += 1; v = f"{f}-{i}"
            try:
                st, r = call("/api/company", {"fields": {f: v}})
            except Exception:
                errs[0] += 1; continue
            if st != 200 or not r.get("ok"):
                errs[0] += 1; continue
            acks[f] = v
            if call("/api/company")[1]["company"][f] != v:
                lost[0] += 1
    fts = [threading.Thread(target=form_thread, args=(f,)) for f in acks]
    [t.start() for t in fts]
    main_lost = main_err = 0
    n_main = 30
    for i in range(n_main):
        v = f"products-{i}"
        out, r = tool("main", "update_company", {"products": v})
        if not (out and out.get("ok")):
            main_err += 1; continue
        if call("/api/company")[1]["company"]["products"] != v:
            main_lost += 1
    stop.set(); [t.join() for t in fts]
    final = call("/api/company")[1]["company"]
    form_final_ok = all(final[f] == acks[f] for f in acks if acks[f])
    print(f"   {n_main} main-tool saves overlapping {sum(1 for v in acks.values() if v)} form writers: main lost {main_lost}, main errors {main_err}, "
          f"form lost {lost[0]}, form errors {errs[0]}, last acked form values {acks}", flush=True)
    check("B1 overlapping form saves and main-tool saves (real paths): every acknowledged value is still saved",
          main_lost == 0 and main_err == 0 and lost[0] == 0 and errs[0] == 0 and form_final_ok and final["products"] == f"products-{n_main - 1}", (main_lost, main_err, lost[0], errs[0], final, acks))
    snap = call("/api/company")[1]["company"]
    srv.terminate(); srv.wait(); srv = start_server()
    check("B2 the final company survives a server restart unchanged", call("/api/company")[1]["company"] == snap)
    st, r = call("/api/company", {"fields": {"name": "Acme Candles", "products": "Hand-poured soy candles and gift sets", "goal": "Understand how rival candle brands price gift sets",
                                              "customers": "Gift buyers in the UK"}})
    check("B3 company complete (needed for creation checks)", st == 200 and r["complete"], r)

    # B4. explicit storage failure through both real paths: saved file replaced by a directory
    cp, bak = ROOT / "runtime" / "company.json", ROOT / "runtime" / "company.json.bak-test"
    good = call("/api/company")[1]["company"]
    os.replace(cp, bak); cp.mkdir()
    form_ok = tool_ok = False; st = r = out = None
    try:
        try:
            st, r = call("/api/company", {"fields": {"goal": "THIS MUST NOT BE REPORTED AS SAVED"}})
            form_ok = st >= 500 and r.get("ok") is False and r.get("code") == "company_storage_error"
        except Exception as e:   # e.g. the server dropped the connection on an unhandled exception
            r = repr(e)
        try:
            out, rr = tool("main", "update_company", {"goal": "THIS MUST NOT BE REPORTED AS SAVED"})
            tool_ok = bool(out) and out.get("ok") is False and out.get("code") == "company_storage_error"
        except Exception as e:
            out = repr(e)
    finally:
        cp.rmdir(); os.replace(bak, cp)
    check("B4 storage failure: form API returns an explicit error status and the main tool returns ok:false (nothing claimed saved)", form_ok and tool_ok, (st, r, out))
    check("B5 after the failure the saved company is exactly what it was", call("/api/company")[1]["company"] == good)

    # ============ C. mandatory capabilities ============
    print("-- C. mandatory specialist capabilities", flush=True)
    base = {"role": "market_analysis",
            "objective": "Help Acme Candles understand how competing candle brands price and position themselves so the owner can set gift-set prices with evidence.",
            "instructions": "You analyse competitors for Acme Candles, which sells hand-poured soy candles to gift buyers. Use only the company context and what the owner tells you; label assumptions; never invent prices.",
            "skills": [{"name": "gift-set-price-review", "content": "# Gift-set price review\n1. Read the company context.\n2. Ask the owner which gift sets and competitors to compare.\n3. Compare only evidenced prices; list unknowns; end with two concrete actions."}]}
    MANDATORY = ["memory", "read_company_context", "skills"]
    made = {}
    for label, nm, extra in [("empty list", "Acme Analyst Empty", {"requested_tools": []}), ("partial: memory only", "Acme Analyst Partial", {"requested_tools": ["memory"]}),
                             ("key omitted", "Acme Analyst Omitted", {}), ("full list", "Acme Analyst Full", {"requested_tools": ["read_company_context", "memory", "skills"]})]:
        out, r = tool("main", "create_agent", {**base, "name": nm, **extra})
        aid = out and out.get("agent_id")
        reg = call(f"/api/agents/{aid}")[1] if aid else {}
        made[label] = aid
        check(f"C1 create with {label}: response, registry grants are all mandatory tools", out and out.get("ok") and sorted(out["granted_tools"]) == MANDATORY and sorted(reg.get("granted_tools", [])) == MANDATORY, (out, reg.get("granted_tools")))
    aid = made["empty list"]
    st, r = call(f"/api/chat/{aid}", {"message": "hi"})
    names = r["text"].split("tools ", 1)[-1]
    check("C2 the worker's actual toolsets (what the model can call) carry memory + skill tools + company context for an empty request",
          r["ok"] and all(n in names for n in ("memory", "skill_view", "skills_list", "read_company_context")) and "create_agent" not in names and "update_company" not in names, r["text"])
    print("   tools the model saw:", names[:200], flush=True)
    o, rr = tool(aid, "skill_view", {"name": "competitor-analysis-baseline"})
    sv = json.dumps(o) if o else rr.get("text", "")
    check("C3 specialist (empty request) can load its baseline skill with skill_view", o is not None and "Evidence" in sv, sv[:300])
    o, rr = tool(aid, "skill_view", {"name": "gift-set-price-review"})
    check("C4 ... and its custom skill", o is not None and "Gift-set price review" in json.dumps(o), (rr.get("text") or "")[:300])
    pdir = ROOT / "runtime" / "hermes_home" / "profiles"
    call(f"/api/chat/{aid}", {"message": "remember: sign every report with PURPLE-OTTER"})
    mem = "".join(f.read_text(encoding="utf-8") for f in (pdir / aid / "memories").glob("*.md")) if (pdir / aid / "memories").exists() else ""
    other = made["partial: memory only"]
    omem = "".join(f.read_text(encoding="utf-8") for f in (pdir / other / "memories").glob("*.md")) if (pdir / other / "memories").exists() else ""
    mmem = "".join(f.read_text(encoding="utf-8") for f in (pdir / "main" / "memories").glob("*.md")) if (pdir / "main" / "memories").exists() else ""
    check("C5 specialist (empty request) uses its OWN persistent memory; another specialist and main do not see it", "PURPLE-OTTER" in mem and "PURPLE-OTTER" not in omem + mmem, (mem, omem))
    o, rr = tool(aid, "create_agent", {**base, "name": "Rogue Analyst", "requested_tools": []})
    o2, rr2 = tool(aid, "update_company", {"goal": "hijack"})
    check("C6 specialist cannot create agents or update company details (tools not exposed)", o is None and o2 is None and "not available" in rr["text"] and "not available" in rr2["text"]
          and call("/api/company")[1]["company"]["goal"] != "hijack" and len(call("/api/agents")[1]) == 4, (rr["text"], rr2["text"]))
    # specialist-facing company context stays limited to granted sections
    o, rr = tool(aid, "read_company_context", {"section": "brand"})
    check("C7 ungranted optional section is still refused for the specialist", o is not None and o.get("code") == "section_not_granted", o)

    n0 = len(call("/api/agents")[1])
    for label, nm, tools in [("out-of-set tool", "Acme Analyst Web", ["web_search"]), ("valid + out-of-set", "Acme Analyst Mixed", ["memory", "email"])]:
        out, r = tool("main", "create_agent", {**base, "name": nm, "requested_tools": tools})
        check(f"C8 {label} is still rejected (validated before mandatory grants); nothing created",
              out and out.get("ok") is False and out.get("code") == "tool_not_permitted" and len(call("/api/agents")[1]) == n0, out)
    srv.terminate(); srv.wait(); srv = start_server()
    reg = {a["agent_id"]: call(f"/api/agents/{a['agent_id']}")[1]["granted_tools"] for a in call("/api/agents")[1]}
    check("C9 after restart every registry record still has all mandatory tools", len(reg) == 4 and all(sorted(v) == MANDATORY for v in reg.values()), reg)
    st, r = call(f"/api/chat/{aid}", {"message": "hi again"})
    check("C10 after restart the empty-request specialist still gets the full toolsets", r["ok"] and all(n in r["text"] for n in ("memory", "skill_view", "read_company_context")), r["text"])
finally:
    for p in procs:
        p.terminate()
    shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if results and all(results) else 1)
