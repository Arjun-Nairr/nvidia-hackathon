"""Flyer generation (V2-04): one Gemini image per manual request for a social_media specialist, saved, UNCHECKED, retrievable after restart.

Backend-owned and UI-independent. The specialist supplies a registered catalogue product, 1-3 of THAT product's registered merchant image ids and a
prompt; everything that matters is derived or enforced HERE:
- Identity: agent from the worker's environment, request from the backend (turn_state.request_id); company/product/candidate ids are generated or looked up
  here. There is no URL, path, credential, provider setting, run, candidate or allowance argument.
- Inputs: only the selected product's catalogue-registered merchant images are sent to Gemini, as their ORIGINAL bytes (decoded and size-bounded first).
  Competitor/ad images are cited by id as provenance only and are never sent. Synthetic stand-ins are refused unless the operator sets
  ECOM_FLYER_ALLOW_SYNTHETIC=1 (isolated tests), and the stored record then says so.
- Attempts: ONE initial attempt per manual request in this slice (ATTEMPTS_ENABLED); the final bound of two is recorded (ATTEMPTS_FINAL_MAX) for the reviewed
  correction path of ticket 5. The slot is reserved in ONE immediate SQLite transaction BEFORE the send; once reserved it is consumed by any outcome:
  provider refusal, malformed/corrupt/multiple output, unknown outcome (connection lost), storage failure. Nothing here ever re-sends. A completed result is
  retrieved; an attempt without an outcome is reported as uncertain. Validation errors and a missing key happen BEFORE the reservation and consume nothing.
- Transport: one plain HTTPS POST (no SDK, no redirects, no retries), TLS verification on, key only in the x-goog-api-key header, store=false.
- Output: exactly one inline image, bounded, fully decoded, type/dimensions checked, hash recorded, stored privately and registered. File validity says
  nothing about content: every saved flyer is UNCHECKED (no agent review or approval exists before ticket 5).
- Retrieval: a saved output is re-validated EVERY time it is listed, detailed, returned from the cache or served (_artifact: managed path, existence, bounded
  size, saved size and hash, full decode, type and dimensions). A failure is an explicit storage/integrity failure with no image reference; the original
  generation outcome and the consumed attempt are untouched and nothing is ever regenerated.
- Diagnostics: everything derived from the provider or from an exception is passed through _clean (key redacted, bounded) before it is stored or shown.
Contract source: Google's official Interactions API reference and image-generation guide, re-read 2026-10-13 (see research/v2-04-flyer-generation-result-20261013.md).
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
MAX_OUTPUT_BYTES, MIN_EDGE, MAX_EDGE = 16_000_000, 64, 8192
MAX_RESPONSE_BYTES = 40_000_000
PROMPT_MIN, PROMPT_MAX = 40, 3000
TIMEOUT_S = 180
ATTEMPTS_FINAL_MAX = 2        # the reviewed bound: initial generation + ONE correction (ticket 5)
ATTEMPTS_ENABLED = 1          # this slice executes the initial generation only; ticket 5 raises it to ATTEMPTS_FINAL_MAX together with its correction path
SCOPE_DEFAULT, SCOPE_MAX_DEFAULT = "default", 6
CONTENT_STATUS = "unchecked"
UNCHECKED_NOTE = ("UNCHECKED: the file decoded as one valid image and nothing more. No agent has reviewed it against the product, price or requested text, "
                  "and it is not approved. Do not describe it as verified, accurate or final.")
ARGS = {"generate_flyer": {"product_id", "selected_product_image_ids", "prompt", "reference_ad_image_ids"}, "read_flyer": {"flyer_id"}}
RUN_RE, IMG_RE = re.compile(r"fly-[0-9a-f]{10}"), re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
ARTIFACT_RE = re.compile(r"cand-[0-9a-f]{10}\.(?:jpg|png|webp)")


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


def _reserve(agent_id, request_id, snap):
    """ONE immediate transaction: existing run/attempt -> report it; else scope check, run + attempt rows. -> (state, run, attempt)."""
    c = core.db()
    try:
        research._begin_immediate(c)
        run = c.execute("SELECT * FROM flyer_runs WHERE agent_id=? AND request_id=?", (agent_id, request_id)).fetchone()
        if run:
            att = c.execute("SELECT * FROM flyer_attempts WHERE run_id=? ORDER BY attempt_no DESC LIMIT 1", (run["run_id"],)).fetchone()
            n = c.execute("SELECT COUNT(*) FROM flyer_attempts WHERE run_id=?", (run["run_id"],)).fetchone()[0]
            if att is not None and n >= ATTEMPTS_ENABLED:
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
        c.execute("INSERT INTO flyer_attempts(candidate_id, run_id, attempt_no, status, prompt, context_text, product_json, inputs_json, references_json, provider, model, "
                  "request_json, inputs_synthetic, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (cand, rid, 1, "reserved", snap["prompt"], snap["context_text"], json.dumps(snap["product"]), json.dumps(snap["inputs"]), json.dumps(snap["references"]),
                   "gemini-interactions", snap["model"], json.dumps(snap["request"]), 1 if snap["synthetic"] else 0, now))
        c.commit()
        return "go", dict(c.execute("SELECT * FROM flyer_runs WHERE run_id=?", (rid,)).fetchone()), {"candidate_id": cand, "run_id": rid}
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


# ---------------- tool bodies ----------------
def _prepare(agent_id, tool, args):
    if not isinstance(args, dict):
        return None, research._fail("bad_request", "Arguments must be an object.")
    extra = sorted(set(args) - ARGS[tool])
    if extra:
        return None, research._fail("invalid_argument", f"Unsupported argument(s) {extra}. The provider, model, credentials, paths, URLs, run, candidate, attempt number and "
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


def _attempt_view(a):
    return {"candidate_id": a["candidate_id"], "attempt_no": a["attempt_no"], "status": a["status"], "outcome": a["outcome"], "error": a["error"], "provider": a["provider"],
            "model": a["model"], "http_status": a["http_status"], "usage": json.loads(a["usage"]) if a["usage"] else None, "interaction_id": a["interaction_id"], "ms": a["ms"],
            "created_at": _iso(a["created_at"]), "dispatched_at": _iso(a["dispatched_at"]), "finished_at": _iso(a["finished_at"])}


def _run_state(run, a):
    if a is None:
        return "no_attempt"
    if a["status"] == "done":
        return CONTENT_STATUS if a["outcome"] == "ok" else "failed"
    return "in_progress_or_unknown"


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


def _flyer_summary(run, a):
    st = _run_state(run, a)
    problem = None
    if st == CONTENT_STATUS:
        _, problem = _artifact(run["run_id"], a)
        if problem:   # the generation SUCCEEDED and its attempt is consumed; only the stored artifact is bad
            st = "storage_failure"
    return {"flyer_id": run["run_id"], "status": st, "agent_id": run["agent_id"], "request_id": run["request_id"], "product_id": run["product_id"], "created_at": _iso(run["created_at"]),
            "candidate_id": a["candidate_id"] if a else None, "outcome": a["outcome"] if a else None,
            "error": (f"The generated image was saved but its stored file failed the integrity check: {problem}. It was not generated again and no second attempt is available."
                      if problem else a["error"] if a else None),
            "error_kind": "storage_integrity" if problem else (a["outcome"] if a and st == "failed" else None),
            "integrity": ({"state": "failed", "problem": problem} if problem else {"state": "valid"} if st == CONTENT_STATUS else None),
            "image": ({"url": f"/api/flyers/images/{run['run_id']}", "width": a["out_width"], "height": a["out_height"], "mime_type": a["out_mime"], "sha256": a["out_sha256"],
                       "bytes": a["out_bytes"]} if st == CONTENT_STATUS else None),
            "content_status": CONTENT_STATUS if st == CONTENT_STATUS else None, "inputs_synthetic": bool(a["inputs_synthetic"]) if a else None,
            "note": UNCHECKED_NOTE if st == CONTENT_STATUS else None}


def _existing(agent_id, request_id):
    """(run, attempt) when this request already used every attempt this slice executes, else None. A pure read: it is what makes a repeated call (and a call after the
    key was removed or the app restarted) return the stored result instead of anything new."""
    with core.db() as d:
        run = d.execute("SELECT * FROM flyer_runs WHERE agent_id=? AND request_id=?", (agent_id, request_id)).fetchone()
        if not run:
            return None
        att = _latest(d, run["run_id"])
        n = d.execute("SELECT COUNT(*) FROM flyer_attempts WHERE run_id=?", (run["run_id"],)).fetchone()[0]
    return (dict(run), dict(att)) if att is not None and n >= ATTEMPTS_ENABLED else None


def _latest(d, run_id):
    return d.execute("SELECT * FROM flyer_attempts WHERE run_id=? ORDER BY attempt_no DESC LIMIT 1", (run_id,)).fetchone()


def get_flyer(flyer_id):
    if not isinstance(flyer_id, str) or not RUN_RE.fullmatch(flyer_id):
        return None
    with core.db() as d:
        run = d.execute("SELECT * FROM flyer_runs WHERE run_id=?", (flyer_id,)).fetchone()
        if not run:
            return None
        a = _latest(d, flyer_id)
        al = d.execute("SELECT * FROM flyer_allowance WHERE scope=?", (run["scope"],)).fetchone()
        n = d.execute("SELECT COUNT(*) FROM flyer_attempts WHERE run_id=?", (flyer_id,)).fetchone()[0]
    out = _flyer_summary(run, a)
    out["identity"] = {"agent_id": run["agent_id"], "company_id": run["company_id"], "company_name": run["company_name"], "conversation_id": run["conversation_id"],
                       "request_id": run["request_id"], "message_id": run["message_id"], "product_id": run["product_id"], "run_id": run["run_id"], "scope": run["scope"]}
    out["attempts"] = {"used": n, "enabled": ATTEMPTS_ENABLED, "final_max": run["attempts_final_max"],
                       "note": "This slice runs the initial generation only; the reviewed correction path is a later ticket. The final bound is two."}
    if a:
        out["attempt"] = {**_attempt_view(a), "prompt": a["prompt"], "context_text": a["context_text"], "product": json.loads(a["product_json"]),
                          "inputs": json.loads(a["inputs_json"]), "references": json.loads(a["references_json"]), "request": json.loads(a["request_json"]),
                          "output": ({"image_id": run["run_id"], "sha256": a["out_sha256"], "bytes": a["out_bytes"], "width": a["out_width"], "height": a["out_height"],
                                      "mime_type": a["out_mime"]} if out["status"] == CONTENT_STATUS else None)}
    out["allowance"] = {"scope": run["scope"], "attempts_used": al["attempts_used"] if al else None, "attempts_max": al["attempts_max"] if al else None}
    return out


def list_flyers(agent_id=None):
    with core.db() as d:
        runs = d.execute("SELECT * FROM flyer_runs" + (" WHERE agent_id=?" if agent_id else "") + " ORDER BY created_at DESC", (agent_id,) if agent_id else ()).fetchall()
        return [_flyer_summary(r, _latest(d, r["run_id"])) for r in runs]


def allowances():
    with core.db() as d:
        return [dict(r) for r in d.execute("SELECT * FROM flyer_allowance ORDER BY scope")]


def image_state(flyer_id):
    """-> ("ok", bytes, mime) | ("integrity", problem, None) | ("none", None, None). The id is validated and resolved through the database; no path comes from the
    caller, and the bytes are served only if the saved artifact passes _artifact."""
    if not isinstance(flyer_id, str) or not RUN_RE.fullmatch(flyer_id):
        return "none", None, None
    with core.db() as d:
        a = d.execute("SELECT * FROM flyer_attempts WHERE run_id=? AND outcome='ok' ORDER BY attempt_no DESC LIMIT 1", (flyer_id,)).fetchone()
    if not a or not a["out_path"]:
        return "none", None, None
    raw, problem = _artifact(flyer_id, a)
    return ("ok", raw, a["out_mime"]) if raw is not None else ("integrity", problem, None)


def image_file(flyer_id):
    """(bytes, content_type) of the managed output image, or None (unknown id OR failed integrity check; image_state tells them apart)."""
    s, a, b = image_state(flyer_id)
    return (a, b) if s == "ok" else None


def _existing_reply(run, a):
    """What a repeated call in the same request gets: the stored result or an explicit statement. Never a new generation."""
    view = {"flyer_id": run["run_id"], "candidate_id": a["candidate_id"]}
    if a["status"] == "done" and a["outcome"] == "ok":
        s = _flyer_summary(run, a)
        if s["status"] == "storage_failure":   # generated and counted earlier; the stored file is bad: say so, never regenerate
            return research._fail("artifact_integrity_failed", s["error"], hint="Report that the saved flyer image is damaged or missing; do not try to generate again.", **view,
                                  status="storage_failure", outcome="ok", integrity=s["integrity"])
        return {"ok": True, "cached": True, **view, "status": s["status"], "image": s["image"], "retrieve": f"/api/flyers/{run['run_id']}", "note": UNCHECKED_NOTE,
                "attempts": {"used": 1, "enabled": ATTEMPTS_ENABLED, "final_max": ATTEMPTS_FINAL_MAX},
                "why": "This request already generated its flyer; the stored result is returned and nothing was generated or spent again."}
    if a["status"] == "done":
        return research._fail("attempt_already_consumed", f"This request's generation attempt already ended with {a['outcome']!r}" + (f" ({a['error']})" if a["error"] else "") +
                              ". It consumed the attempt and was NOT repeated; no second attempt is available until the reviewed correction path exists.",
                              hint="Report this outcome to the user; do not try to generate again.", **view, status="failed", outcome=a["outcome"])
    return research._fail("generation_outcome_unknown", "A generation attempt for this request was reserved" + (" and sent" if a["status"] == "dispatched" else "") +
                          " but no outcome is recorded: it is still running in this request or was interrupted. It was NOT repeated and may or may not have been charged.",
                          hint="Report that the outcome is uncertain; do not try to generate again in this request.", **view, status="in_progress_or_unknown")


def generate(agent_id, args):
    ag, e = _prepare(agent_id, "generate_flyer", args)
    if e:
        return e
    rid = getattr(turn_state, "request_id", None)
    if not rid:
        return research._fail("no_manual_request", "Flyer generation runs only inside a manual user request; none is active.")
    prior = _existing(agent_id, rid)
    if prior:   # this request already used its attempt: whatever the arguments, the answer is the stored outcome (no credentials or network needed)
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
    request = {"endpoint": ENDPOINT, "model": cfg["model"], "aspect_ratio": ASPECT, "image_size": cfg["size"], "mime_type": OUT_MIME, "delivery": "inline", "store": False,
               "input_images": len(inputs), "timeout_s": TIMEOUT_S, "retries": 0}
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
    cand, run_id = a["candidate_id"], a["run_id"]
    # 6. ONE send (the slot is already consumed whatever happens next)
    payload = {"model": cfg["model"],
               "input": [{"type": "text", "text": context_text}] + [{"type": "image", "mime_type": i["mime_type"], "data": base64.b64encode(i["_raw"]).decode("ascii")} for i in inputs],
               "response_format": {"type": "image", "aspect_ratio": ASPECT, "image_size": cfg["size"], "mime_type": OUT_MIME, "delivery": "inline"}, "store": False}
    _update(cand, status="dispatched", dispatched_at=time.time())
    t0 = time.perf_counter()
    try:
        status, body = _post(cfg["base"] + ENDPOINT, key, payload, research.diag().tls_context())
    except Exception as ex:   # timeout, DNS, TLS, connection lost: the provider may have processed it -> outcome unknown, slot consumed, never replayed
        why = _clean(f"{type(ex).__name__}: {ex}", key, 200)
        _finish(cand, "network_error", error=why, ms=round((time.perf_counter() - t0) * 1000))
        return research._fail("generation_outcome_unknown", f"The request was sent but no usable answer came back ({why}). It may or may not have been processed and charged; "
                              "the attempt is consumed and was NOT repeated.", hint="Report that the outcome is unknown; do not try again.", flyer_id=run_id, candidate_id=cand, status="failed")
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
                              hint="Report this failure honestly; no flyer exists.", flyer_id=run_id, candidate_id=cand, status="failed", outcome=outcome)
    # 7. store privately, then record (a file or database fault after a paid success is reported as exactly that)
    try:
        folder = flyer_dir(run_id)
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{cand}.{info['ext']}"
        tmp = folder / f"{name}.{os.getpid()}.tmp"
        tmp.write_bytes(raw)
        os.replace(tmp, folder / name)
        _finish(cand, "ok", out_path=name, out_sha256=info["sha256"], out_bytes=info["bytes"], out_width=info["width"], out_height=info["height"], out_mime=info["mime_type"],
                **common)
        with core.db() as d:
            d.execute("UPDATE flyer_runs SET final_candidate_id=? WHERE run_id=?", (cand, run_id))
    except Exception as ex:
        try:
            _finish(cand, "ok_unsaved", error=_clean(f"{type(ex).__name__}: {ex}", key, 200), **common)
        except Exception:
            pass
        return research._fail("storage_error", "The flyer was generated (and counted) but could not be saved locally, so it cannot be used. It was NOT generated again.",
                              hint="Report this local storage fault as a blocker.", flyer_id=run_id, candidate_id=cand, status="failed")
    return {"ok": True, "flyer_id": run_id, "candidate_id": cand, "status": CONTENT_STATUS, "note": UNCHECKED_NOTE, "retrieve": f"/api/flyers/{run_id}",
            "image": {"url": f"/api/flyers/images/{run_id}", "width": info["width"], "height": info["height"], "mime_type": info["mime_type"], "sha256": info["sha256"],
                      "bytes": info["bytes"]},
            "inputs": [{"image_id": i["image_id"], "sha256": i["sha256"]} for i in inputs], "model": cfg["model"], "usage": meta.get("usage"), "ms": ms,
            "attempts": {"used": 1, "enabled": ATTEMPTS_ENABLED, "final_max": ATTEMPTS_FINAL_MAX}}


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
