"""DIAGNOSTIC TESTS for scripts/marketplace_check.py: failure handling and bookkeeping with MOCKED transports and synthetic documented-shape
payloads. These are NOT live ScrapeCreators evidence and say nothing about real Marketplace inventory. No network, no credentials, no Hermes;
runs in a temp root (ECOM_APP_ROOT), never touches runtime/ or secrets/ of the project.
  venv-python tests/marketplace_check_test.py"""
import contextlib, importlib.util, io, json, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if len(sys.argv) > 1 and sys.argv[1] == "--child":      # one overlapping CLI invocation with a counting mock transport
    _sp = importlib.util.spec_from_file_location("marketplace_check", ROOT / "scripts" / "marketplace_check.py")
    _m = importlib.util.module_from_spec(_sp)
    _sp.loader.exec_module(_m)
    _counter, _start, _iid = sys.argv[2], float(sys.argv[3]), sys.argv[4]

    def _tr(url, headers, timeout, ctx):
        with open(_counter, "a") as f:
            f.write("x\n")
        time.sleep(0.05)
        return 200, json.dumps({"success": True, "id": _iid, "title": "t", "credits_charged": 1, "credits_remaining": 1}).encode(), "application/json"
    os.environ["SCRAPECREATORS_API_KEY"] = "SENTINEL-KEY-0123456789"
    while time.time() < _start:
        pass
    sys.exit(_m.main(["item", _iid], transport=_tr))
TMP = Path(tempfile.mkdtemp(prefix="mkt_"))
os.environ["ECOM_APP_ROOT"] = str(TMP)
os.environ.pop("SCRAPECREATORS_API_KEY", None)
spec = importlib.util.spec_from_file_location("marketplace_check", ROOT / "scripts" / "marketplace_check.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
KEY = "SENTINEL-KEY-0123456789"
results = []


def check(name, ok, detail=""):
    ok = bool(ok); results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{str(detail)[:500]}]"), flush=True)


def fresh():
    shutil.rmtree(TMP / "runtime", ignore_errors=True)
    shutil.rmtree(TMP / "secrets", ignore_errors=True)
    shutil.rmtree(TMP / "tests", ignore_errors=True)
    os.environ.pop("SCRAPECREATORS_API_KEY", None)


class T:
    """Mock transport. Records calls; `plan` is a callable (n, url) -> (status, body, ctype) or raises."""
    def __init__(self, plan):
        self.plan, self.calls = plan, []

    def __call__(self, url, headers, timeout, ctx):
        self.calls.append((url, dict(headers)))
        r = self.plan(len(self.calls), url)
        if isinstance(r, Exception):
            raise r
        s, b, c = r
        return s, (b if isinstance(b, bytes) else json.dumps(b).encode()), c


def ok(body):
    return lambda n, u: (200, body, "application/json")


def run(argv, transport=None, key=KEY):
    if key:
        os.environ["SCRAPECREATORS_API_KEY"] = key
    else:
        os.environ.pop("SCRAPECREATORS_API_KEY", None)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = m.main(argv, transport=transport)
    return code, buf.getvalue()


def ledger():
    return m.load_ledger()


# Synthetic payloads shaped like the DOCUMENTED responses (field names from the docs; values invented)
LOC = {"success": True, "credits_remaining": 998, "credits_charged": 1,
       "locations": [{"name": "Dallas, Texas", "subtitle": "City", "multi_line_address": [], "page_id": "1", "latitude": 32.78, "longitude": -96.8, "city": "Dallas", "postal_code": "75201"}]}
SEARCH = {"success": True, "credits_remaining": 997, "credits_charged": 1, "has_next_page": True, "cursor": "CUR1", "listings": [
    {"id": "111", "url": "https://www.facebook.com/marketplace/item/111/", "title": "Queen comforter set new", "price": {"formatted_amount": "$40", "amount": 40},
     "location": {"city": "Dallas", "state": "TX", "display_name": "Dallas, TX"}, "primary_photo": {"id": "p1", "url": "https://cdn.example/p1.jpg?oh=SIGNED&oe=1"},
     "category_id": "c", "is_live": True, "is_sold": False, "delivery_types": ["IN_PERSON"]},
    {"id": "222", "title": "Blackout curtains"},                                    # no price, photo, location, url
    {"id": "333", "url": "https://www.facebook.com/marketplace/item/333/", "title": "Mountain bike", "price": {"amount": 90, "formatted_amount": "$90"}}]}
ITEM = {"success": True, "credits_remaining": 996, "credits_charged": 1, "id": "111", "url": "https://www.facebook.com/marketplace/item/111/", "title": "Queen comforter set new",
        "description": "Brand new in bag. Call 214-555-0199 or mail pat@example.com", "price": {"formatted_amount_zeros_stripped": "$40", "amount": 40, "currency": "USD"},
        "location_text": "Dallas, TX", "location": {"latitude": 32.7, "longitude": -96.8}, "attributes": [{"attribute_name": "Condition", "value": "new", "label": "New"}],
        "photos": [{"id": "p1", "url": "https://cdn.example/p1.jpg?oh=SIGNED&oe=1", "width": 800, "height": 600, "accessibility_caption": "A bed"}],
        "seller": {"id": "S-777", "name": "Pat Example", "profile_picture": "https://cdn.example/pat.jpg"}, "creation_time": 1760000000}
ITEM_SPARSE = {"success": True, "credits_remaining": 995, "credits_charged": 1, "id": "222", "title": "Blackout curtains", "photos": [], "seller": None}


def png(w=40, h=30):
    from PIL import Image
    b = io.BytesIO(); Image.new("RGB", (w, h), (200, 200, 255)).save(b, "PNG"); return b.getvalue()


print("DIAGNOSTIC TESTS (mocked transport; not live scraper evidence)", flush=True)

# 1. missing credentials: clear fix, nothing sent, nothing counted
fresh()
t = T(ok(LOC))
code, out = run(["locate", "Dallas"], t, key=None)
check("missing key: exit 4, names the file and field, no request sent, ledger untouched",
      code == 4 and "SCRAPECREATORS_API_KEY" in out and "secrets/local.env" in out and not t.calls and not ledger()["requests"], (code, out))
env = {k: v for k, v in os.environ.items() if k != "SCRAPECREATORS_API_KEY"}
p = subprocess.run([sys.executable, str(ROOT / "scripts" / "marketplace_check.py"), "status"], capture_output=True, text=True, env=env)
check("CLI status without a key says MISSING and exits cleanly", p.returncode == 0 and "MISSING" in p.stdout and "0/20" in p.stdout, p.stdout + p.stderr)
(TMP / "secrets").mkdir(exist_ok=True)
(TMP / "secrets" / "local.env").write_text(f"# c\nLLM_PROVIDER=x\n{m.KEY_NAME}={KEY}\n", encoding="utf-8")
code, out = run(["status"], key=None)
check("key read from secrets/local.env is reported as configured and never printed", "configured" in out and KEY not in out, out)

# 2. input validation: nothing sent, nothing counted
fresh()
t = T(ok(SEARCH))
c1, o1 = run(["search", "comforter", "--lat", "32.7", "--lng", "-96.8", "--condition", "brand_new"], t)
try:
    m.Client(KEY, t).get("search", {"query": "x", "lat": 1, "lng": 1, "url": "https://evil.example"}); undoc = False
except ValueError:
    undoc = True
c2, o2 = run(["search", "comforter", "--lat", "32.7", "--lng", "-96.8", "--sort-by", "cheapest"], t)
check("invalid enum / undocumented parameter / arbitrary URL rejected locally: no request, no credits", c1 == 2 and c2 == 2 and undoc and not t.calls and not ledger()["requests"], (c1, c2, undoc))

# 3. documented flow + normalization + provenance
fresh()
t = T(lambda n, u: (200, [LOC, SEARCH, ITEM][n - 1], "application/json"))
c, o = run(["locate", "Dallas"], t)
c, o = run(["search", "queen comforter", "--location", "1", "--condition", "new", "--radius-km", "50"], t)
c, o = run(["item", "111"], t)
ev = m.load_evidence()
q = t.calls[1][0]
check("flow works against documented shapes: locate -> search (lat/lng/condition/radius sent) -> item; key only in the x-api-key header",
      c == 0 and "lat=32.78" in q and "lng=-96.8" in q and "condition=new" in q and "radius_km=50.0" in q and "query=queen+comforter" in q and KEY not in q
      and all(h.get("x-api-key") == KEY for _, h in t.calls), (q, c))
l111, l222 = ev["listings"]["111"], ev["listings"]["222"]
check("normalized record keeps id/url/title/price/location/photo/provenance and merges the item detail (description, photos, seller id, condition, currency)",
      l111["source_url"].endswith("/111/") and l111["price"]["amount"] == 40 and l111["price"]["currency"] == "USD" and l111["description"].startswith("Brand new")
      and l111["photos"][0]["width"] == 800 and l111["seller"] == {"id": "S-777", "exposed": True, "fields": ["id", "name", "profile_picture"]}
      and l111["condition"] == "new" and len(l111["provenance"]) == 2 and l111["provenance"][0]["filters"]["condition"] == "new" and l111["retrieved_at"], l111)
check("seller name / profile picture are not retained anywhere in the record", "Pat Example" not in json.dumps(ev) and "pat.jpg" not in json.dumps(ev))
check("absent fields stay None/unknown, never invented (no price, photo, URL, location, seller)",
      l222["price"] == {"amount": None, "currency": None, "formatted": None} and l222["primary_photo"] is None and l222["source_url"] is None
      and l222["location"]["display_name"] is None and l222["seller"]["id"] is None and l222["seller"]["exposed"] is False and l222["description"] is None, l222)
led = ledger()
check("ledger counts 3 requests with MEASURED credits_charged/remaining from responses and per-request time",
      len(led["requests"]) == 3 and m.usage(led)["credits_charged_reported"] == 3 and m.usage(led)["credits_remaining_last_reported"] == 996
      and all(r["ms"] is not None for r in led["requests"]), m.usage(led))

# 4. key never leaks, including through provider error bodies and exception messages
fresh()
t = T(lambda n, u: (401, {"error": f"invalid api key {KEY}"}, "application/json") if n == 1 else OSError(f"connect failed for key {KEY}"))
c1, o1 = run(["locate", "Dallas"], t)
c2, o2 = run(["locate", "Dallas"], t)
blob = o1 + o2 + "".join(p.read_text(encoding="utf-8", errors="ignore") for p in (TMP / "runtime").rglob("*") if p.is_file())
check("provider error body and exception text containing the key are scrubbed from output, ledger and evidence", KEY not in blob and "***" in blob, blob[:300])

# 5. authentication failure: explicit, one request, no retry, batch stops
fresh()
t = T(lambda n, u: (403, {"error": "forbidden"}, "application/json"))
c, o = run(["item", "1", "2", "3"], t)
check("auth failure (403): reported as auth_failed, exactly one request made and counted, remaining ids not attempted", c == 1 and "auth_failed" in o and len(t.calls) == 1 and ledger()["requests"][0]["outcome"] == "auth_failed", (o, len(t.calls)))
fresh()
t = T(lambda n, u: (401, {}, "application/json"))
c, o = run(["locate", "Dallas"], t)
check("auth failure (401) is also explicit", c == 1 and "auth_failed" in o and len(t.calls) == 1, o)

# 6. empty inventory vs provider failure vs HTTP error are different outcomes
fresh()
t = T(ok({"success": True, "credits_remaining": 9, "credits_charged": 1, "listings": [], "has_next_page": False}))
c, o = run(["search", "velvet drapes", "--lat", "1", "--lng", "2"], t)
check("empty results: success exit, reported as EMPTY (not an error), recorded as a search with 0 results", c == 0 and "EMPTY" in o and m.load_evidence()["searches"][0]["results"] == 0, o)
for label, plan, kind in [("success:false body", lambda n, u: (200, {"success": False, "error": "upstream blocked"}, "application/json"), "provider_error"),
                          ("HTTP 500", lambda n, u: (500, b"<html>", "text/html"), "provider_error"),
                          ("HTTP 429", lambda n, u: (429, {"error": "slow down"}, "application/json"), "credits_or_rate_limit"),
                          ("not JSON 200", lambda n, u: (200, b"<html>ok</html>", "text/html"), "bad_response"),
                          ("timeout", lambda n, u: TimeoutError("timed out"), "network_error")]:
    fresh()
    c, o = run(["locate", "Dallas"], T(plan))
    check(f"error kind distinguished: {label} -> {kind}, exit 1, counted once", c == 1 and f"[{kind}]" in o and len(ledger()["requests"]) == 1, o)

# 7. image checks
good = png()
cases = [("accessible, decodable image", (200, good, "image/png"), "usable"), ("404", (404, b"", "text/html"), "http_error"),
         ("HTML page instead of an image", (200, b"<html>login</html>", "text/html"), "not_image"),
         ("truncated image bytes", (200, good[:60], "image/png"), "decode_failed"), ("network fault", OSError("reset"), "network_error"),
         ("oversized", (200, b"\0" * 20, "image/png"), None)]
for label, resp, want in cases:
    if want is None:
        r = m.check_image("https://cdn.example/x.jpg", T(lambda n, u, resp=resp: resp), max_bytes=10)
        want = "too_large"
    else:
        r = m.check_image("https://cdn.example/x.jpg?sig=S", T(lambda n, u, resp=resp: resp))
    check(f"image check: {label} -> {want}", r["kind"] == want and (r["kind"] != "usable" or (r["width"], r["height"], r["decoded"]) == (40, 30, True)), r)
check("image check: listing without a photo URL -> no_url", m.check_image(None)["kind"] == "no_url")

# 8. request budget: hard ceiling across invocations, failures counted, nothing sent after exhaustion
fresh()
t = T(lambda n, u: (401, {}, "application/json") if n % 2 else (200, LOC, "application/json"))
last = None
for i in range(m.MAX_REQUESTS):
    last = m.Client(KEY, t).get("location", {"query": f"c{i}"})       # a NEW client each time = a new invocation
over = m.Client(KEY, t, limit=999).get("location", {"query": "one too many"})
check("budget: 20 requests (half of them failures) are counted across fresh clients; the 21st is refused with no network call even if a larger limit is asked for",
      len(ledger()["requests"]) == 20 and over["kind"] == "budget_exhausted" and len(t.calls) == 20, (len(ledger()["requests"]), len(t.calls), over))
c, o = run(["item", "9"], t)
check("CLI reports budget exhaustion explicitly and sends nothing", c == 1 and "budget_exhausted" in o and len(t.calls) == 20, o)
check("budget is persisted: the request counter survives a new process", ledger()["max_requests"] == 20 and subprocess.run([sys.executable, str(ROOT / "scripts" / "marketplace_check.py"), "status"], capture_output=True, text=True,
      env={**env, "ECOM_APP_ROOT": str(TMP)}).stdout.count("20/20") == 1)

# 9. fixture: refuses without live evidence; redacts when asked on synthetic data (flagged live:false)
fresh()
code, out = run(["fixture"])
check("fixture refuses with no evidence (nothing fabricated, no file)", code == 3 and not m.FIXTURE.exists(), out)
t = T(lambda n, u: (200, [LOC, SEARCH, ITEM][n - 1], "application/json"))
run(["locate", "Dallas"], t); run(["search", "comforter", "--location", "1"], t); run(["item", "111"], t)
code, out = run(["fixture"])
check("fixture refuses when the requests came from an injected (test) transport", code == 3 and not m.FIXTURE.exists(), out)
fx = m.build_fixture(m.load_evidence(), m.load_ledger(), require_live=False)
txt = json.dumps(fx)
check("redaction (synthetic data): phone/email removed, seller id pseudonymised, signed photo query stripped, no seller name, flagged live=false",
      "214-555-0199" not in txt and "pat@example.com" not in txt and "S-777" not in txt and "seller_1" in txt and "SIGNED" not in txt
      and "Pat Example" not in txt and fx["live"] is False and fx["usage"]["api_requests"] == 3, txt[:400])
c, o = run(["report"])
rep0 = json.loads(o)
check("report: before manual review nothing counts as relevant; the keyword heuristic matches 2 of 3 titles (the bike does not)",
      rep0["manually_relevant"] == 0 and rep0["listings_seen"] == 3 and rep0["heuristic_textile_term_match"] == 2, rep0)
run(["review", "111", "relevant", "queen comforter, new"]); run(["review", "222", "relevant", "curtains"])
rep = json.loads(run(["report"])[1])
check("report: 2 relevant, 1 with a known seller id, 1 relevant with unknown seller", rep["manually_relevant"] == 2 and rep["distinct_known_sellers_among_relevant"] == 1
      and rep["relevant_with_unknown_seller"] == 1 and rep["relevant_with_image"] == 1, rep)


# ================= CORRECTION REGRESSIONS (ticket 02 review findings + mini audit) =================
print("-- correction regressions (mocked transport; NOT live evidence)", flush=True)


def seed_ledger(n, outcome="ok"):
    led = {"max_requests": 20, "requests": [{"n": i + 1, "ts": 1.0, "endpoint": "location", "params": {"query": "x"}, "mode": "injected", "status": 200,
                                              "outcome": outcome, "credits_charged": 1, "credits_remaining": 100 - i, "ms": 5} for i in range(n)], "image_fetches": []}
    m.save_json(m.WORK / "ledger.json", led)
    return led


def run_safe(argv, t):
    try:
        return run(argv, t)
    except BaseException as e:   # unfixed code may crash rather than fail cleanly
        return (-99, "RAISED " + repr(e))


def attempt(fn):
    try:
        return fn()
    except BaseException as e:   # the OLD code may crash instead of failing cleanly; that is a failure of the check, not of the harness
        return {"raised": repr(e)}


# --- 1. the budget fails closed on damaged/unreadable/invalid ledger state
damaged = {"truncated JSON": b'{"max_requests": 20, "requests": [{"n": 1, "endp', "empty file": b"", "not an object": b"[]",
           "requests not a list": json.dumps({"max_requests": 20, "requests": "x", "image_fetches": []}).encode(),
           "entries not objects": json.dumps({"max_requests": 20, "requests": [1, 2], "image_fetches": []}).encode(),
           "entry missing fields": json.dumps({"max_requests": 20, "requests": [{"n": 1}], "image_fetches": []}).encode(),
           "missing keys": b"{}"}
for label, raw in damaged.items():
    fresh()
    t = T(ok(LOC))
    for i in range(20):                                # exhaust the real allowance first
        m.Client(KEY, t).get("location", {"query": f"c{i}"})
    (m.WORK / "ledger.json").write_bytes(raw)
    before_calls = len(t.calls)
    r = attempt(lambda t=t: m.Client(KEY, t).get("location", {"query": "after damage"}))
    code, out = run_safe(["locate", "Dallas"], t)
    same = (m.WORK / "ledger.json").read_bytes() == raw
    check(f"damaged ledger ({label}): no further request sent, clear error, damaged bytes preserved (allowance NOT reset)",
          len(t.calls) == before_calls and "raised" not in r and r.get("ok") is False and r.get("kind") == "ledger_error" and code != 0 and same,
          (len(t.calls) - before_calls, r, code, out[:120], same))
fresh()
t = T(ok(LOC))
seed_ledger(3)
orig = Path.read_text
def deny(self, *a, **k):
    if self.name == "ledger.json":
        raise PermissionError(13, "Access is denied")
    return orig(self, *a, **k)
Path.read_text = deny
try:
    r = attempt(lambda: m.Client(KEY, t).get("location", {"query": "x"}))
finally:
    Path.read_text = orig
check("unreadable ledger (read permission error): no request sent, explicit ledger_error, file untouched",
      not t.calls and r.get("kind") == "ledger_error" and len(json.loads((m.WORK / "ledger.json").read_text())["requests"]) == 3, (r, len(t.calls)))
fresh()
t = T(ok(LOC))
r = attempt(lambda: m.Client(KEY, t).get("location", {"query": "x"}))
check("a genuinely ABSENT ledger still initializes normally (first request counted as #1)", r.get("ok") is True and len(ledger()["requests"]) == 1 and len(t.calls) == 1, r)
fresh()
m.save_json(m.WORK / "evidence.json", {"locations": [], "searches": [], "listings": {}, "review": {}, "images": []})
(m.WORK / "evidence.json").write_bytes(b'{"locations": [')
t = T(ok(SEARCH))
code, out = run_safe(["search", "comforter", "--lat", "1", "--lng", "2"], t)
check("damaged evidence file: command stops BEFORE any request and the file is preserved (no silent reset of reviews/listings)",
      code != 0 and not t.calls and (m.WORK / "evidence.json").read_bytes() == b'{"locations": [', (code, out[:150], len(t.calls)))

# --- audit: overlapping invocations must not break the 20-request cap
fresh()
seed_ledger(10)
cnt = TMP / "calls.txt"
res = []
for rnd in range(2):
    fresh()
    seed_ledger(10)
    cnt.write_text("")
    start = time.time() + 3
    env2 = {**os.environ, "ECOM_APP_ROOT": str(TMP), "PYTHONUTF8": "1"}
    ps = [subprocess.Popen([sys.executable, __file__, "--child", str(cnt), str(start), str(1000 + i)], env=env2, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for i in range(14)]
    crashed = sum(1 for p_ in ps if "Traceback" in p_.communicate()[1])
    sent = len(cnt.read_text().split())
    led = ledger()
    res.append((sent, len(led["requests"]), sorted(r["n"] for r in led["requests"]) == list(range(1, len(led["requests"]) + 1)), crashed))
check("overlapping invocations: 14 simultaneous processes against 10 remaining requests send at most 10, EVERY sent request is counted in one consistent ledger, none crashes (2 rounds)",
      all(s_ <= 10 and l_ == 10 + s_ and c_ and x_ == 0 for s_, l_, c_, x_ in res), ("(sent, ledger entries, numbering consistent, crashed children)", res))

# --- 2. merge keeps known detail when a later search omits it, and still updates with genuinely supplied values
fresh()
S2 = {"success": True, "credits_remaining": 900, "credits_charged": 1, "has_next_page": False, "cursor": None, "listings": [
    {"id": "111", "url": "https://www.facebook.com/marketplace/item/111/", "title": "Queen comforter set new", "price": {"formatted_amount": "$35", "amount": 35},
     "location": {"city": "Dallas", "state": "TX", "display_name": "Dallas, TX"}, "primary_photo": {"id": "p1", "url": "https://cdn.example/p1.jpg?oh=SIGNED&oe=1"}},
    {"id": "444", "url": "https://www.facebook.com/marketplace/item/444/", "title": "Linen curtains pair", "price": {"formatted_amount": "$25", "amount": 25}}]}
I444 = {"success": True, "credits_remaining": 899, "credits_charged": 1, "id": "444", "title": "Linen curtains pair", "description": "Two panels",
        "price": {"amount": 25, "currency": "USD"}, "photos": [{"id": "q1", "url": "https://cdn.example/q1.jpg", "width": 10, "height": 10}], "seller": {"id": "S-777", "name": "Pat"}}
seq = [LOC, SEARCH, ITEM, S2, I444]
t = T(lambda n, u: (200, seq[n - 1], "application/json"))
run(["locate", "Dallas"], t); run(["search", "comforter", "--location", "1", "--condition", "new"], t); run(["item", "111"], t)
c, o = run(["search", "bedding", "--location", "1", "--condition", "new"], t)
run(["item", "444"], t)
ev = m.load_evidence()
a = ev["listings"]["111"]
check("search -> item -> OVERLAPPING search: known seller id and currency survive; genuinely supplied price amount updates; provenance has all three requests",
      a["seller"]["id"] == "S-777" and a["seller"]["exposed"] is True and a["price"]["currency"] == "USD" and a["price"]["amount"] == 35 and a["price"]["formatted"] == "$35"
      and a["description"].startswith("Brand new") and a["photos"] and a["condition"] == "new" and a["location"]["text"] == "Dallas, TX" and a["location"]["display_name"] == "Dallas, TX"
      and [q["endpoint"] for q in a["provenance"]] == ["search", "item", "search"], a)
run(["review", "111", "relevant", "x"]); run(["review", "444", "relevant", "y"]); run(["review", "222", "relevant", "z"])
rep = json.loads(run(["report"])[1])
fx = m.build_fixture(ev, m.load_ledger(), require_live=False)
f111 = next(l for l in fx["listings"] if l["listing_id"] == "111")
check("report and fixture reflect the preserved detail: 2 listings share ONE pseudonymous seller, currency kept, 1 relevant listing has an unknown seller",
      rep["distinct_known_sellers_among_relevant"] == 1 and rep["relevant_with_unknown_seller"] == 1 and f111["seller"]["id"] == "seller_1"
      and f111["price"]["currency"] == "USD" and next(l for l in fx["listings"] if l["listing_id"] == "444")["seller"]["id"] == "seller_1", (rep, f111["seller"], f111["price"]))
fresh()
seq = [SEARCH, ITEM]
t = T(lambda n, u: (200, seq[n - 1], "application/json"))
run(["search", "comforter", "--lat", "1", "--lng", "2"], t); run(["item", "111"], t)
b = m.load_evidence()["listings"]["111"]
check("ordinary search -> item enrichment still works (description, photos, seller, currency, condition filled)",
      b["description"] and b["photos"] and b["seller"]["id"] == "S-777" and b["price"]["currency"] == "USD" and b["primary_photo"]["id"] == "p1", b)

# --- 3. malformed 200 responses are not empty inventory
def one(argv, body, status=200):
    fresh()
    t = T(lambda n, u: (status, body, "application/json"))
    c, o = run_safe(argv, t)
    e = m.load_evidence()
    return c, o, e, ledger(), t


S_ARGS = ["search", "comforter", "--lat", "1", "--lng", "2"]
for label, body in [("error-only 200", {"error": "quota exceeded"}), ("success true but no listings", {"success": True, "credits_charged": 1}),
                    ("listings null", {"success": True, "listings": None}), ("listings is an object", {"success": True, "listings": {}}),
                    ("listings is a string", {"success": True, "listings": "none"}), ("listing entry not an object", {"success": True, "listings": [1]}),
                    ("empty object", {}), ("error alongside listings", {"success": True, "error": "partial failure", "listings": []})]:
    c, o, e, led, t = one(S_ARGS, body)
    check(f"search malformed 200 ({label}): exit 1, NOT reported as empty inventory, no search/listing evidence, counted once",
          c == 1 and "EMPTY" not in o and not e["searches"] and not e["listings"] and len(led["requests"]) == 1 and led["requests"][0]["outcome"] in ("bad_response", "provider_error"),
          (c, o[:150], e["searches"], led["requests"][0]["outcome"] if led["requests"] else None))
c, o, e, led, t = one(S_ARGS, {"success": True, "credits_remaining": 5, "credits_charged": 1, "listings": [], "has_next_page": False})
check("valid empty listings array IS empty inventory: exit 0, EMPTY, search recorded with 0 results", c == 0 and "EMPTY" in o and e["searches"] and e["searches"][0]["results"] == 0, (c, o))
c, o, e, led, t = one(S_ARGS, {"success": True, "credits_charged": 1, "listings": [{"id": "9"}]})
check("valid SPARSE listing (id only) is accepted: exit 0, stored with unknown fields, not EMPTY",
      c == 0 and "EMPTY" not in o and e["listings"]["9"]["title"] is None and e["listings"]["9"]["price"]["amount"] is None and e["searches"][0]["results"] == 1, (c, o, e["listings"]))
c, o, e, led, t = one(S_ARGS, {"success": True, "listings": [{"title": "no id"}, {"id": "9", "title": "ok"}]})
check("a listing without an id is not stored and is counted, the rest of the page is kept", c == 0 and list(e["listings"]) == ["9"] and e["searches"][0].get("skipped_without_id") == 1, (c, e["searches"], list(e["listings"])))
for label, argv, body, want in [("locate: no locations key", ["locate", "Dallas"], {"success": True}, 1), ("locate: locations wrong type", ["locate", "Dallas"], {"success": True, "locations": "x"}, 1),
                                ("locate: valid empty list", ["locate", "Dallas"], {"success": True, "locations": []}, 0),
                                ("item: no identifying/content field", ["item", "5"], {"success": True, "credits_charged": 1}, 1),
                                ("item: photos wrong type", ["item", "5"], {"success": True, "id": "5", "photos": "x"}, 1),
                                ("item: error-only 200", ["item", "5"], {"error": "not available"}, 1),
                                ("item: sparse but valid", ["item", "5"], {"success": True, "id": "5"}, 0)]:
    c, o, e, led, t = one(argv, body)
    stored = bool(e["listings"]) or bool(e["locations"])
    check(f"{label}: exit {want}" + ("" if want == 0 else ", nothing stored, counted once"),
          c == want and len(led["requests"]) == 1 and (want == 0 or not stored) and (want == 1 or "FAILED" not in o), (c, o[:150], stored))

# ================= STORAGE-WRITE FAILURES (ticket 02 corrections review) =================
print("-- storage-write failure handling (injected os.replace / write failures; mocked transport; NOT live evidence)", flush=True)
m.SAVE_DELAY = 0                                     # no sleeping in tests; the retry COUNT is still the real one
ATTEMPTS = getattr(m, "SAVE_ATTEMPTS", 5)
real_replace = os.replace


@contextlib.contextmanager
def replace_fails(name, when, exc=lambda: PermissionError(13, "Access is denied")):
    """os.replace onto `name` raises while when(attempt_number) is true. attempt numbers count every try, retries included."""
    calls = []

    def fake(src, dst, *a, **k):
        if Path(dst).name == name:
            calls.append(1)
            if when(len(calls)):
                raise exc()
        return real_replace(src, dst, *a, **k)
    os.replace = fake
    try:
        yield calls
    finally:
        os.replace = real_replace


def tmps():
    return sorted(p_.name for p_ in m.WORK.rglob("*.tmp")) if m.WORK.exists() else []


def led_raw():
    return json.loads((m.WORK / "ledger.json").read_text(encoding="utf-8"))


# A. pre-send ledger write fails persistently: ZERO requests, explicit nonzero, state intact, temp cleaned, bounded retries
fresh()
seed_ledger(3)
raw0 = (m.WORK / "ledger.json").read_bytes()
t = T(ok(LOC))
with replace_fails("ledger.json", lambda n: True) as calls:
    r = attempt(lambda: m.Client(KEY, t).get("location", {"query": "x"}))
    n_get = len(calls)
    c, o = run_safe(["locate", "Dallas"], t)
check("A pre-send ledger write fails: ZERO transport calls, kind ledger_write_error, CLI exits nonzero saying the request was NOT sent, ledger bytes intact, no temp file left",
      not t.calls and r.get("kind") == "ledger_write_error" and r.get("ok") is False and c not in (0, -99) and "NOT sent" in o
      and (m.WORK / "ledger.json").read_bytes() == raw0 and not tmps(), (len(t.calls), r, c, o[:160], tmps()))
check("A2 the local write is retried a bounded number of times (not forever) before the error is returned", n_get == ATTEMPTS, (n_get, ATTEMPTS))

# B. outcome write fails AFTER the send: exactly one call, persisted count kept, explicit report, result not lost, no replay
fresh()
t = T(ok(LOC))
with replace_fails("ledger.json", lambda n: n >= 2):          # attempt 1 = the pre-send entry (succeeds); every later write fails
    c, o = run_safe(["locate", "Dallas"], t)
    led = led_raw() if (m.WORK / "ledger.json").exists() else {"requests": []}
    ev = m.load_evidence()
check("B post-send outcome write fails: exactly ONE transport call (no replay), the pre-send entry still counts the request, exit 6, message says it WAS sent and counted",
      len(t.calls) == 1 and len(led["requests"]) == 1 and c == 6 and "WAS sent" in o and "counted" in o and not tmps(), (len(t.calls), len(led["requests"]), c, o[:300], tmps()))
check("B2 ...and the result itself was still saved to evidence (only the ledger annotation failed)", len(ev["locations"]) == 1, ev["locations"])
fresh()
t = T(ok(LOC))
with replace_fails("ledger.json", lambda n: n >= 2):
    r = attempt(lambda: (lambda cl: (cl.get("location", {"query": "x"}), cl.warnings))(m.Client(KEY, t)))
check("B3 Client.get still returns the response data and records a warning naming the request number", isinstance(r, tuple) and r[0].get("ok") is True and r[1] and "#1" in r[1][0], r)

# C. evidence save fails after a sent+counted request: counted request retained, no replay, no false success, prior evidence intact
fresh()
t = T(lambda n, u: (200, SEARCH, "application/json"))
run(["search", "comforter", "--lat", "1", "--lng", "2"], t)
ev_before = (m.WORK / "evidence.json").read_bytes()
with replace_fails("evidence.json", lambda n: True) as calls:
    c, o = run_safe(["search", "curtains", "--lat", "1", "--lng", "2"], t)
led = led_raw()
check("C evidence save fails: second request sent once and counted (ledger 2, outcome ok), NOT repeated, exit 6, no success line, earlier evidence bytes intact, no temp file",
      len(t.calls) == 2 and len(led["requests"]) == 2 and led["requests"][1]["outcome"] == "ok" and c == 6 and "result(s)" not in o and "NOT be saved" in o
      and (m.WORK / "evidence.json").read_bytes() == ev_before and not tmps(), (len(t.calls), c, o[:300], tmps()))

# D. batch: first id saved, second id's evidence write fails -> stop, report saved / unsaved / not attempted accurately
fresh()
t = T(lambda n, u: (200, {"success": True, "id": str(n), "title": f"item {n}", "credits_charged": 1, "credits_remaining": 9}, "application/json"))
with replace_fails("evidence.json", lambda n: n >= 2):
    c, o = run_safe(["item", "1", "2", "3"], t)
ev = m.load_evidence()
check("D batch: item 1 saved, item 2 sent+counted but NOT saved, item 3 not attempted; exactly 2 calls, ledger 2, exit 6, report names each",
      len(t.calls) == 2 and led_raw() and len(led_raw()["requests"]) == 2 and c == 6 and list(ev["listings"]) == ["1"]
      and "not attempted" in o and "3" in o.split("not attempted")[-1] and "NOT saved" in o, (len(t.calls), c, list(ev["listings"]), o[:400]))

# E. batch: earlier request fine, later pre-send write fails -> only the earlier one was sent; the report says which was NOT sent
fresh()
t = T(lambda n, u: (200, {"success": True, "id": str(n), "title": f"item {n}", "credits_charged": 1, "credits_remaining": 9}, "application/json"))
with replace_fails("ledger.json", lambda n: n >= 3):          # id 1: pre (1) + post (2) fine; id 2: pre-send write fails
    c, o = run_safe(["item", "1", "2"], t)
check("E batch: item 1 sent and saved; item 2 was NOT sent (its ledger write failed); exactly 1 call; nonzero; nothing claims 'nothing was sent' for item 1",
      len(t.calls) == 1 and c not in (0, -99) and list(m.load_evidence()["listings"]) == ["1"] and led_raw()["requests"].__len__() == 1 and "NOT sent" in o, (len(t.calls), c, o[:300]))

# F. transient failures: retried locally and succeed; persistent covered by A2
fresh()
t = T(ok(LOC))
with replace_fails("ledger.json", lambda n: n <= 2) as calls:
    r = attempt(lambda: m.Client(KEY, t).get("location", {"query": "x"}))
check("F transient PermissionError twice then success: request sent ONCE, ledger entry complete (outcome ok), no temp left",
      r.get("ok") is True and len(t.calls) == 1 and len(led_raw()["requests"]) == 1 and led_raw()["requests"][0]["outcome"] == "ok" and not tmps(), (r, len(t.calls)))

# G. a non-transient error (disk full) is not retried and is explicit
fresh()
t = T(ok(LOC))
with replace_fails("ledger.json", lambda n: True, exc=lambda: OSError(28, "No space left on device")) as calls:
    r = attempt(lambda: m.Client(KEY, t).get("location", {"query": "x"}))
check("G disk full: not retried (1 attempt), zero transport calls, explicit ledger_write_error", len(calls) == 1 and not t.calls and r.get("kind") == "ledger_write_error", (len(calls), r))

# H. failure while writing the temp file itself
fresh()
seed_ledger(2)
raw0 = (m.WORK / "ledger.json").read_bytes()
real_wt = Path.write_text


def bad_wt(self, *a, **k):
    if self.name.endswith(".tmp"):
        raise PermissionError(13, "Access is denied")
    return real_wt(self, *a, **k)
Path.write_text = bad_wt
try:
    t = T(ok(LOC))
    r = attempt(lambda: m.Client(KEY, t).get("location", {"query": "x"}))
finally:
    Path.write_text = real_wt
check("H temp-file write fails: zero transport calls, explicit error, existing ledger intact, no temp left",
      not t.calls and r.get("kind") == "ledger_write_error" and (m.WORK / "ledger.json").read_bytes() == raw0 and not tmps(), (r, tmps()))

# I. abandoned temp files from a crashed run are swept under the lock; real state is untouched
fresh()
seed_ledger(2)
m.save_json(m.WORK / "evidence.json", {"locations": [], "searches": [], "listings": {}, "review": {}, "images": []})
(m.WORK / "ledger.json.99999.tmp").write_text("{half", encoding="utf-8")
(m.WORK / "evidence.json.4242.tmp").write_text("junk", encoding="utf-8")
(m.WORK / "images").mkdir()
(m.WORK / "images" / "keep.jpg").write_bytes(b"x")
b1, b2 = (m.WORK / "ledger.json").read_bytes(), (m.WORK / "evidence.json").read_bytes()
c, o = run_safe(["review", "nothing", "relevant"], T(ok(LOC)))
check("I abandoned *.tmp files are removed by the next locked command; ledger, evidence and other files untouched",
      not tmps() and (m.WORK / "ledger.json").read_bytes() == b1 and (m.WORK / "evidence.json").read_bytes() == b2 and (m.WORK / "images" / "keep.jpg").exists(), (tmps(), c, o))

# J. run lock cannot be created: explicit, nothing sent, no traceback
fresh()
(m.WORK / "run.lock").mkdir(parents=True)
t = T(ok(LOC))
c, o = run_safe(["locate", "Dallas"], t)
check("J run lock unavailable: nonzero, no request, no uncaught exception", not t.calls and c not in (0, -99) and "RAISED" not in o, (c, o[:200]))

# K. saved-entry type check: malformed stored entries stop the command BEFORE any request
good = {"locations": [], "searches": [], "listings": {}, "review": {}, "images": []}
for label, patch in [("listing entry is a string", {"listings": {"111": "oops"}}), ("listing entry lacks seller/price objects", {"listings": {"111": {"listing_id": "111"}}}),
                     ("search entry not an object", {"searches": [1]}), ("review entry not an object", {"review": {"111": "x"}}),
                     ("image entry not an object", {"images": [3]}), ("location entry not an object", {"locations": ["x"]})]:
    fresh()
    seed_ledger(1)
    (m.WORK).mkdir(parents=True, exist_ok=True)
    raw = json.dumps({**good, **patch}).encode()
    (m.WORK / "evidence.json").write_bytes(raw)
    t = T(lambda n, u: (200, SEARCH, "application/json"))
    c, o = run_safe(["search", "comforter", "--lat", "1", "--lng", "2"], t)
    c2, o2 = run_safe(["report"], t)
    check(f"K malformed saved evidence ({label}): search stops before any request, report fails cleanly, file untouched",
          not t.calls and c not in (0, -99) and c2 not in (0, -99) and "RAISED" not in o + o2 and (m.WORK / "evidence.json").read_bytes() == raw, (c, o[:120], c2, o2[:120]))

# L. the default API transport never follows a redirect: the credential header must not reach another address (ticket 05 review; scripted local server)
import http.server, threading
LEAKS = []


class RedirH(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        if self.path.startswith("/leak"):
            LEAKS.append({"has_key": self.headers.get("x-api-key") == KEY})
            body = json.dumps({"success": True, "locations": []}).encode()
            self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
            return
        self.send_response(302)
        self.send_header("Location", f"http://localhost:{self.server.server_address[1]}/leak")
        self.send_header("Content-Length", "0"); self.end_headers()


httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), RedirH)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
fresh()
saved_api = m.API
m.API = f"http://127.0.0.1:{httpd.server_address[1]}"
try:
    res = m.Client(KEY).get("location", {"query": "Dallas"})     # default (live) transport against the local redirecting stand-in
finally:
    m.API = saved_api
    httpd.shutdown()
check("L the default API transport does not follow a cross-host redirect: the request fails explicitly (HTTP 302), it is counted, and the redirect target never received the credential",
      res["ok"] is False and res["status"] == 302 and not LEAKS and len(ledger()["requests"]) == 1, (res.get("kind"), res.get("status"), LEAKS))

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{sum(results)}/{len(results)} diagnostic checks passed (mocked transport; NOT live evidence)")
sys.exit(0 if results and all(results) else 1)
