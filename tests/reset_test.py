"""Reset-script test on a COPY of the project with fabricated demo state (never the real runtime). Run from the copy:
RESET_TEST_I_AM_A_COPY=1 python tests/reset_test.py"""
import json, os, shutil, sqlite3, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if os.environ.get("RESET_TEST_I_AM_A_COPY") != "1":
    sys.exit("Refusing to run: set RESET_TEST_I_AM_A_COPY=1 and run from a COPY of the project.")
RT, HOME = ROOT / "runtime", ROOT / "runtime" / "hermes_home"
results = []


def check(name, ok, detail=""):
    ok = bool(ok); results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{str(detail)[:300]}]"), flush=True)


def run(*args):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "reset_demo.py"), *args], capture_output=True, text=True, cwd=ROOT)


def mk_db(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path); c.execute("CREATE TABLE messages(id INTEGER PRIMARY KEY, content TEXT)")
    c.executemany("INSERT INTO messages(content) VALUES(?)", [(r,) for r in rows]); c.commit(); c.close()


# ---- fabricate demo state + things that must survive
shutil.rmtree(RT, ignore_errors=True)
SECRET = "SECRET-TOKEN-DO-NOT-LEAK-123"
for prof in ("main", "demo-analyst"):
    p = HOME / "profiles" / prof
    (p / "skills" / "s1").mkdir(parents=True); (p / "memories").mkdir(); (p / "plugins" / "ecom-agents").mkdir(parents=True)
    (p / "SOUL.md").write_text(f"# {prof} Northloom instructions"); (p / "skills" / "s1" / "SKILL.md").write_text("skill text")
    (p / "plans").mkdir()
    if prof == "main":   # the other profile keeps an EMPTY memories/ dir, like real ones (this once failed backup verification)
        (p / "memories" / "USER.md").write_text("prefers PURPLE-OTTER")
    (p / "config.yaml").write_text("model: {}\n")
    (p / "auth.json").write_text(json.dumps({"token": SECRET})); (p / ".env").write_text(f"KEY={SECRET}")
    mk_db(p / "state.db", ["hello", "world", "northloom chat"])
(HOME / "auth.json").write_text(json.dumps({"providers": {"openai-codex": {"tokens": {"access_token": SECRET}}}}))
(HOME / "config.yaml").write_text("model:\n  provider: openai-codex\n  default: gpt-test\n")
(RT / "hf_cache").mkdir(); (RT / "hf_cache" / "weights.bin").write_text("model weights")
(RT / "ca_bundle.pem").write_text("-----BEGIN CERTIFICATE-----")
(ROOT / "secrets").mkdir(exist_ok=True); (ROOT / "secrets" / "local.env").write_text(f"LLM_PROVIDER=openai-codex\nLLM_MODEL=gpt-test\nNEBIUS_API_KEY={SECRET}\n")
(ROOT / "data").mkdir(exist_ok=True); (ROOT / "data" / "company.json").write_text('{"name": "Northloom Apparel"}')
a = sqlite3.connect(RT / "app.db")
a.executescript("CREATE TABLE agents(agent_id TEXT, name TEXT); CREATE TABLE messages(id INTEGER PRIMARY KEY, agent_id TEXT, content TEXT);")
a.execute("INSERT INTO agents VALUES('demo-analyst','Demo')"); a.execute("INSERT INTO messages(agent_id,content) VALUES('main','hi')"); a.commit(); a.close()
(RT / "timing.jsonl").write_text("{}\n")
(ROOT / "outside_sentinel.txt").write_text("must survive")

# ---- dry run changes nothing
r = run()
check("dry run lists targets and removes nothing", r.returncode == 0 and "Dry run" in r.stdout and (HOME / "profiles" / "main" / "SOUL.md").exists(), r.stdout + r.stderr)
# ---- real run
r = run("--yes")
out = r.stdout + r.stderr
check("reset ran and reports a verified backup", r.returncode == 0 and "Backup verified" in out, out)
check("no secret value appears in the script output", SECRET not in out)
bk = sorted((ROOT / "backups").glob("demo-reset-*"))
check("one dated project-local backup exists", len(bk) == 1, bk)
b = bk[0] if bk else ROOT
man = json.loads((b / "manifest.json").read_text())
check("backup holds app.db, company data and both profiles' SOUL, skills, memories and conversation DB",
      all((b / "profiles" / p / x).exists() for p in ("main", "demo-analyst") for x in ("SOUL.md", "skills/s1/SKILL.md", "memories", "plans", "state.db", "config.yaml"))
      and (b / "app.db").exists() and (b / "company" / "data" / "company.json").exists(), sorted(man["files"])[:12])
chk = sqlite3.connect(b / "profiles" / "main" / "state.db"); n = chk.execute("select count(*) from messages").fetchone()[0]; chk.close()
check("backed-up conversation DB is intact (3 rows)", n == 3)
check("credentials were NOT copied into the backup", not any(f.name in ("auth.json", ".env") for f in b.rglob("*")) and SECRET not in "".join(f.read_text(errors="ignore") for f in b.rglob("*") if f.is_file()))
check("demo state removed: app.db, company data, old profile, diagnostics",
      not (RT / "app.db").exists() and not (ROOT / "data" / "company.json").exists() and not (HOME / "profiles" / "demo-analyst").exists()
      and not (RT / "timing.jsonl").exists())
main = HOME / "profiles" / "main"
check("clean main recreated without old memories/conversations",
      main.exists() and "PURPLE-OTTER" not in "".join(f.read_text(errors="ignore") for f in main.rglob("*") if f.is_file() and f.suffix in (".md", ".yaml", ".json")) and
      "Northloom" not in (main / "SOUL.md").read_text(), list(main.glob("*"))[:6])
check("login, config, secrets, TLS bundle, model cache and unrelated files preserved",
      SECRET in (HOME / "auth.json").read_text() and "gpt-test" in (HOME / "config.yaml").read_text() and (ROOT / "secrets" / "local.env").exists()
      and (RT / "ca_bundle.pem").exists() and (RT / "hf_cache" / "weights.bin").exists() and (ROOT / "outside_sentinel.txt").exists())
# ---- one-time
r2 = run("--yes")
check("second run is refused (one-time)", r2.returncode != 0 and "already ran" in (r2.stdout + r2.stderr), r2.stdout + r2.stderr)
check("normal startup code path never calls the reset", "reset_demo" not in (ROOT / "app" / "server.py").read_text() + (ROOT / "scripts" / "setup.py").read_text() + ((ROOT / "run.bat").read_text() if (ROOT / "run.bat").exists() else ""))
print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if results and all(results) else 1)
