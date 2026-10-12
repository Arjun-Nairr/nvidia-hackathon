"""Live Facebook Marketplace research (ticket 05): four narrow, backend-owned tools (location lookup, search, item details, listing photo)
used by a granted specialist inside ONE manual chat request. The specialist decides what to search and look at; this module only provides
reliable tools, permissions, budgets and persistence.

Trust and budget rules (all enforced HERE, never by the model):
- Identity: the agent comes from the worker's environment and the request from the backend (turn_state.request_id). A run is created lazily,
  at most once per (agent, request), and everything the specialist retrieves is scoped to it. The model cannot name, reuse or open runs.
- Credentials stay in the backend (secrets/local.env or process env). Photo downloads never carry them. No arbitrary URL is accepted: photos
  come only from URLs a provider item/search response recorded for a listing of this run, on an allow-listed CDN host.
- Allowance: a persisted, finite, per-scope count of API attempts and photo downloads (plus per-run caps). An attempt is counted in one
  atomic SQLite transaction BEFORE it is sent, failures included. Concurrent processes serialise on that transaction, so they cannot
  overspend. Nothing in a tool can raise or reset a cap; an existing allowance row is never re-sized from the environment.
- No automatic replay: identical successful requests are answered from the run's stored result (not re-sent, not re-counted); an identical
  request whose earlier outcome is unknown (crash, timeout, dropped connection), whose successful result could not be saved locally
  (ok_unsaved) or whose answer was the wrong listing (identity_mismatch) is refused rather than re-sent.
- Transport: API redirects are never followed (so the credential cannot be forwarded); a photo redirect is followed only to a host and
  scheme that pass the same allow-list as the first URL (HTTPS never downgrades), and the stored host is the host that served the file.
- The standalone diagnostic (scripts/marketplace_check.py, its 20-request ledger) is reused only for its pure helpers (response checks,
  normalisation, TLS context, image decoding); its ledger and evidence files are never read or written here.
"""
import hashlib, importlib.util, json, os, re, time, urllib.error, urllib.parse, urllib.request, uuid
from pathlib import Path
from app import core, turn_state

TOOLS = core.MARKETPLACE_TOOLS
API_KINDS = ("location", "search", "item")
DEFAULTS = {"run_api": 12, "run_images": 4, "scope_api": 60, "scope_images": 20}   # per-run and per-scope caps, derived from the ticket-02 sample (19 requests)
SCOPE_DEFAULT = "default"
PHOTO_HOSTS = (".fbcdn.net", ".facebook.com", ".fbsbx.com")   # ECOM_PHOTO_HOSTS (exact hosts, comma-separated) adds hosts for isolated tests only
MAX_ROWS = 25
ARGS = {"marketplace_locate": {"query"},
        "marketplace_search": {"query", "location_no", "radius_km", "condition", "sort_by", "min_price", "max_price", "next_page"},
        "marketplace_item": {"listing_id"},
        "marketplace_photo": {"listing_id"}}
_diag = None


def diag():
    """The diagnostic's verified helpers, imported by path (not copied). Importing has no side effects; its CLI and ledger are not used."""
    global _diag
    if _diag is None:
        spec = importlib.util.spec_from_file_location("marketplace_check", Path(__file__).resolve().parent.parent / "scripts" / "marketplace_check.py")   # code root, not the data root
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _diag = m
    return _diag


def _env_int(name, default):
    try:
        v = int(os.environ.get(name, ""))
        return v if v >= 0 else default
    except ValueError:
        return default


def api_base():
    return (os.environ.get("ECOM_SCRAPECREATORS_URL") or "https://api.scrapecreators.com").rstrip("/")


def _fail(code, message, field=None, hint=None, **extra):
    return {**core.err(code, message, field, None, hint), **extra}


# ---------------- runs and allowance (SQLite; one atomic transaction per reservation) ----------------
def _begin_immediate(c):
    c.commit()
    c.execute("BEGIN IMMEDIATE")


def _allowance_row(c, scope):
    row = c.execute("SELECT * FROM research_allowance WHERE scope=?", (scope,)).fetchone()
    if row is None:   # first use of a scope: caps come from configuration ONCE; an existing row is never re-sized from the environment
        c.execute("INSERT OR IGNORE INTO research_allowance(scope, api_max, image_max, api_used, image_used, created_at) VALUES(?,?,?,0,0,?)",
                  (scope, _env_int("ECOM_RESEARCH_API_MAX", DEFAULTS["scope_api"]), _env_int("ECOM_RESEARCH_IMAGE_MAX", DEFAULTS["scope_images"]), time.time()))
        row = c.execute("SELECT * FROM research_allowance WHERE scope=?", (scope,)).fetchone()
    return row


def open_run(agent_id, request_id):
    """Get or create THE run of this (agent, request). The identity pair is backend-supplied; there is no way to ask for another run."""
    c = core.db()
    try:
        _begin_immediate(c)
        row = c.execute("SELECT * FROM research_runs WHERE agent_id=? AND request_id=?", (agent_id, request_id)).fetchone()
        if row is None:
            scope = os.environ.get("ECOM_RESEARCH_SCOPE") or SCOPE_DEFAULT
            _allowance_row(c, scope)
            ag = c.execute("SELECT conversation_id FROM agents WHERE agent_id=?", (agent_id,)).fetchone()
            msg = c.execute("SELECT id FROM messages WHERE agent_id=? AND who='user' ORDER BY id DESC LIMIT 1", (agent_id,)).fetchone()
            rid = "run-" + uuid.uuid4().hex[:10]
            c.execute("INSERT INTO research_runs(run_id, agent_id, conversation_id, request_id, message_id, scope, api_max, image_max, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                      (rid, agent_id, ag["conversation_id"] if ag else None, request_id, msg["id"] if msg else None, scope,
                       _env_int("ECOM_RESEARCH_RUN_API_MAX", DEFAULTS["run_api"]), _env_int("ECOM_RESEARCH_RUN_IMAGE_MAX", DEFAULTS["run_images"]), time.time()))
            row = c.execute("SELECT * FROM research_runs WHERE run_id=?", (rid,)).fetchone()
        c.commit()
        return dict(row)
    except BaseException:
        c.rollback()
        raise
    finally:
        c.close()


def run_for(agent_id, request_id):
    if not agent_id or not request_id:
        return None
    with core.db() as d:
        r = d.execute("SELECT * FROM research_runs WHERE agent_id=? AND request_id=?", (agent_id, request_id)).fetchone()
    return dict(r) if r else None


def allowance_view(run_id):
    with core.db() as d:
        r = d.execute("SELECT * FROM research_runs WHERE run_id=?", (run_id,)).fetchone()
        if not r:
            return None
        a = d.execute("SELECT * FROM research_allowance WHERE scope=?", (r["scope"],)).fetchone()
        used_api = d.execute("SELECT COUNT(*) FROM research_calls WHERE run_id=? AND kind IN ('location','search','item')", (run_id,)).fetchone()[0]
        used_img = d.execute("SELECT COUNT(*) FROM research_calls WHERE run_id=? AND kind='photo'", (run_id,)).fetchone()[0]
    return {"scope": r["scope"], "api_attempts_left": max(0, min(r["api_max"] - used_api, a["api_max"] - a["api_used"])),
            "photo_downloads_left": max(0, min(r["image_max"] - used_img, a["image_max"] - a["image_used"])),
            "run_api_attempts": used_api, "run_photo_downloads": used_img,
            "scope_api_used": a["api_used"], "scope_api_max": a["api_max"], "scope_images_used": a["image_used"], "scope_images_max": a["image_max"]}


def _pkey(params):
    return json.dumps(params, sort_keys=True, ensure_ascii=False)


def _begin_call(run, kind, params):
    """Dedupe + reserve in ONE transaction. -> ("cached", call_row) | ("error", dict) | ("go", call_id)."""
    key = _pkey(params)
    images = kind == "photo"
    c = core.db()
    try:
        _begin_immediate(c)
        prev = c.execute("SELECT * FROM research_calls WHERE run_id=? AND kind=? AND params_key=? ORDER BY id DESC", (run["run_id"], kind, key)).fetchall()
        for p in prev:
            if p["status"] == "done" and p["outcome"] == "ok":
                c.commit()
                return "cached", dict(p)
        for p in prev:   # an identical request whose outcome is unknown, unsaved or the wrong listing must not be re-sent (it was processed and may have been charged)
            if p["status"] != "done" or p["outcome"] == "network_error":
                c.commit()
                return "error", _fail("uncertain_previous_attempt",
                                      f"An identical {kind} request was already sent in this run and its outcome is unknown ({p['outcome'] or 'no outcome recorded'}). "
                                      "It was NOT repeated and nothing was spent.", hint="Change the request, use what you already have, or report this as a blocker.",
                                      allowance=None)
            if p["outcome"] == "ok_unsaved":
                c.commit()
                return "error", _fail("storage_error", f"An identical {kind} request already SUCCEEDED in this run but its result could not be saved locally. It was NOT "
                                      "repeated and nothing was spent: the provider already answered and a second request would only spend the allowance again.",
                                      hint="Use the evidence you already have or report this local storage fault as a blocker.", allowance=None)
            if p["outcome"] == "identity_mismatch":
                c.commit()
                return "error", _fail("item_identity_mismatch", "An identical item request already returned a DIFFERENT listing's details in this run. It was NOT repeated.",
                                      hint="Do not use details for this listing; work with other listings or report the blocker.", allowance=None)
        r = c.execute("SELECT * FROM research_runs WHERE run_id=?", (run["run_id"],)).fetchone()
        a = _allowance_row(c, r["scope"])
        if images:
            used_run = c.execute("SELECT COUNT(*) FROM research_calls WHERE run_id=? AND kind='photo'", (run["run_id"],)).fetchone()[0]
            run_cap, scope_used, scope_cap, what = r["image_max"], a["image_used"], a["image_max"], "photo download"
        else:
            used_run = c.execute("SELECT COUNT(*) FROM research_calls WHERE run_id=? AND kind IN ('location','search','item')", (run["run_id"],)).fetchone()[0]
            run_cap, scope_used, scope_cap, what = r["api_max"], a["api_used"], a["api_max"], "ScrapeCreators request"
        if used_run >= run_cap or scope_used >= scope_cap:
            c.commit()
            which = "this run's" if used_run >= run_cap else f"the {r['scope']!r} scope's"
            return "error", _fail("allowance_exhausted", f"The {what} allowance is exhausted ({which} limit: {run_cap if used_run >= run_cap else scope_cap}). "
                                  "Nothing was sent. The allowance cannot be raised from here.",
                                  hint="Work only with the evidence you already collected, save an honest partial draft if it supports one, or report the blocker.")
        col = "image_used" if images else "api_used"
        c.execute(f"UPDATE research_allowance SET {col}={col}+1 WHERE scope=?", (r["scope"],))
        cur = c.execute("INSERT INTO research_calls(run_id, kind, params, params_key, status, ts) VALUES(?,?,?,?,?,?)",
                        (run["run_id"], kind, key, key, "reserved", time.time()))
        c.commit()
        return "go", cur.lastrowid
    except BaseException:
        c.rollback()
        raise
    finally:
        c.close()


def _finish_call(call_id, outcome, status=None, error=None, result=None, credits=None, remaining=None, ms=None):
    with core.db() as d:
        d.execute("UPDATE research_calls SET status='done', outcome=?, http_status=?, error=?, result=?, credits_charged=?, credits_remaining=?, ms=? WHERE id=?",
                  (outcome, status, (error or None) and str(error)[:300], json.dumps(result) if result is not None else None, credits, remaining, ms, call_id))


# ---------------- provider transport ----------------
class RedirectRefused(Exception):
    pass


def _read(r):
    return r.status, r.read(8_000_001), r.headers.get("Content-Type", "")


def photo_redirect_ok(old_url, new_url):
    """Is following this photo redirect allowed? Same host/scheme rule as the first URL; HTTPS never downgrades. -> (ok, host or reason)."""
    o, n = urllib.parse.urlparse(old_url), urllib.parse.urlparse(new_url)
    if n.scheme not in ("http", "https"):
        return False, f"scheme {n.scheme!r} is not allowed"
    if o.scheme == "https" and n.scheme != "https":
        return False, "HTTPS to HTTP downgrade"
    ok, host = _host_ok(new_url)
    return (True, host) if ok else (False, f"host {host!r} is not an allowed Facebook CDN host")


def _photo_get(state):
    """CDN download: no credential header is ever accepted; each redirect hop is validated BEFORE it is followed (max 3). state['final'] = served URL."""
    def get(url, headers, timeout, ctx):
        if any(k.lower() == "x-api-key" for k in headers):
            raise ValueError("a credential must never be attached to a photo download")

        class Guard(urllib.request.HTTPRedirectHandler):
            max_redirections = 3

            def redirect_request(self, req, fp, code, msg, hdrs, newurl):
                new = urllib.parse.urljoin(req.full_url, newurl)
                ok, why = photo_redirect_ok(req.full_url, new)
                if not ok:
                    raise RedirectRefused(f"photo redirect refused: {why}")
                return super().redirect_request(req, fp, code, msg, hdrs, new)
        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx), Guard())
        try:
            with opener.open(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
                state["final"] = r.geturl()
                return _read(r)
        except urllib.error.HTTPError as e:
            state["final"] = e.url or url
            return e.code, e.read(65536), e.headers.get("Content-Type", "") if e.headers else ""
    return get


def _classify(kind, status, body, key):
    """Same outcome vocabulary as the diagnostic's Client: ok | provider_error | bad_response | not_found | auth_failed | credits_or_rate_limit | ..."""
    d = diag()
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        data = None
    msg = ""
    if isinstance(data, dict):
        msg = str(data.get("error") or data.get("message") or "")[:200].replace(key, "***") if key else str(data.get("error") or data.get("message") or "")[:200]
    if status == 200:
        if not isinstance(data, dict):
            return "bad_response", "malformed response: response was not a JSON object", None
        if data.get("success") not in (None, True) or data.get("error"):
            return "provider_error", msg or "provider reported a failure in a 200 response", data
        why = d.response_problem(kind, data)
        if why:
            return "bad_response", f"malformed response: {why}", data
        return "ok", None, data
    if 300 <= status < 400:
        return "redirect_refused", f"the provider answered with a redirect (HTTP {status}); redirects are never followed, so the API credential is not sent to another address", None
    k = {400: "bad_request", 401: "auth_failed", 403: "auth_failed", 402: "credits_or_rate_limit", 429: "credits_or_rate_limit", 404: "not_found"}.get(status)
    return (k or ("provider_error" if status >= 500 else "http_error")), (msg or f"HTTP {status}"), data


def _api(run, kind, params):
    """One counted, never-repeated provider request. -> ("ok", data, call_id) | ("cached", call_row, None) | ("error", errdict, call_id)."""
    d = diag()
    key = d.get_key()
    if not key:
        return "error", _fail("missing_credentials", "The ScrapeCreators API key is not configured on the backend, so no Marketplace request was sent.",
                              hint="Tell the user that the research capability needs SCRAPECREATORS_API_KEY in secrets/local.env."), None
    state, v = _begin_call(run, kind, params)
    if state == "cached":
        return "cached", v, None
    if state == "error":
        return "error", v, None
    call_id = v
    url = api_base() + d.ENDPOINTS[kind] + "?" + urllib.parse.urlencode(params)
    t0 = time.perf_counter()
    try:
        status, body, _ctype = d.api_get(url, {"x-api-key": key, "Accept": "application/json", "User-Agent": "ecom-agents-research/1"}, 60, d.tls_context())   # never follows redirects
    except Exception as e:   # timeout, DNS, TLS: outcome unknown (the provider may have processed it): never retried
        ms = round((time.perf_counter() - t0) * 1000)
        why = f"{type(e).__name__}: {e}"[:200].replace(key, "***")
        _finish_call(call_id, "network_error", error=why, ms=ms)
        return "error", _fail("network_error", f"The request was sent but no usable answer came back ({why}). It was counted and will not be repeated.",
                              hint="Do not assume it succeeded; use other evidence or report the blocker."), call_id
    ms = round((time.perf_counter() - t0) * 1000)
    outcome, why, data = _classify(kind, status, body, key)
    credits = remaining = None
    if isinstance(data, dict):
        credits, remaining = data.get("credits_charged"), data.get("credits_remaining")
    if outcome != "ok":
        _finish_call(call_id, outcome, status=status, error=why, credits=credits, remaining=remaining, ms=ms)
        return "error", _fail("provider_error" if outcome in ("provider_error", "http_error") else outcome,
                              f"ScrapeCreators {kind} request failed: {why}" + (f" (HTTP {status})" if status else "") + ". The attempt was counted and not repeated.",
                              hint="Do not invent results. Try a different request or report the blocker."), call_id
    return "ok", (data, status, credits, remaining, ms), call_id


# ---------------- run evidence ----------------
def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _load_records(run_id):
    with core.db() as d:
        rows = d.execute("SELECT listing_id, record FROM research_listings WHERE run_id=? ORDER BY first_call", (run_id,)).fetchall()
    return {r["listing_id"]: json.loads(r["record"]) for r in rows}


def _store_records(run_id, call_id, recs):
    """Merge normalised records into the run's evidence with the diagnostic's field-level merge (a later partial record never erases a known value)."""
    d = diag()
    ev = {"listings": _load_records(run_id)}
    for rec in recs:
        if rec.get("listing_id"):
            d.merge(ev, rec)
    with core.db() as c:
        for lid, rec in ev["listings"].items():
            c.execute("INSERT INTO research_listings(run_id, listing_id, record, first_call, retrieved_at) VALUES(?,?,?,?,?) "
                      "ON CONFLICT(run_id, listing_id) DO UPDATE SET record=excluded.record, retrieved_at=excluded.retrieved_at",
                      (run_id, lid, json.dumps(rec), call_id, rec.get("retrieved_at")))


def _ids(raw):
    """The listing id a provider record names twice: its `id` field and the id inside its Marketplace item URL (either may be None)."""
    got = str(raw.get("id")).strip() if raw.get("id") not in (None, "") else None
    m = re.search(r"/marketplace/item/(\d+)", str(raw.get("url") or ""))
    return got, (m.group(1) if m else None)


def run_evidence(run_id):
    """The run's evidence in the same shape listing.evidence() returns for a recorded file, plus live provenance. Seller IDs are pseudonymised;
    nothing here comes from the recorded Dallas sample."""
    recs = _load_records(run_id)
    pseudo, listings = {}, []
    for rec in recs.values():
        r = json.loads(json.dumps(rec))
        s = r.get("seller") if isinstance(r.get("seller"), dict) else {}
        if s.get("id"):
            s["id"] = pseudo.setdefault(s["id"], f"seller_{len(pseudo) + 1}")
        listings.append(r)
    with core.db() as d:
        ph = d.execute("SELECT * FROM research_photos WHERE run_id=? ORDER BY fetched_at", (run_id,)).fetchall()
    checks = [{"listing_id": p["listing_id"], "kind": "usable", "http_status": 200, "content_type": p["content_type"], "bytes": p["bytes"], "sha256": p["sha256"],
               "width": p["width"], "height": p["height"], "decoded": True, "format": p["format"], "url_host": p["host"], "fetched_at": p["fetched_at"]} for p in ph]
    data = {"schema": 1, "live": True, "source": "ScrapeCreators Facebook Marketplace (live research run)", "run_id": run_id, "listings": listings, "image_checks": checks}
    sha = hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()
    return {"data": data, "by_id": {str(l["listing_id"]): l for l in listings}, "sha256": sha, "file": f"live-run:{run_id}", "source": "live_research", "run_id": run_id}


def photo_registered(run_id, image_id):
    if not run_id:
        return False
    with core.db() as d:
        return d.execute("SELECT 1 FROM research_photos WHERE run_id=? AND image_id=?", (run_id, image_id)).fetchone() is not None


def image_dir(run_id):
    return core.RUNTIME / "research" / run_id / "images"


# ---------------- tool bodies ----------------
def _prepare(agent_id, tool, args):
    """Common gate. -> (run, None) or (None, errdict). Nothing is spent here."""
    if not isinstance(args, dict):
        return None, _fail("bad_request", "Arguments must be an object.")
    extra = sorted(set(args) - ARGS[tool])
    if extra:
        return None, _fail("invalid_argument", f"Unsupported argument(s) {extra}. The allowance, run and credentials are controlled by the backend and cannot be set from a tool call.",
                           "arguments", hint=f"Allowed arguments: {sorted(ARGS[tool])}.")
    with core.db() as d:
        ag = d.execute("SELECT granted_tools FROM agents WHERE agent_id=?", (agent_id,)).fetchone()
    if not ag:
        return None, _fail("unknown_agent", f"Marketplace research needs a registered specialist; {agent_id!r} is not one.")
    if tool not in json.loads(ag["granted_tools"] or "[]"):
        return None, _fail("not_granted", f"This specialist was not granted {tool}.")
    rid = getattr(turn_state, "request_id", None)
    if not rid:
        return None, _fail("no_manual_request", "Marketplace research runs only inside a manual user request; none is active.")
    run = open_run(agent_id, rid)
    turn_state.run_id = run["run_id"]
    return run, None


def _with_allowance(out, run):
    out["allowance"] = allowance_view(run["run_id"])
    return out


def _text(v, field, lo=1, hi=100):
    v = v.strip() if isinstance(v, str) else ""
    if not lo <= len(v) <= hi:
        return None, _fail("bad_argument", f"{field} must be {lo}-{hi} characters of text.", field)
    return v, None


def locate(agent_id, args):
    run, e = _prepare(agent_id, "marketplace_locate", args)
    if e:
        return e
    q, e = _text(args.get("query"), "query")
    if e:
        return e
    st, v, cid = _api(run, "location", {"query": q})
    if st == "error":
        return _with_allowance(v, run)
    if st == "cached":
        locs = json.loads(v["result"])["locations"]
        _select_location(run["run_id"], v["id"])
        return _with_allowance({"ok": True, "cached": True, "query": q, "locations": [{k: x[k] for k in ("location_no", "name", "subtitle", "city")} for x in locs]}, run)
    data, status, credits, remaining, ms = v
    locs = [{"location_no": i, "name": x.get("name"), "subtitle": x.get("subtitle"), "city": x.get("city"), "latitude": x.get("latitude"), "longitude": x.get("longitude")}
            for i, x in enumerate(data.get("locations") or [], 1)]
    _finish_call(cid, "ok", status=status, result={"locations": locs}, credits=credits, remaining=remaining, ms=ms)
    _select_location(run["run_id"], cid)
    out = {"ok": True, "query": q, "locations": [{k: x[k] for k in ("location_no", "name", "subtitle", "city")} for x in locs]}
    if not locs:
        out.update(empty=True, note="The provider returned no location for this text. Try another spelling or a nearby city.")
    return _with_allowance(out, run)


def _select_location(run_id, call_id):
    """The lookup the specialist was last SHOWN (a fresh answer or a free cache hit) is the one its location_no refers to."""
    with core.db() as d:
        d.execute("UPDATE research_runs SET selected_location_call=? WHERE run_id=?", (call_id, run_id))


def _selected_locations(run_id):
    with core.db() as d:
        r = d.execute("SELECT c.result FROM research_runs u JOIN research_calls c ON c.id = u.selected_location_call "
                      "WHERE u.run_id=? AND c.kind='location' AND c.outcome='ok'", (run_id,)).fetchone()
    return json.loads(r["result"])["locations"] if r else []


def _summarise(rec):
    from app import listing
    s = listing._summary(rec)
    return {"listing_id": s["listing_id"], "title": s["title"], "price": s["price"], "location": s["location"], "condition": s["condition"],
            "detail_level": s["detail_level"], "has_photo_reference": bool(rec.get("photos") or rec.get("primary_photo"))}


def search(agent_id, args):
    run, e = _prepare(agent_id, "marketplace_search", args)
    if e:
        return e
    d = diag()
    q, e = _text(args.get("query"), "query")
    if e:
        return e
    locs = _selected_locations(run["run_id"])
    n = args.get("location_no")
    if isinstance(n, bool) or not isinstance(n, int):
        return _fail("bad_argument", "location_no must be an integer from this run's marketplace_locate result.", "location_no",
                     hint="Call marketplace_locate first." if not locs else f"Valid location numbers: 1-{len(locs)}.")
    if not 1 <= n <= len(locs):
        return _fail("bad_location_no", f"location_no {n} is not one of this run's located places ({len(locs)}).", "location_no",
                     hint="Call marketplace_locate first." if not locs else f"Valid location numbers: 1-{len(locs)}.")
    loc = locs[n - 1]
    place = {"location_no": n, "name": loc.get("name"), "city": loc.get("city")}
    params = {"query": q, "lat": loc["latitude"], "lng": loc["longitude"]}
    for k, lo, hi in (("radius_km", 1, 500), ("min_price", 0, 10**7), ("max_price", 0, 10**7)):
        if args.get(k) is not None:
            v = args[k]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
                return _fail("bad_argument", f"{k} must be a number between {lo} and {hi}.", k)
            params[k] = float(v)
    for k in ("condition", "sort_by"):
        if args.get(k) is not None:
            if args[k] not in d.ENUMS[k]:
                return _fail("bad_argument", f"{k} must be one of {sorted(d.ENUMS[k])}.", k)
            params[k] = args[k]
    if args.get("next_page"):   # the cursor comes from this run's own earlier page of the SAME search, never from the model
        with core.db() as c:
            prev = c.execute("SELECT params, result FROM research_calls WHERE run_id=? AND kind='search' AND outcome='ok' ORDER BY id DESC", (run["run_id"],)).fetchall()
        cur = None
        for r in prev:
            p, res = json.loads(r["params"]), json.loads(r["result"] or "{}")
            if {k: v for k, v in p.items() if k != "cursor"} == params and res.get("cursor") and res.get("has_next_page"):
                cur = res["cursor"]
                break
        if not cur:
            return _fail("no_next_page", "There is no further page recorded for this exact search in this run.", "next_page")
        params["cursor"] = cur
    st, v, cid = _api(run, "search", params)
    if st == "error":
        return _with_allowance(v, run)
    recs = _load_records(run["run_id"])
    if st == "cached":
        info = json.loads(v["result"])
        rows = [_summarise(recs[i]) for i in info["listing_ids"] if i in recs]
        return _with_allowance({"ok": True, "cached": True, "query": q, "place": place, "results": len(rows), "listings": rows[:MAX_ROWS],
                                "has_more_pages": bool(info.get("has_next_page"))}, run)
    data, status, credits, remaining, ms = v
    now = _now()
    filt = {k: x for k, x in params.items() if k not in ("query", "cursor")}
    new, ids, dropped = [], [], 0
    for raw in data.get("listings") or []:
        got, url_id = _ids(raw) if isinstance(raw, dict) else (None, None)
        if got is not None and url_id is not None and got != url_id:   # one row naming two listings: its provenance cannot be trusted, so it is not kept
            dropped += 1
            continue
        rec = d.norm_search_item(raw, {"endpoint": "search", "query": q, "filters": filt, "call_id": cid}, now)
        if rec["listing_id"]:
            new.append(rec)
            ids.append(rec["listing_id"])
    try:
        _store_records(run["run_id"], cid, new)
    except Exception as ex:   # sent and counted, result not kept: say exactly that, never re-send
        _finish_call(cid, "ok_unsaved", status=status, error=f"{type(ex).__name__}: {ex}", credits=credits, remaining=remaining, ms=ms)
        return _with_allowance(_fail("storage_error", "The search WAS sent and counted but its results could not be saved, so they cannot be used. It was not repeated.",
                                     hint="Report this as a blocker."), run)
    _finish_call(cid, "ok", status=status, result={"listing_ids": ids, "cursor": data.get("cursor"), "has_next_page": data.get("has_next_page"), "empty": not ids,
                                                  "place": place, "dropped_conflicting_rows": dropped}, credits=credits, remaining=remaining, ms=ms)
    recs = _load_records(run["run_id"])
    rows = [_summarise(recs[i]) for i in ids]
    out = {"ok": True, "query": q, "place": place, "results": len(rows), "listings": rows[:MAX_ROWS], "has_more_pages": bool(data.get("has_next_page")),
           "note": "Relevance is YOUR judgement: results can be unrelated. Prices are asking prices, not sales."}
    if dropped:
        out["dropped_conflicting_rows"] = dropped
    if not rows:
        out.update(empty=True, note="The provider returned no listings for this search. Change the query, filters or location instead of repeating it.")
    return _with_allowance(out, run)


def item(agent_id, args):
    run, e = _prepare(agent_id, "marketplace_item", args)
    if e:
        return e
    lid, e = _text(args.get("listing_id"), "listing_id", 1, 64)
    if e:
        return e
    recs = _load_records(run["run_id"])
    if lid not in recs:
        return _with_allowance(_fail("unknown_listing", f"Listing {lid!r} was not returned by a search in this run, so its details cannot be requested.", "listing_id",
                                     hint="Use a listing_id from a marketplace_search result of this request."), run)
    st, v, cid = _api(run, "item", {"id": lid})
    if st == "error":
        return _with_allowance(v, run)
    if st == "cached":
        r = recs[lid]
        return _with_allowance({"ok": True, "cached": True, "listing": _detail(r)}, run)
    data, status, credits, remaining, ms = v
    d = diag()
    # Identity: EACH identifier the response supplies (id, and the id in its source URL) must name the requested listing; any contradiction is a different
    # listing's data and is never merged. A response with neither is accepted but recorded as UNCONFIRMED: whether the provider always returns an id was
    # not independently verified.
    got, url_id = _ids(data)
    other = next((x for x in (got, url_id) if x is not None and x != lid), None)
    if other is None:
        identity = "id_match" if got is not None else "url_match" if url_id is not None else "unconfirmed_no_id_in_response"
    else:
        identity = None
    if identity is None:
        _finish_call(cid, "identity_mismatch", status=status, error=f"response named listing {other} (id {got!r}, url id {url_id!r}), requested {lid}", credits=credits, remaining=remaining, ms=ms)
        return _with_allowance(_fail("item_identity_mismatch", f"The provider answered the request for listing {lid} with details of a different listing ({other}). "
                                     "The response was discarded and nothing was saved under either listing. The attempt was counted and not repeated.",
                                     hint="Do not use details for this listing; work with other listings or report the blocker."), run)
    rec = d.norm_item(data, {"endpoint": "item", "call_id": cid}, _now())
    rec["listing_id"] = lid   # the id that was asked for (and that this run's search returned): confirmed or flagged above
    rec["identity"] = identity
    try:
        _store_records(run["run_id"], cid, [rec])
    except Exception as ex:
        _finish_call(cid, "ok_unsaved", status=status, error=f"{type(ex).__name__}: {ex}", credits=credits, remaining=remaining, ms=ms)
        return _with_allowance(_fail("storage_error", "The item request WAS sent and counted but its result could not be saved. It was not repeated.", hint="Report this as a blocker."), run)
    _finish_call(cid, "ok", status=status, result={"listing_id": lid, "identity": identity}, credits=credits, remaining=remaining, ms=ms)
    out = {"ok": True, "listing": _detail(_load_records(run["run_id"])[lid])}
    if identity == "unconfirmed_no_id_in_response":
        out["identity_note"] = "The response carried no listing id or URL, so it is NOT independently confirmed that these details belong to this listing."
    return _with_allowance(out, run)


def _detail(rec):
    """What the specialist reads about one listing: the same whitelist a saved draft keeps (no URLs of private photos, no seller fields)."""
    from app import listing
    s, sup = listing._summary(rec), listing._support(rec)
    return {**s, "source_url": rec.get("source_url"), **sup, "identity": rec.get("identity"), "retrieval": "live ScrapeCreators request in this run"}


def _photo_url(rec):
    for p in rec.get("photos") or []:
        if isinstance(p, dict) and p.get("url"):
            return p["url"]
    pp = rec.get("primary_photo")
    return pp.get("url") if isinstance(pp, dict) else None


def _host_ok(url):
    p = urllib.parse.urlparse(url or "")
    host = (p.hostname or "").lower()
    extra = [h.strip().lower() for h in os.environ.get("ECOM_PHOTO_HOSTS", "").split(",") if h.strip()]
    if host in extra:
        return p.scheme in ("http", "https"), host
    return p.scheme == "https" and any(host.endswith(s) for s in PHOTO_HOSTS), host


def photo(agent_id, args):
    run, e = _prepare(agent_id, "marketplace_photo", args)
    if e:
        return e
    lid, e = _text(args.get("listing_id"), "listing_id", 1, 64)
    if e:
        return e
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", lid):
        return _fail("bad_argument", "listing_id has an unsupported form.", "listing_id")
    recs = _load_records(run["run_id"])
    if lid not in recs:
        return _with_allowance(_fail("unknown_listing", f"Listing {lid!r} was not returned by a search in this run.", "listing_id",
                                     hint="Use a listing_id from a marketplace_search result of this request."), run)
    with core.db() as c:
        have = c.execute("SELECT * FROM research_photos WHERE run_id=? AND listing_id=?", (run["run_id"], lid)).fetchone()
    if have and any(p.is_file() for p in image_dir(run["run_id"]).glob(lid + ".*")):
        return _with_allowance({"ok": True, "cached": True, "image_id": lid, "listing_id": lid, "sha256": have["sha256"], "bytes": have["bytes"], "width": have["width"],
                                "height": have["height"], "next": f"inspect_image(image_id={lid!r}) shows the pixels."}, run)
    url = _photo_url(recs[lid])
    if not url:
        return _with_allowance(_fail("no_photo_reference", f"Listing {lid} has no photo reference in the recorded results of this run.", "listing_id",
                                     hint="Say that this listing's photo could not be inspected."), run)
    ok, host = _host_ok(url)
    if not ok:
        return _with_allowance(_fail("photo_host_not_allowed", "The photo is not hosted on an allowed Facebook CDN host and was not fetched.", "listing_id"), run)
    state, v = _begin_call(run, "photo", {"listing_id": lid})
    if state == "error":
        return _with_allowance(v, run)
    if state == "cached":   # an earlier download succeeded but its file/record is gone: do not silently re-download
        return _with_allowance(_fail("photo_unavailable", "The photo was downloaded earlier in this run but is no longer available locally. It was not downloaded again.", "listing_id"), run)
    cid = v
    dg = diag()
    t0 = time.perf_counter()
    served = {}
    res = dg.check_image(url, transport=_photo_get(served), ctx=dg.tls_context())   # no credentials are attached; every redirect hop is validated
    ms = round((time.perf_counter() - t0) * 1000)
    body = res.pop("_body", None)
    refused = "RedirectRefused" in str(res.get("error") or "")
    if res["kind"] != "usable" or not body:
        _finish_call(cid, "redirect_refused" if refused else res["kind"], status=res.get("http_status"), error=res.get("error"), ms=ms)
        return _with_allowance(_fail("photo_redirect_refused" if refused else "photo_unavailable",
                                     f"The photo for listing {lid} could not be used ({res['kind']}: {res.get('error')}). The download was counted and not repeated.",
                                     "listing_id", hint="Say that this listing's photo could not be inspected; do not describe it."), run)
    host = (urllib.parse.urlparse(served.get("final") or url).hostname or host).lower()   # the host that actually served the bytes
    ext = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif"}.get(res.get("format"), "bin")
    try:
        folder = image_dir(run["run_id"])
        folder.mkdir(parents=True, exist_ok=True)
        tmp = folder / f"{lid}.{ext}.{os.getpid()}.tmp"
        tmp.write_bytes(body)
        os.replace(tmp, folder / f"{lid}.{ext}")
        with core.db() as c:
            c.execute("INSERT OR REPLACE INTO research_photos(run_id, listing_id, image_id, sha256, bytes, width, height, content_type, format, host, fetched_at, path) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (run["run_id"], lid, lid, res["sha256"], res["bytes"], res["width"], res["height"], res["content_type"],
                                                         res.get("format"), host, time.time(), f"{lid}.{ext}"))
    except Exception as ex:   # file system OR database: the download happened and was counted, the result is not kept, and it is not fetched again
        _finish_call(cid, "ok_unsaved", status=200, error=f"{type(ex).__name__}: {ex}", ms=ms)
        return _with_allowance(_fail("storage_error", "The photo was downloaded and counted but could not be saved locally. It was not downloaded again.",
                                     hint="Say that this listing's photo could not be inspected."), run)
    _finish_call(cid, "ok", status=200, result={"sha256": res["sha256"], "bytes": res["bytes"]}, ms=ms)
    return _with_allowance({"ok": True, "image_id": lid, "listing_id": lid, "sha256": res["sha256"], "bytes": res["bytes"], "width": res["width"], "height": res["height"],
                            "next": f"inspect_image(image_id={lid!r}) shows the pixels."}, run)


# ---------------- read API (SQLite only) ----------------
def run_view(run_id):
    with core.db() as d:
        r = d.execute("SELECT * FROM research_runs WHERE run_id=?", (run_id,)).fetchone()
        if not r:
            return None
        calls = [dict(x) for x in d.execute("SELECT * FROM research_calls WHERE run_id=? ORDER BY id", (run_id,))]
        photos = [dict(x) for x in d.execute("SELECT listing_id, image_id, sha256, bytes, width, height, content_type, host, fetched_at FROM research_photos WHERE run_id=?", (run_id,))]
        drafts = [x[0] for x in d.execute("SELECT draft_id FROM listing_drafts WHERE research_run_id=? ORDER BY created_at", (run_id,))]
    out_calls = []
    for c in calls:
        p = json.loads(c["params"] or "{}")
        place = (json.loads(c["result"] or "{}").get("place") if c["kind"] == "search" else None)
        out_calls.append({"n": c["id"], "kind": c["kind"], "params": {k: v for k, v in p.items() if k not in ("lat", "lng")}, "place": place,
                          "status": c["status"], "outcome": c["outcome"],
                          "http_status": c["http_status"], "credits_charged": c["credits_charged"], "credits_remaining": c["credits_remaining"], "ms": c["ms"],
                          "error": c["error"], "at": c["ts"]})
    with core.db() as d:
        nl = d.execute("SELECT COUNT(*) FROM research_listings WHERE run_id=?", (run_id,)).fetchone()[0]
    return {"run_id": run_id, "agent_id": r["agent_id"], "conversation_id": r["conversation_id"], "request_id": r["request_id"], "scope": r["scope"], "created_at": r["created_at"],
            "calls": out_calls, "listings_recorded": nl, "photos": photos, "draft_ids": drafts, "allowance": allowance_view(run_id)}


def list_runs(agent_id=None):
    with core.db() as d:
        rows = d.execute("SELECT run_id, agent_id, scope, created_at FROM research_runs" + (" WHERE agent_id=?" if agent_id else "") + " ORDER BY created_at",
                         (agent_id,) if agent_id else ()).fetchall()
    return [{"run_id": r["run_id"], "agent_id": r["agent_id"], "scope": r["scope"], "created_at": r["created_at"], "allowance": allowance_view(r["run_id"])} for r in rows]


def allowances():
    with core.db() as d:
        return [dict(r) for r in d.execute("SELECT * FROM research_allowance ORDER BY scope")]
