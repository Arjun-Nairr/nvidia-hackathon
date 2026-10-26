"""Flyer generation, actual-pixel review and at most ONE correction (V2-04 + V2-05) for a social_media specialist. Backend-owned and UI-independent.

The specialist supplies a registered catalogue product, 1-3 of THAT product's registered merchant image ids and a prompt; everything that matters is derived or enforced HERE:
- Identity: agent from the worker's environment, request from the backend (turn_state.request_id); company/product/candidate/run ids are generated or looked up
  here. There is no URL, path, credential, provider setting, run, attempt or allowance argument on any tool.
- Inputs: only the selected product's catalogue-registered merchant images are sent to Gemini, as their ORIGINAL bytes (decoded and size-bounded first). Competitor/ad
  images are cited by id as provenance only and are never sent. Synthetic stand-ins are refused unless the operator sets ECOM_FLYER_ALLOW_SYNTHETIC=1 (isolated tests).
- Attempts: at most TWO dispatched generation attempts per manual request: the initial one and ONE correction (ATTEMPTS_ENABLED). Each slot is reserved in ONE
  immediate SQLite transaction BEFORE the send; once reserved it is consumed by any outcome: provider refusal, malformed/corrupt/multiple output, unknown outcome
  (connection lost), storage failure. Nothing here ever re-sends. A completed result is retrieved; an attempt without an outcome is reported as uncertain. Validation
  errors and a missing key happen BEFORE a reservation and consume nothing. A correction is only possible against the FIRST candidate when it has a stored VERIFIED review
  that recorded defects, names those defects, and finds the original product facts and merchant photographs unchanged.
- Review: inspect_flyer shows the model a candidate's actual pixels (after its integrity check) together with the merchant's photographs; the delivery status Hermes
  decided is recorded by the backend in image_inspections (kind flyer_candidate, bound to agent, request, run, candidate id and the file's SHA-256). review_flyer is
  accepted only for a candidate of this request that was inspected in this request AND after a model response followed the inspection (never in the same tool-call
  batch); it counts as a completed visual review only when the review material was byte for byte in an actual model request (Hermes pre_api_request hook, then post_api_request
  for that request), otherwise it is stored UNVERIFIED and the result stays UNCHECKED. A capability prediction (image_part_sent) alone never verifies. One review per candidate. Reviews are fallible agent reviews, never human approval.
- Final selection: finalize_flyer selects ONE candidate explicitly; with two valid candidates and no selection the flyer is 'awaiting_selection' (never 'the newest').
- Output: exactly one inline image per attempt, bounded, fully decoded, type/dimensions checked, hash recorded, stored privately and registered.
- Retrieval: a saved output is re-validated EVERY time it is listed, detailed, returned from the cache, inspected or served (_artifact: managed path, existence,
  bounded size, saved size and hash, full decode, type and dimensions). A failure is an explicit storage/integrity failure with no image reference, distinct from a
  content defect; the generation outcome and the consumed attempt are untouched and nothing is ever regenerated.
- Diagnostics: everything derived from the provider or from an exception is passed through _clean (key redacted, bounded) before it is stored or shown.
Contract source: Google's official Interactions API reference and image-generation guide, re-read 2026-10-13 (see research/v2-04-flyer-generation-result-20261013.md and
research/v2-05-review-correction-result-20261013.md). The documented edit path re-sends the image to modify as an inline image input beside the text prompt; the
multi-turn path (previous_interaction_id) needs stored interactions and is not used (store=false).
"""
import base64, hashlib, io, json, os, re, time, urllib.error, urllib.parse, urllib.request, uuid
from app import ads, core, listing, research, turn_state

KEY_NAME = "GEMINI_API_KEY"
MODEL_DEFAULT = "gemini-nano-banana-2.1"
BASE_DEFAULT = "https://generativelanguage.googleapis.com"
ENDPOINT = "/v1beta/interactions"
ASPECT = "4:5"
SIZES = ("1K", "2K")
OUT_MIME = "image/jpeg"                      # the only value the API reference enumerates for response_format.mime_type
IN_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}   # input types shared by our registry and Gemini
OUT_FORMATS = {"JPEG": ("jpg", "image/jpeg"), "PNG": ("png", "image/png"), "WEBP": ("webp", "image/webp")}
MAX_INPUTS, MAX_INPUT_TOTAL = 3, 12_000_000
MAX_REQUEST_IMAGE_BYTES = 20_000_000          # documented inline limit per request: merchant photographs + (for a correction) the previous draft
MAX_OUTPUT_BYTES, MIN_EDGE, MAX_EDGE = 16_000_000, 64, 8192
MAX_RESPONSE_BYTES = 40_000_000
PROMPT_MIN, PROMPT_MAX = 40, 3000
TIMEOUT_S = 180
ATTEMPTS_FINAL_MAX = 2        # initial generation + ONE correction
ATTEMPTS_ENABLED = 2          # ticket 5: both are executed (the correction only through _correct, after a verified review with defects)
SCOPE_DEFAULT, SCOPE_MAX_DEFAULT = "default", 6
CONTENT_STATUS = "unchecked"
UNCHECKED_NOTE = ("UNCHECKED: the file decoded as one valid image and nothing more. No agent has reviewed it against the product, price or requested text, "
                  "and it is not approved. Do not describe it as verified, accurate or final.")
PASSED_NOTE = ("Agent review passed: an automated visual review of this candidate's actual pixels found no defect in the three checks. It is a fallible agent review, not "
               "human approval and not a guarantee that the product is reproduced exactly.")
UNRESOLVED_NOTE = ("UNAPPROVED draft with unresolved issues: the agent's visual review of this candidate found defects (or could not clear every check) and no further "
                   "correction is available or was made. The image file is valid; its content is not cleared.")
ARGS = {"generate_flyer": {"product_id", "selected_product_image_ids", "prompt", "reference_ad_image_ids", "previous_candidate_id", "corrections"},
        "read_flyer": {"flyer_id"}, "inspect_flyer": {"candidate_id"},
        "review_flyer": {"candidate_id", "candidate_sha256", "checks", "defects", "uncertainties", "summary"},
        "finalize_flyer": {"candidate_id", "rationale"}}
CHECKS = ("product_appearance", "required_text_price", "layout_readability")
RESULTS = ("pass", "fail", "uncertain")
RUN_RE, IMG_RE = re.compile(r"fly-[0-9a-f]{10}"), re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
CAND_RE = re.compile(r"cand-[0-9a-f]{10}")
ARTIFACT_RE = re.compile(r"cand-[0-9a-f]{10}\.(?:jpg|png|webp)")
# review/selection text may not claim human approval, certification or a guarantee (the backend never produces such wording either)
_APPROVAL = re.compile(r"\b(?:human|merchant|owner|manager|customer|client|team)[- ]approv|\bapproved by\b|\bguarantee[sd]?\b|\bcertified\b|\b100\s*%\s*(?:accurate|match|correct)", re.I)


# ---------------- configuration (backend only) ----------------
def _get(name):
    return (os.environ.get(name) or "").strip() or core.load_secrets().get(name) or None


def gemini_key():
    return _get(KEY_NAME)


def connected():
    return bool(gemini_key())


def settings():
    """-> (cfg, problem). Nothing about the provider can come from a tool call."""
    base = (os.environ.get("ECOM_GEMINI_URL") or BASE_DEFAULT).rstrip("/")
    u = urllib.parse.urlparse(base)
    if u.scheme != "https" and not (u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost", "::1")):
        return None, "ECOM_GEMINI_URL must be https (plain http is allowed only for a loopback test stand-in)."
    size = _get("GEMINI_IMAGE_SIZE") or "2K"
    if size not in SIZES:
        return None, f"GEMINI_IMAGE_SIZE must be one of {', '.join(SIZES)} (got {size!r})."
    return {"base": base, "model": _get("GEMINI_MODEL") or MODEL_DEFAULT, "size": size}, None


def _clean(v, key=None, n=240):
    """Provider- or exception-derived text made safe to store and show: the API key redacted, whitespace collapsed, bounded. Every such string goes through here."""
    s = " ".join(str(v if v is not None else "").split())
    k = key or gemini_key()
    return (s.replace(k, "***") if k else s)[:n]


def _iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)) if isinstance(ts, (int, float)) else None


def _synthetic_allowed():
    return os.environ.get("ECOM_FLYER_ALLOW_SYNTHETIC") == "1"


def flyer_dir(run_id):
    return core.RUNTIME / "flyers" / run_id


# ---------------- inputs: merchant assets ----------------
def _is_synthetic(cat, img):
    text = f"{img.get('kind') or ''} {cat.get('notice') or ''}".lower()
    return bool(cat.get("demo") or img.get("synthetic") or re.search(r"synthetic|illustration|not a photograph|placeholder|fictional", text))


def _provenance_missing(img):
    pv = img.get("provenance")
    need = ("owner", "date", "usage_statement")
    return [k for k in need if not (isinstance(pv, dict) and str(pv.get(k) or "").strip())]


def _load_merchant_image(iid):
    """-> (info, None) | (None, error). Reads the registered merchant file, bounded and fully decoded. Never takes a path."""
    path = next((p for r in core.merchant_image_roots() for e in core.IMAGE_EXTS for p in [r / f"{iid}{e}"] if p.is_file()), None)
    if path is None:
        return None, research._fail("merchant_image_missing", f"The catalogue registers merchant image {iid!r} but no such file is available to the backend. This is a "
                                    "setup blocker: the real photograph has not been supplied.", "selected_product_image_ids",
                                    hint="Tell the user which merchant photo is missing; do not substitute another image.")
    try:
        size = path.stat().st_size
        if size > core.MAX_IMAGE_BYTES:
            return None, research._fail("merchant_image_too_large", f"Merchant image {iid!r} is {size} bytes; the limit is {core.MAX_IMAGE_BYTES}.", "selected_product_image_ids")
        raw = path.read_bytes()
        from PIL import Image
        im = Image.open(io.BytesIO(raw))
        fmt = im.format
        im.load()
    except Exception as e:
        return None, research._fail("merchant_image_unreadable", f"Merchant image {iid!r} could not be decoded ({type(e).__name__}).", "selected_product_image_ids")
    if fmt not in IN_FORMATS:
        return None, research._fail("merchant_image_unsupported", f"Merchant image {iid!r} is {fmt!r}; flyer generation accepts {', '.join(IN_FORMATS)}.", "selected_product_image_ids")
    return {"image_id": iid, "mime_type": IN_FORMATS[fmt], "format": fmt, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "width": im.width,
            "height": im.height, "_raw": raw}, None


def _facts_text(cat, p, company, ids):
    pr = p.get("price") or {}
    specs = "; ".join(f"{k}: {v}" for k, v in (p.get("specifications") or {}).items())
    brand = str(company.get("brand") or "").strip()
    return ("--- Supplied merchant facts (authoritative: reproduce exactly, add nothing) ---\n"
            f"Merchant: {(cat.get('merchant') or {}).get('name') or company.get('name')}\n"
            f"Product: {p.get('name')}\n"
            f"Declared price: {pr.get('amount')} {pr.get('currency')}\n"
            f"Specifications: {specs}\n"
            + (f"Brand direction (merchant supplied): {brand}\n" if brand else "")
            + f"--- Attached images ---\n{len(ids)} real photograph(s) of this exact product ({', '.join(ids)}). The product in the flyer must be this product; "
              "do not alter its design, colour or proportions.\n")


# ---------------- persistence ----------------
def _allowance_row(c, scope):
    row = c.execute("SELECT * FROM flyer_allowance WHERE scope=?", (scope,)).fetchone()
    if row is None:   # first use: the cap comes from configuration ONCE; an existing row is never re-sized from the environment
        c.execute("INSERT OR IGNORE INTO flyer_allowance(scope, attempts_max, attempts_used, created_at) VALUES(?,?,0,?)",
                  (scope, research._env_int("ECOM_FLYER_MAX_ATTEMPTS", SCOPE_MAX_DEFAULT), time.time()))
        row = c.execute("SELECT * FROM flyer_allowance WHERE scope=?", (scope,)).fetchone()
    return row


_ATT_COLS = ("candidate_id, run_id, attempt_no, status, prompt, context_text, product_json, inputs_json, references_json, provider, model, request_json, inputs_synthetic, "
             "predecessor_id, corrections_json, created_at")


def _insert_attempt(c, cand, rid, no, snap, now, predecessor=None, corrections=None):
    c.execute(f"INSERT INTO flyer_attempts({_ATT_COLS}) VALUES({','.join('?' * 16)})",
              (cand, rid, no, "reserved", snap["prompt"], snap["context_text"], json.dumps(snap["product"]), json.dumps(snap["inputs"]), json.dumps(snap["references"]),
               "gemini-interactions", snap["model"], json.dumps(snap["request"]), 1 if snap["synthetic"] else 0, predecessor,
               json.dumps(corrections) if corrections is not None else None, now))


def _reserve(agent_id, request_id, snap):
    """ONE immediate transaction for the INITIAL attempt: existing run -> report it; else scope check, run + attempt rows. -> (state, run, attempt)."""
    c = core.db()
    try:
        research._begin_immediate(c)
        run = c.execute("SELECT * FROM flyer_runs WHERE agent_id=? AND request_id=?", (agent_id, request_id)).fetchone()
        if run:
            att = c.execute("SELECT * FROM flyer_attempts WHERE run_id=? ORDER BY attempt_no DESC LIMIT 1", (run["run_id"],)).fetchone()
            if att is not None:
                c.commit()
                return "existing", dict(run), dict(att)
        scope = os.environ.get("ECOM_FLYER_SCOPE") or SCOPE_DEFAULT
        a = _allowance_row(c, scope)
        if a["attempts_used"] >= a["attempts_max"]:
            c.commit()
            return "exhausted", None, {"scope": scope, "max": a["attempts_max"]}
        c.execute("UPDATE flyer_allowance SET attempts_used=attempts_used+1 WHERE scope=?", (scope,))
        now = time.time()
        if run is None:
            rid = "fly-" + uuid.uuid4().hex[:10]
            ag = c.execute("SELECT conversation_id FROM agents WHERE agent_id=?", (agent_id,)).fetchone()
            msg = c.execute("SELECT id FROM messages WHERE agent_id=? AND who='user' ORDER BY id DESC LIMIT 1", (agent_id,)).fetchone()
            c.execute("INSERT INTO flyer_runs(run_id, agent_id, company_id, company_name, conversation_id, request_id, message_id, product_id, scope, attempts_final_max, "
                      "created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (rid, agent_id, core.COMPANY_ID, snap["company_name"], ag["conversation_id"] if ag else None, request_id, msg["id"] if msg else None,
                       snap["product_id"], scope, ATTEMPTS_FINAL_MAX, now))
        else:
            rid = run["run_id"]
        cand = "cand-" + uuid.uuid4().hex[:10]
        _insert_attempt(c, cand, rid, 1, snap, now)
        c.commit()
        return "go", dict(c.execute("SELECT * FROM flyer_runs WHERE run_id=?", (rid,)).fetchone()), {"candidate_id": cand, "run_id": rid}
    except BaseException:
        c.rollback()
        raise
    finally:
        c.close()


def _reserve_correction(agent_id, request_id, prev_id, snap):
    """ONE immediate transaction for the CORRECTION: the run must exist and hold exactly the first attempt, a done 'ok' candidate with a VERIFIED review that recorded
    defects; a second attempt that already exists is reported, never duplicated (UNIQUE(run_id, attempt_no) is the last guard). The slot is charged to the run's own
    scope (fixed at its first use). -> (state, run, attempt) with state go | existing | exhausted | no_run | bad_candidate | not_eligible."""
    c = core.db()
    try:
        research._begin_immediate(c)
        run = c.execute("SELECT * FROM flyer_runs WHERE agent_id=? AND request_id=?", (agent_id, request_id)).fetchone()
        if not run:
            c.commit()
            return "no_run", None, None
        prev = c.execute("SELECT * FROM flyer_attempts WHERE candidate_id=? AND run_id=?", (prev_id, run["run_id"])).fetchone()
        if prev is None or prev["attempt_no"] != 1:
            c.commit()
            return "bad_candidate", dict(run), None
        n = c.execute("SELECT COUNT(*) FROM flyer_attempts WHERE run_id=?", (run["run_id"],)).fetchone()[0]
        if n >= 2:
            att = c.execute("SELECT * FROM flyer_attempts WHERE run_id=? ORDER BY attempt_no DESC LIMIT 1", (run["run_id"],)).fetchone()
            c.commit()
            return "existing", dict(run), dict(att)
        rv = c.execute("SELECT verified, verdict FROM flyer_reviews WHERE candidate_id=?", (prev_id,)).fetchone()
        if prev["status"] != "done" or prev["outcome"] != "ok" or not rv or not rv["verified"] or rv["verdict"] != "defects_found":
            c.commit()
            return "not_eligible", dict(run), None
        a = _allowance_row(c, run["scope"])
        if a["attempts_used"] >= a["attempts_max"]:
            c.commit()
            return "exhausted", dict(run), {"scope": run["scope"], "max": a["attempts_max"]}
        c.execute("UPDATE flyer_allowance SET attempts_used=attempts_used+1 WHERE scope=?", (run["scope"],))
        cand = "cand-" + uuid.uuid4().hex[:10]
        _insert_attempt(c, cand, run["run_id"], 2, snap, time.time(), predecessor=prev_id, corrections=snap["corrections"])
        c.commit()
        return "go", dict(run), {"candidate_id": cand, "run_id": run["run_id"]}
    except BaseException:
        c.rollback()
        raise
    finally:
        c.close()


def _update(candidate_id, **cols):
    sets = ", ".join(f"{k}=?" for k in cols)
    with core.db() as d:
        d.execute(f"UPDATE flyer_attempts SET {sets} WHERE candidate_id=?", (*cols.values(), candidate_id))


def _finish(candidate_id, outcome, **kw):
    _update(candidate_id, status="done", outcome=outcome, finished_at=time.time(), **kw)


# ---------------- provider transport and response ----------------
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _post(url, key, payload, ctx):
    """One send. -> (status, body bytes). HTTP error statuses are returned; network faults raise. Redirects are never followed (the key stays put)."""
    import ssl
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST",
                                 headers={"x-goog-api-key": key, "Content-Type": "application/json", "Accept": "application/json", "User-Agent": "ecom-agents-flyer/1"})
    opener = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=ctx if isinstance(ctx, ssl.SSLContext) else None))
    try:
        with opener.open(req, timeout=TIMEOUT_S) as r:
            return r.status, r.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as e:
        return e.code, e.read(65536)


def _msg(data, key):
    m = ""
    if isinstance(data, dict):
        e = data.get("error")
        m = str((e.get("message") if isinstance(e, dict) else e) or data.get("message") or "")
        errs = data.get("errors")
        if not m and isinstance(errs, list) and errs and isinstance(errs[0], dict):
            m = str(errs[0].get("message") or errs[0].get("code") or "")
    return _clean(m, key)


def _interpret(status, body, key):
    """-> (outcome, message, raw_image_bytes | None, meta). Everything after a send is classified here (malformed shapes included: they are a terminal
    'bad_response', never an exception); only 'ok' carries bytes. Every message is already sanitised (_clean)."""
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except (ValueError, RecursionError):
        data = None
    meta = {}

    def out(outcome, msg, raw=None):
        return outcome, (_clean(msg, key) if msg else None), raw, meta
    if 300 <= status < 400:
        return out("redirect_refused", f"the provider answered with a redirect (HTTP {status}); redirects are never followed")
    if status != 200:
        k = {400: "bad_request", 401: "auth_failed", 403: "auth_failed", 404: "model_not_found", 429: "rate_limited"}.get(status) or ("provider_error" if status >= 500 else "http_error")
        return out(k, _msg(data, key) or f"HTTP {status}")
    if not isinstance(data, dict):
        return out("bad_response", f"the response body was not a JSON object (it was {type(data).__name__})")
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    meta.update(interaction_id=_clean(data.get("id"), key, 120) or None if isinstance(data.get("id"), str) else None,
                usage={k: usage.get(k) for k in ("total_input_tokens", "total_output_tokens", "total_thought_tokens", "total_tokens") if isinstance(usage.get(k), int)})
    if data.get("status") != "completed":
        m = _msg(data, key)
        return out("provider_failed", f"the interaction ended with status {_clean(data.get('status'), key, 80)!r}" + (f": {m}" if m else ""))
    steps = data.get("steps")
    if steps is not None and not isinstance(steps, list):
        return out("bad_response", f"malformed response: steps is {type(steps).__name__}, not an array")
    blocks, text = [], []
    for i, step in enumerate(steps or []):
        if not isinstance(step, dict):
            return out("bad_response", f"malformed response: steps[{i}] is {type(step).__name__}, not an object")
        if step.get("type") != "model_output":
            continue
        content = step.get("content")
        if content is not None and not isinstance(content, list):
            return out("bad_response", f"malformed response: steps[{i}].content is {type(content).__name__}, not an array")
        for j, b in enumerate(content or []):
            if not isinstance(b, dict):
                return out("bad_response", f"malformed response: steps[{i}].content[{j}] is {type(b).__name__}, not an object")
            if b.get("type") == "image":
                blocks.append(b)
            elif b.get("type") == "text" and isinstance(b.get("text"), str):
                text.append(b["text"])
    if not blocks:
        return out("no_image", "the provider completed without an image" + (f" (its text: {_clean(' '.join(text), key, 200)!r})" if text else ""))
    if len(blocks) > 1:
        return out("multiple_images", f"the provider returned {len(blocks)} images; exactly one is required and none is kept")
    b = blocks[0]
    if not isinstance(b.get("data"), str) or not b["data"]:
        return out("invalid_output", "the image block carried no inline data (only inline delivery is accepted; no provider URL is fetched)")
    try:
        raw = base64.b64decode(b["data"], validate=True)
    except ValueError:
        return out("invalid_output", "the image data is not valid base64")
    meta["declared_mime"] = b.get("mime_type") if isinstance(b.get("mime_type"), str) else None
    return out("ok", None, raw)


def _check_image(raw, declared):
    """Integrity gate -> (info, None) | (None, reason). Bounded, fully decoded, permitted type, sensible dimensions."""
    if not raw:
        return None, "the image is empty"
    if len(raw) > MAX_OUTPUT_BYTES:
        return None, f"the image is {len(raw)} bytes; the limit is {MAX_OUTPUT_BYTES}"
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(raw))
        fmt = im.format
        im.load()                           # a truncated or corrupt file fails here
    except Exception as e:
        return None, f"the image could not be decoded ({type(e).__name__}): corrupt, truncated or not an image"
    if fmt not in OUT_FORMATS:
        return None, f"the image format {fmt!r} is not permitted ({', '.join(OUT_FORMATS)})"
    w, h = im.size
    if not (MIN_EDGE <= w <= MAX_EDGE and MIN_EDGE <= h <= MAX_EDGE):
        return None, f"the image is {w}x{h}; each side must be {MIN_EDGE}-{MAX_EDGE}"
    ext, mime = OUT_FORMATS[fmt]
    if declared and declared != mime:
        return None, f"the provider labelled the image {declared!r} but its bytes decode as {mime!r}"
    return {"ext": ext, "mime_type": mime, "format": fmt, "width": w, "height": h, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}, None


def _artifact(run_id, a):
    """THE validation of a persisted output -> (bytes, None) | (None, problem). Managed-path resolution, existence/readability, bounded size, the saved size and
    hash, full decode, permitted type and the saved dimensions. Computed on every read; nothing about it is stored, so a repaired file is valid again."""
    name = a["out_path"] or ""
    if not ARTIFACT_RE.fullmatch(name) or not name.startswith(a["candidate_id"] + "."):
        return None, "the stored file reference is not a managed flyer file"
    folder = flyer_dir(run_id)
    p = folder / name
    try:
        if p.is_symlink() or p.resolve().parent != folder.resolve():
            return None, "the stored file reference resolves outside the managed flyer folder"
        if not p.is_file():
            return None, "the saved image file is missing"
        size = p.stat().st_size
        if size > MAX_OUTPUT_BYTES:
            return None, f"the saved image is {size} bytes, over the {MAX_OUTPUT_BYTES} limit"
        if a["out_bytes"] is not None and size != a["out_bytes"]:
            return None, f"the saved image is {size} bytes; {a['out_bytes']} were saved (truncated or replaced)"
        raw = p.read_bytes()
    except OSError as e:
        return None, f"the saved image could not be read ({type(e).__name__})"
    if hashlib.sha256(raw).hexdigest() != a["out_sha256"]:
        return None, "the saved image no longer matches its saved hash (replaced or damaged)"
    info, bad = _check_image(raw, a["out_mime"])
    if bad:
        return None, f"the saved image failed validation: {bad}"
    if (info["width"], info["height"]) != (a["out_width"], a["out_height"]):
        return None, "the saved image's dimensions differ from the saved record"
    return raw, None


# ---------------- state, views and reads (stored data only: no provider, no credentials) ----------------
def _prepare(agent_id, tool, args):
    if not isinstance(args, dict):
        return None, research._fail("bad_request", "Arguments must be an object.")
    extra = sorted(set(args) - ARGS[tool])
    if extra:
        return None, research._fail("invalid_argument", f"Unsupported argument(s) {extra}. The provider, model, credentials, paths, URLs, run, attempt number and "
                                    "allowance are controlled by the backend and cannot be set from a tool call.", "arguments", hint=f"Allowed arguments: {sorted(ARGS[tool])}.")
    with core.db() as d:
        ag = d.execute("SELECT role, granted_tools FROM agents WHERE agent_id=?", (agent_id,)).fetchone()
    if not ag:
        return None, research._fail("unknown_agent", f"Flyer generation needs a registered specialist; {agent_id!r} is not one.")
    if ag["role"] != "social_media":
        return None, research._fail("not_permitted_for_role", f"Flyer generation is only available to a social_media specialist, not role {ag['role']!r}.")
    if tool not in json.loads(ag["granted_tools"] or "[]"):
        return None, research._fail("not_granted", f"This specialist was not granted {tool}.")
    return ag, None


def _ok(a):
    return a["status"] == "done" and a["outcome"] == "ok"


def _load(d, run_id):
    atts = [dict(r) for r in d.execute("SELECT * FROM flyer_attempts WHERE run_id=? ORDER BY attempt_no", (run_id,))]
    revs = {r["candidate_id"]: dict(r) for r in d.execute("SELECT * FROM flyer_reviews WHERE run_id=?", (run_id,))}
    return atts, revs


def _latest(d, run_id):
    return d.execute("SELECT * FROM flyer_attempts WHERE run_id=? ORDER BY attempt_no DESC LIMIT 1", (run_id,)).fetchone()


def _effective(run_id, atts, final_id):
    """-> (attempt | None, explicitly_selected, {candidate_id: integrity problem}). The candidate the flyer stands for: the SELECTED one (whatever its file state: a damaged
    selection stays an explicit failure and never falls back to the other candidate), or - with no selection - the only candidate whose file passes the shared artifact
    check. Two valid candidates and no selection have none: the newest is never assumed. When no file is valid the newest damaged one stands in, so the flyer reports a
    storage failure instead of an 'awaiting selection' that nothing could serve. The problem map lists the damaged candidates found while deciding (empty after a selection)."""
    oks = [a for a in atts if _ok(a)]
    if final_id:
        return next((a for a in oks if a["candidate_id"] == final_id), None), True, {}
    valid, damaged = [], {}
    for a in oks:
        problem = _artifact(run_id, a)[1]
        if problem:
            damaged[a["candidate_id"]] = problem
        else:
            valid.append(a)
    if len(valid) == 1:
        return valid[0], False, damaged
    if valid:
        return None, False, damaged
    return (next((a for a in reversed(oks) if a["candidate_id"] in damaged), None)), False, damaged


def _cand_status(run_id, a, rev):
    """-> (status, integrity problem | None) of ONE candidate from its own stored file and its own review (never from another candidate or the flyer's selection)."""
    problem = _artifact(run_id, a)[1]
    if problem:   # the generation SUCCEEDED and its attempt is consumed; only the stored artifact is bad (distinct from a content defect)
        return "storage_failure", problem
    if rev and rev["verified"]:
        return ("agent_review_passed" if rev["verdict"] == "passed" else "unresolved_issues"), None
    return CONTENT_STATUS, None


def _status_note(st, rev):
    if st == "agent_review_passed":
        return PASSED_NOTE
    if st == "unresolved_issues":
        return UNRESOLVED_NOTE
    if st == CONTENT_STATUS:
        return (UNCHECKED_NOTE if not rev else
                f"UNCHECKED: a review was recorded but this candidate's pixels were not confirmed delivered to the reviewing model (delivery: {rev['delivery']}), so it is not a "
                "completed visual review and the candidate is not cleared. It is not approved.")
    return None


def _review_view(r):
    if not r:
        return None
    return {"review_id": r["review_id"], "candidate_id": r["candidate_id"], "sha256": r["sha256"], "verdict": r["verdict"], "verified": bool(r["verified"]),
            "delivery": r["delivery"], "checks": json.loads(r["checks_json"]), "defects": json.loads(r["defects_json"]), "uncertainties": r["uncertainties"] or None,
            "summary": r["summary"], "references": json.loads(r["refs_json"] or "[]"), "request_id": r["request_id"], "created_at": _iso(r["created_at"]),
            "note": ("Agent review of the candidate's delivered pixels: fallible, not human approval." if r["verified"] else
                     f"UNVERIFIED: the candidate's pixels were not confirmed delivered to the reviewing model (delivery: {r['delivery']}); this is not a completed visual review.")}


def _issues(r):
    """Unresolved issues a verified review left: its defects, then checks it could not clear. An unverified review contributes none (nothing was verified)."""
    if not r or not r["verified"] or r["verdict"] not in ("defects_found", "inconclusive"):
        return []
    out = [{**d, "kind": "defect"} for d in json.loads(r["defects_json"])]
    out += [{"check": n, "description": c["observation"], "kind": "uncertain"} for n, c in json.loads(r["checks_json"]).items() if c["result"] == "uncertain"]
    return out


def _correction_state(atts, revs):
    if not atts:
        return {"available": False, "reason": "no candidate has been generated in this request"}
    first = atts[0]
    if len(atts) >= 2:
        return {"available": False, "reason": "the one correction of this request was already used"}
    if first["status"] != "done":
        return {"available": False, "reason": "the first attempt has no recorded outcome"}
    if first["outcome"] != "ok":
        return {"available": False, "reason": f"the first attempt produced no candidate ({first['outcome']}); there is nothing to correct and no review may be invented"}
    rv = revs.get(first["candidate_id"])
    if not rv:
        return {"available": False, "reason": "the candidate has no saved review: inspect_flyer, then review_flyer"}
    if not rv["verified"]:
        return {"available": False, "reason": "its review is unverified (the pixels were not confirmed delivered)"}
    if rv["verdict"] != "defects_found":
        return {"available": False, "reason": f"its verified review recorded no defect to correct (verdict {rv['verdict']})"}
    return {"available": True, "reason": "a verified review recorded defects: generate_flyer with previous_candidate_id and corrections naming the defect numbers"}


def _research_live(d, agent_id, request_id):
    p = d.execute("SELECT * FROM ad_packages WHERE agent_id=? AND request_id=?", (agent_id, request_id)).fetchone()
    if not p:
        return {"ad_package_id": None, "ad_run_id": None, "status": None, "selection_basis": None, "blocker": None, "reference_image_ids": [],
                "reach_gate": {"state": "no_ad_research_saved", "ranking_enabled": False,
                               "note": "No ad-research package was saved in this request; generation does not depend on one."}}
    try:
        body = json.loads(p["references_json"] or "{}")
        refs = body.get("references") if isinstance(body, dict) else body
        gate = json.loads(p["reach_gate"] or "null")
    except ValueError:
        refs, gate = [], None
    return {"ad_package_id": p["package_id"], "ad_run_id": p["run_id"], "status": p["status"], "selection_basis": p["selection_basis"], "blocker": p["blocker"],
            "reach_gate": gate if isinstance(gate, dict) else {"state": "unknown"},
            "reference_image_ids": [r.get("image_id") for r in (refs or []) if isinstance(r, dict) and r.get("image_id")]}


def _research(d, run):
    if run["research_json"]:
        try:
            return json.loads(run["research_json"])
        except ValueError:
            pass
    return _research_live(d, run["agent_id"], run["request_id"])


def _image_block(url, a):
    return {"url": url, "width": a["out_width"], "height": a["out_height"], "mime_type": a["out_mime"], "sha256": a["out_sha256"], "bytes": a["out_bytes"]}


def _flyer_summary(run, atts, revs):
    run_id = run["run_id"]
    latest = atts[-1] if atts else None
    oks = [a for a in atts if _ok(a)]
    eff, selected, damaged = _effective(run_id, atts, run["final_candidate_id"])
    problem, rev = None, None
    if latest is None:
        st = "no_attempt"
    elif latest["status"] != "done":
        st = "in_progress_or_unknown"
    elif eff is None:
        st = "awaiting_selection" if len(oks) >= 2 else "failed"
    else:
        rev = revs.get(eff["candidate_id"])
        st, problem = _cand_status(run_id, eff, rev)
    shown = eff or (latest if st in ("failed", "no_attempt", "in_progress_or_unknown") else None)
    failed_a = next((a for a in reversed(atts) if a["status"] == "done" and a["outcome"] != "ok"), None)
    usable = st in (CONTENT_STATUS, "agent_review_passed", "unresolved_issues")
    note = _status_note(st, rev) or ("Two valid candidates exist and none was explicitly selected as the final flyer; no default is served. Each candidate has its own image."
                                     if st == "awaiting_selection" else None)
    others = {c: p for c, p in damaged.items() if not eff or c != eff["candidate_id"]}   # damaged candidates the flyer does not stand for
    if others and st != "storage_failure":   # a surviving candidate is shown; say what happened to the other one (nothing was selected or regenerated)
        note = (note or "") + " " + "; ".join(f"Candidate {c} cannot be used: its saved file failed the integrity check ({p})" for c, p in others.items()) + (
            ". It was not generated again and no final selection was recorded.")
    err = (f"The generated image was saved but its stored file failed the integrity check: {problem}. It was not generated again; an integrity failure is not a content "
           "defect and generating again does not repair it." + "".join(f" Candidate {c}: {p}." for c, p in others.items())
           if problem else (failed_a["error"] if st == "failed" and failed_a else None))
    return {"flyer_id": run_id, "status": st, "status_text": {"agent_review_passed": "Agent review passed (fallible; not human approval)",
                                                             "unresolved_issues": "UNAPPROVED draft with unresolved issues", "unchecked": "UNCHECKED",
                                                             "awaiting_selection": "Awaiting final selection", "storage_failure": "Storage / integrity failure",
                                                             "failed": "Generation failed", "in_progress_or_unknown": "Outcome unknown or still running",
                                                             "no_attempt": "No attempt"}[st],
            "agent_id": run["agent_id"], "request_id": run["request_id"], "product_id": run["product_id"], "created_at": _iso(run["created_at"]),
            "candidate_id": shown["candidate_id"] if shown else None, "outcome": shown["outcome"] if shown else (failed_a["outcome"] if failed_a else None),
            "error": err, "error_kind": "storage_integrity" if problem else (failed_a["outcome"] if st == "failed" and failed_a else None),
            "integrity": ({"state": "failed", "problem": problem} if problem else {"state": "valid"} if usable else None),
            "image": _image_block(f"/api/flyers/images/{run_id}", eff) if usable else None,
            "content_status": (CONTENT_STATUS if st == CONTENT_STATUS else st if usable else None), "inputs_synthetic": bool(shown["inputs_synthetic"]) if shown else None,
            "note": note,
            "final": {"selected": selected and eff is not None, "candidate_id": eff["candidate_id"] if (selected and eff) else None,
                      "effective_candidate_id": eff["candidate_id"] if eff else None, "selected_at": run["selected_at"], "rationale": run["selection_rationale"]},
            "review": _review_view(rev), "unresolved_issues": _issues(rev), "candidates_total": len(atts), "attempts_used": len(atts), "correction_used": len(atts) >= 2,
            **({"damaged_candidates": [{"candidate_id": c, "problem": p} for c, p in others.items()]} if others else {})}   # only when present (Activity output is cut at 3000 chars)


def _candidate_view(run, a, rev, final_id):
    run_id, ok = run["run_id"], _ok(a)
    problem = _artifact(run_id, a)[1] if ok else None
    valid = ok and not problem
    return {"candidate_id": a["candidate_id"], "attempt_no": a["attempt_no"], "kind": "correction" if a["attempt_no"] > 1 else "initial",
            "predecessor_id": a["predecessor_id"], "status": a["status"], "outcome": a["outcome"], "error": a["error"], "provider": a["provider"], "model": a["model"],
            "http_status": a["http_status"], "usage": json.loads(a["usage"]) if a["usage"] else None, "interaction_id": a["interaction_id"], "ms": a["ms"],
            "created_at": _iso(a["created_at"]), "dispatched_at": _iso(a["dispatched_at"]), "finished_at": _iso(a["finished_at"]),
            "prompt": a["prompt"], "context_text": a["context_text"], "product": json.loads(a["product_json"]), "inputs": json.loads(a["inputs_json"]),
            "references": json.loads(a["references_json"]), "request": json.loads(a["request_json"]), "corrections": json.loads(a["corrections_json"] or "[]"),
            "integrity": ({"state": "failed", "problem": problem} if problem else {"state": "valid"} if valid else None),
            "image": _image_block(f"/api/flyers/images/{a['candidate_id']}", a) if valid else None,
            "output": ({"image_id": run_id, "sha256": a["out_sha256"], "bytes": a["out_bytes"], "width": a["out_width"], "height": a["out_height"], "mime_type": a["out_mime"]}
                       if valid else None),
            "review": _review_view(rev), "selected": bool(final_id and a["candidate_id"] == final_id)}


def _history(run, atts, revs):
    ev = []
    for a in atts:
        ev.append((a["created_at"] or 0, {"event": "correction_reserved" if a["attempt_no"] > 1 else "generation_reserved", "candidate_id": a["candidate_id"],
                                           "predecessor_id": a["predecessor_id"]}))
        if a["finished_at"]:
            ev.append((a["finished_at"], {"event": "generation_finished", "candidate_id": a["candidate_id"], "outcome": a["outcome"], "error": a["error"]}))
    for r in revs.values():
        ev.append((r["created_at"] or 0, {"event": "review_saved", "candidate_id": r["candidate_id"], "verdict": r["verdict"], "verified": bool(r["verified"]),
                                           "delivery": r["delivery"], "defects": len(json.loads(r["defects_json"]))}))
    out = [dict(e, at=_iso(ts)) for ts, e in sorted(ev, key=lambda x: x[0])]
    if run["final_candidate_id"]:
        out.append({"event": "final_selected", "candidate_id": run["final_candidate_id"], "at": run["selected_at"], "rationale": run["selection_rationale"]})
    return out


def get_flyer(flyer_id):
    if not isinstance(flyer_id, str) or not RUN_RE.fullmatch(flyer_id):
        return None
    with core.db() as d:
        run = d.execute("SELECT * FROM flyer_runs WHERE run_id=?", (flyer_id,)).fetchone()
        if not run:
            return None
        atts, revs = _load(d, flyer_id)
        al = d.execute("SELECT * FROM flyer_allowance WHERE scope=?", (run["scope"],)).fetchone()
        res = _research(d, run)
    out = _flyer_summary(run, atts, revs)
    cands = [_candidate_view(run, a, revs.get(a["candidate_id"]), run["final_candidate_id"]) for a in atts]
    out["identity"] = {"agent_id": run["agent_id"], "company_id": run["company_id"], "company_name": run["company_name"], "conversation_id": run["conversation_id"],
                       "request_id": run["request_id"], "message_id": run["message_id"], "product_id": run["product_id"], "run_id": run["run_id"], "scope": run["scope"]}
    out["attempts"] = {"used": len(atts), "enabled": ATTEMPTS_ENABLED, "final_max": run["attempts_final_max"], "corrections_used": max(0, len(atts) - 1),
                       "correction": _correction_state(atts, revs),
                       "note": "At most two generation attempts per request: the initial one and ONE correction after a verified review that recorded defects."}
    out["candidates"] = cands
    pick = out["candidate_id"]
    out["attempt"] = next((c for c in cands if c["candidate_id"] == pick), None)
    out["research"] = res
    out["history"] = _history(run, atts, revs)
    out["allowance"] = {"scope": run["scope"], "attempts_used": al["attempts_used"] if al else None, "attempts_max": al["attempts_max"] if al else None}
    return out


def list_flyers(agent_id=None):
    with core.db() as d:
        runs = d.execute("SELECT * FROM flyer_runs" + (" WHERE agent_id=?" if agent_id else "") + " ORDER BY created_at DESC", (agent_id,) if agent_id else ()).fetchall()
        return [_flyer_summary(r, *_load(d, r["run_id"])) for r in runs]


def allowances():
    with core.db() as d:
        return [dict(r) for r in d.execute("SELECT * FROM flyer_allowance ORDER BY scope")]


def image_state(ident):
    """-> ("ok", bytes, mime) | ("integrity", problem, None) | ("unselected", None, None) | ("none", None, None). `ident` is a flyer id (the flyer's EFFECTIVE candidate: the
    explicitly selected one, or the only valid one) or a candidate id (that candidate's own file). Resolved through the database; no path comes from the caller, and
    bytes are served only if the saved artifact passes _artifact."""
    if not isinstance(ident, str):
        return "none", None, None
    with core.db() as d:
        if RUN_RE.fullmatch(ident):
            run = d.execute("SELECT * FROM flyer_runs WHERE run_id=?", (ident,)).fetchone()
            if not run:
                return "none", None, None
            atts, _ = _load(d, ident)
            a, _, _ = _effective(ident, atts, run["final_candidate_id"])
            if a is None:
                return ("unselected" if len([x for x in atts if _ok(x)]) >= 2 else "none"), None, None
            run_id = ident
        elif CAND_RE.fullmatch(ident):
            a = d.execute("SELECT * FROM flyer_attempts WHERE candidate_id=?", (ident,)).fetchone()
            if not a or not _ok(a):
                return "none", None, None
            a, run_id = dict(a), a["run_id"]
        else:
            return "none", None, None
    if not a["out_path"]:
        return "none", None, None
    raw, problem = _artifact(run_id, a)
    return ("ok", raw, a["out_mime"]) if raw is not None else ("integrity", problem, None)


def image_file(flyer_id):
    """(bytes, content_type) of the managed output image, or None (unknown id OR failed integrity check; image_state tells them apart)."""
    s, a, b = image_state(flyer_id)
    return (a, b) if s == "ok" else None


# ---------------- replies for a repeated call ----------------
def _existing(agent_id, request_id):
    """(run, latest attempt) when this request already holds an attempt, else None. A pure read: it is what makes a repeated call (and a call after the key was
    removed or the app restarted) return the stored result instead of anything new."""
    with core.db() as d:
        run = d.execute("SELECT * FROM flyer_runs WHERE agent_id=? AND request_id=?", (agent_id, request_id)).fetchone()
        if not run:
            return None
        att = _latest(d, run["run_id"])
    return (dict(run), dict(att)) if att is not None else None


def _existing_reply(run, a):
    """What a repeated call in the same request gets: the stored result or an explicit statement. Never a new generation."""
    with core.db() as d:
        atts, revs = _load(d, run["run_id"])
    view = {"flyer_id": run["run_id"], "candidate_id": a["candidate_id"]}
    corr = a["attempt_no"] > 1
    label = "correction" if corr else "generation"
    state = _correction_state(atts, revs)
    if _ok(a):
        # One coherent ATTEMPT result: candidate, image, review, status, issues and note are all this attempt's own. The flyer's selection and status are separate fields
        # (flyer_status, final), so a selected older candidate is never labelled onto the newest attempt's image.
        s = _flyer_summary(run, atts, revs)
        rev = revs.get(a["candidate_id"])
        st, problem = _cand_status(run["run_id"], a, rev)
        flyer_level = {"flyer_status": s["status"], "final": s["final"], "review": _review_view(rev), "unresolved_issues": _issues(rev)}
        if problem:   # generated and counted earlier; the stored file is bad: say so, never regenerate
            return research._fail("artifact_integrity_failed", f"The generated image was saved but its stored file failed the integrity check: {problem}. It was not generated "
                                  "again; an integrity failure is not a content defect.", hint="Report that the saved flyer image is damaged or missing; do not try to generate again.",
                                  **view, status="storage_failure", outcome="ok", integrity={"state": "failed", "problem": problem}, **flyer_level)
        return {"ok": True, "cached": True, **view, "scope": "attempt", "status": st, "image": _image_block(f"/api/flyers/images/{a['candidate_id']}", a),
                "retrieve": f"/api/flyers/{run['run_id']}", "note": _status_note(st, rev), **flyer_level,
                "attempts": {"used": len(atts), "enabled": ATTEMPTS_ENABLED, "final_max": ATTEMPTS_FINAL_MAX}, "correction": corr, "correction_state": state,
                "why": f"This request already produced this {label}; the stored result is returned and nothing was generated or spent again."}
    if a["status"] == "done":
        return research._fail("attempt_already_consumed", f"This request's {label} attempt already ended with {a['outcome']!r}" + (f" ({a['error']})" if a["error"] else "") +
                              ". It consumed its slot and was NOT repeated.", hint="Report this outcome to the user; do not try to generate again.", **view, status="failed",
                              outcome=a["outcome"], correction_state=state)
    return research._fail("generation_outcome_unknown", f"A {label} attempt for this request was reserved" + (" and sent" if a["status"] == "dispatched" else "") +
                          " but no outcome is recorded: it is still running in this request or was interrupted. It was NOT repeated and may or may not have been charged.",
                          hint="Report that the outcome is uncertain; do not try to generate again in this request.", **view, status="in_progress_or_unknown")


# ---------------- generation (initial attempt and the one correction) ----------------
def _dispatch(run_id, cand, cfg, key, payload, inputs, attempt_no, predecessor=None):
    """The ONE send for an already reserved slot, its classification and its private storage. Both attempts use exactly this path."""
    _update(cand, status="dispatched", dispatched_at=time.time())
    t0 = time.perf_counter()
    base = {"flyer_id": run_id, "candidate_id": cand, "correction": predecessor is not None}
    try:
        status, body = _post(cfg["base"] + ENDPOINT, key, payload, research.diag().tls_context())
    except Exception as ex:   # timeout, DNS, TLS, connection lost: the provider may have processed it -> outcome unknown, slot consumed, never replayed
        why = _clean(f"{type(ex).__name__}: {ex}", key, 200)
        _finish(cand, "network_error", error=why, ms=round((time.perf_counter() - t0) * 1000))
        return research._fail("generation_outcome_unknown", f"The request was sent but no usable answer came back ({why}). It may or may not have been processed and charged; "
                              "the attempt is consumed and was NOT repeated.", hint="Report that the outcome is unknown; do not try again.", **base, status="failed")
    ms = round((time.perf_counter() - t0) * 1000)
    try:
        outcome, why, raw, meta = _interpret(status, body, key)
    except Exception as ex:   # belt and braces: an OBSERVED response that cannot be interpreted is a terminal failure with its status and timing, not an unknown transport outcome
        outcome, why, raw, meta = "bad_response", f"the response could not be interpreted ({type(ex).__name__})", None, {}
    common = {"http_status": status, "ms": ms, "usage": json.dumps(meta.get("usage")) if meta.get("usage") else None, "interaction_id": meta.get("interaction_id")}
    info = None
    if outcome == "ok":
        info, bad = _check_image(raw, meta.get("declared_mime"))
        if bad:
            outcome, why = "invalid_output", _clean(bad, key)
    if outcome != "ok":
        _finish(cand, outcome, error=why, **common)
        return research._fail("generation_failed", f"Gemini generation did not produce a usable image: {outcome}: {why}. The attempt was consumed and not repeated.",
                              hint="Report this failure honestly; no flyer exists from this attempt.", **base, status="failed", outcome=outcome)
    try:   # store privately, then record (a file or database fault after a paid success is reported as exactly that)
        folder = flyer_dir(run_id)
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{cand}.{info['ext']}"
        tmp = folder / f"{name}.{os.getpid()}.tmp"
        tmp.write_bytes(raw)
        os.replace(tmp, folder / name)
        _finish(cand, "ok", out_path=name, out_sha256=info["sha256"], out_bytes=info["bytes"], out_width=info["width"], out_height=info["height"], out_mime=info["mime_type"],
                **common)
    except Exception as ex:
        try:
            _finish(cand, "ok_unsaved", error=_clean(f"{type(ex).__name__}: {ex}", key, 200), **common)
        except Exception:
            pass
        return research._fail("storage_error", "The flyer was generated (and counted) but could not be saved locally, so it cannot be used. It was NOT generated again.",
                              hint="Report this local storage fault as a blocker.", **base, status="failed")
    nxt = ("Look at its actual pixels with inspect_flyer, record your review with review_flyer, then finalize_flyer. Until a verified review exists it is UNCHECKED."
           if predecessor else "Look at its actual pixels with inspect_flyer, record your review with review_flyer (one correction is possible only if a verified review "
                               "records defects), then finalize_flyer. Until a verified review exists it is UNCHECKED.")
    return {"ok": True, **base, "predecessor_id": predecessor, "status": CONTENT_STATUS, "note": UNCHECKED_NOTE, "next": nxt, "retrieve": f"/api/flyers/{run_id}",
            "image": {"url": f"/api/flyers/images/{cand}", "width": info["width"], "height": info["height"], "mime_type": info["mime_type"], "sha256": info["sha256"],
                      "bytes": info["bytes"]},
            "inputs": [{"image_id": i["image_id"], "sha256": i["sha256"]} for i in inputs], "model": cfg["model"], "usage": meta.get("usage"), "ms": ms,
            "attempts": {"used": attempt_no, "enabled": ATTEMPTS_ENABLED, "final_max": ATTEMPTS_FINAL_MAX}}


STORE = False


def _response_format(cfg):
    """The image response_format that is actually sent. `delivery` is deliberately absent: the live service answered HTTP 400 'Image delivery mode is not supported.'
    when it was set (V2-06 probe, 2026-10-25) although the API reference lists it; the documented image-generation examples omit it and the default is inline data."""
    return {"type": "image", "aspect_ratio": ASPECT, "image_size": cfg["size"], "mime_type": OUT_MIME}


def _request_record(cfg, n_images):
    """The sanitized request metadata stored with an attempt, derived from the SAME values _payload sends (never a separate copy)."""
    rf = _response_format(cfg)
    return {"endpoint": ENDPOINT, "model": cfg["model"], "aspect_ratio": rf["aspect_ratio"], "image_size": rf["image_size"], "mime_type": rf["mime_type"], "store": STORE,
            "input_images": n_images, "timeout_s": TIMEOUT_S, "retries": 0}


def _payload(cfg, context_text, images):
    return {"model": cfg["model"],
            "input": [{"type": "text", "text": context_text}] + [{"type": "image", "mime_type": m, "data": base64.b64encode(raw).decode("ascii")} for m, raw in images],
            "response_format": _response_format(cfg), "store": STORE}


def generate(agent_id, args):
    ag, e = _prepare(agent_id, "generate_flyer", args)
    if e:
        return e
    rid = getattr(turn_state, "request_id", None)
    if not rid:
        return research._fail("no_manual_request", "Flyer generation runs only inside a manual user request; none is active.")
    if ("previous_candidate_id" in args) != ("corrections" in args):
        return research._fail("bad_argument", "A correction needs BOTH previous_candidate_id and corrections; neither is allowed on an initial generation.", "corrections")
    if "previous_candidate_id" in args:
        return _correct(agent_id, rid, args)
    prior = _existing(agent_id, rid)
    if prior:   # this request already holds an attempt: whatever the arguments, the answer is the stored outcome (no credentials or network needed)
        return _existing_reply(*prior)
    # 1. structure of the model's arguments (nothing is reserved or sent by any failure below)
    pid, ids, prompt, refs_in = args.get("product_id"), args.get("selected_product_image_ids"), args.get("prompt"), args.get("reference_ad_image_ids")
    if not isinstance(pid, str) or not pid.strip() or len(pid) > 64:
        return research._fail("bad_argument", "product_id must be a catalogue product id (see read_catalogue).", "product_id")
    if not isinstance(ids, list) or not 1 <= len(ids) <= MAX_INPUTS or any(not isinstance(i, str) or not IMG_RE.fullmatch(i) for i in ids) or len(set(ids)) != len(ids):
        return research._fail("bad_argument", f"selected_product_image_ids must list 1-{MAX_INPUTS} distinct registered merchant image ids of the product.", "selected_product_image_ids")
    if not isinstance(prompt, str) or not PROMPT_MIN <= len(prompt.strip()) <= PROMPT_MAX:
        return research._fail("bad_argument", f"prompt must be {PROMPT_MIN}-{PROMPT_MAX} characters: the design brief, required text and layout.", "prompt")
    if refs_in is None:
        refs_in = []
    if not isinstance(refs_in, list) or len(refs_in) > 3 or any(not isinstance(i, str) for i in refs_in) or len(set(refs_in)) != len(refs_in):
        return research._fail("bad_argument", "reference_ad_image_ids must be a list of at most 3 distinct ad image ids from this request's ad research.", "reference_ad_image_ids")
    # 2. setup: credentials and provider configuration (a clear structured error; no attempt is claimed)
    key = gemini_key()
    if not key:
        return research._fail("missing_credentials", f"Flyer generation is not set up: {KEY_NAME} is missing in secrets/local.env (or the environment). Nothing was sent, "
                              "no attempt was used and no substitute generator was tried.", hint="Tell the user to add their Gemini API key to secrets/local.env and ask again.")
    cfg, problem = settings()
    if problem:
        return research._fail("provider_config_invalid", problem, hint="Tell the user to correct the backend configuration.")
    # 3. merchant assets: catalogue company match, product, registered images of THAT product, provenance, bytes
    cat, ce = listing.catalogue()
    if ce:
        return {**ce, "ok": False}
    prods = [p for p in cat["products"] if isinstance(p, dict)]
    p = next((x for x in prods if x.get("product_id") == pid), None)
    if p is None:
        return research._fail("unknown_product", f"No catalogue product {pid!r}.", "product_id", hint=f"Known products: {[x.get('product_id') for x in prods]}.")
    miss = listing.product_missing(p)
    if miss:
        return research._fail("product_facts_missing", f"The catalogue is missing required facts for {pid}: {miss}. A flyer cannot be generated without them.", "product_id",
                              hint="Tell the user which facts are missing; do not invent them.")
    reg = {i["image_id"]: i for i in listing.product_images(p)}
    unknown = [i for i in ids if i not in reg]
    if unknown:
        return research._fail("image_not_registered_for_product", f"Image id(s) {unknown} are not registered merchant photographs of product {pid}. Only the product's own "
                              "catalogue images can be selected; competitor ad images, Marketplace photos and unknown ids are rejected.", "selected_product_image_ids",
                              hint=f"This product's registered images: {sorted(reg)}.")
    synthetic = [i for i in ids if _is_synthetic(cat, reg[i])]
    if synthetic and not _synthetic_allowed():
        return research._fail("synthetic_asset_not_allowed", f"Image(s) {synthetic} are marked synthetic/fictional stand-ins, not the merchant's real photographs. Flyer generation "
                              "uses real supplied photographs only.", "selected_product_image_ids",
                              hint="This is a setup blocker: the real photographs and product facts must be supplied in the catalogue.")
    if not synthetic:
        short = {i: _provenance_missing(reg[i]) for i in ids if _provenance_missing(reg[i])}
        if short:
            return research._fail("asset_provenance_missing", f"The catalogue does not state the provenance (owner, date, usage_statement) of image(s) {sorted(short)}: {short}. "
                                  "Real generation needs documented, lawfully usable merchant photographs.", "selected_product_image_ids",
                                  hint="Setup blocker: add the missing provenance to the catalogue; do not proceed or substitute.")
    inputs, total = [], 0
    for iid in ids:
        info, ie = _load_merchant_image(iid)
        if ie:
            return ie
        total += info["bytes"]
        inputs.append(info)
    if total > MAX_INPUT_TOTAL:
        return research._fail("inputs_too_large", f"The selected photographs total {total} bytes; the limit is {MAX_INPUT_TOTAL}. Select fewer or smaller photos.", "selected_product_image_ids")
    # 4. cited competitor references: provenance only, never sent
    refs = []
    if refs_in:
        run_ad = ads.run_for(agent_id, rid)
        have = ads._registered(run_ad["run_id"]) if run_ad else {}
        by_id = {v["image_id"]: v for v in have.values()}
        ad_recs = ads._load_ads(run_ad["run_id"]) if run_ad else {}
        for rid_img in refs_in:
            v = by_id.get(rid_img)
            if v is None:
                return research._fail("reference_not_registered", f"reference_ad_image_ids contains {rid_img!r}, which was not downloaded by this request's ad research.",
                                      "reference_ad_image_ids", hint="Cite only ad images you downloaded and inspected in this request, or omit the references.")
            rec = ad_recs.get(v["ad_no"]) or {}
            refs.append({"image_id": rid_img, "source_ad_id": v["ad_archive_id"], "source_url": rec.get("source_url"), "sha256": v["sha256"], "sent_to_provider": False})
    # 5. the exact context that will be sent, then ONE atomic reservation
    company = core.load_company()
    facts = _facts_text(cat, p, company, ids)
    context_text = prompt.strip() + "\n\n" + facts
    request = _request_record(cfg, len(inputs))
    snap = {"company_name": company.get("name"), "product_id": pid, "prompt": prompt.strip(), "context_text": context_text, "model": cfg["model"], "request": request,
            "synthetic": bool(synthetic),
            "product": {"product_id": pid, "name": p.get("name"), "price": p.get("price"), "specifications": p.get("specifications"), "category": p.get("category"),
                        "merchant": (cat.get("merchant") or {}).get("name"), "catalogue_file": cat.get("_file"), "catalogue_sha256": cat.get("_sha256"), "demo": bool(cat.get("demo"))},
            "inputs": [{k: v for k, v in i.items() if k != "_raw"} | {"kind": reg[i["image_id"]].get("kind"), "provenance": reg[i["image_id"]].get("provenance"),
                                                                      "synthetic": i["image_id"] in synthetic} for i in inputs],
            "references": refs}
    state, run, a = _reserve(agent_id, rid, snap)
    if state == "existing":
        return _existing_reply(run, a)
    if state == "exhausted":
        return research._fail("allowance_exhausted", f"The {a['scope']!r} flyer-generation allowance ({a['max']} attempts) is exhausted. Nothing was sent. It cannot be raised from here.",
                              hint="Tell the user the generation allowance is used up.")
    return _dispatch(a["run_id"], a["candidate_id"], cfg, key, _payload(cfg, context_text, [(i["mime_type"], i["_raw"]) for i in inputs]), inputs, 1)


def _correct(agent_id, rid, args):
    """The ONE correction. Everything about the original request is re-used from the stored first attempt; the model supplies only the previous candidate id and
    corrections that name recorded defects."""
    prev_id, corr_in = args.get("previous_candidate_id"), args.get("corrections")
    if not isinstance(prev_id, str) or not CAND_RE.fullmatch(prev_id):
        return research._fail("bad_argument", "previous_candidate_id must be a candidate id returned by generate_flyer in this request.", "previous_candidate_id")
    bad = research._fail("bad_argument", "corrections must be a list of 1-6 objects {defect_no, instruction}: each names a defect number recorded by review_flyer and gives a "
                         "specific instruction of 10-400 characters; defect numbers are distinct.", "corrections")
    if not isinstance(corr_in, list) or not 1 <= len(corr_in) <= 6:
        return bad
    wanted, seen_no = [], set()
    for c in corr_in:
        if not isinstance(c, dict) or set(c) - {"defect_no", "instruction"} or not isinstance(c.get("defect_no"), int) or isinstance(c.get("defect_no"), bool) or c["defect_no"] in seen_no:
            return bad
        ins = " ".join(c["instruction"].split()) if isinstance(c.get("instruction"), str) else ""
        if not 10 <= len(ins) <= 400 or _APPROVAL.search(ins):
            return bad
        seen_no.add(c["defect_no"])
        wanted.append({"defect_no": c["defect_no"], "instruction": ins})
    with core.db() as d:
        run = d.execute("SELECT * FROM flyer_runs WHERE agent_id=? AND request_id=?", (agent_id, rid)).fetchone()
        if not run:
            return research._fail("no_prior_candidate", "No flyer has been generated in this request, so there is nothing to correct.",
                                  hint="Call generate_flyer with the product, images and prompt first.")
        run = dict(run)
        atts, revs = _load(d, run["run_id"])
    prev = next((a for a in atts if a["candidate_id"] == prev_id), None)
    if prev is None:
        return research._fail("candidate_not_in_request", f"Candidate {prev_id} does not belong to this request.", "previous_candidate_id",
                              hint=f"This request's candidates: {[a['candidate_id'] for a in atts]}.")
    if len(atts) >= 2:   # the correction was already made: a duplicate or a restart gets the stored result; a second correction is refused
        if prev["attempt_no"] != 1:
            return research._fail("correction_limit_reached", "This request already used its one correction; a second correction (or a third generation) does not exist.",
                                  hint="Review the corrected candidate and select the final one with finalize_flyer.", flyer_id=run["run_id"], candidate_id=atts[-1]["candidate_id"],
                                  status=_flyer_summary(run, atts, revs)["status"])
        return _existing_reply(run, atts[-1])
    # the original request is fixed: an identical re-send is accepted, anything different is refused
    stored_in = json.loads(prev["inputs_json"])
    fixed = {"product_id": run["product_id"], "selected_product_image_ids": [i["image_id"] for i in stored_in], "prompt": prev["prompt"],
             "reference_ad_image_ids": [r["image_id"] for r in json.loads(prev["references_json"])]}
    given = {k: (args[k].strip() if isinstance(args[k], str) else args[k]) for k in fixed if k in args}
    changed = [k for k, v in given.items() if v != fixed[k] and not (k == "reference_ad_image_ids" and v is None and not fixed[k])]
    if changed:
        return research._fail("correction_cannot_change_original", f"A correction re-uses the original product, photographs, prompt and references; {changed} cannot be changed.",
                              "arguments", hint="Send only previous_candidate_id and corrections.")
    if not _ok(prev):
        return research._fail("no_eligible_candidate", f"The first attempt of this request ended with {prev['outcome'] or 'no recorded outcome'!r}; there is no candidate to correct. "
                              "This is a blocker: no review may be invented to authorise another generation.", hint="Report that no usable candidate exists.",
                              flyer_id=run["run_id"], candidate_id=prev_id, status="failed")
    prev_raw, problem = _artifact(run["run_id"], prev)
    if problem:
        return research._fail("artifact_integrity_failed", f"The first candidate's stored file failed the integrity check: {problem}. This is not a content defect and cannot be "
                              "corrected by generating again.", hint="Report the integrity failure; do not try to generate again.", flyer_id=run["run_id"], candidate_id=prev_id,
                              status="storage_failure", integrity={"state": "failed", "problem": problem})
    rv = revs.get(prev_id)
    if not rv:
        return research._fail("review_required", "A correction needs a saved review of this candidate that recorded defects. Inspect it with inspect_flyer and save "
                              "review_flyer first.", "previous_candidate_id", hint="Call inspect_flyer, then review_flyer.")
    if not rv["verified"]:
        return research._fail("review_not_verified", f"The review of {prev_id} is unverified (delivery: {rv['delivery']}): the candidate's pixels were not confirmed delivered to the "
                              "reviewing model, so it cannot authorise a correction.", "previous_candidate_id", hint="Report that the visual review could not be completed.")
    defects = {d["defect_no"]: d for d in json.loads(rv["defects_json"])}
    if rv["verdict"] != "defects_found" or not defects:
        return research._fail("no_defect_to_correct", f"The verified review of {prev_id} recorded no defect (verdict {rv['verdict']}), so there is nothing to correct.",
                              "previous_candidate_id", hint="Finalize the candidate with finalize_flyer, or report the uncertainty.")
    unknown_no = sorted(w["defect_no"] for w in wanted if w["defect_no"] not in defects)
    if unknown_no:
        return research._fail("unknown_defect", f"Defect number(s) {unknown_no} are not recorded in the review of {prev_id}.", "corrections",
                              hint=f"Recorded defect numbers: {sorted(defects)}.")
    # setup: credentials and provider configuration
    key = gemini_key()
    if not key:
        return research._fail("missing_credentials", f"Flyer generation is not set up: {KEY_NAME} is missing in secrets/local.env (or the environment). Nothing was sent, "
                              "no attempt was used.", hint="Tell the user to add their Gemini API key to secrets/local.env and ask again.")
    cfg, problem = settings()
    if problem:
        return research._fail("provider_config_invalid", problem, hint="Tell the user to correct the backend configuration.")
    # the original facts and merchant photographs must be unchanged (never silently replaced)
    cat, ce = listing.catalogue()
    if ce:
        return {**ce, "ok": False}
    stored_p = json.loads(prev["product_json"])
    p = next((x for x in cat["products"] if isinstance(x, dict) and x.get("product_id") == run["product_id"]), None)
    if p is None:
        return research._fail("original_facts_changed", f"Product {run['product_id']!r} is no longer in the catalogue, so the original facts cannot be preserved.", hint="Report it.")
    now_p = {"name": p.get("name"), "price": p.get("price"), "specifications": p.get("specifications"), "category": p.get("category"),
             "merchant": (cat.get("merchant") or {}).get("name")}
    diff = [k for k, v in now_p.items() if stored_p.get(k) != v]
    if diff:
        return research._fail("original_facts_changed", f"The catalogue's {diff} for {run['product_id']!r} differ from the facts the first candidate was generated from. A "
                              "correction must preserve the original facts and will not use the changed ones.", hint="Report that the merchant facts changed after generation.")
    reg = {i["image_id"]: i for i in listing.product_images(p)}
    moved = [i["image_id"] for i in stored_in if i["image_id"] not in reg or reg[i["image_id"]].get("provenance") != i.get("provenance")
             or _is_synthetic(cat, reg[i["image_id"]]) != bool(i.get("synthetic"))]
    if moved:
        return research._fail("original_input_changed", f"Merchant photograph(s) {moved} are no longer registered for this product with the same provenance; the original "
                              "inputs cannot be preserved.", "selected_product_image_ids", hint="Report that the registered merchant photographs changed after generation.")
    if any(i.get("synthetic") for i in stored_in) and not _synthetic_allowed():
        return research._fail("synthetic_asset_not_allowed", "The original inputs are synthetic stand-ins and the operator seam that allowed them is off.",
                              "selected_product_image_ids", hint="Setup blocker.")
    cur, total = [], 0
    for i in stored_in:
        info, ie = _load_merchant_image(i["image_id"])
        if ie:
            return ie
        total += info["bytes"]
        cur.append(info)
    changed_ids = [i["image_id"] for i, c in zip(stored_in, cur) if c["sha256"] != i["sha256"]]
    if changed_ids:
        return research._fail("original_input_changed", f"Merchant photograph(s) {changed_ids} no longer have the bytes the first candidate was generated from (hash differs). "
                              "The original inputs are never replaced silently.", "selected_product_image_ids",
                              hint="Report that the merchant photographs changed after generation; restore them or start a new request.")
    if total + len(prev_raw) > MAX_REQUEST_IMAGE_BYTES:
        return research._fail("inputs_too_large", f"The merchant photographs plus the previous draft total {total + len(prev_raw)} bytes; the limit is {MAX_REQUEST_IMAGE_BYTES}.")
    # the exact context: the stored original prompt + facts, then the specific corrections
    lines = [f"{n}. (defect {w['defect_no']}, {defects[w['defect_no']]['check']}) {defects[w['defect_no']]['description']} -> {w['instruction']}"
             for n, w in enumerate(wanted, 1)]
    context_text = (prev["context_text"] + "\n\n--- Correction request (this is the final attempt) ---\nThe LAST attached image is the previous draft flyer. Keep everything "
                    "in it that is correct and change ONLY what these specific corrections name; the supplied merchant facts and the merchant photographs above remain "
                    "authoritative.\n" + "\n".join(lines) + "\n")
    corrections = [{"defect_no": w["defect_no"], "check": defects[w["defect_no"]]["check"], "defect": defects[w["defect_no"]]["description"], "instruction": w["instruction"]}
                   for w in wanted]
    request = {**_request_record(cfg, len(cur) + 1), "predecessor_id": prev_id, "predecessor_sha256": prev["out_sha256"]}   # rebuilt, not copied: an older stored record may differ from what is sent now
    snap = {"prompt": prev["prompt"], "context_text": context_text, "model": cfg["model"], "request": request, "synthetic": bool(prev["inputs_synthetic"]),
            "product": stored_p, "inputs": stored_in, "references": json.loads(prev["references_json"]), "corrections": corrections}
    state, run2, a = _reserve_correction(agent_id, rid, prev_id, snap)
    if state == "existing":
        return _existing_reply(run2, a)
    if state == "exhausted":
        return research._fail("allowance_exhausted", f"The {a['scope']!r} flyer-generation allowance ({a['max']} attempts) is exhausted. Nothing was sent. It cannot be raised from here.",
                              hint="Tell the user the generation allowance is used up; the first candidate remains an unresolved draft.")
    if state != "go":   # lost a race with a concurrent change of this request's records: nothing was sent
        return research._fail("no_eligible_candidate", "The first candidate is no longer eligible for a correction; nothing was sent.", flyer_id=run["run_id"], candidate_id=prev_id)
    images = [(i["mime_type"], i["_raw"]) for i in cur] + [(prev["out_mime"], prev_raw)]
    return _dispatch(a["run_id"], a["candidate_id"], cfg, key, _payload(cfg, context_text, images), cur, 2, predecessor=prev_id)


# ---------------- review: inspect, review, finalize ----------------
def _own(agent_id, rid, cid):
    """-> (run, attempt, None) | (None, None, error): the candidate must belong to THIS agent's run of THIS manual request."""
    if not isinstance(cid, str) or not CAND_RE.fullmatch(cid):
        return None, None, research._fail("bad_argument", "candidate_id must be a candidate id returned by generate_flyer in this request.", "candidate_id")
    with core.db() as d:
        run = d.execute("SELECT * FROM flyer_runs WHERE agent_id=? AND request_id=?", (agent_id, rid)).fetchone()
        a = d.execute("SELECT * FROM flyer_attempts WHERE candidate_id=? AND run_id=?", (cid, run["run_id"])).fetchone() if run else None
    if not run or not a:
        return None, None, research._fail("candidate_not_in_request", f"Candidate {cid} does not belong to this request of this specialist (a review, inspection or selection "
                                          "binds to the trusted agent, request and run).", "candidate_id",
                                          hint="Use a candidate id that generate_flyer returned in this request.")
    return dict(run), dict(a), None


def _integrity_fail(run, a, problem, what):
    return research._fail("artifact_integrity_failed", f"The saved image of {a['candidate_id']} failed its integrity check: {problem}. This is an integrity failure, not a content "
                          f"defect; it cannot be {what}.", hint="Report the integrity failure; do not review or regenerate.", flyer_id=run["run_id"], candidate_id=a["candidate_id"],
                          status="storage_failure", integrity={"state": "failed", "problem": problem})


def inspect(agent_id, args):
    """Show the model a candidate's ACTUAL pixels together with the merchant's photographs. Backend-written inspection record; delivery is what Hermes decided."""
    _, e = _prepare(agent_id, "inspect_flyer", args)
    if e:
        return e
    rid = getattr(turn_state, "request_id", None)
    if not rid:
        return research._fail("no_manual_request", "Flyer review runs only inside a manual user request; none is active.")
    run, a, e = _own(agent_id, rid, args.get("candidate_id"))
    if e:
        return e
    if not _ok(a):
        return research._fail("no_candidate_image", f"Candidate {a['candidate_id']} has no image (its attempt ended with {a['outcome'] or 'no outcome'!r}); there is nothing to inspect "
                              "or review.", "candidate_id", hint="Report that no usable candidate exists; do not describe or review a flyer you could not see.")
    raw, problem = _artifact(run["run_id"], a)
    if problem:
        return _integrity_fail(run, a, problem, "inspected")
    stored_in = json.loads(a["inputs_json"])
    refs, parts = [], []
    for i in stored_in:
        info, ie = _load_merchant_image(i["image_id"])
        if ie:
            return ie
        if info["sha256"] != i["sha256"]:
            return research._fail("merchant_reference_changed", f"Merchant photograph {i['image_id']!r} no longer has the bytes this candidate was generated from; it cannot be "
                                  "used as the reference of a review.", "candidate_id", hint="Report that the merchant photographs changed after generation.")
        pr = core.model_ready(i["image_id"], info["_raw"])
        if not pr.get("ok"):
            return pr
        refs.append({"image_id": i["image_id"], "sha256": info["sha256"]})
        parts.append((i["image_id"], pr))
    cand = core.model_ready(a["candidate_id"], raw)
    if not cand.get("ok"):
        return cand
    delivery = turn_state.image_delivery()
    product = json.loads(a["product_json"])
    pr_ = product.get("price") or {}
    specs = "; ".join(f"{k}: {v}" for k, v in (product.get("specifications") or {}).items())
    with core.db() as d:
        cur = d.execute("INSERT INTO image_inspections(agent_id, image_id, kind, sha256, width, height, ts, delivery, request_id, run_id, detail) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (agent_id, a["candidate_id"], "flyer_candidate", a["out_sha256"], a["out_width"], a["out_height"], time.time(),
                         delivery if delivery in listing.DELIVERY else "unknown", rid, run["run_id"], json.dumps({"references": refs})))
    # the capability prediction above is NOT delivery: the hooks confirm it only when these exact images are in an actual model request and a response follows
    expect_delivery(cur.lastrowid, [cand["data_url"]] + [pr["data_url"] for _, pr in parts])
    head = (f"REVIEW MATERIAL for candidate {a['candidate_id']} (candidate_sha256 {a['out_sha256']}, {a['out_width']}x{a['out_height']}). The FIRST image below is the generated flyer's "
            f"real pixels; the following {len(parts)} image(s) are the merchant's own photographs of the product that were supplied to the generator.\n"
            f"Supplied facts: product {product.get('name')!r}; declared price {pr_.get('amount')} {pr_.get('currency')}; specifications: {specs or 'none'}.\n"
            f"The brief the generator received (required text and layout): {a['prompt']}\n"
            "Judge ONLY what is visible, with three checks: product_appearance (does the product in the flyer match the merchant photographs in colour, pattern and proportions), "
            "required_text_price (is every required word and the declared price present and exact, nothing invented), layout_readability (is it legible and arranged as asked). "
            "Mark each pass, fail or uncertain and say what you saw; give every failed check a defect with a specific correction; state what you are unsure of. Then, in your NEXT response (never in "
            f"the same tool-call batch as inspect_flyer), call review_flyer with this candidate_id and candidate_sha256. Your review is a fallible agent review, not human approval.")
    content = [{"type": "text", "text": head}, {"type": "image_url", "image_url": {"url": cand["data_url"]}}]
    for iid, pr in parts:
        content += [{"type": "text", "text": f"Merchant photograph {iid} (supplied, original):"}, {"type": "image_url", "image_url": {"url": pr["data_url"]}}]
    return {"_multimodal": True, "content": content,
            # used when pixels cannot travel and in saved history: must never claim the model saw the image, and never carries the hash it would need to echo
            "text_summary": (f"[inspect_flyer {a['candidate_id']}: the candidate's pixels are not visible in this message. If you cannot see the image, say the flyer could not be "
                             "reviewed; never describe it and do not claim a review.]"),
            "meta": {"candidate_id": a["candidate_id"], "sha256": a["out_sha256"], "width": a["out_width"], "height": a["out_height"], "references": refs, "delivery": delivery}}


def _data_urls(node, out):
    """Every data:image URL string anywhere in a request payload (chat messages or Responses input items alike)."""
    if isinstance(node, str):
        if node.startswith("data:image"):
            out.add(hashlib.sha256(node.encode("utf-8")).hexdigest())
    elif isinstance(node, dict):
        for v in node.values():
            _data_urls(v, out)
    elif isinstance(node, (list, tuple)):
        for v in node:
            _data_urls(v, out)


def expect_delivery(inspection_id, data_urls):
    """Register an inspection row whose EXACT image data URLs must appear in a later model request that a response then completes (note_request / note_response below).
    Used by inspect_flyer and inspect_image; the capability prediction stored on the row is never confirmation."""
    turn_state.pending_images[inspection_id] = {"urls": {hashlib.sha256(u.encode("utf-8")).hexdigest() for u in data_urls}, "request": None}


def note_request(request_messages, api_request_id):
    """pre_api_request hook: an inspection counts as delivered only if EVERY image of its review material (candidate pixels and merchant photographs) is, byte for byte, in
    the payload actually being sent to the model for this attempt. A later attempt that lacks them (parts stripped, text fallback) withdraws it."""
    pend = turn_state.pending_images
    if not pend:
        return
    seen = set()
    _data_urls(request_messages, seen)
    for p in pend.values():
        p["request"] = api_request_id if p["urls"] <= seen else None


def note_response(api_request_id):
    """post_api_request hook: a model response has completed. Every pending inspection now has its model-response boundary (a review may follow, in a later assistant message);
    one whose pixels were in THIS response's request is recorded as delivered. Nothing else can confirm a delivery."""
    pend = turn_state.pending_images
    if not pend:
        return
    now = time.time()
    with core.db() as d:
        for iid, p in list(pend.items()):
            d.execute("UPDATE image_inspections SET boundary_at=?, delivered_at=? WHERE id=?", (now, now if p["request"] == api_request_id else None, iid))
            del pend[iid]


def _text(v, name, lo, hi):
    if not isinstance(v, str):
        return None, f"{name} must be text"
    s = " ".join(v.split())
    if not lo <= len(s) <= hi:
        return None, f"{name} must be {lo}-{hi} characters (got {len(s)})"
    if _APPROVAL.search(s):
        return None, f"{name} may not claim human approval, certification or a guarantee"
    return s, None


def _validate_review(args):
    """-> (clean, None) | (None, error)."""
    def bad(m, f="checks"):
        return None, research._fail("bad_review", m, f, hint="checks needs exactly product_appearance, required_text_price and layout_readability, each {result: pass|fail|uncertain, "
                                    "observation}; every failed check needs a defect {check, description, correction}; summary 20-600 characters.")
    sh = args.get("candidate_sha256")
    if not isinstance(sh, str) or not re.fullmatch(r"[0-9a-f]{64}", sh):
        return bad("candidate_sha256 must be the 64-hex hash shown with the inspected candidate", "candidate_sha256")
    ch = args.get("checks")
    if not isinstance(ch, dict) or set(ch) != set(CHECKS):
        return bad(f"checks must contain exactly {list(CHECKS)}")
    checks = {}
    for n in CHECKS:
        c = ch[n]
        if not isinstance(c, dict) or set(c) - {"result", "observation"} or c.get("result") not in RESULTS:
            return bad(f"checks.{n} must be {{result: pass|fail|uncertain, observation}}", f"checks.{n}")
        obs, e = _text(c.get("observation"), f"checks.{n}.observation", 10, 600)
        if e:
            return bad(e, f"checks.{n}")
        checks[n] = {"result": c["result"], "observation": obs}
    din = args.get("defects") or []
    if not isinstance(din, list) or len(din) > 8:
        return bad("defects must be a list of at most 8", "defects")
    defects = []
    for i, d in enumerate(din, 1):
        if not isinstance(d, dict) or set(d) - {"check", "description", "correction"} or d.get("check") not in CHECKS:
            return bad("each defect must be {check, description, correction} with check one of the three checks", "defects")
        desc, e1 = _text(d.get("description"), "defect.description", 10, 400)
        fix, e2 = _text(d.get("correction"), "defect.correction", 10, 400)
        if e1 or e2:
            return bad(e1 or e2, "defects")
        if checks[d["check"]]["result"] == "pass":
            return bad(f"a defect names check {d['check']!r}, which you marked pass", "defects")
        defects.append({"defect_no": i, "check": d["check"], "description": desc, "correction": fix})
    for n in CHECKS:
        if checks[n]["result"] == "fail" and not any(d["check"] == n for d in defects):
            return bad(f"check {n!r} failed but no defect with a specific correction is given for it", "defects")
    summary, e = _text(args.get("summary"), "summary", 20, 600)
    if e:
        return bad(e, "summary")
    unc = args.get("uncertainties")
    if unc is not None:
        unc, e = _text(unc, "uncertainties", 0, 600)
        if e:
            return bad(e, "uncertainties")
    verdict = "defects_found" if any(c["result"] == "fail" for c in checks.values()) else "inconclusive" if any(c["result"] == "uncertain" for c in checks.values()) else "passed"
    return {"sha256": sh, "checks": checks, "defects": defects, "summary": summary, "uncertainties": unc or "", "verdict": verdict}, None


def review(agent_id, args):
    _, e = _prepare(agent_id, "review_flyer", args)
    if e:
        return e
    rid = getattr(turn_state, "request_id", None)
    if not rid:
        return research._fail("no_manual_request", "Flyer review runs only inside a manual user request; none is active.")
    run, a, e = _own(agent_id, rid, args.get("candidate_id"))
    if e:
        return e
    cid = a["candidate_id"]
    with core.db() as d:
        have = d.execute("SELECT * FROM flyer_reviews WHERE candidate_id=?", (cid,)).fetchone()
    if have:
        return research._fail("review_already_saved", f"Candidate {cid} already has its review (one review per candidate); it cannot be replaced.",
                              hint="Use the stored review.", flyer_id=run["run_id"], candidate_id=cid, review=_review_view(dict(have)))
    if not _ok(a):
        return research._fail("no_candidate_image", f"Candidate {cid} has no image (its attempt ended with {a['outcome'] or 'no outcome'!r}); there is nothing to review.",
                              "candidate_id", hint="Report that no usable candidate exists; a review cannot be invented.")
    rv, e = _validate_review(args)
    if e:
        return e
    _, problem = _artifact(run["run_id"], a)
    if problem:
        return _integrity_fail(run, a, problem, "reviewed")
    with core.db() as d:
        rows = d.execute("SELECT * FROM image_inspections WHERE agent_id=? AND kind='flyer_candidate' AND image_id=? AND request_id=? AND run_id=? AND sha256=? ORDER BY id DESC",
                         (agent_id, cid, rid, run["run_id"], a["out_sha256"])).fetchall()
    # the newest inspection that was actually delivered, else the newest one at all (a premature re-inspection does not void an earlier delivered one)
    insp = next((r for r in rows if r["delivered_at"]), None) or next((r for r in rows if r["boundary_at"]), None) or (rows[0] if rows else None)
    if not insp or insp["sha256"] != a["out_sha256"]:
        return research._fail("candidate_not_inspected", f"No inspection of {cid} with its current bytes is recorded for this request: a review needs the candidate's actual "
                              "pixels delivered through inspect_flyer in this request (a description, a URL or an earlier inspection does not count).", "candidate_id",
                              hint="Call inspect_flyer(candidate_id) first and review only what you see.")
    if rv["sha256"] != a["out_sha256"]:
        return research._fail("candidate_hash_mismatch", f"candidate_sha256 does not equal the hash of candidate {cid}; a review binds to the exact image it was made from.",
                              "candidate_sha256", hint="Use the candidate_sha256 shown with the inspected pixels.")
    if not insp["boundary_at"]:
        return research._fail("image_not_yet_delivered", f"The pixels of {cid} have not been delivered to you yet: inspect_flyer only prepares them, and they reach you with the NEXT "
                              "model request. A review in the same tool-call batch as inspect_flyer (or before any model response followed it) is refused and nothing was saved.",
                              "candidate_id", hint=f"Call inspect_flyer({cid}) on its own, look at the images in your next message, and only then call review_flyer in a LATER "
                              "response. If the images never reach you, say so instead of reviewing.")
    verified = bool(insp["delivered_at"])   # the exact review material was in a model request and a response followed
    delivery = "image_part_sent" if verified else ("unknown" if insp["delivery"] == "image_part_sent" else insp["delivery"] or "unknown")   # a prediction alone never stands
    review_id = "rev-" + uuid.uuid4().hex[:10]
    try:
        with core.db() as d:
            d.execute("INSERT INTO flyer_reviews(review_id, candidate_id, run_id, agent_id, request_id, sha256, width, height, inspection_id, delivery, verified, verdict, checks_json, "
                      "defects_json, uncertainties, summary, refs_json, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (review_id, cid, run["run_id"], agent_id, rid, a["out_sha256"], a["out_width"], a["out_height"], insp["id"], delivery, 1 if verified else 0,
                       rv["verdict"] if verified else "unverified", json.dumps(rv["checks"]), json.dumps(rv["defects"]), rv["uncertainties"], rv["summary"],
                       insp["detail"] and json.dumps(json.loads(insp["detail"]).get("references", [])) or "[]", time.time()))
    except Exception:   # a concurrent save of the same candidate's review (UNIQUE candidate_id)
        with core.db() as d:
            have = d.execute("SELECT * FROM flyer_reviews WHERE candidate_id=?", (cid,)).fetchone()
        if have:
            return research._fail("review_already_saved", f"Candidate {cid} already has its review (one review per candidate).", flyer_id=run["run_id"], candidate_id=cid,
                                  review=_review_view(dict(have)))
        return research._fail("storage_error", "The review could not be saved. Nothing was changed.", hint="Report this as a blocker.")
    with core.db() as d:
        row = _flyer_summary(dict(d.execute("SELECT * FROM flyer_runs WHERE run_id=?", (run["run_id"],)).fetchone()), *_load(d, run["run_id"]))
        atts, revs = _load(d, run["run_id"])
    state = _correction_state(atts, revs)
    verdict = rv["verdict"] if verified else "unverified"
    return {"ok": True, "review_id": review_id, "flyer_id": run["run_id"], "candidate_id": cid, "sha256": a["out_sha256"], "verdict": verdict, "verified": verified,
            "delivery": delivery, "defects": rv["defects"] if verified else [], "status": row["status"], "correction": state,
            "note": ("Saved as a fallible agent review of the candidate's delivered pixels (not human approval). " + (
                     "Defects were recorded: one correction is possible (generate_flyer with previous_candidate_id and corrections)." if state["available"] and len(atts) == 1
                     else "Select the final candidate with finalize_flyer.")) if verified else
            (f"UNVERIFIED: the candidate's pixels were not confirmed delivered to you (delivery: {delivery}). The review is stored as unverified, does not count as a "
             "completed visual review and cannot authorise a correction; the flyer stays UNCHECKED. Say so plainly.")}


def finalize(agent_id, args):
    _, e = _prepare(agent_id, "finalize_flyer", args)
    if e:
        return e
    rid = getattr(turn_state, "request_id", None)
    if not rid:
        return research._fail("no_manual_request", "Flyer selection runs only inside a manual user request; none is active.")
    rat, why = _text(args.get("rationale"), "rationale", 20, 600)
    if why:
        return research._fail("bad_argument", why + ". Give a short, factual reason for choosing this candidate (no claim of human approval or guarantee).", "rationale")
    run, a, e = _own(agent_id, rid, args.get("candidate_id"))
    if e:
        return e
    cid = a["candidate_id"]
    if run["final_candidate_id"]:
        if run["final_candidate_id"] != cid:
            return research._fail("final_already_selected", f"This request already selected {run['final_candidate_id']} as its final candidate; the selection cannot be changed.",
                                  flyer_id=run["run_id"], candidate_id=run["final_candidate_id"])
    elif not _ok(a):
        return research._fail("no_candidate_image", f"Candidate {cid} has no image (its attempt ended with {a['outcome'] or 'no outcome'!r}) and cannot be the final flyer.",
                              "candidate_id", hint="Select a candidate that has an image, or report the blocker.")
    else:
        _, problem = _artifact(run["run_id"], a)
        if problem:
            return _integrity_fail(run, a, problem, "selected as the final flyer")
        with core.db() as d:
            res = _research(d, run)
            cur = d.execute("UPDATE flyer_runs SET final_candidate_id=?, selection_rationale=?, selected_at=?, research_json=? WHERE run_id=? AND final_candidate_id IS NULL",
                            (cid, rat, _iso(time.time()), json.dumps(res), run["run_id"]))
            won = cur.rowcount == 1
            run = dict(d.execute("SELECT * FROM flyer_runs WHERE run_id=?", (run["run_id"],)).fetchone())
        if not won and run["final_candidate_id"] != cid:
            return research._fail("final_already_selected", f"This request already selected {run['final_candidate_id']} as its final candidate; the selection cannot be changed.",
                                  flyer_id=run["run_id"], candidate_id=run["final_candidate_id"])
    with core.db() as d:
        s = _flyer_summary(run, *_load(d, run["run_id"]))
    return {"ok": True, "flyer_id": run["run_id"], "candidate_id": cid, "status": s["status"], "status_text": s["status_text"], "final": s["final"],
            "unresolved_issues": s["unresolved_issues"], "retrieve": f"/api/flyers/{run['run_id']}", "note": s["note"],
            "say": "Report this status exactly: " + s["status_text"] + ". " + ("List the unresolved issues plainly." if s["unresolved_issues"] else "")}


def read_flyer(agent_id, args):
    _, e = _prepare(agent_id, "read_flyer", args)
    if e:
        return e
    fid = args.get("flyer_id")
    if fid is None:
        return {"ok": True, "flyers": list_flyers(agent_id), "note": "Stored data only; no generation or provider request was made."}
    f = get_flyer(fid)
    if not f or f["identity"]["agent_id"] != agent_id:
        return research._fail("unknown_flyer", f"No saved flyer {fid!r} for this specialist.", "flyer_id")
    return {"ok": True, "flyer": f, "note": "Stored data only; no generation or provider request was made."}
