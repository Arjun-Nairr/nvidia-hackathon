"""Ticket 02 DIAGNOSTIC: is there usable home-textile Facebook Marketplace data (listings, prices, descriptions, photos, sellers)
reachable through ScrapeCreators' documented endpoints? Standalone and read-only. NOT a production tool: nothing registers it with any agent.

Documented (docs.scrapecreators.com, read 2026-10-10): GET https://api.scrapecreators.com/v1/facebook/marketplace/{location/search | search | item},
header x-api-key, 1 credit per request each. Search needs lat/lng (from location/search), optional condition/radius/price/sort filters and a cursor.

Key: SCRAPECREATORS_API_KEY in secrets/local.env or the process environment. Never printed, logged or written to any artifact.
Budget: at most MAX_REQUESTS (20) API requests TOTAL across all invocations (counted in runtime/marketplace_check/ledger.json BEFORE sending,
failures included), no automatic retries. The ledger fails CLOSED: only an absent file starts a fresh allowance; a damaged, unreadable or
invalid ledger (or evidence file) stops the command before any request and is never rewritten. State-changing commands run one at a time
(OS file lock), so overlapping invocations cannot over-spend or lose updates. Photo downloads are separate (CDN, no key, no credits), capped at MAX_IMAGE_FETCHES.

  python scripts/marketplace_check.py status
  python scripts/marketplace_check.py locate Dallas
  python scripts/marketplace_check.py search "queen comforter" --location 1 --condition new [--radius-km 50] [--next]
  python scripts/marketplace_check.py item 123 456 ...        (one request per id)
  python scripts/marketplace_check.py review 123 relevant|irrelevant|unsure "note"
  python scripts/marketplace_check.py images --n 3 [ID ...]
  python scripts/marketplace_check.py report | fixture
"""
import argparse, contextlib, hashlib, io, json, os, re, ssl, sys, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(os.environ.get("ECOM_APP_ROOT") or Path(__file__).resolve().parent.parent)
WORK = ROOT / "runtime" / "marketplace_check"          # git-ignored private working data: ledger, evidence, sample photos
FIXTURE = ROOT / "tests" / "fixtures" / "marketplace_sample.json"
API = "https://api.scrapecreators.com"
KEY_NAME = "SCRAPECREATORS_API_KEY"
MAX_REQUESTS = 20
MAX_IMAGE_FETCHES = 6
SAVE_ATTEMPTS = 20         # local state writes retry a refused file replacement this many times (Windows refuses os.replace while a reader has the
SAVE_DELAY = 0.05          # file open; measured: 5 attempts still failed 4% of the time against a tight reader loop). API requests are NEVER retried
ENDPOINTS = {"location": "/v1/facebook/marketplace/location/search", "search": "/v1/facebook/marketplace/search", "item": "/v1/facebook/marketplace/item"}
ALLOWED = {"location": {"query"},
           "search": {"query", "category_id", "lat", "lng", "radius_km", "min_price", "max_price", "sort_by", "delivery_method", "condition",
                      "date_listed", "availability", "cursor"},
           "item": {"id"}}
ENUMS = {"sort_by": {"suggested", "distance_ascend", "creation_time_descend", "price_ascend", "price_descend"},
         "delivery_method": {"all", "local_pickup", "shipping"}, "condition": {"new", "used_like_new", "used_good", "used_fair"},
         "date_listed": {"all", "1", "7", "30", "last_24_hours", "last_7_days", "last_30_days"}, "availability": {"available", "sold", "all"}}
TEXTILE = re.compile(r"\b(bed(ding|spread|sheets?|skirt)?|comforters?|duvets?|quilts?|coverlets?|sheets?|pillow(case|s)?|shams?|mattress (cover|topper|pad)|"
                     r"blankets?|throws?|curtains?|drapes?|drapery|valances?|blackout|bed ?in ?a ?bag)\b", re.I)


class MissingCredentials(Exception):
    pass


def missing_message():
    return (f"No ScrapeCreators API key found. Add a line `{KEY_NAME}=<your key>` to secrets/local.env (or set the {KEY_NAME} environment "
            "variable). Nothing was requested and no credits were used.")


def get_key():
    k = (os.environ.get(KEY_NAME) or "").strip()
    if not k:
        p = ROOT / "secrets" / "local.env"
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    n, v = line.split("=", 1)
                    if n.strip() == KEY_NAME:
                        k = v.strip().strip('"').strip("'")
    return k or None


def tls_context():
    """Verification stays ON; behind TLS-scanning antivirus the project's CA bundle (certifi + Windows store) is used when present."""
    b = ROOT / "runtime" / "ca_bundle.pem"
    return ssl.create_default_context(cafile=str(b)) if b.exists() else ssl.create_default_context()


def http_get(url, headers, timeout, ctx, max_bytes=8_000_000):
    """Default transport -> (status, body bytes, content-type). HTTP error statuses are returned, not raised; network faults raise."""
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return r.status, r.read(max_bytes + 1), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, e.read(65536), e.headers.get("Content-Type", "") if e.headers else ""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):   # None: urllib raises the 3xx as an HTTPError, so the request goes nowhere else
        return None


def api_get(url, headers, timeout, ctx, max_bytes=8_000_000):
    """Transport for API requests (they carry the x-api-key header): redirects are NEVER followed, so the credential cannot be forwarded to another
    address. A 3xx comes back as its status and is reported as an HTTP error. Photo checks keep http_get (no credential is attached to them)."""
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx), _NoRedirect())
    try:
        with opener.open(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
            return r.status, r.read(max_bytes + 1), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, e.read(65536), e.headers.get("Content-Type", "") if e.headers else ""


class SaveError(Exception):
    """A local state write failed (after bounded retries). The previous file, if any, is intact and our temp file is removed."""


def save_json(path, obj):
    """Atomic write via our own temp file. A refused replacement (PermissionError) is retried a few times; other OSErrors fail at once.
    Only the local write is ever retried, never a request."""
    tmp = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    for attempt in range(SAVE_ATTEMPTS):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, path)
            return
        except OSError as e:
            with contextlib.suppress(OSError):
                tmp.unlink()                      # only our own temp file; the existing state file is never touched
            if not isinstance(e, PermissionError) or attempt + 1 == SAVE_ATTEMPTS:
                raise SaveError(f"could not write {path.name} ({type(e).__name__}: {e}; {attempt + 1} attempt(s))") from None
            time.sleep(SAVE_DELAY)


class StateError(Exception):
    """A state file exists but cannot be trusted. Nothing is sent and the file is left exactly as it is."""


def load_state(path, default, valid):
    """Absent file -> `default` (genuine first use). Present but unreadable, not JSON or structurally invalid -> StateError, never a silent reset:
    resetting would erase an unknown spending/evidence history."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return default
    except OSError as e:
        why = f"cannot be read ({type(e).__name__})"
    else:
        try:
            data = json.loads(raw)
        except ValueError:
            data, why = None, "is not valid JSON (truncated or corrupted)"
        else:
            why = valid(data)
            if not why:
                return data
    raise StateError(f"{path.name} {why}. The file was left untouched; restore it from a backup or inspect it by hand. "
                     "The tool will not reset it automatically because that would reset the request allowance / erase evidence.")


def _ledger_problem(d):
    if not isinstance(d, dict) or not isinstance(d.get("requests"), list) or not isinstance(d.get("image_fetches"), list):
        return "has an invalid structure (expected an object with 'requests' and 'image_fetches' lists)"
    for r in d["requests"]:
        if not (isinstance(r, dict) and isinstance(r.get("n"), int) and r.get("endpoint") in ENDPOINTS and isinstance(r.get("outcome"), str)):
            return "has an invalid request entry"
    return None


def _evidence_problem(d):
    if not isinstance(d, dict) or not all(isinstance(d.get(k), t) for k, t in (("locations", list), ("searches", list), ("listings", dict),
                                                                                  ("review", dict), ("images", list))):
        return "has an invalid structure"
    # entry types the commands rely on (a hand-edited or damaged file must stop here, not crash after a request was spent)
    if any(not isinstance(x, dict) for x in d["locations"] + d["images"]) or any(not (isinstance(x, dict) and isinstance(x.get("query"), str)) for x in d["searches"]):
        return "has an invalid locations/searches/images entry"
    if any(not (isinstance(v, dict) and isinstance(v.get("verdict"), str)) for v in d["review"].values()):
        return "has an invalid review entry"
    if any(not (isinstance(v, dict) and isinstance(v.get("listing_id"), str) and isinstance(v.get("seller"), dict) and isinstance(v.get("price"), dict))
           for v in d["listings"].values()):
        return "has an invalid listing entry"
    return None


def load_ledger():
    return load_state(WORK / "ledger.json", {"max_requests": MAX_REQUESTS, "requests": [], "image_fetches": []}, _ledger_problem)


if os.name == "nt":
    import msvcrt

    def _try_lock(f):
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)

    def _unlock(f):
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _try_lock(f):
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(f):
        fcntl.flock(f, fcntl.LOCK_UN)


@contextlib.contextmanager
def run_lock(timeout=120):
    """One state-changing invocation at a time (OS file lock, released if the holder dies). Without it, simultaneous invocations each read
    the same ledger, all send, and the request cap and the ledger are both wrong."""
    try:
        WORK.mkdir(parents=True, exist_ok=True)
        lockfile = open(WORK / "run.lock", "a+b")
    except OSError as e:
        raise SaveError(f"cannot create the run lock ({type(e).__name__}: {e})") from None
    deadline = time.monotonic() + timeout
    with lockfile as f:
        while True:
            try:
                _try_lock(f)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise StateError("another marketplace_check invocation is still running. Nothing was sent.")
                time.sleep(0.05)
        for stale in WORK.glob("*.tmp"):          # exclusive now: any temp file is abandoned by a crashed run; state files are never matched
            with contextlib.suppress(OSError):
                stale.unlink()
        try:
            yield
        finally:
            _unlock(f)


class Client:
    def __init__(self, key, transport=None, limit=MAX_REQUESTS):
        self.key, self.limit = key, min(int(limit), MAX_REQUESTS)   # the ceiling can be lowered, never raised
        self.live = transport is None
        self.warnings = []
        self.sent = 0                  # requests actually handed to the transport by this client (the true "was it sent" stage)
        self.transport = transport or api_get
        self.ctx = tls_context() if self.live else None

    def scrub(self, s):
        s = str(s)
        return s.replace(self.key, "***") if self.key else s

    def get(self, kind, params):
        """One bounded API call. Returns {ok, kind, status, data, error, request_no}. Invalid params and missing key send NOTHING."""
        bad = sorted(set(params) - ALLOWED[kind])
        if bad:
            raise ValueError(f"parameter(s) {bad} are not documented for the {kind} endpoint")
        for k, v in params.items():
            if k in ENUMS and v not in ENUMS[k]:
                raise ValueError(f"{k}={v!r} is not one of {sorted(ENUMS[k])}")
        if not self.key:
            raise MissingCredentials(missing_message())
        try:
            led = load_ledger()
        except StateError as e:
            return {"ok": False, "kind": "ledger_error", "status": None, "data": None, "request_no": None, "error": f"No request was sent. {e}"}
        if len(led["requests"]) >= self.limit:
            return {"ok": False, "kind": "budget_exhausted", "status": None, "data": None, "request_no": None,
                    "error": f"request budget exhausted ({len(led['requests'])}/{self.limit}); nothing was sent"}
        entry = {"n": len(led["requests"]) + 1, "ts": time.time(), "endpoint": kind, "params": dict(params), "mode": "live" if self.live else "injected",
                 "status": None, "outcome": "sent", "credits_charged": None, "credits_remaining": None, "ms": None}
        led["requests"].append(entry)
        try:
            save_json(WORK / "ledger.json", led)      # counted BEFORE sending: a crash mid-request still uses budget
        except SaveError as e:
            return {"ok": False, "kind": "ledger_write_error", "status": None, "data": None, "request_no": None,
                    "error": f"The request was NOT sent: it could not be recorded in the ledger first ({e}). No credits were used."}
        url = API + ENDPOINTS[kind] + "?" + urllib.parse.urlencode(params)
        t0 = time.perf_counter()
        res = {"ok": False, "kind": "network_error", "status": None, "data": None, "error": None, "request_no": entry["n"]}
        self.sent += 1
        try:
            status, body, ctype = self.transport(url, {"x-api-key": self.key, "Accept": "application/json", "User-Agent": "ecom-agents-diagnostic/1"}, 60, self.ctx)
            res["status"] = status
            try:
                data = json.loads(body.decode("utf-8", "replace"))
            except ValueError:
                data = None
            msg = ""
            if isinstance(data, dict):
                msg = self.scrub(data.get("error") or data.get("message") or "")[:200]
            if status == 200:
                why = None if isinstance(data, dict) else "response was not a JSON object"
                if data and isinstance(data, dict) and (data.get("success") not in (None, True) or data.get("error")):
                    res.update(kind="provider_error", error=msg or "provider reported a failure in a 200 response")
                elif why or (why := response_problem(kind, data)):
                    res.update(kind="bad_response", error=f"malformed response: {why}")
                else:
                    res.update(ok=True, kind="ok", data=data)
            else:
                k = {400: "bad_request", 401: "auth_failed", 403: "auth_failed", 402: "credits_or_rate_limit", 429: "credits_or_rate_limit", 404: "not_found"}.get(status)
                res.update(kind=k or ("provider_error" if status >= 500 else "http_error"), error=msg or f"HTTP {status}")
            if isinstance(data, dict):
                entry["credits_charged"], entry["credits_remaining"] = data.get("credits_charged"), data.get("credits_remaining")
        except Exception as e:   # timeouts, DNS, TLS: explicit, never silent
            res["error"] = self.scrub(f"{type(e).__name__}: {e}")[:200]
        entry["ms"], entry["status"], entry["outcome"] = round((time.perf_counter() - t0) * 1000), res["status"], res["kind"]
        try:   # re-read strictly: if the file went bad mid-request it is left alone (the pre-send entry already counted this request)
            led = load_ledger()
            led["requests"][entry["n"] - 1] = entry
            save_json(WORK / "ledger.json", led)
        except (StateError, IndexError, SaveError) as e:
            self.warnings.append(f"request #{entry['n']} WAS sent and is counted in the ledger (written before sending), but its outcome ({res['kind']}) "
                                 f"could not be written to it: {e}. It was not repeated.")
        return res


def response_problem(kind, d):
    """Minimum documented shape of a 200 response (None if acceptable). Optional listing fields stay nullable: only the collection a
    caller depends on is required, and an empty collection is valid."""
    if kind == "location":
        if not isinstance(d.get("locations"), list) or any(not isinstance(x, dict) for x in d["locations"]):
            return "'locations' is missing or not an array of objects"
    elif kind == "search":
        if not isinstance(d.get("listings"), list):
            return "'listings' is missing or not an array"
        if any(not isinstance(x, dict) for x in d["listings"]):
            return "'listings' contains an entry that is not an object"
    elif kind == "item":
        if not any(d.get(k) for k in ("id", "title", "url", "description")):
            return "no item fields (id, title, url or description) present"
        for k in ("photos", "attributes"):
            if d.get(k) is not None and not isinstance(d[k], list):
                return f"'{k}' is not an array"
    return None


# ---- normalization: only what the API returned; absent stays None (never guessed)
def _price(p):
    p = p if isinstance(p, dict) else {}
    return {"amount": p.get("amount"), "currency": p.get("currency"),
            "formatted": p.get("formatted_amount") or p.get("formatted_amount_zeros_stripped")}


def _seller(s):
    if not isinstance(s, dict):
        return {"id": None, "exposed": False, "fields": []}
    sid = next((s[k] for k in ("id", "user_id", "seller_id", "profile_id") if s.get(k)), None)
    return {"id": str(sid) if sid else None, "exposed": True, "fields": sorted(s)}   # name/photo/etc. deliberately dropped


def norm_search_item(raw, prov, now):
    loc = raw.get("location") if isinstance(raw.get("location"), dict) else {}
    pp = raw.get("primary_photo") if isinstance(raw.get("primary_photo"), dict) else {}
    return {"listing_id": str(raw.get("id")) if raw.get("id") else None, "source_url": raw.get("url"), "title": raw.get("title"), "description": None,
            "price": _price(raw.get("price")), "location": {"city": loc.get("city"), "state": loc.get("state"), "display_name": loc.get("display_name"), "text": None},
            "seller": {"id": None, "exposed": False, "fields": []}, "photos": [], "primary_photo": {"id": pp.get("id"), "url": pp.get("url")} if pp else None,
            "category_id": raw.get("category_id"), "condition": None, "creation_time": raw.get("creation_time"),
            "status": {k: raw.get(k) for k in ("is_live", "is_sold", "is_pending", "is_hidden")}, "delivery_types": raw.get("delivery_types"),
            "provenance": [prov], "retrieved_at": now}


def norm_item(raw, prov, now):
    attrs = raw.get("attributes") if isinstance(raw.get("attributes"), list) else []
    cond = next((a.get("value") or a.get("label") for a in attrs if isinstance(a, dict) and str(a.get("attribute_name", "")).lower() == "condition"), None)
    photos = [{"id": p.get("id"), "url": p.get("url"), "width": p.get("width"), "height": p.get("height"), "caption": p.get("accessibility_caption")}
              for p in (raw.get("photos") or []) if isinstance(p, dict)]
    loc = raw.get("location") if isinstance(raw.get("location"), dict) else {}
    return {"listing_id": str(raw.get("id")) if raw.get("id") else None, "source_url": raw.get("url"), "title": raw.get("title"), "description": raw.get("description"),
            "price": _price(raw.get("price")), "location": {"city": None, "state": None, "display_name": None, "text": raw.get("location_text"),
                                                            "latitude": loc.get("latitude"), "longitude": loc.get("longitude")},
            "seller": _seller(raw.get("seller")), "photos": photos, "primary_photo": None, "category_id": raw.get("category_id"), "condition": cond,
            "creation_time": raw.get("creation_time"), "status": {k: raw.get(k) for k in ("is_live", "is_sold", "is_pending", "is_hidden")},
            "delivery_types": raw.get("delivery_types"), "attributes": [a for a in attrs if isinstance(a, dict)], "provenance": [prov], "retrieved_at": now}


def _blank(v):
    return v is None or v == "" or v == [] or v == {}


def merge(evidence, rec):
    """Merge a later record into the stored one field by field. Supplied (non-blank) values update; omitted ones never erase a known value
    (a search result carries no seller or currency, an item result no city/state). Known seller id and `exposed` are kept."""
    if not rec.get("listing_id"):
        return False
    cur = evidence["listings"].get(rec["listing_id"])
    if not cur:
        evidence["listings"][rec["listing_id"]] = rec
        return True
    for k, v in rec.items():
        if k == "provenance":
            cur["provenance"] = (cur.get("provenance") or []) + v
        elif k == "seller":
            old = cur.get("seller") if isinstance(cur.get("seller"), dict) else {}
            cur["seller"] = {"id": v.get("id") or old.get("id"), "exposed": bool(old.get("exposed") or v.get("exposed")),
                             "fields": sorted(set(old.get("fields") or []) | set(v.get("fields") or []))}
        elif isinstance(v, dict) and isinstance(cur.get(k), dict):
            cur[k] = {**cur[k], **{kk: vv for kk, vv in v.items() if not _blank(vv)}}
        elif not _blank(v):
            cur[k] = v
    return False


def load_evidence():
    return load_state(WORK / "evidence.json", {"locations": [], "searches": [], "listings": {}, "review": {}, "images": []}, _evidence_problem)


def heuristic_match(rec):
    return sorted({m.group(0).lower() for m in TEXTILE.finditer(f"{rec.get('title') or ''} {rec.get('description') or ''}")})


# ---- photo check: fetched, content-type, size, magic bytes, full decode (Pillow is already installed in the Hermes venv)
def check_image(url, transport=None, ctx=None, timeout=30, max_bytes=5_000_000):
    out = {"url_host": urllib.parse.urlparse(url or "").netloc, "kind": None, "http_status": None, "content_type": None, "bytes": None,
           "sha256": None, "width": None, "height": None, "decoded": None, "error": None}
    if not url:
        return {**out, "kind": "no_url", "error": "listing exposes no photo URL"}
    try:
        status, body, ctype = (transport or http_get)(url, {"User-Agent": "Mozilla/5.0", "Accept": "image/*"}, timeout, ctx)
    except Exception as e:
        return {**out, "kind": "network_error", "error": f"{type(e).__name__}: {e}"[:200]}
    out.update(http_status=status, content_type=ctype, bytes=len(body))
    if status != 200:
        return {**out, "kind": "http_error", "error": f"HTTP {status}"}
    if len(body) > max_bytes:
        return {**out, "kind": "too_large", "error": f"over {max_bytes} bytes"}
    out["sha256"] = hashlib.sha256(body).hexdigest()
    if not str(ctype).lower().startswith("image/"):
        return {**out, "kind": "not_image", "error": f"content-type {ctype!r}"}
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(body))
        im.load()                                   # full decode, not just a header
        out.update(width=im.width, height=im.height, decoded=True, format=im.format)
    except ImportError:
        return {**out, "kind": "unchecked", "decoded": None, "error": "Pillow not installed; bytes fetched but not decoded"}
    except Exception as e:
        return {**out, "kind": "decode_failed", "decoded": False, "error": f"{type(e).__name__}: {e}"[:200]}
    return {**out, "kind": "usable", "_body": body}


# ---- redaction for the shareable fixture
PHONE = re.compile(r"(\+?\d[\d\s().-]{7,}\d)")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def redact_text(s):
    return EMAIL.sub("[email]", PHONE.sub("[phone]", s)) if isinstance(s, str) else s


def strip_query(u):
    if not u:
        return u
    p = urllib.parse.urlparse(u)
    return urllib.parse.urlunparse((p.scheme, p.netloc, p.path, "", "", ""))


def build_fixture(ev, ledger, require_live=True):
    reqs = ledger.get("requests", [])
    if require_live and (not reqs or any(r.get("mode") != "live" for r in reqs)):
        raise RuntimeError("no live evidence: the ledger is empty or contains injected/test requests; refusing to write a fixture")
    sellers, listings = {}, []
    for rec in ev["listings"].values():
        r = json.loads(json.dumps(rec))
        sid = (r.get("seller") or {}).get("id")
        if sid:
            r["seller"]["id"] = sellers.setdefault(sid, f"seller_{len(sellers) + 1}")   # stable pseudonym; the platform id is not kept
        r["description"], r["title"] = redact_text(r.get("description")), redact_text(r.get("title"))
        if r.get("primary_photo"):
            r["primary_photo"]["url"] = strip_query(r["primary_photo"].get("url"))
        for p in r.get("photos") or []:
            p["url"] = strip_query(p.get("url"))
        r["manual_review"] = ev["review"].get(r["listing_id"])
        r["heuristic_textile_terms"] = heuristic_match(r)
        listings.append(r)
    imgs = [{k: v for k, v in i.items() if k not in ("_body", "url")} for i in ev["images"]]
    return {"schema": 1, "live": all(q.get("mode") == "live" for q in reqs) and bool(reqs), "source": "ScrapeCreators Facebook Marketplace (documented endpoints)",
            "note": "Redacted: seller ids pseudonymised, names/profile data not kept, phone/email patterns removed, photo URLs stripped of signed query strings. "
                    "Photo bytes are NOT stored here (third-party images; kept only in git-ignored runtime/).",
            "usage": usage(ledger), "locations_checked": [{k: v for k, v in l.items() if k in ("name", "subtitle", "city", "latitude", "longitude")} for l in ev["locations"]],
            "searches": ev["searches"], "listings": listings, "image_checks": imgs}


def usage(ledger):
    rq = ledger.get("requests", [])
    ch = [r["credits_charged"] for r in rq if isinstance(r.get("credits_charged"), (int, float))]
    rem = [r["credits_remaining"] for r in rq if r.get("credits_remaining") is not None]
    return {"api_requests": len(rq), "max_requests": ledger.get("max_requests", MAX_REQUESTS), "by_endpoint": {k: sum(1 for r in rq if r["endpoint"] == k) for k in ENDPOINTS},
            "by_outcome": {o: sum(1 for r in rq if r["outcome"] == o) for o in sorted({r["outcome"] for r in rq})},
            "credits_charged_reported": sum(ch) if ch else None, "requests_with_reported_credits": len(ch), "credits_remaining_last_reported": rem[-1] if rem else None,
            "documented_cost_per_request": 1, "api_time_ms": sum(r["ms"] or 0 for r in rq), "image_fetches": len(ledger.get("image_fetches", []))}


# ---- commands
def save_evidence(c, ev, request_no):
    """Persist evidence for a request that was ALREADY sent and counted. A failure is reported as exactly that; the request is never repeated."""
    try:
        save_json(WORK / "evidence.json", ev)
        return True
    except SaveError as e:
        c.warnings.append(f"request #{request_no} WAS sent and counted, but its result could NOT be saved to evidence.json ({e}). The previous evidence is "
                          "intact and the request was not repeated; its data is lost unless it is requested again, which spends another request.")
        return False


def cmd_locate(c, a):
    ev = load_evidence()
    r = c.get("location", {"query": a.query})
    if not r["ok"]:
        return fail(r)
    ev["locations"] = r["data"].get("locations") or []
    if not save_evidence(c, ev, r["request_no"]):
        return 6
    print(f"{len(ev['locations'])} location(s) for {a.query!r}:")
    for i, l in enumerate(ev["locations"], 1):
        print(f"  [{i}] {l.get('name')} | {l.get('subtitle')} | lat {l.get('latitude')} lng {l.get('longitude')} | city {l.get('city')}")
    return 0


def cmd_search(c, a):
    ev = load_evidence()
    if a.lat is None:
        if not a.location or a.location > len(ev["locations"]):
            print("choose a location: run `locate <city>` then pass --location N, or give --lat/--lng"); return 2
        loc = ev["locations"][a.location - 1]
        a.lat, a.lng = loc["latitude"], loc["longitude"]
    cursor = None
    if a.next:
        prev = next((s for s in reversed(ev["searches"]) if s["query"] == a.query and s.get("cursor")), None)
        if not prev:
            print("no earlier page with a cursor for this query"); return 2
        cursor = prev["cursor"]
    p = {"query": a.query, "lat": a.lat, "lng": a.lng}
    for k in ("radius_km", "condition", "sort_by", "min_price", "max_price", "delivery_method", "date_listed", "availability"):
        if getattr(a, k) is not None:
            p[k] = getattr(a, k)
    if cursor:
        p["cursor"] = cursor
    r = c.get("search", p)
    if not r["ok"]:
        return fail(r)
    d, now = r["data"], time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    items = d.get("listings") or []
    filt = {k: v for k, v in p.items() if k not in ("query", "cursor")}
    new = skipped = 0
    for raw in items:
        rec = norm_search_item(raw, {"endpoint": "search", "query": a.query, "filters": filt, "request_no": r["request_no"]}, now)
        if not rec["listing_id"]:
            skipped += 1
            continue
        new += merge(ev, rec)
    ev["searches"].append({"query": a.query, "filters": filt, "page": 1 + (sum(1 for s in ev["searches"] if s["query"] == a.query) if a.next else 0),
                           "results": len(items), "new_listings": new, "skipped_without_id": skipped, "has_next_page": d.get("has_next_page"), "cursor": d.get("cursor"), "request_no": r["request_no"], "retrieved_at": now})
    if not save_evidence(c, ev, r["request_no"]):
        return 6
    print(f"search {a.query!r}: {len(items)} result(s), {new} new, has_next_page={d.get('has_next_page')}" + ("  [EMPTY: provider returned no listings]" if not items else ""))
    for raw in items:
        if not raw.get("id"):
            continue
        rec = ev["listings"].get(str(raw.get("id")), {})
        print(f"  {rec.get('listing_id')} | {(rec.get('price') or {}).get('formatted')} | {str(rec.get('title'))[:60]} | {(rec.get('location') or {}).get('display_name')} | photo={'y' if rec.get('primary_photo') else 'n'} | terms={heuristic_match(rec)}")
    return 0


def cmd_item(c, a):
    ev = load_evidence()
    code, saved = 0, []
    for n, i in enumerate(a.ids):
        rest = a.ids[n + 1:]
        r = c.get("item", {"id": i})
        if not r["ok"]:
            code = fail(r)
            if r["kind"] in ("budget_exhausted", "auth_failed", "ledger_error", "ledger_write_error"):
                print(f"  batch stopped: saved {saved}; item {i} NOT sent/failed; not attempted: {rest}")
                break
            continue
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        rec = norm_item(r["data"], {"endpoint": "item", "request_no": r["request_no"]}, now)
        rec["listing_id"] = rec["listing_id"] or str(i)
        merge(ev, rec)
        if not save_evidence(c, ev, r["request_no"]):
            print(f"  batch stopped: saved {saved}; item {i} sent and counted but NOT saved; not attempted: {rest}")
            return 6
        saved.append(rec["listing_id"])
        print(f"  item {rec['listing_id']}: description={'y' if rec['description'] else 'n'} photos={len(rec['photos'])} seller_exposed={rec['seller']['exposed']} "
              f"seller_id={'y' if rec['seller']['id'] else 'n'} price={rec['price']['formatted']} condition={rec['condition']}")
    return code


def cmd_review(c, a):
    ev = load_evidence()
    if a.id not in ev["listings"]:
        print("unknown listing id"); return 2
    ev["review"][a.id] = {"verdict": a.verdict, "note": a.note or "", "by": "claude-manual"}
    save_json(WORK / "evidence.json", ev)
    return 0


def cmd_images(c, a):
    ev, led = load_evidence(), load_ledger()
    ids = a.ids or [i for i, r in ev["listings"].items() if r.get("photos") or r.get("primary_photo")][: a.n]
    for i in ids:
        if len(led["image_fetches"]) >= MAX_IMAGE_FETCHES:
            print("image fetch cap reached"); break
        rec = ev["listings"].get(i)
        url = ((rec.get("photos") or [{}])[0].get("url") if rec else None) or ((rec.get("primary_photo") or {}).get("url") if rec else None)
        res = check_image(url, ctx=tls_context())
        body = res.pop("_body", None)
        if body:
            try:
                (WORK / "images").mkdir(parents=True, exist_ok=True)
                ext = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif"}.get(res.get("format"), "bin")
                (WORK / "images" / f"{i}.{ext}").write_bytes(body)
            except OSError as e:
                res["error"] = f"image fetched and decoded but could not be saved to disk ({type(e).__name__}: {e})"
        led["image_fetches"].append({"listing_id": i, "ts": time.time(), "kind": res["kind"]})
        ev["images"].append({"listing_id": i, **res})
        print(f"  image {i}: {res['kind']} http={res['http_status']} {res['content_type']} {res['bytes']}B {res['width']}x{res['height']}" + (f" ({res['error']})" if res["error"] else ""))
    save_json(WORK / "ledger.json", led)
    save_json(WORK / "evidence.json", ev)
    return 0


def cmd_report(c, a):
    ev, led = load_evidence(), load_ledger()
    L = list(ev["listings"].values())
    rel = [r for r in L if ev["review"].get(r["listing_id"], {}).get("verdict") == "relevant"]
    sellers = {r["seller"]["id"] for r in rel if r["seller"]["id"]}
    u = usage(led)
    print(json.dumps({"usage": u, "searches": len(ev["searches"]), "listings_seen": len(L), "with_primary_or_detail_photo": sum(1 for r in L if r.get("photos") or r.get("primary_photo")),
                      "with_description": sum(1 for r in L if r.get("description")), "with_price": sum(1 for r in L if (r.get("price") or {}).get("amount") is not None),
                      "heuristic_textile_term_match": sum(1 for r in L if heuristic_match(r)), "manually_relevant": len(rel),
                      "manually_irrelevant": sum(1 for r in L if ev["review"].get(r["listing_id"], {}).get("verdict") == "irrelevant"),
                      "relevant_with_image": sum(1 for r in rel if r.get("photos") or r.get("primary_photo")), "distinct_known_sellers_among_relevant": len(sellers),
                      "relevant_with_unknown_seller": sum(1 for r in rel if not r["seller"]["id"]), "details_retrieved": sum(1 for r in L if r.get("photos") or r.get("description")),
                      "image_checks": {k: sum(1 for i in ev["images"] if i["kind"] == k) for k in sorted({i["kind"] for i in ev["images"]})}}, indent=1))
    return 0


def cmd_fixture(c, a):
    try:
        fx = build_fixture(load_evidence(), load_ledger())
    except RuntimeError as e:
        print(f"NOT WRITTEN: {e}"); return 3
    save_json(FIXTURE, fx)
    print(f"wrote {FIXTURE.relative_to(ROOT)} ({len(fx['listings'])} listings)")
    return 0


def cmd_status(c, a):
    print(f"API key ({KEY_NAME}): {'configured' if get_key() else 'MISSING - ' + missing_message()}")
    u = usage(load_ledger())
    print(f"requests used {u['api_requests']}/{u['max_requests']}; image fetches {u['image_fetches']}/{MAX_IMAGE_FETCHES}; work dir {WORK.relative_to(ROOT)}")
    return 0


def fail(r):
    print(f"FAILED [{r['kind']}] {r['error']}" + (f" (HTTP {r['status']})" if r.get("status") else "") + (f"; request #{r['request_no']} counted" if r.get("request_no") else ""))
    return 1


def main(argv=None, transport=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("report")
    sub.add_parser("fixture")
    p = sub.add_parser("locate"); p.add_argument("query")
    p = sub.add_parser("search"); p.add_argument("query")
    p.add_argument("--location", type=int); p.add_argument("--lat", type=float); p.add_argument("--lng", type=float)
    p.add_argument("--radius-km", dest="radius_km", type=float); p.add_argument("--condition"); p.add_argument("--sort-by", dest="sort_by")
    p.add_argument("--min-price", dest="min_price", type=float); p.add_argument("--max-price", dest="max_price", type=float)
    p.add_argument("--delivery-method", dest="delivery_method"); p.add_argument("--date-listed", dest="date_listed"); p.add_argument("--availability")
    p.add_argument("--next", action="store_true", help="fetch the next page (cursor from the previous search of the same query)")
    p = sub.add_parser("item"); p.add_argument("ids", nargs="+")
    p = sub.add_parser("review"); p.add_argument("id"); p.add_argument("verdict", choices=["relevant", "irrelevant", "unsure"]); p.add_argument("note", nargs="?")
    p = sub.add_parser("images"); p.add_argument("--n", type=int, default=3); p.add_argument("ids", nargs="*")
    a = ap.parse_args(argv)
    local = {"status": cmd_status, "report": cmd_report, "fixture": cmd_fixture, "review": cmd_review, "images": cmd_images}
    c, rc = None, 0

    def stage():
        return (f"{c.sent} API request(s) were sent by this command and were counted before sending; none was repeated." if c and c.sent
                else "No API request was sent by this command.")
    try:
        lock = run_lock() if a.cmd in ("locate", "search", "item", "review", "images") else contextlib.nullcontext()
        with lock:
            if a.cmd in local:
                rc = local[a.cmd](None, a)
            else:
                c = Client(get_key(), transport)
                rc = {"locate": cmd_locate, "search": cmd_search, "item": cmd_item}[a.cmd](c, a)
    except StateError as e:
        print(f"STOPPED: {e} {stage()}")
        rc = 5
    except SaveError as e:
        print(f"STOPPED: a local file write failed: {e}. Existing files were left intact. {stage()}")
        rc = 6
    except MissingCredentials as e:
        print(f"CANNOT RUN: {e}")
        rc = 4
    except ValueError as e:
        print(f"INVALID INPUT (nothing sent, no credits used): {e}")
        rc = 2
    for w in (c.warnings if c else []):
        print(f"WARNING: {w}")
    if rc == 0 and c and c.warnings:
        rc = 6                      # a request succeeded but part of its result/outcome could not be saved: never a clean exit
    return rc


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    sys.exit(main())
