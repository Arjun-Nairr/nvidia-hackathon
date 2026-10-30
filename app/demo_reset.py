"""Restart the demo: the ONE reset operation behind the in-app Restart demo button (server.reset_demo) and the fresh_demo.bat launcher. An explicit operator action, never an
agent tool. Archives the current demo progress, verifies the archive, and only then clears the progress in place; it never touches paid accounting, allowances, run evidence or
saved results, and it calls nothing external.

Progress = the onboarding row, the company context, the agent registry, every chat message, the customization log, the specialists' Hermes profiles and main's private memory,
sessions and history. Everything else in app.db stays as it is (research_*, ad_*, flyer_*, listing_drafts, image_inspections, the allowances and paid counters), as do credentials,
model configuration, prepared catalogue/photos and logs. Old results cannot reach the fresh demo: their agent ids are recorded in retired_agents and never handed out again
(core.free_agent_id), and message ids are AUTOINCREMENT, so no new message can take an old one's id.

Order and failure handling: a pending marker is written first (start-up refuses while it exists: refuse_if_pending), then the archive is copied and verified. A failure up to here
removes the partial archive and the marker and reports that NOTHING was cleared. After a verified archive, clearing runs (one SQLite transaction for the registry/messages, then
files); if it stops part-way the marker stays and running the reset again finishes it. The previous accounting in an archive is for reference only and is never restored."""
import hashlib, json, os, shutil, sqlite3, stat, time
from app import core, onboarding

ARCHIVES = core.RUNTIME / "demo_archives"
PENDING = core.RUNTIME / "demo_reset_pending.json"
PROGRESS_TABLES = ("agents", "messages", "agent_config_log", "onboarding")
RESULT_TABLES = ("listing_drafts", "research_runs", "ad_runs", "ad_packages", "flyer_runs", "image_inspections")   # tables whose agent_id ties a saved result to an agent
SECRET_NAMES = {"auth.json", "auth.lock", ".env"}                         # credentials are never copied into an archive
CACHE_DIRS = {"cache", "audio_cache", "image_cache", "__pycache__"}       # regenerable; not archived
MAIN_PRIVATE = ("memories", "sessions", "plans", "workspace", "home", "state.db", "state.db-wal", "state.db-shm", "prompt_stamps.json", ".skills_prompt_snapshot.json")
FINISH = ("Run fresh_demo.bat again to finish the restart (or press Restart demo if the app is still running). The previous progress is safe in {archive}.")
README = """Archived demo progress ({when} UTC)

app.db        the whole database at the moment of the restart (registry, chats, onboarding, customization log, AND the paid accounting of that moment)
company.json  the company context
profiles/     every Hermes profile (instructions, skills, private memory, sessions); credential files (.env, auth.json, auth.lock) and caches were not copied
manifest.json file hashes, progress row counts and the agent ids retired by this restart

To look something up, open app.db with any SQLite tool or read the files; nothing here is loaded by the app.
NEVER copy this app.db over runtime/app.db: its paid counters and allowances are older than the live ones and restoring them would hand out spent budget again.
To bring the old conversation back, stop the app and copy only progress rows (agents, messages, agent_config_log, onboarding), company.json and the profile folders back;
the old agent ids are listed in retired_agents and must then be removed from that table. Paid accounting is never restored from an archive.
"""


class Incomplete(Exception):
    pass


INVALID = ("The demo-restart marker runtime/demo_reset_pending.json cannot be used ({why}), so the app will not start and no restart will run: it cannot tell whether a restart was interrupted. "
           "Nothing was changed. If a restart did stop and a folder under runtime/demo_archives has a manifest.json, replace the marker's content with "
           '{{"archive": "runtime/demo_archives/<that folder>", "stage": "clearing"}} and run fresh_demo.bat; if no restart ever stopped, delete the marker file.')


class MarkerInvalid(Exception):
    pass


def _archive_path(rel):
    """The archive folder a marker names: it must be a direct child of runtime/demo_archives (nothing else is ever archived into, verified against, or deleted)."""
    p = (core.ROOT / rel).resolve()
    if p.parent != ARCHIVES.resolve():
        raise MarkerInvalid(f"it names {rel!r}, which is not a folder under runtime/demo_archives")
    return p


def read_marker():
    """-> None when there is DEFINITELY no marker, else the marker {"archive", "stage": "archiving"|"clearing"}. Raises MarkerInvalid when a marker exists but cannot be trusted:
    an unreadable or malformed marker never means 'no reset pending'."""
    try:
        raw = PENDING.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as e:
        raise MarkerInvalid(f"it cannot be read: {type(e).__name__}") from e
    try:
        m = json.loads(raw.decode("utf-8"))
    except ValueError as e:
        raise MarkerInvalid("it is not valid JSON") from e
    if not isinstance(m, dict) or m.get("stage") not in ("archiving", "clearing") or not isinstance(m.get("archive"), str):
        raise MarkerInvalid("it does not have the expected form")
    _archive_path(m["archive"])
    return m


def pending():
    """None when no reset is pending; the marker otherwise. An unusable marker is reported as pending with an `invalid` reason, never as None."""
    try:
        return read_marker()
    except MarkerInvalid as e:
        return {"invalid": str(e), "archive": None, "stage": None}


def guard_message(p):
    if p.get("invalid"):
        return INVALID.format(why=p["invalid"])
    return ("A demo restart was interrupted " + ("while archiving (nothing had been cleared). " if p.get("stage") == "archiving" else "while clearing. ")
            + FINISH.format(archive=p.get("archive")))


def refuse_if_pending():
    """Start-up guard (scripts/setup.py, app.server): a half-finished restart must be finished, not resumed as if it were a demo."""
    p = pending()
    if p:
        raise SystemExit("The app will not start on a half-cleared demo. " + guard_message(p))


def _write_marker(rel, stage):
    tmp = PENDING.with_suffix(".tmp")
    tmp.write_text(json.dumps({"archive": rel, "stage": stage, "started_at": time.time()}), encoding="utf-8")
    os.replace(tmp, PENDING)   # atomic: a crash leaves the old marker or the new one, never half of one


def verify_archive(arch):
    """-> None when the archive is complete and intact, else the reason. Recovery clears progress only against an archive that passes this (manifest written last, hashes, integrity)."""
    try:
        man = json.loads((arch / "manifest.json").read_text(encoding="utf-8"))
        files = man["files"]
        if not isinstance(files, dict):
            return "its manifest is malformed"
        bad = [r for r, h in files.items() if not (arch / r).is_file() or _sha(arch / r) != h]
        if bad:
            return f"{len(bad)} archived file(s) are missing or changed, e.g. {bad[0]}"
        if man.get("db_sha256") and _sha(arch / "app.db") != man["db_sha256"]:
            return "the archived database was changed"
        c = sqlite3.connect(f"file:{(arch / 'app.db').as_posix()}?mode=ro", uri=True)
        try:
            if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                return "the archived database fails its integrity check"
        finally:
            c.close()
    except (OSError, ValueError, KeyError, sqlite3.Error) as e:
        return f"it is incomplete or unreadable ({type(e).__name__})"
    return None


def _sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _copy(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _rel(p):
    return p.relative_to(core.ROOT).as_posix()


def _counts(con):
    return {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in PROGRESS_TABLES}


def _retired_ids(d):
    ids = {r[0] for r in d.execute("SELECT agent_id FROM agents")}
    have = {r[0] for r in d.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in RESULT_TABLES:
        if t in have:
            ids |= {r[0] for r in d.execute(f"SELECT DISTINCT agent_id FROM {t} WHERE agent_id IS NOT NULL")}
    ids |= {r[0] for r in d.execute("SELECT agent_id FROM retired_agents")}
    return sorted(i for i in ids if i and i != "main")


def _archive(arch):
    """Copy and VERIFY: the database (SQLite backup API: a consistent copy even with WAL), company.json and the profiles. Raises on any mismatch."""
    arch.mkdir(parents=True)
    d = core.db()
    try:
        d.execute(onboarding._SCHEMA)
        d.commit()
        live, retire = _counts(d), _retired_ids(d)
    finally:
        d.close()
    src, dst = sqlite3.connect(core.DB_PATH), sqlite3.connect(arch / "app.db")
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    a = sqlite3.connect(arch / "app.db")
    try:
        if a.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or _counts(a) != live:
            raise OSError("the archived database does not match the live one")
    finally:
        a.close()
    files = {}
    sources = [core.COMPANY_PATH] if core.COMPANY_PATH.exists() else []
    prof = core.HERMES_ROOT / "profiles"
    if prof.exists():
        for p in sorted(prof.rglob("*")):
            parts = p.relative_to(prof).parts
            if p.is_file() and not p.is_symlink() and p.name not in SECRET_NAMES and not CACHE_DIRS & set(parts[1:]):
                sources.append(p)
    for p in sources:
        rel = p.relative_to(core.HERMES_ROOT).as_posix() if p.is_relative_to(core.HERMES_ROOT) else p.name
        files[rel] = _sha(p)
        _copy(p, arch / rel)
    bad = [r for r, h in files.items() if _sha(arch / r) != h]
    if bad:
        raise OSError(f"{len(bad)} archived file(s) differ from the original, e.g. {bad[0]}")
    (arch / "manifest.json").write_text(json.dumps({"created_at": time.time(), "progress_rows": live, "retired_agents": retire, "files": files, "db_sha256": _sha(arch / "app.db")}, indent=1), encoding="utf-8")   # written LAST: no manifest = no complete archive
    (arch / "README.txt").write_text(README.format(when=time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())), encoding="utf-8")
    return live, retire


def _clear_registry(archive):
    """One transaction: retire every old agent id, then delete only the progress rows; onboarding starts again at the website step."""
    d = core.db()
    try:
        d.execute(onboarding._SCHEMA)
        d.execute("BEGIN IMMEDIATE")
        now = time.time()
        retire = _retired_ids(d)
        d.executemany("INSERT OR IGNORE INTO retired_agents(agent_id, retired_at, archive) VALUES(?,?,?)", [(i, now, archive) for i in retire])
        for t in PROGRESS_TABLES:
            d.execute(f"DELETE FROM {t}")
        d.execute("INSERT INTO onboarding(id, state, created_at, updated_at) VALUES(1, 'awaiting_source', ?, ?)", (now, now))
        d.commit()
    except BaseException:
        d.rollback()
        raise
    finally:
        d.close()


def _rmtree(p):
    def onerror(func, path, _):   # read-only files (a skill can hold one) are made writable once, then removed
        os.chmod(path, stat.S_IWRITE)
        func(path)
    shutil.rmtree(p, onerror=onerror)


def _clear_profiles(ids):
    """Remove the archived profiles of every retired specialist, then main's private memory, sessions and history (its SOUL, config, plugin and baseline skills stay)."""
    prof = core.HERMES_ROOT / "profiles"
    for i in ids:
        p = prof / i
        if i != "main" and p.is_dir() and p.resolve().parent == prof.resolve():
            _rmtree(p)
    main = prof / "main"
    for name in MAIN_PRIVATE:
        p = main / name
        if p.is_dir():
            _rmtree(p)
        elif p.exists():
            p.unlink()
    for name in ("memories", "sessions"):
        (main / name).mkdir(parents=True, exist_ok=True)


def _blank_company():
    with core.company_lock():
        core._write_company(core._blank_company())


def reset(stop_workers=lambda: None):
    """-> {ok: True, archive, progress_rows, retired_agents} or {ok: False, code, error[, archive]}. The caller guarantees no agent or onboarding operation is running (server.reset_demo).
    An existing marker decides what happens: stage clearing = a verified archive exists, so this call COMPLETES that operation against it (no new archive: the live state is half-cleared and the
    original snapshot stays authoritative); stage archiving = nothing was cleared yet, so the unfinished archive is discarded and the reset starts over; an unusable marker refuses."""
    try:
        marker = read_marker()
    except MarkerInvalid as e:
        return {"ok": False, "code": "reset_marker_invalid", "retryable": False, "error": INVALID.format(why=e)}
    if marker and marker["stage"] == "clearing":
        rel = marker["archive"]
        bad = verify_archive(_archive_path(rel))
        if bad:   # never clear anything against an unverified archive; the marker and the guard stay
            return {"ok": False, "code": "recovery_archive_invalid", "archive": rel, "retryable": False,
                    "error": f"The interrupted restart cannot be finished: its archive {rel} cannot be verified ({bad}). Nothing more was cleared and the app stays blocked. "
                             "Restore the archive folder from a copy, or ask for help; do not delete the marker unless you are sure what was cleared."}
        man = json.loads((_archive_path(rel) / "manifest.json").read_text(encoding="utf-8"))
        live, retire = man.get("progress_rows"), man.get("retired_agents")
        stop_workers()
    else:
        if marker:   # stage archiving: nothing had been cleared, so the unfinished archive is only garbage
            shutil.rmtree(_archive_path(marker["archive"]), ignore_errors=True)
        arch = ARCHIVES / (time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + f"-{time.time_ns() % 1_000_000:06d}")
        rel = _rel(arch)
        try:
            ARCHIVES.mkdir(parents=True, exist_ok=True)
            _write_marker(rel, "archiving")
            stop_workers()   # only this app's own idle Hermes workers: their open sessions must not write into the profiles while they are copied and cleared
            live, retire = _archive(arch)
            _write_marker(rel, "clearing")
        except Exception as e:   # nothing has been cleared up to here (the marker says clearing only after the verified archive)
            shutil.rmtree(arch, ignore_errors=True)
            PENDING.unlink(missing_ok=True)
            return {"ok": False, "code": "archive_failed", "retryable": True,
                    "error": f"The current demo could not be archived ({type(e).__name__}: {e}), so nothing was cleared and the demo is unchanged. "
                             "Check free disk space and that no other program holds files in the project's runtime folder, then try again."}
    try:
        _clear_registry(rel)
        d = core.db()
        try:
            ids = [r[0] for r in d.execute("SELECT agent_id FROM retired_agents")]
        finally:
            d.close()
        _clear_profiles(ids)
        _blank_company()
    except Exception as e:   # the marker (stage clearing, original archive) is left exactly as it is: the guard holds and a retry completes this operation
        return {"ok": False, "code": "reset_incomplete", "archive": rel, "retryable": True,
                "error": f"The restart stopped part-way ({type(e).__name__}: {e}). " + FINISH.format(archive=rel)}
    PENDING.unlink(missing_ok=True)
    return {"ok": True, "archive": rel, "progress_rows": live, "retired_agents": retire}
