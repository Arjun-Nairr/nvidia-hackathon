"""ONE-TIME demo reset (authorised once by Arjun). Backs up, verifies the backup, then removes the demo company context, agent registry,
transcripts and every profile (instructions, skills, memories, conversation DBs), and recreates a clean `main`.
Never run on startup; refuses to run twice (runtime/.demo-reset-done.json) or while the app/workers are running.
Preserved: login (runtime/hermes_home/auth.json + config.yaml), secrets/, TLS bundle, Laya/model caches, .venv-laya, all source.
Usage: python scripts/reset_demo.py            (dry run: prints what would be backed up/removed)
       python scripts/reset_demo.py --yes      (does it)"""
import hashlib, json, os, shutil, sqlite3, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / "runtime"
HOME = RUNTIME / "hermes_home"
PROFILES = HOME / "profiles"
MARKER = RUNTIME / ".demo-reset-done.json"
SECRET_NAMES = {"auth.json", "auth.lock", ".env"}          # credentials are never copied into the backup
SKIP_DIRS = {"__pycache__", "cache", "audio_cache", "image_cache", "sandboxes"}
DIAG = ["timing.jsonl", "timing_diag_last.json", "worker_live_diag_last.json", "route_table_last.json", "server.log"]


def inside(p):
    """Resolved path must be strictly inside this project, not the project/runtime/home roots themselves, and not a symlink."""
    p = Path(p)
    if p.is_symlink():
        raise SystemExit(f"REFUSING: {p} is a symlink")
    rp = p.resolve()
    rp.relative_to(ROOT.resolve())
    if rp in (ROOT.resolve(), RUNTIME.resolve(), HOME.resolve(), PROFILES.resolve()):
        raise SystemExit(f"REFUSING: {rp} is a protected root")
    return rp


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def running():
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -match 'app\\.server|app\\.worker|laya_worker|mock_llm' } | "
                              "ForEach-Object { \"$($_.ProcessId) $($_.Name)\" }"], capture_output=True, text=True, timeout=60).stdout
        return [l for l in out.splitlines() if l.strip()]
    except Exception:
        return ["could not check running processes"]


def copy_db(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    a, b = sqlite3.connect(src), sqlite3.connect(dst)
    a.backup(b); b.close(); a.close()
    c = sqlite3.connect(dst)
    ok = c.execute("PRAGMA integrity_check").fetchone()[0]
    c.close()
    if ok != "ok":
        raise SystemExit(f"backup of {src.name} failed integrity check: {ok}")


def copy_tree(src, dst):
    n = 0
    for dirpath, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        rel = Path(dirpath).relative_to(src)
        (dst / rel).mkdir(parents=True, exist_ok=True)   # keep the directory layout, including empty dirs such as memories/
        for f in files:
            if f in SECRET_NAMES:
                continue
            sp = Path(dirpath) / f
            if f.endswith((".db", ".db-wal", ".db-shm")):
                if f.endswith(".db"):
                    copy_db(sp, dst / rel / f); n += 1
                continue
            (dst / rel).mkdir(parents=True, exist_ok=True)
            shutil.copy2(sp, dst / rel / f); n += 1
    return n


def expected_count(src):
    n = 0
    for dirpath, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        n += sum(1 for f in files if f not in SECRET_NAMES and not f.endswith((".db-wal", ".db-shm")))
    return n


def main(do_it):
    if MARKER.exists():
        raise SystemExit(f"REFUSING: this one-time reset already ran ({MARKER.name}). Normal startup never resets data.")
    procs = running()
    if procs:
        raise SystemExit("REFUSING: stop the app, its workers and Laya first. Still running:\n  " + "\n  ".join(procs))
    targets = {"app_db": [RUNTIME / n for n in ("app.db", "app.db-wal", "app.db-shm")],
               "company": [RUNTIME / "company.json", ROOT / "data" / "company.json"],
               "profiles": sorted(p for p in PROFILES.glob("*") if p.is_dir()) if PROFILES.exists() else [],
               "diagnostics": [RUNTIME / n for n in DIAG], "logs": sorted((RUNTIME / "logs").glob("*")) if (RUNTIME / "logs").exists() else []}
    for group in targets.values():
        for t in group:
            inside(t)                                   # every reset target must be inside the project
    existing = {k: [t for t in v if t.exists()] for k, v in targets.items()}
    print("Reset targets (all inside the project):")
    for k, v in existing.items():
        for t in v:
            print(f"  [{k}] {t.relative_to(ROOT)}")
    print("Preserved: runtime/hermes_home/auth.json + config.yaml, secrets/, runtime/ca_bundle.pem, runtime/hf_cache, .venv-laya, source")
    if not do_it:
        print("\nDry run only. Re-run with --yes to back up, verify and reset.")
        return
    stamp = time.strftime("%Y%m%d-%H%M%S")
    bdir = ROOT / "backups" / f"demo-reset-{stamp}"
    inside(bdir.parent / "x")
    bdir.mkdir(parents=True)
    manifest = {"created": stamp, "profiles": {}, "files": {}}
    if (RUNTIME / "app.db").exists():
        copy_db(RUNTIME / "app.db", bdir / "app.db")
        c = sqlite3.connect(bdir / "app.db")
        manifest["app_db"] = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("agents", "messages")}
        c.close()
    for src in existing["company"]:
        dst = bdir / "company" / src.relative_to(ROOT)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    for src in existing["profiles"]:
        manifest["profiles"][src.name] = {"copied_files": copy_tree(src, bdir / "profiles" / src.name), "expected_files": expected_count(src)}
    for src in existing["diagnostics"] + [t for t in existing["logs"] if t.is_file()]:
        dst = bdir / "diagnostics" / src.relative_to(RUNTIME)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    for f in sorted(bdir.rglob("*")):
        if f.is_file():
            manifest["files"][str(f.relative_to(bdir))] = {"bytes": f.stat().st_size, "sha256": sha(f)}
    (bdir / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")

    # ---- verify the backup BEFORE removing anything
    problems = []
    for rel, meta in manifest["files"].items():
        f = bdir / rel
        if not f.is_file() or f.stat().st_size != meta["bytes"]:
            problems.append(f"missing/size mismatch: {rel}")
    for name, m in manifest["profiles"].items():
        if m["copied_files"] != m["expected_files"]:
            problems.append(f"profile {name}: copied {m['copied_files']} != expected {m['expected_files']}")
        src = PROFILES / name
        for must in ("SOUL.md", "config.yaml", "memories", "skills", "state.db"):
            if (src / must).exists() and not (bdir / "profiles" / name / must).exists():
                problems.append(f"profile {name}: {must} not in backup")
    if existing["app_db"] and not (bdir / "app.db").exists():
        problems.append("app.db not in backup")
    if any(t.name == "company.json" for t in existing["company"]) and not (bdir / "company").exists():
        problems.append("company data not in backup")
    if problems:
        raise SystemExit("BACKUP VERIFICATION FAILED, nothing was removed:\n  " + "\n  ".join(problems))
    print(f"Backup verified: {bdir.relative_to(ROOT)}  ({len(manifest['files'])} files, profiles: {sorted(manifest['profiles'])}, app.db rows: {manifest.get('app_db')})")

    # ---- reset
    for group in ("app_db", "company", "diagnostics"):
        for t in existing[group]:
            inside(t).unlink()
    for t in existing["profiles"]:
        shutil.rmtree(inside(t))
    for t in existing["logs"]:
        if t.is_file():
            inside(t).unlink()
    d = ROOT / "data"
    if d.exists() and not any(d.iterdir()):
        d.rmdir()
    # ---- clean main profile (credentials/config untouched; setup.py never reads or writes auth.json)
    subprocess.run([sys.executable, str(ROOT / "scripts" / "setup.py")], check=True, cwd=ROOT, capture_output=True)
    MARKER.write_text(json.dumps({"reset_at": stamp, "backup": str(bdir.relative_to(ROOT))}), encoding="utf-8")
    print("Reset done. Clean main profile recreated. Start the app with run.bat.")


if __name__ == "__main__":
    main("--yes" in sys.argv)
