"""Run the ticket-05 live harness (tests/research_live_check.py) in a throwaway copy of the project and ARCHIVE its outputs before that copy is deleted.

  python scripts/research_live_launch.py --live-authorized            # REAL ScrapeCreators + CDN + subscription model; spends the live allowance
  python scripts/research_live_launch.py --scripted --mock-llm-port N # scripted local services (tests); never live evidence
  add --via-main [--scope NAME] [--retain-runtime] with --workdir DIR for the V1 clean demonstration (specialist created by the real main agent; the run's
  whole runtime is KEPT at DIR after the archive is verified, with the copied login and API keys removed from it)

Archive rule (the lesson of the first live run, whose only copy of the database was deleted after the harness crashed):
 1. everything the harness prints is streamed straight into <archive>/<stamp>/harness.log (kept even if the harness is killed);
 2. after the harness exits - whatever its exit code - research_live_result.json and runtime/timing.jsonl are copied to <archive>/<stamp>/ and the
    copied result is verified (exists, parses, same sha256);
 3. ONLY THEN is the copy deleted. If the result is missing or the copy did not verify, the copy is RETAINED and its path is printed (exit 3);
 4. manifest.json records mode, exit codes, file hashes and whether the copy was deleted.
The real runtime, credentials and the diagnostic ledger are never modified; the copy gets only the provider/model lines, the ScrapeCreators key line,
the copied login and TLS bundle (real mode). No marketplace_check ledger/evidence/photos are copied. Nothing is retried."""
import argparse, hashlib, json, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEEP_KEYS = ("LLM_PROVIDER", "LLM_MODEL", "SCRAPECREATORS_API_KEY")


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def scrub_files(folder, secrets):
    """Replace each secret value in the archived text files (the harness scrubs its JSON; stdout logs are scrubbed here)."""
    for f in Path(folder).iterdir():
        if f.suffix in (".log", ".json", ".jsonl") and f.is_file():
            t = f.read_text(encoding="utf-8", errors="replace")
            u = t
            for sec in secrets:
                if sec and len(sec) >= 8:
                    u = u.replace(sec, "***")
            if u != t:
                f.write_text(u, encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--live-authorized", action="store_true", help="required for a real run (it spends the live allowance); never implied")
    ap.add_argument("--scripted", action="store_true", help="scripted local services (needs --mock-llm-port); archive behaviour tests")
    ap.add_argument("--mock-llm-port", type=int)
    ap.add_argument("--archive-dir", default=str(ROOT / "research" / "live-archive"))
    ap.add_argument("--workdir")
    ap.add_argument("--via-main", action="store_true", help="create the specialist through the real main-agent flow (needs the local Laya classifier in real mode)")
    ap.add_argument("--scope", help="research allowance scope name for this run (fresh runtime = fresh scope)")
    ap.add_argument("--retain-runtime", action="store_true", help="keep the verified runtime at --workdir (credentials removed) instead of deleting it")
    a = ap.parse_args(argv)
    if a.retain_runtime and not a.workdir:
        print("--retain-runtime needs --workdir (a stable folder)")
        return 2
    if a.scripted == a.live_authorized:
        print("choose exactly one of --live-authorized (real) or --scripted (tests)")
        return 2
    if a.scripted and not a.mock_llm_port:
        print("--scripted needs --mock-llm-port")
        return 2
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    dest = Path(a.archive_dir) / (stamp + ("-scripted" if a.scripted else "-live"))
    dest.mkdir(parents=True, exist_ok=False)
    work = Path(a.workdir) if a.workdir else Path(tempfile.mkdtemp(prefix="research_live_"))
    manifest = {"stamp": stamp, "mode": "scripted" if a.scripted else "live", "via_main": a.via_main, "scope": a.scope, "workdir": str(work), "copy_deleted": False,
                "files": {}}

    def write_manifest():
        (dest / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    try:
        for d in ("app", "scripts", "tests"):
            shutil.copytree(ROOT / d, work / d, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "live-archive"), dirs_exist_ok=True)
        (work / "secrets").mkdir(exist_ok=True)
        if a.scripted:
            lines = ["LLM_PROVIDER=nebius-token-factory", "LLM_MODEL=mock-model", "NEBIUS_API_KEY=mock-key", f"NEBIUS_BASE_URL=http://127.0.0.1:{a.mock_llm_port}/v1"]
        else:
            src = ROOT / "secrets" / "local.env"
            lines = [l for l in src.read_text(encoding="utf-8").splitlines() if l.split("=", 1)[0].strip() in KEEP_KEYS]
            if not any(l.startswith("SCRAPECREATORS_API_KEY=") and l.split("=", 1)[1].strip() for l in lines):
                raise RuntimeError("SCRAPECREATORS_API_KEY is not configured in secrets/local.env")
            (work / "runtime" / "hermes_home").mkdir(parents=True, exist_ok=True)
            for rel in ("runtime/hermes_home/auth.json", "runtime/hermes_home/config.yaml", "runtime/ca_bundle.pem"):
                shutil.copy2(ROOT / rel, work / rel)
        (work / "secrets" / "local.env").write_text("\n".join(lines) + "\n", encoding="ascii")
        env = {**os.environ, "PYTHONUTF8": "1", "RESEARCH_LIVE_I_AM_A_COPY": "1"}
        env.pop("SSLKEYLOGFILE", None)
        if a.via_main:
            env["RESEARCH_LIVE_VIA_MAIN"] = "1"
        if a.scope:
            env["RESEARCH_LIVE_SCOPE"] = a.scope
        if a.scripted:
            env["RESEARCH_LIVE_SCRIPTED"] = "1"
            if a.via_main:
                env["ECOM_CLASSIFIER"] = "off"   # test seam: scripted runs have no Laya
        else:
            if a.via_main:   # main's requests are classified by the project's real local Laya (read-only use of its environment and model cache)
                laya, hf = ROOT / ".venv-laya" / "Scripts" / "python.exe", ROOT / "runtime" / "hf_cache"
                if not laya.is_file() or not hf.is_dir():
                    raise RuntimeError("the local Laya classifier (.venv-laya, runtime/hf_cache) is not available; main-agent routing cannot run")
                env["ECOM_LAYA_PY"], env["ECOM_HF_CACHE"] = str(laya), str(hf)
            for k in ("SCRAPECREATORS_API_KEY", "RESEARCH_LIVE_SCRIPTED", "RESEARCH_LIVE_INJECT_FAIL", "ECOM_SCRAPECREATORS_URL", "ECOM_PHOTO_HOSTS", "ECOM_CLASSIFIER",
                      "ECOM_APP_ROOT", "ECOM_RESEARCH_RUN_API_MAX", "ECOM_RESEARCH_RUN_IMAGE_MAX", "ECOM_VISION_MODELS", "ECOM_IMAGE_DIRS", "ECOM_CATALOGUE_FILE",
                      "ECOM_EVIDENCE_FILE", "ECOM_CHAT_MAX_ITERATIONS", "ECOM_RESEARCH_MAX_ITERATIONS"):   # an ambient override must not change a live run
                env.pop(k, None)
        with (dest / "setup.log").open("w", encoding="utf-8") as lf:
            rc = subprocess.run([sys.executable, str(work / "scripts" / "setup.py")], cwd=work, env=env, stdout=lf, stderr=subprocess.STDOUT).returncode
        manifest["setup_exit"] = rc
        if rc != 0:
            raise RuntimeError(f"setup failed (exit {rc}); see setup.log")
        with (dest / "harness.log").open("w", encoding="utf-8") as lf:      # streamed: survives a crash or kill of the harness
            rc = subprocess.run([sys.executable, str(work / "tests" / "research_live_check.py")], cwd=work, env=env, stdout=lf, stderr=subprocess.STDOUT).returncode
        manifest["harness_exit"] = rc
    except BaseException as e:   # launcher-level failure: keep the copy, keep what exists
        manifest["launcher_error"] = f"{type(e).__name__}: {str(e)[:300]}"
        rc = 4
    # ---- archive BEFORE any deletion
    verified = False
    try:
        secrets = [os.environ.get("SCRAPECREATORS_API_KEY", "")]
        envf = work / "secrets" / "local.env"
        if envf.is_file():
            secrets += [l.split("=", 1)[1].strip() for l in envf.read_text(encoding="utf-8").splitlines() if l.startswith(("SCRAPECREATORS_API_KEY=", "NEBIUS_API_KEY="))]
        res = work / "research_live_result.json"
        if res.is_file():
            shutil.copy2(res, dest / "result.json")
            json.loads((dest / "result.json").read_text(encoding="utf-8"))
            verified = sha(res) == sha(dest / "result.json")
        tm = work / "runtime" / "timing.jsonl"
        if tm.is_file():
            shutil.copy2(tm, dest / "timing.jsonl")
        scrub_files(dest, secrets)   # after the hash comparison above the copy is sanitized; the result file was sanitized by the harness already
    except Exception as e:
        manifest["archive_error"] = f"{type(e).__name__}: {str(e)[:300]}"
    for f in sorted(dest.iterdir()):
        if f.name != "manifest.json":
            manifest["files"][f.name] = {"bytes": f.stat().st_size, "sha256": sha(f)}
    manifest["archive_verified"] = verified
    if verified and a.retain_runtime:
        # keep the runtime for inspection, but never leave a copied login or API key in it: a retained copy could otherwise refresh the single-use
        # Codex token and invalidate the real login, and an idle copy has no reason to hold the scraper key
        removed = []
        for f in (work / "runtime" / "hermes_home").rglob("auth.json"):
            f.unlink()
            removed.append(str(f.relative_to(work)))
        envf = work / "secrets" / "local.env"
        if envf.is_file():
            keep = [l for l in envf.read_text(encoding="utf-8").splitlines() if l.split("=", 1)[0].strip() in ("LLM_PROVIDER", "LLM_MODEL")]
            envf.write_text("\n".join(keep) + "\n", encoding="ascii")
            removed.append("secrets/local.env: API keys")
        manifest["retained_runtime"] = {"path": str(work), "credentials_removed": removed,
                                        "start": f'cd /d "{work}" && "%LOCALAPPDATA%\\hermes\\hermes-agent\\venv\\Scripts\\python.exe" -m app.server 8840'}
        manifest["copy_deleted"] = False
    elif verified:
        for _ in range(15):   # a killed server's worker processes may still hold files for a moment (Windows): wait, then try again
            shutil.rmtree(work, ignore_errors=True)
            if not work.exists():
                break
            time.sleep(1)
        manifest["copy_deleted"] = not work.exists()
        if work.exists():
            manifest["copy_note"] = "archive verified but the copy could not be fully deleted (files still in use); remove it by hand"
    write_manifest()
    if not verified:
        print(f"ARCHIVE NOT VERIFIED: no readable result was produced. The throwaway copy is RETAINED at {work}; harness log kept in {dest}")
        return 3
    print(f"archived to {dest} (harness exit {manifest.get('harness_exit')}; copy deleted: {manifest['copy_deleted']})")
    return manifest.get("harness_exit", rc)


if __name__ == "__main__":
    sys.exit(main())
