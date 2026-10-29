"""Facebook image-ad research (V2-03): backend-owned tools a granted social_media specialist uses inside ONE manual chat request, and the persisted
research package it saves. The specialist decides what to search, which ads to look at and which images to inspect; this module only provides
reliable tools, permissions, finite budgets and persistence. It is independent of Marketplace research (app/research.py): separate tables,
separate allowance, separate image store; Marketplace evidence can never be presented as ad evidence and vice versa.

Trust and budget rules (enforced HERE, never by the model):
- Identity: the agent comes from the worker's environment and the request from the backend (turn_state.request_id). One run per (agent, request),
  opened lazily; the model cannot name, reuse or open runs. Only a registered agent whose ROLE is social_media and whose stored grants include the tool
  may call it.
- Inputs: structured query text and numbers returned earlier by the backend (ad_no, advertiser_no, image_no). No URL, page id, credential, country,
  date or budget argument exists; US and the image-ad media type are fixed by the backend.
- Allowance: per manual request (default 8 scraper attempts, 4 image downloads) inside a per-scope total. An attempt is reserved in ONE atomic SQLite
  transaction BEFORE it is sent; failed and unknown attempts count. Identical successful requests are answered from the run store; an identical request
  whose outcome is unknown (or whose result could not be saved) is refused, never re-sent. No transport retries exist anywhere in this module.
- Transport: API redirects are never followed (the credential cannot be forwarded); CDN image redirects are followed only to allow-listed hosts
  (<=3 hops, no HTTPS downgrade), no credential is attached to a download, TLS verification stays on. Signed CDN URLs never leave the backend.
- Reach: reported only from provider fields whose meaning is documented (Meta's eu_total_reach, EU geography). Anything else that looks like reach is
  ambiguous and stays unknown. Impressions, spend, likes and run duration are never reach. Ranking is a backend-computed gate that needs the SAME
  documented metric, the SAME geography and an ESTABLISHED, equal measurement period (REACH_PERIOD_FIELD); ad start/end dates are never a period. Its
  absence disables ranking only.
- Platform: only ads that can run on Facebook qualify. A known platform list that does not include Facebook excludes the ad (search and detail alike); a
  missing list stays 'unknown' and is never filled in.
- Inspections: an ad image counts as inspected only by an inspection bound to THIS request and run (image_inspections.request_id/run_id).
"""
import json, os, re, time, urllib.parse, uuid
from app import core, research, turn_state

COUNTRY = "US"                       # fixed: no geography change to obtain a metric
SOURCE = "ScrapeCreators Facebook Ad Library (live research run)"
ENDPOINTS = {"advertiser": "/v1/facebook/adLibrary/search/companies", "company": "/v1/facebook/adLibrary/company/ads",
             "keyword": "/v1/facebook/adLibrary/search/ads", "detail": "/v1/facebook/adLibrary/ad"}
ACCOUNTING = {"advertiser": "advertiser", "company": "search", "keyword": "search", "detail": "detail", "image": "image"}
API_KINDS = ("advertiser", "search", "detail")
DEFAULTS = {"run_api": 8, "run_images": 4, "scope_api": 40, "scope_images": 20}   # per manual request / per scope (ECOM_ADS_*), see _env_int callers
SCOPE_DEFAULT = "default"
MEDIA_TYPES = ("IMAGE_AND_MEME", "IMAGE", "MEME")   # "meme" in the Ad Library means an ad with text and an image
# The provider/Meta field that states WHEN eu_total_reach was measured. None = no documented field exists (checked 2026-10-12: Meta's archived-ad reference and the
# ScrapeCreators ad/search examples name none), so no period is ever established and reach ranking stays off. If a documented field appears, name it here (read from
# aaa_info) and the gate compares only values that state the same period. Never infer it from start_date/end_date.
REACH_PERIOD_FIELD = None
MAX_ROWS = 25
ARGS = {"fb_ads_find_advertiser": {"query"},
        "fb_ads_search": {"query", "advertiser_no", "status", "order", "next_page"},
        "fb_ad_detail": {"ad_no"},
        "fb_ad_image": {"ad_no", "image_no"},
        "save_ad_research": {"summary", "selection_basis", "references", "blocker", "limitations"},
        "read_ad_research": {"package_id"}}
_EFFECT = re.compile(r"\b(effective(ness)?|performs?|performed|performing|high[- ]performing|successful(ly)?|proven|converts?|converted|converting|roi|"
                     r"works? well|worked well|drives? sales|drove sales)\b", re.I)


def _iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)) if isinstance(ts, (int, float)) else None


def _pkey(params):
    return json.dumps(params, sort_keys=True, ensure_ascii=False)


# ---------------- runs and allowance ----------------
def _allowance_row(c, scope):
    row = c.execute("SELECT * FROM ad_allowance WHERE scope=?", (scope,)).fetchone()
    if row is None:   # first use of a scope: caps come from configuration ONCE; an existing row is never re-sized from the environment
        c.execute("INSERT OR IGNORE INTO ad_allowance(scope, api_max, image_max, api_used, image_used, created_at) VALUES(?,?,?,0,0,?)",
                  (scope, research._env_int("ECOM_ADS_API_MAX", DEFAULTS["scope_api"]), research._env_int("ECOM_ADS_IMAGE_MAX", DEFAULTS["scope_images"]), time.time()))
        row = c.execute("SELECT * FROM ad_allowance WHERE scope=?", (scope,)).fetchone()
    return row


def _media_type():
    v = (os.environ.get("ECOM_ADS_MEDIA_TYPE") or MEDIA_TYPES[0]).upper()
    return v if v in MEDIA_TYPES else MEDIA_TYPES[0]


def open_run(agent_id, request_id):
    """Get or create THE run of this (agent, request). The pair is backend-supplied; there is no way to ask for another run."""
    c = core.db()
    try:
        research._begin_immediate(c)
        row = c.execute("SELECT * FROM ad_runs WHERE agent_id=? AND request_id=?", (agent_id, request_id)).fetchone()
        if row is None:
            scope = os.environ.get("ECOM_ADS_SCOPE") or SCOPE_DEFAULT
            _allowance_row(c, scope)
            ag = c.execute("SELECT conversation_id FROM agents WHERE agent_id=?", (agent_id,)).fetchone()
            msg = c.execute("SELECT id FROM messages WHERE agent_id=? AND who='user' ORDER BY id DESC LIMIT 1", (agent_id,)).fetchone()
            rid = "adrun-" + uuid.uuid4().hex[:10]
            c.execute("INSERT INTO ad_runs(run_id, agent_id, company_id, company_name, conversation_id, request_id, message_id, scope, api_max, image_max, "
                      "media_type, country, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (rid, agent_id, core.COMPANY_ID, core.load_company().get("name") or None, ag["conversation_id"] if ag else None, request_id,
                       msg["id"] if msg else None, scope, research._env_int("ECOM_ADS_RUN_API_MAX", DEFAULTS["run_api"]),
                       research._env_int("ECOM_ADS_RUN_IMAGE_MAX", DEFAULTS["run_images"]), _media_type(), COUNTRY, time.time()))
            row = c.execute("SELECT * FROM ad_runs WHERE run_id=?", (rid,)).fetchone()
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
        r = d.execute("SELECT * FROM ad_runs WHERE agent_id=? AND request_id=?", (agent_id, request_id)).fetchone()
    return dict(r) if r else None


def allowance_view(run_id):
    with core.db() as d:
        r = d.execute("SELECT * FROM ad_runs WHERE run_id=?", (run_id,)).fetchone()
        if not r:
            return None
        a = d.execute("SELECT * FROM ad_allowance WHERE scope=?", (r["scope"],)).fetchone()
        used_api = d.execute("SELECT COUNT(*) FROM ad_calls WHERE run_id=? AND kind IN ('advertiser','search','detail')", (run_id,)).fetchone()[0]
        used_img = d.execute("SELECT COUNT(*) FROM ad_calls WHERE run_id=? AND kind='image'", (run_id,)).fetchone()[0]
    return {"scope": r["scope"], "api_attempts_left": max(0, min(r["api_max"] - used_api, a["api_max"] - a["api_used"])),
            "image_downloads_left": max(0, min(r["image_max"] - used_img, a["image_max"] - a["image_used"])),
            "run_api_attempts": used_api, "run_image_downloads": used_img, "run_api_max": r["api_max"], "run_image_max": r["image_max"],
            "scope_api_used": a["api_used"], "scope_api_max": a["api_max"], "scope_images_used": a["image_used"], "scope_images_max": a["image_max"]}


def _begin_call(run, kind, endpoint, params):
    """Dedupe + reserve in ONE transaction. -> ("cached", call_row) | ("error", dict) | ("go", call_id)."""
    key = _pkey({"endpoint": endpoint, **params})
    images = kind == "image"
    c = core.db()
    try:
        research._begin_immediate(c)
        prev = c.execute("SELECT * FROM ad_calls WHERE run_id=? AND params_key=? ORDER BY id DESC", (run["run_id"], key)).fetchall()
        for p in prev:
            if p["status"] == "done" and p["outcome"] == "ok":
                c.commit()
                return "cached", dict(p)
        for p in prev:   # an identical request whose outcome is unknown, unsaved or the wrong ad must not be re-sent (it was processed and may have been charged)
            if p["status"] != "done" or p["outcome"] == "network_error":
                c.commit()
                return "error", research._fail("uncertain_previous_attempt",
                                               f"An identical {kind} request was already sent in this run and its outcome is unknown ({p['outcome'] or 'no outcome recorded'}). "
                                               "It was NOT repeated and nothing was spent.", hint="Change the request, use what you already have, or report this as a blocker.")
            if p["outcome"] == "ok_unsaved":
                c.commit()
                return "error", research._fail("storage_error", f"An identical {kind} request already SUCCEEDED in this run but its result could not be saved locally. "
                                               "It was NOT repeated and nothing was spent.", hint="Use the evidence you already have or report this local storage fault as a blocker.")
            if p["outcome"] == "identity_mismatch":
                c.commit()
                return "error", research._fail("ad_identity_mismatch", "An identical ad detail request already returned a DIFFERENT ad's details in this run. It was NOT repeated.",
                                               hint="Do not use details for this ad; work with other ads or report the blocker.")
        r = c.execute("SELECT * FROM ad_runs WHERE run_id=?", (run["run_id"],)).fetchone()
        a = _allowance_row(c, r["scope"])
        if images:
            used_run = c.execute("SELECT COUNT(*) FROM ad_calls WHERE run_id=? AND kind='image'", (run["run_id"],)).fetchone()[0]
            run_cap, scope_used, scope_cap, what = r["image_max"], a["image_used"], a["image_max"], "ad image download"
        else:
            used_run = c.execute("SELECT COUNT(*) FROM ad_calls WHERE run_id=? AND kind IN ('advertiser','search','detail')", (run["run_id"],)).fetchone()[0]
            run_cap, scope_used, scope_cap, what = r["api_max"], a["api_used"], a["api_max"], "ScrapeCreators ad request"
        if used_run >= run_cap or scope_used >= scope_cap:
            c.commit()
            which = "this request's" if used_run >= run_cap else f"the {r['scope']!r} scope's"
            return "error", research._fail("allowance_exhausted", f"The {what} allowance is exhausted ({which} limit: {run_cap if used_run >= run_cap else scope_cap}). "
                                           "Nothing was sent. The allowance cannot be raised from here.",
                                           hint="Work only with the evidence you already collected, save an honest partial package if it supports one, or report the blocker.")
        col = "image_used" if images else "api_used"
        c.execute(f"UPDATE ad_allowance SET {col}={col}+1 WHERE scope=?", (r["scope"],))
        cur = c.execute("INSERT INTO ad_calls(run_id, kind, endpoint, params, params_key, status, ts) VALUES(?,?,?,?,?,?,?)",
                        (run["run_id"], kind, endpoint, _pkey(params), key, "reserved", time.time()))
        c.commit()
        return "go", cur.lastrowid
    except BaseException:
        c.rollback()
        raise
    finally:
        c.close()


def _finish_call(call_id, outcome, status=None, error=None, result=None, credits=None, remaining=None, ms=None):
    with core.db() as d:
        d.execute("UPDATE ad_calls SET status='done', outcome=?, http_status=?, error=?, result=?, credits_charged=?, credits_remaining=?, ms=? WHERE id=?",
                  (outcome, status, (error or None) and str(error)[:300], json.dumps(result) if result is not None else None, credits, remaining, ms, call_id))


# ---------------- provider transport and response shape ----------------
def _rows(endpoint, data):
    keys = {"advertiser": ("searchResults",), "company": ("results", "searchResults"), "keyword": ("searchResults", "results")}[endpoint]
    for k in keys:
        if isinstance(data.get(k), list):
            return data[k]
    return None


def _shape_problem(endpoint, data):
    if endpoint == "detail":
        return None if any(data.get(k) for k in ("adArchiveID", "ad_archive_id", "adArchiveId", "url", "snapshot", "pageName")) else "no ad fields (id, url, snapshot or page name) present"
    rows = _rows(endpoint, data)
    if rows is None:
        return "the documented result list is missing or not an array"
    if any(not isinstance(x, dict) for x in rows):
        return "the result list contains an entry that is not an object"
    return None


def _classify(endpoint, status, body, key):
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        data = None
    msg = ""
    if isinstance(data, dict):
        msg = str(data.get("error") or data.get("message") or "")[:200]
        msg = msg.replace(key, "***") if key else msg
    if status == 200:
        if not isinstance(data, dict):
            return "bad_response", "malformed response: response was not a JSON object", None
        if data.get("success") not in (None, True) or data.get("error"):
            return "provider_error", msg or "provider reported a failure in a 200 response", data
        why = _shape_problem(endpoint, data)
        return ("bad_response", f"malformed response: {why}", data) if why else ("ok", None, data)
    if 300 <= status < 400:
        return "redirect_refused", f"the provider answered with a redirect (HTTP {status}); redirects are never followed, so the API credential is not sent elsewhere", None
    k = {400: "bad_request", 401: "auth_failed", 403: "auth_failed", 402: "credits_or_rate_limit", 429: "credits_or_rate_limit", 404: "not_found"}.get(status)
    return (k or ("provider_error" if status >= 500 else "http_error")), (msg or f"HTTP {status}"), data


def _api(run, endpoint, params):
    """One counted, never-repeated provider request. -> ("ok", (data, status, credits, remaining, ms), call_id) | ("cached", row, None) | ("error", errdict, call_id)."""
    d = research.diag()
    key = d.get_key()
    if not key:
        return "error", research._fail("missing_credentials", "The ScrapeCreators API key is not configured on the backend, so no ad request was sent.",
                                       hint="Tell the user that ad research needs SCRAPECREATORS_API_KEY in secrets/local.env."), None
    kind = ACCOUNTING[endpoint]
    state, v = _begin_call(run, kind, endpoint, params)
    if state == "cached":
        return "cached", v, None
    if state == "error":
        return "error", v, None
    call_id = v
    url = research.api_base() + ENDPOINTS[endpoint] + "?" + urllib.parse.urlencode(params)
    t0 = time.perf_counter()
    try:
        status, body, _ct = d.api_get(url, {"x-api-key": key, "Accept": "application/json", "User-Agent": "ecom-agents-ads/1"}, 60, d.tls_context())   # never follows redirects
    except Exception as e:   # timeout, DNS, TLS: outcome unknown (the provider may have processed it): never retried
        ms = round((time.perf_counter() - t0) * 1000)
        why = f"{type(e).__name__}: {e}"[:200].replace(key, "***")
        _finish_call(call_id, "network_error", error=why, ms=ms)
        return "error", research._fail("network_error", f"The request was sent but no usable answer came back ({why}). It was counted and will not be repeated.",
                                       hint="Do not assume it succeeded; use other evidence or report the blocker."), call_id
    ms = round((time.perf_counter() - t0) * 1000)
    outcome, why, data = _classify(endpoint, status, body, key)
    credits = remaining = None
    if isinstance(data, dict):
        credits, remaining = data.get("credits_charged"), data.get("credits_remaining")
    if outcome != "ok":
        _finish_call(call_id, outcome, status=status, error=why, credits=credits, remaining=remaining, ms=ms)
        return "error", research._fail("provider_error" if outcome in ("provider_error", "http_error") else outcome,
                                       f"ScrapeCreators {endpoint} request failed: {why}" + (f" (HTTP {status})" if status else "") + ". The attempt was counted and not repeated.",
                                       hint="Do not invent results. Try a different request or report the blocker."), call_id
    return "ok", (data, status, credits, remaining, ms), call_id


# ---------------- normalisation (only what the provider returned; absent stays None) ----------------
def _now():
    return research._now()


def _pick(raw, *names):
    for n in names:
        if raw.get(n) not in (None, ""):
            return raw[n]
    return None


def _txt(v, n):
    if isinstance(v, dict):
        v = v.get("text")
    if isinstance(v, list):
        v = " ".join(str(x.get("text") if isinstance(x, dict) else x) for x in v if x)
    return " ".join(v.split())[:n] if isinstance(v, str) and v.strip() else None


def _id(v):
    if isinstance(v, bool) or v in (None, ""):
        return None
    if isinstance(v, float) and v == int(v):
        v = int(v)
    s = str(v).strip()
    return s if re.fullmatch(r"\d{1,24}", s) else None


def _date(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
        return None
    try:
        return time.strftime("%Y-%m-%d", time.gmtime(v))
    except (OverflowError, OSError, ValueError):
        return None


def _ref(x):
    """The best image reference of an image/card object (or a plain URL string)."""
    if isinstance(x, str):
        return x if x.startswith("http") else None
    if isinstance(x, dict):
        for k in ("original_image_url", "resized_image_url", "watermarked_resized_image_url", "image_url", "url"):
            if isinstance(x.get(k), str) and x[k].startswith("http"):
                return x[k]
    return None


def _key(ref):
    p = urllib.parse.urlparse(ref)
    return (p.hostname or "").lower() + p.path


def ad_id_from_url(url):
    if not isinstance(url, str):
        return None
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    return _id((q.get("id") or [None])[0])


def norm_ad(raw, endpoint, call_id, now):
    snap = raw.get("snapshot") if isinstance(raw.get("snapshot"), dict) else {}
    aid = _id(_pick(raw, "ad_archive_id", "adArchiveID", "adArchiveId"))
    images, seen = [], set()

    def add(ref, source):
        if ref and _key(ref) not in seen:
            seen.add(_key(ref))
            images.append({"image_no": len(images) + 1, "ref": ref, "key": _key(ref), "source": source})
    for i, im in enumerate(snap.get("images") or []):
        add(_ref(im), f"images[{i}]")
    for i, im in enumerate(snap.get("extra_images") or []):
        add(_ref(im), f"extra_images[{i}]")
    cards = []
    for i, cd in enumerate(snap.get("cards") or []):
        if isinstance(cd, dict):
            ref = _ref(cd)
            add(ref, f"cards[{i}]")
            cards.append({"card_no": len(cards) + 1, "title": _txt(cd.get("title"), 160), "body": _txt(cd.get("body"), 300),
                          "cta_text": _txt(cd.get("cta_text"), 60), "image_key": _key(ref) if ref else None})
    fmt = _txt(snap.get("display_format"), 40)
    video = bool((fmt or "").upper() == "VIDEO" or snap.get("videos"))
    imp = _pick(raw, "impressions_with_index", "impressionsWithIndex")
    other = {}
    if isinstance(imp, dict):
        if imp.get("impressions_text") not in (None, ""):
            other["impressions_text"] = imp["impressions_text"]
        if isinstance(imp.get("impressions_index"), (int, float)) and not isinstance(imp["impressions_index"], bool) and imp["impressions_index"] >= 0:
            other["impressions_index"] = imp["impressions_index"]
    if raw.get("spend") not in (None, ""):
        other["spend"], other["currency"] = raw["spend"], raw.get("currency")
    aaa = raw.get("aaa_info") if isinstance(raw.get("aaa_info"), dict) else raw.get("aaaInfo") if isinstance(raw.get("aaaInfo"), dict) else {}
    reach = {}
    if _pick(raw, "reach_estimate", "reachEstimate") is not None:
        reach["reach_estimate"] = _pick(raw, "reach_estimate", "reachEstimate")
    if aaa.get("eu_total_reach") not in (None, ""):
        reach["eu_total_reach"] = aaa["eu_total_reach"]
    if aaa.get("age_country_gender_reach_breakdown") or raw.get("age_country_gender_reach_breakdown"):
        reach["breakdown_present"] = True
    if REACH_PERIOD_FIELD and aaa.get(REACH_PERIOD_FIELD) not in (None, ""):   # only a DOCUMENTED period field; ad start/end dates are never a measurement window
        reach["period"] = str(aaa[REACH_PERIOD_FIELD])[:60]
    plats = _pick(raw, "publisher_platform", "publisherPlatform")
    link = snap.get("link_url") if isinstance(snap.get("link_url"), str) else None
    active = _pick(raw, "is_active", "isActive")
    return {"ad_archive_id": aid, "source_url": f"https://www.facebook.com/ads/library?id={aid}" if aid else None,
            "advertiser": {"page_id": _id(_pick(raw, "page_id", "pageID", "pageId")), "name": _txt(_pick(raw, "page_name", "pageName") or snap.get("page_name"), 120)},
            "active": active if isinstance(active, bool) else None, "start_date": _date(_pick(raw, "start_date", "startDate")), "end_date": _date(_pick(raw, "end_date", "endDate")),
            "display_format": fmt, "platforms": [str(x)[:30] for x in plats][:12] if isinstance(plats, list) else None,
            "text": _txt(snap.get("body"), 1500), "title": _txt(snap.get("title"), 200), "caption": _txt(snap.get("caption"), 200),
            "link_description": _txt(snap.get("link_description"), 300), "cta_text": _txt(snap.get("cta_text"), 60), "cta_type": _txt(snap.get("cta_type"), 40),
            "landing_url": link[:400] if link else None, "images": images, "cards": cards,
            "campaign": {"campaign_id": _id(_pick(raw, "collation_id", "collationID", "collationId")),
                         "campaign_ad_count": next((x for x in (_pick(raw, "collation_count", "collationCount"),) if isinstance(x, int) and not isinstance(x, bool)), None)},
            "countries": [str(x)[:3] for x in _pick(raw, "targeted_or_reached_countries", "targetedOrReachedCountries")][:30]
                          if isinstance(_pick(raw, "targeted_or_reached_countries", "targetedOrReachedCountries"), list) else None,
            "reach_raw": reach, "other_metrics": other, "excluded": "video" if video else None,
            "detail_level": "detailed" if endpoint == "detail" else "list_only", "identity": None,
            "retrieved_at": now, "sources": [{"endpoint": endpoint, "call_id": call_id, "at": now}]}


def _merge(old, new):
    """Field-level merge: a later partial record never erases a known value; images/cards are unioned (existing image numbers are stable)."""
    out = dict(old)
    for k, v in new.items():
        if k in ("images", "cards"):
            continue
        if k in ("reach_raw", "other_metrics", "campaign", "advertiser"):
            out[k] = {**(old.get(k) or {}), **{a: b for a, b in (v or {}).items() if b is not None}}
        elif k == "sources":
            out[k] = (old.get(k) or []) + v
        elif k == "detail_level":
            out[k] = "detailed" if "detailed" in (old.get(k), v) else v
        elif v not in (None, "", [], {}):
            out[k] = v
    imgs = [dict(i) for i in old.get("images") or []]
    by_key = {i["key"]: i for i in imgs}
    for i in new.get("images") or []:
        if i["key"] in by_key:
            by_key[i["key"]]["ref"] = i["ref"]   # newest signed URL; the number and any registered image stay
        else:
            imgs.append({**i, "image_no": len(imgs) + 1})
            by_key[i["key"]] = imgs[-1]
    out["images"] = imgs
    out["cards"] = new.get("cards") or old.get("cards") or []
    return out


def exclusion(rec):
    """Why a recorded ad is NOT an eligible Facebook image-ad reference, or None: 'video' | 'not_on_facebook'. Derived from the record's CURRENT fields, so a later search
    or detail response that names the ad's platforms applies to an ad recorded earlier. A missing/empty platform list is unknown and does not exclude."""
    if rec.get("excluded") == "video":
        return "video"
    plats = rec.get("platforms")
    if isinstance(plats, list) and plats and not any("FACEBOOK" in str(p).upper() for p in plats):
        return "not_on_facebook"
    return None


def platform_status(rec):
    if exclusion(rec) == "not_on_facebook":
        return "excluded_not_on_facebook"
    plats = rec.get("platforms")
    return "facebook" if isinstance(plats, list) and plats else "unknown"


def _ineligible(no, rec, field="ad_no"):
    """The refusal for an ad that cannot be fetched or selected, or None."""
    ex = exclusion(rec)
    if ex == "not_on_facebook":
        return research._fail("ad_not_on_facebook", f"Ad {no} is not delivered on Facebook (its listed platforms: {', '.join(rec.get('platforms') or [])}). Only Facebook image ads are "
                              "researched; it was excluded and nothing was substituted.", field, hint="Work with other ads, or report that none qualified.")
    if ex == "video":
        return research._fail("not_an_image_ad", f"Ad {no} turned out to be a video ad. Only image ads are researched.", field)
    return None


def reach_view(rec):
    """What the backend can honestly say about ONE ad's reach. Reported only for a provider field with a documented meaning and geography."""
    raw = rec.get("reach_raw") or {}
    eu, est = raw.get("eu_total_reach"), raw.get("reach_estimate")
    period = raw.get("period") or None

    def num(v):
        if isinstance(v, bool):
            return None
        if isinstance(v, (int, float)) and v >= 0:
            return v
        return float(v) if isinstance(v, str) and re.fullmatch(r"\d+(\.\d+)?", v.strip()) else None
    if num(eu) is not None:
        return {"state": "reported", "metric": "eu_total_reach", "value": num(eu), "geography": "EU", "period": period, "source": "provider field aaa_info.eu_total_reach",
                "meaning": "Meta's estimated combined reach across EU locations, available only for ads delivered in the EU. It is NOT US reach. "
                           + (f"Measurement period: {period}." if period else "Measurement period not stated."),
                "comparable_with": ("other ads' eu_total_reach that state the same measurement period" if period else
                                    "nothing: the measurement period is unknown, so it cannot be shown to cover the same period as another ad's value")}
    if eu is not None or est is not None:
        f, v = ("eu_total_reach", eu) if eu is not None else ("reach_estimate", est)
        return {"state": "ambiguous", "metric": f, "value": None, "provider_value": v, "geography": None, "period": None, "source": f"provider field {f}",
                "meaning": "The provider does not define this value (Meta documents reach only for EU/UK ads and political/issue ads), so its metric, period and geography "
                           "are unknown. It is preserved but never used to rank or compare."}
    return {"state": "unavailable", "metric": None, "value": None, "geography": None, "period": None, "source": "not_provided",
            "meaning": "No reach value was provided for this ad. That is unknown, not zero."}


def reach_gate(recs):
    recs = [r for r in recs if not exclusion(r)]   # an ad that is not an eligible Facebook ad contributes nothing, not even a reach value
    views = [reach_view(r) for r in recs]
    rep = [v for v in views if v["state"] == "reported"]
    amb = sum(1 for v in views if v["state"] == "ambiguous")
    metrics = {(v["metric"], v["geography"]) for v in rep}
    periods = {v["period"] for v in rep}
    period = None
    if len(rep) >= 2 and len(metrics) > 1:
        state, why = "disabled_incompatible_metrics", "Reported reach values have different metrics or geographies and are not comparable."
    elif len(rep) >= 2 and None in periods:
        state, why = "disabled_period_unknown", ("Reported reach values share a metric and geography, but the measurement period of at least one is not stated, so they cannot be shown to "
                                                 "cover comparable periods. Ad start and end dates are not a measurement period. The values are kept; ranking stays off.")
    elif len(rep) >= 2 and len(periods) > 1:
        state, why = "disabled_incompatible_metrics", "Reported reach values state different measurement periods and are not comparable."
    elif len(rep) >= 2:
        period = next(iter(periods))
        state, why = "enabled", ("Ranking may use the reported value among the ads that carry it, only: same metric (eu_total_reach), geography (EU) and stated measurement period. It is "
                                 "exposure in the EU, not US reach and not evidence of sales or effectiveness; relevance to the merchant's product and audience still comes first.")
    elif len(rep) == 1:
        state, why = "disabled_single_value", "Only one ad carries a reported reach value, so there is nothing to compare it with."
    elif amb:
        state, why = "disabled_reach_ambiguous", "Some ads carry a value that looks like reach but whose meaning, period and geography are undefined; it stays unknown."
    else:
        state, why = "disabled_reach_unavailable", "No ad carries a reach value. Reach is unknown (not zero): select by relevance and say that reach ranking was unavailable."
    return {"state": state, "ranking_enabled": state == "enabled", "metric": next(iter(metrics))[0] if state == "enabled" else None,
            "geography": next(iter(metrics))[1] if state == "enabled" else None, "period": period, "ads_recorded": len(recs), "ads_with_reported_reach": len(rep),
            "ads_with_ambiguous_reach": amb, "reason": why,
            "rule": "Never substitute impressions, spend, likes, ad duration, audience size or search order for reach; reach is not proof of sales."}


# ---------------- run store ----------------
def _load_ads(run_id):
    with core.db() as d:
        rows = d.execute("SELECT ad_no, ad_archive_id, record FROM ad_records WHERE run_id=? ORDER BY ad_no", (run_id,)).fetchall()
    return {r["ad_no"]: json.loads(r["record"]) for r in rows}


def _registered(run_id):
    with core.db() as d:
        rows = d.execute("SELECT * FROM ad_images WHERE run_id=?", (run_id,)).fetchall()
    return {(r["ad_archive_id"], r["image_no"]): dict(r) for r in rows}


def _store_ads(run_id, call_id, recs):
    """Insert/merge records in ONE immediate transaction (ad_no allocation is atomic). -> ad_nos in input order."""
    c = core.db()
    try:
        research._begin_immediate(c)
        nos = []
        for rec in recs:
            row = c.execute("SELECT ad_no, record FROM ad_records WHERE run_id=? AND ad_archive_id=?", (run_id, rec["ad_archive_id"])).fetchone()
            if row:
                merged = _merge(json.loads(row["record"]), rec)
                c.execute("UPDATE ad_records SET record=?, retrieved_at=? WHERE run_id=? AND ad_no=?", (json.dumps(merged), rec["retrieved_at"], run_id, row["ad_no"]))
                nos.append(row["ad_no"])
            else:
                n = c.execute("SELECT COALESCE(MAX(ad_no),0)+1 FROM ad_records WHERE run_id=?", (run_id,)).fetchone()[0]
                c.execute("INSERT INTO ad_records(run_id, ad_no, ad_archive_id, record, first_call, retrieved_at) VALUES(?,?,?,?,?,?)",
                          (run_id, n, rec["ad_archive_id"], json.dumps(rec), call_id, rec["retrieved_at"]))
                nos.append(n)
        c.commit()
        return nos
    except BaseException:
        c.rollback()
        raise
    finally:
        c.close()


def _store_advertisers(run_id, call_id, rows):
    c = core.db()
    try:
        research._begin_immediate(c)
        nos = []
        for r in rows:
            row = c.execute("SELECT advertiser_no FROM ad_advertisers WHERE run_id=? AND page_id=?", (run_id, r["page_id"])).fetchone()
            if row:
                nos.append(row["advertiser_no"])
                continue
            n = c.execute("SELECT COALESCE(MAX(advertiser_no),0)+1 FROM ad_advertisers WHERE run_id=?", (run_id,)).fetchone()[0]
            c.execute("INSERT INTO ad_advertisers(run_id, advertiser_no, page_id, record, first_call) VALUES(?,?,?,?,?)", (run_id, n, r["page_id"], json.dumps(r), call_id))
            nos.append(n)
        c.commit()
        return nos
    except BaseException:
        c.rollback()
        raise
    finally:
        c.close()


def _advertiser(run_id, no):
    with core.db() as d:
        r = d.execute("SELECT * FROM ad_advertisers WHERE run_id=? AND advertiser_no=?", (run_id, no)).fetchone()
    return json.loads(r["record"]) | {"page_id": r["page_id"], "advertiser_no": r["advertiser_no"]} if r else None


def _campaigns(recs_by_no):
    groups = {}
    for no, r in recs_by_no.items():
        cid = (r.get("campaign") or {}).get("campaign_id")
        if cid:
            groups.setdefault(cid, []).append(no)
    return groups


def public_ad(no, rec, regs=None, groups=None, full=True):
    """The model-/API-facing view of one ad: public source link and normalised content; never a signed CDN URL or landing-page query."""
    regs = regs or {}
    cid = (rec.get("campaign") or {}).get("campaign_id")
    imgs = [{"image_no": i["image_no"], "from": i["source"], "image_id": (regs.get((rec["ad_archive_id"], i["image_no"])) or {}).get("image_id")} for i in rec.get("images") or []]
    land = urllib.parse.urlparse(rec.get("landing_url") or "").hostname
    om = rec.get("other_metrics") or {}
    ex = exclusion(rec)
    out = {"ad_no": no, "source_ad_id": rec["ad_archive_id"], "source_url": rec.get("source_url"), "platform_status": platform_status(rec),
           "advertiser": {"name": (rec.get("advertiser") or {}).get("name"), "page_id": (rec.get("advertiser") or {}).get("page_id")},
           "active": rec.get("active"), "start_date": rec.get("start_date"), "end_date": rec.get("end_date"), "display_format": rec.get("display_format"),
           "text": (rec.get("text") or "")[:300 if full else 160] or None, "headline": rec.get("title"), "cta": rec.get("cta_text") or rec.get("cta_type"),
           "landing_domain": land, "image_count": len(imgs), "images": imgs, "card_count": len(rec.get("cards") or []),
           "campaign": {"campaign_id": cid, "campaign_ad_count": (rec.get("campaign") or {}).get("campaign_ad_count"),
                        "recorded_ad_nos_in_campaign": sorted((groups or {}).get(cid, [])) if cid else None,
                        "note": "grouping only: each source_ad_id is its own ad; a shared campaign does not prove an identical creative" if cid else None},
           "reach": reach_view(rec), "detail_level": rec.get("detail_level"), "retrieved_at": rec.get("retrieved_at")}
    if ex == "video":
        out["excluded"] = "video ad: not an image ad, no image can be downloaded"
    elif ex:
        out["excluded"] = ("not delivered on Facebook (listed platforms: " + ", ".join(rec.get("platforms") or []) + "): excluded; its image cannot be downloaded or selected "
                           "and no other platform's ad is substituted")
    if not full:   # list view: compact (the meaning/notes appear once per result and in fb_ad_detail), so a 25-ad page stays small
        out["reach"] = {k: v for k, v in out["reach"].items() if k in ("state", "metric", "value", "geography", "provider_value")}
        out["campaign"] = {k: v for k, v in out["campaign"].items() if k != "note"}
        out["images"] = [i["image_no"] for i in imgs]
        out.pop("landing_domain", None)
    if full:
        out["cards"] = [{"card_no": c["card_no"], "title": c.get("title"), "body": c.get("body"), "cta": c.get("cta_text"),
                         "image_no": next((i["image_no"] for i in rec.get("images") or [] if i["key"] == c.get("image_key")), None)} for c in (rec.get("cards") or [])[:8]]
        out["description"] = rec.get("link_description")
        out["platforms"] = rec.get("platforms")
        out["countries_listed"] = rec.get("countries")
        out["identity"] = rec.get("identity")
        if om:
            out["other_metrics"] = {**om, "note": "NOT reach: never use as reach, as a proxy for reach or as a ranking basis"}
    return out


def _with_allowance(out, run):
    out["allowance"] = allowance_view(run["run_id"])
    return out


# ---------------- tool bodies ----------------
def _prepare(agent_id, tool, args, need_run=True):
    """Common gate. -> (run, None) or (None, errdict). Nothing is spent here."""
    if not isinstance(args, dict):
        return None, research._fail("bad_request", "Arguments must be an object.")
    extra = sorted(set(args) - ARGS[tool])
    if extra:
        return None, research._fail("invalid_argument", f"Unsupported argument(s) {extra}. The allowance, run, country, credentials and URLs are controlled by the backend and "
                                    "cannot be set from a tool call.", "arguments", hint=f"Allowed arguments: {sorted(ARGS[tool])}.")
    with core.db() as d:
        ag = d.execute("SELECT role, granted_tools FROM agents WHERE agent_id=?", (agent_id,)).fetchone()
    if not ag:
        return None, research._fail("unknown_agent", f"Ad research needs a registered specialist; {agent_id!r} is not one.")
    if ag["role"] != "social_media":
        return None, research._fail("not_permitted_for_role", f"Facebook ad research is only available to a social_media specialist, not role {ag['role']!r}.")
    if tool not in json.loads(ag["granted_tools"] or "[]"):
        return None, research._fail("not_granted", f"This specialist was not granted {tool}.")
    if not need_run:
        return None, None
    rid = getattr(turn_state, "request_id", None)
    if not rid:
        return None, research._fail("no_manual_request", "Ad research runs only inside a manual user request; none is active.")
    run = open_run(agent_id, rid)
    turn_state.ad_run_id = run["run_id"]
    return run, None


def find_advertiser(agent_id, args):
    run, e = _prepare(agent_id, "fb_ads_find_advertiser", args)
    if e:
        return e
    q, e = research._text(args.get("query"), "query", 2, 100)
    if e:
        return e
    st, v, cid = _api(run, "advertiser", {"query": q})
    if st == "error":
        return _with_allowance(v, run)
    if st == "cached":
        res = json.loads(v["result"])
        return _with_allowance({"ok": True, "cached": True, "query": q, "advertisers": res["advertisers"]}, run)
    data, status, credits, remaining, ms = v
    rows, dropped, seen = [], 0, set()
    for x in _rows("advertiser", data):
        pid = _id(x.get("page_id"))
        if not pid or x.get("page_is_deleted") is True or pid in seen:
            dropped += 1
            continue
        seen.add(pid)
        rows.append({"page_id": pid, "name": _txt(x.get("name"), 120), "category": _txt(x.get("category"), 80),
                     "likes": x.get("likes") if isinstance(x.get("likes"), int) and not isinstance(x.get("likes"), bool) else None,
                     "verification": _txt(x.get("verification"), 40)})
    try:
        nos = _store_advertisers(run["run_id"], cid, rows)
    except Exception as ex:
        _finish_call(cid, "ok_unsaved", status=status, error=f"{type(ex).__name__}: {ex}", credits=credits, remaining=remaining, ms=ms)
        return _with_allowance(research._fail("storage_error", "The advertiser search WAS sent and counted but its results could not be saved, so they cannot be used. "
                                              "It was not repeated.", hint="Report this as a blocker."), run)
    out_rows = [{"advertiser_no": n, **{k: r[k] for k in ("name", "category", "likes", "verification")}} for n, r in zip(nos, rows)][:MAX_ROWS]
    _finish_call(cid, "ok", status=status, result={"advertisers": out_rows, "dropped": dropped}, credits=credits, remaining=remaining, ms=ms)
    out = {"ok": True, "query": q, "advertisers": out_rows, "note": "Pages whose name matches the query; whether one advertises relevant IMAGE ads is for fb_ads_search to show."}
    if not out_rows:
        out.update(empty=True, note="The provider returned no advertiser for this text. Try a different spelling, or search ads by keyword instead.")
    return _with_allowance(out, run)


def _skipped(info, nonfb):
    """What a search page did not offer, and why (disclosed, never silently dropped)."""
    return {k: n for k, n in (("dropped_without_id", info.get("dropped_without_id")), ("duplicates_in_response", info.get("duplicates_in_response")),
                              ("excluded_video_ads", info.get("excluded_video")), ("excluded_non_facebook_ads", nonfb)) if n}


def search(agent_id, args):
    run, e = _prepare(agent_id, "fb_ads_search", args)
    if e:
        return e
    q, adv = args.get("query"), args.get("advertiser_no")
    if (q is None) == (adv is None):
        return research._fail("bad_argument", "Provide exactly one of query (keyword search) or advertiser_no (that advertiser's ads).", "query")
    status = args.get("status", "ACTIVE")
    if status not in ("ACTIVE", "INACTIVE", "ALL"):
        return research._fail("bad_argument", "status must be ACTIVE, INACTIVE or ALL.", "status")
    order = args.get("order", "default")
    if order not in ("default", "most_recent"):
        return research._fail("bad_argument", "order must be default or most_recent. The default order is the provider's own and is NOT a reach ranking.", "order")
    params = {"country": COUNTRY, "media_type": run["media_type"], "status": status}
    if order == "most_recent":
        params["sort_by"] = "relevancy_monthly_grouped"
    if adv is not None:
        if isinstance(adv, bool) or not isinstance(adv, int):
            return research._fail("bad_argument", "advertiser_no must be an integer from this request's fb_ads_find_advertiser result.", "advertiser_no")
        a = _advertiser(run["run_id"], adv)
        if not a:
            return _with_allowance(research._fail("unknown_advertiser", f"advertiser_no {adv} was not returned by an advertiser search of this request.", "advertiser_no",
                                                  hint="Call fb_ads_find_advertiser first, or search by keyword."), run)
        endpoint, label = "company", {"advertiser_no": adv, "advertiser": a.get("name")}
        params["pageId"] = a["page_id"]
    else:
        q, e = research._text(q, "query", 2, 100)
        if e:
            return e
        endpoint, label = "keyword", {"query": q}
        params.update(query=q, search_type="keyword_unordered")
    if args.get("next_page"):   # the cursor comes from this run's own LATEST successful page of the SAME search, never from the model
        with core.db() as c:
            prev = c.execute("SELECT params, result FROM ad_calls WHERE run_id=? AND kind='search' AND outcome='ok' ORDER BY id DESC", (run["run_id"],)).fetchall()
        last = next((r for r in prev if {k: v for k, v in json.loads(r["params"]).items() if k != "cursor"} == params), None)
        cur = json.loads(last["result"] or "{}").get("cursor") if last else None
        if not cur:   # the latest page of this search carried no cursor: it was the last page. Older pages' cursors are never reused.
            return research._fail("no_next_page", ("That was the last page: the provider returned no continuation cursor for the latest page of this exact search in this request."
                                                   if last else "There is no further page recorded for this exact search in this request."), "next_page",
                                  hint="Work with the ads you already have, change the query or advertiser, or report what was and was not found.")
        params["cursor"] = cur
    st, v, cid = _api(run, endpoint, params)
    if st == "error":
        return _with_allowance(v, run)
    ads = _load_ads(run["run_id"])
    groups = _campaigns(ads)
    regs = _registered(run["run_id"])
    if st == "cached":
        info = json.loads(v["result"])
        shown = [n for n in info["ad_nos"] if n in ads and not exclusion(ads[n])]   # eligibility is re-read from the CURRENT records (a later detail may have excluded an ad)
        rows = [public_ad(n, ads[n], regs, groups, False) for n in shown]
        out = {"ok": True, "cached": True, **label, "ads": rows[:MAX_ROWS], "ads_returned": len(rows), "has_more_pages": bool(info.get("cursor")),
               "reach_gate": reach_gate(list(ads.values()))}
        skipped = _skipped(info, sum(1 for n in info["ad_nos"] if n in ads and exclusion(ads[n]) == "not_on_facebook"))
        if skipped:
            out["skipped"] = skipped
        return _with_allowance(out, run)
    data, status_code, credits, remaining, ms = v
    now = _now()
    new, dup, noid, video = [], 0, 0, 0
    seen = set()
    for raw in _rows(endpoint, data):
        r = norm_ad(raw, endpoint, cid, now)
        if not r["ad_archive_id"]:
            noid += 1
            continue
        if r["ad_archive_id"] in seen:
            dup += 1
            continue
        seen.add(r["ad_archive_id"])
        if exclusion(r) == "video":
            video += 1
            continue
        new.append(r)   # an ad whose platforms exclude Facebook is STORED too: a later page/detail then updates the same record and the package can disclose it
    try:
        nos = _store_ads(run["run_id"], cid, new)
    except Exception as ex:   # sent and counted, result not kept: say exactly that, never re-send
        _finish_call(cid, "ok_unsaved", status=status_code, error=f"{type(ex).__name__}: {ex}", credits=credits, remaining=remaining, ms=ms)
        return _with_allowance(research._fail("storage_error", "The ad search WAS sent and counted but its results could not be saved, so they cannot be used. It was not repeated.",
                                              hint="Report this as a blocker."), run)
    cursor = data.get("cursor") if isinstance(data.get("cursor"), str) and data.get("cursor") else None
    _finish_call(cid, "ok", status=status_code, result={"ad_nos": nos, "cursor": cursor, "empty": not nos, "dropped_without_id": noid, "duplicates_in_response": dup,
                                                       "excluded_video": video}, credits=credits, remaining=remaining, ms=ms)
    ads = _load_ads(run["run_id"])
    groups = _campaigns(ads)
    shown = [n for n in nos if not exclusion(ads[n])]
    nonfb = sum(1 for n in nos if exclusion(ads[n]) == "not_on_facebook")
    rows = [public_ad(n, ads[n], regs, groups, False) for n in shown]
    out = {"ok": True, **label, "ads": rows[:MAX_ROWS], "ads_returned": len(rows), "has_more_pages": bool(cursor), "reach_gate": reach_gate(list(ads.values())),
           "ordering": "provider's own order; it is NOT a reach ranking",
           "note": "Relevance is YOUR judgement: results can be unrelated. Campaign grouping is not proof of identical creatives; each source_ad_id is one ad. "
                   "An ad's reach state is explained by fb_ad_detail and the reach_gate; 'unavailable' means unknown, not zero. images lists the image_no values for fb_ad_image."}
    skipped = _skipped({"dropped_without_id": noid, "duplicates_in_response": dup, "excluded_video": video}, nonfb)
    if skipped:
        out["skipped"] = skipped
    if not rows:
        out.update(empty=True, note="The provider returned no usable US image ads for this request. Change the query or advertiser instead of repeating it, or report that none were found.")
    return _with_allowance(out, run)


def detail(agent_id, args):
    run, e = _prepare(agent_id, "fb_ad_detail", args)
    if e:
        return e
    no = args.get("ad_no")
    if isinstance(no, bool) or not isinstance(no, int):
        return research._fail("bad_argument", "ad_no must be an integer from this request's fb_ads_search result.", "ad_no")
    ads = _load_ads(run["run_id"])
    if no not in ads:
        return _with_allowance(research._fail("unknown_ad", f"ad_no {no} was not returned by a search in this request, so its details cannot be requested.", "ad_no",
                                              hint="Use an ad_no from an fb_ads_search result of this request."), run)
    rec = ads[no]
    aid = rec["ad_archive_id"]
    if exclusion(rec) == "not_on_facebook":
        return _with_allowance(_ineligible(no, rec), run)
    st, v, cid = _api(run, "detail", {"id": aid})
    regs, groups = _registered(run["run_id"]), _campaigns(ads)
    if st == "error":
        return _with_allowance(v, run)
    if st == "cached":
        return _with_allowance({"ok": True, "cached": True, "ad": public_ad(no, rec, regs, groups)}, run)
    data, status, credits, remaining, ms = v
    # Identity: each identifier the response supplies (ad id, id inside its URL, page id) must agree with the requested ad. A contradiction is another ad's data
    # and is never merged. A response with no id at all is accepted but recorded as UNCONFIRMED.
    got, url_id = _id(_pick(data, "adArchiveID", "ad_archive_id", "adArchiveId")), ad_id_from_url(data.get("url"))
    page = _id(_pick(data, "pageID", "page_id", "pageId"))
    known_page = (rec.get("advertiser") or {}).get("page_id")
    other = next((x for x in (got, url_id) if x is not None and x != aid), None)
    page_bad = page is not None and known_page is not None and page != known_page
    if other is not None or page_bad:
        _finish_call(cid, "identity_mismatch", status=status, credits=credits, remaining=remaining, ms=ms,
                     error=f"response named ad {other or aid} (id {got!r}, url id {url_id!r}, page {page!r}), requested {aid} (page {known_page!r})")
        return _with_allowance(research._fail("ad_identity_mismatch", f"The provider answered the request for ad {aid} with details of a different ad ({other or 'another page'}). "
                                              "The response was discarded and nothing was saved under either ad. The attempt was counted and not repeated.",
                                              hint="Do not use details for this ad; work with other ads or report the blocker."), run)
    identity = "id_match" if got is not None else "url_match" if url_id is not None else "unconfirmed_no_id_in_response"
    new = norm_ad({**data, "ad_archive_id": aid}, "detail", cid, _now())
    new["identity"] = identity
    new["ad_archive_id"], new["source_url"] = aid, rec["source_url"]
    try:
        _store_ads(run["run_id"], cid, [new])
    except Exception as ex:
        _finish_call(cid, "ok_unsaved", status=status, error=f"{type(ex).__name__}: {ex}", credits=credits, remaining=remaining, ms=ms)
        return _with_allowance(research._fail("storage_error", "The ad detail request WAS sent and counted but its result could not be saved. It was not repeated.",
                                              hint="Report this as a blocker."), run)
    _finish_call(cid, "ok", status=status, result={"ad_no": no, "identity": identity}, credits=credits, remaining=remaining, ms=ms)
    ads = _load_ads(run["run_id"])
    out = {"ok": True, "ad": public_ad(no, ads[no], regs, _campaigns(ads))}
    if identity == "unconfirmed_no_id_in_response":
        out["identity_note"] = "The response carried no ad id or URL, so it is NOT independently confirmed that these details belong to this ad."
    out["reach_gate"] = reach_gate(list(ads.values()))
    return _with_allowance(out, run)


def image_dir(run_id):
    return core.RUNTIME / "ad_research" / run_id / "images"


def image(agent_id, args):
    run, e = _prepare(agent_id, "fb_ad_image", args)
    if e:
        return e
    no, ino = args.get("ad_no"), args.get("image_no")
    if any(isinstance(x, bool) or not isinstance(x, int) for x in (no, ino)):
        return research._fail("bad_argument", "ad_no and image_no must be integers from this request's ad results.", "ad_no")
    ads = _load_ads(run["run_id"])
    if no not in ads:
        return _with_allowance(research._fail("unknown_ad", f"ad_no {no} was not returned by a search in this request.", "ad_no",
                                              hint="Use an ad_no from an fb_ads_search result of this request."), run)
    rec = ads[no]
    aid = rec["ad_archive_id"]
    bad = _ineligible(no, rec)   # before the store lookup: an already downloaded file of an ineligible ad is not served as a candidate either
    if bad:
        return _with_allowance(bad, run)
    img = next((i for i in rec.get("images") or [] if i["image_no"] == ino), None)
    if img is None:
        return _with_allowance(research._fail("unknown_image", f"Ad {no} has no image number {ino} (it has {len(rec.get('images') or [])}).", "image_no",
                                              hint="Use an image_no listed for this ad; fb_ad_detail shows cards and every image reference."), run)
    iid = f"ad-{aid}-{ino}"
    with core.db() as c:
        have = c.execute("SELECT * FROM ad_images WHERE run_id=? AND image_id=?", (run["run_id"], iid)).fetchone()
    if have and (image_dir(run["run_id"]) / have["path"]).is_file():
        return _with_allowance({"ok": True, "cached": True, "image_id": iid, "ad_no": no, "image_no": ino, "sha256": have["sha256"], "bytes": have["bytes"], "width": have["width"],
                                "height": have["height"], "next": f"inspect_image(image_id={iid!r}) shows the pixels."}, run)
    ok, host = research._host_ok(img["ref"])
    if not ok:
        return _with_allowance(research._fail("image_host_not_allowed", "The image is not hosted on an allowed Facebook CDN host and was not fetched.", "image_no"), run)
    state, v = _begin_call(run, "image", "image", {"ad_archive_id": aid, "image_no": ino})
    if state == "error":
        return _with_allowance(v, run)
    if state == "cached":   # an earlier download succeeded but its file/record is gone: do not silently re-download
        return _with_allowance(research._fail("image_unavailable", "The image was downloaded earlier in this request but is no longer available locally. It was not downloaded again.",
                                              "image_no"), run)
    cid = v
    dg = research.diag()
    t0 = time.perf_counter()
    served = {}
    res = dg.check_image(img["ref"], transport=research._photo_get(served), ctx=dg.tls_context())   # no credential attached; each redirect hop validated
    ms = round((time.perf_counter() - t0) * 1000)
    body = res.pop("_body", None)
    refused = "RedirectRefused" in str(res.get("error") or "")
    if res["kind"] != "usable" or not body:
        _finish_call(cid, "redirect_refused" if refused else res["kind"], status=res.get("http_status"), error=res.get("error"), ms=ms)
        return _with_allowance(research._fail("image_redirect_refused" if refused else "image_unavailable",
                                              f"The image could not be used ({res['kind']}: {res.get('error')}). The download was counted and not repeated.", "image_no",
                                              hint="Say that this ad image could not be inspected; do not describe it."), run)
    host = (urllib.parse.urlparse(served.get("final") or img["ref"]).hostname or host).lower()   # the host that actually served the bytes
    ext = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif"}.get(res.get("format"), "bin")
    try:
        folder = image_dir(run["run_id"])
        folder.mkdir(parents=True, exist_ok=True)
        tmp = folder / f"{iid}.{ext}.{os.getpid()}.tmp"
        tmp.write_bytes(body)
        os.replace(tmp, folder / f"{iid}.{ext}")
        with core.db() as c:
            c.execute("INSERT OR REPLACE INTO ad_images(run_id, image_id, ad_archive_id, ad_no, image_no, source_field, sha256, bytes, width, height, content_type, format, host, "
                      "fetched_at, path) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (run["run_id"], iid, aid, no, ino, img["source"], res["sha256"], res["bytes"], res["width"], res["height"], res["content_type"], res.get("format"), host,
                       time.time(), f"{iid}.{ext}"))
    except Exception as ex:   # file system OR database: the download happened and was counted, the result is not kept, and it is not fetched again
        _finish_call(cid, "ok_unsaved", status=200, error=f"{type(ex).__name__}: {ex}", ms=ms)
        return _with_allowance(research._fail("storage_error", "The image was downloaded and counted but could not be saved locally. It was not downloaded again.",
                                              hint="Say that this ad image could not be inspected."), run)
    _finish_call(cid, "ok", status=200, result={"sha256": res["sha256"], "bytes": res["bytes"]}, ms=ms)
    return _with_allowance({"ok": True, "image_id": iid, "ad_no": no, "image_no": ino, "sha256": res["sha256"], "bytes": res["bytes"], "width": res["width"], "height": res["height"],
                            "host": host, "next": f"inspect_image(image_id={iid!r}) shows the pixels."}, run)


def image_registered(run_id, image_id):
    if not run_id or not str(run_id).startswith("adrun-"):
        return False
    with core.db() as d:
        return d.execute("SELECT 1 FROM ad_images WHERE run_id=? AND image_id=?", (run_id, image_id)).fetchone() is not None


# ---------------- the saved package ----------------
def _accounting(run_id):
    v = allowance_view(run_id)
    with core.db() as d:
        calls = [dict(x) for x in d.execute("SELECT id, kind, endpoint, status, outcome, http_status, credits_charged, ms, error FROM ad_calls WHERE run_id=? ORDER BY id", (run_id,))]
    by_kind = {}
    for c in calls:
        k = by_kind.setdefault(c["kind"], {"attempts": 0, "ok": 0, "failed": 0, "unknown": 0})
        k["attempts"] += 1
        k["ok" if c["outcome"] == "ok" else "unknown" if c["status"] != "done" or c["outcome"] in ("network_error", "ok_unsaved") else "failed"] += 1
    credits = [c["credits_charged"] for c in calls if c["credits_charged"] is not None]
    return {"scraper_attempts": v["run_api_attempts"], "scraper_attempts_max": v["run_api_max"], "image_download_attempts": v["run_image_downloads"],
            "image_download_attempts_max": v["run_image_max"], "by_kind": by_kind, "credits_reported_charged": sum(credits) if credits else None,
            "credits_note": "sum of provider-reported credits_charged over calls that reported one; failed calls may be charged without a report",
            "scope": v["scope"], "calls": [{"n": c["id"], "kind": c["kind"], "endpoint": c["endpoint"], "outcome": c["outcome"] or c["status"], "http_status": c["http_status"],
                                            "credits_charged": c["credits_charged"], "ms": c["ms"]} for c in calls]}


def save_package(agent_id, a):
    run, e = _prepare(agent_id, "save_ad_research", a)
    if e:
        return e
    rid = run["run_id"]
    with core.db() as d:
        prior = d.execute("SELECT package_id FROM ad_packages WHERE run_id=?", (rid,)).fetchone()
        n_calls = d.execute("SELECT COUNT(*) FROM ad_calls WHERE run_id=?", (rid,)).fetchone()[0]
    if not prior and not n_calls and allowance_view(rid)["api_attempts_left"] > 0:   # nothing was tried and nothing prevented trying
        return research._fail("no_research_in_request", "No ad research was performed in this request, so there is nothing to save.",
                              hint="Search first; if the research cannot be done, tell the user instead of saving a package.")
    if prior:
        return research._fail("package_already_saved", f"This request already saved its research package ({prior['package_id']}). One package is saved per manual request.",
                              hint="Tell the user the package id; it can be read with read_ad_research.", package_id=prior["package_id"])
    summary, e = research._text(a.get("summary"), "summary", 40, 1500)
    if e:
        return e
    basis = a.get("selection_basis")
    if basis not in ("relevance_only", "reach_ranked"):
        return research._fail("bad_argument", "selection_basis must be relevance_only or reach_ranked.", "selection_basis", hint="Use reach_ranked only when reach_gate says ranking is enabled.")
    lim = a.get("limitations")
    lim = lim.strip()[:600] if isinstance(lim, str) else ""
    refs = a.get("references") if a.get("references") is not None else []
    if not isinstance(refs, list) or len(refs) > 6:
        return research._fail("bad_references", "references must be a list of at most 6 entries.", "references")
    blocker = a.get("blocker")
    if not refs:
        blocker, e = research._text(blocker, "blocker", 20, 600)
        if e:
            return research._fail("blocker_required", "With no references you must state the blocker (what was searched and why nothing relevant was found) in 20-600 characters.", "blocker")
    elif blocker:
        return research._fail("bad_argument", "blocker is only for a package without references.", "blocker")
    from app import listing
    for where, text in [("summary", summary)] + [(f"references[{i}].why_relevant", r.get("why_relevant")) for i, r in enumerate(refs) if isinstance(r, dict)]:
        m = listing._SALES_CLAIM.search(text or "") or _EFFECT.search(text or "")
        if m:
            return research._fail("unsupported_claim", f"{where} makes a sales/effectiveness/popularity claim ({m.group(0)!r}). Ads in the Library show what was run, not whether it "
                                  "worked, sold or reached people.", where, hint="Describe what the ad shows and why it is relevant to the merchant's product, nothing about results.")
    ads = _load_ads(rid)
    regs = _registered(rid)
    gate = reach_gate(list(ads.values()))
    if basis == "reach_ranked" and not gate["ranking_enabled"]:
        return research._fail("reach_ranking_unavailable", f"selection_basis reach_ranked is not allowed: reach ranking is {gate['state']}. {gate['reason']}", "selection_basis",
                              hint="Select by relevance (relevance_only) and say that reach ranking was unavailable.", reach_gate=gate)
    with core.db() as d:
        insp = {}   # ONLY inspections bound to this request and this run count; another request's (or a legacy unbound) inspection of identical bytes does not
        for r in d.execute("SELECT * FROM image_inspections WHERE agent_id=? AND kind='live_ad_image' AND request_id=? AND run_id=? ORDER BY id",
                           (agent_id, run["request_id"], rid)):
            old = insp.get((r["image_id"], r["sha256"]))   # the latest inspection of exactly these bytes within this request wins, but never replaces a CONFIRMED one
            if old is None or r["delivered_at"] or not old["delivered_at"]:
                insp[(r["image_id"], r["sha256"])] = dict(r)
    groups = _campaigns(ads)
    out_refs, missing, seen_img = [], [], set()
    for i, r in enumerate(refs):
        w = f"references[{i}]"
        if not isinstance(r, dict) or set(r) - {"ad_no", "image_id", "why_relevant", "visual_features", "observations", "uncertainties"}:
            return research._fail("bad_references", f"{w} must be an object with ad_no, image_id, why_relevant, visual_features, observations and optionally uncertainties.", w)
        no, iid = r.get("ad_no"), r.get("image_id")
        if isinstance(no, bool) or not isinstance(no, int) or no not in ads:
            return research._fail("unknown_ad", f"{w}.ad_no {no!r} is not an ad returned by a search in this request.", f"{w}.ad_no")
        bad = _ineligible(no, ads[no], f"{w}.ad_no")
        if bad:   # e.g. a detail response identified it as Instagram-only AFTER its image was downloaded and inspected
            return bad
        reg = next((x for x in regs.values() if x["image_id"] == iid and x["ad_no"] == no), None) if isinstance(iid, str) else None
        if reg is None:
            return research._fail("image_not_registered", f"{w}.image_id {iid!r} is not an image of ad {no} downloaded in this request with fb_ad_image.", f"{w}.image_id",
                                  hint="Download the image with fb_ad_image, inspect it with inspect_image, then cite it.")
        if iid in seen_img:
            return research._fail("duplicate_reference", f"{w}.image_id {iid!r} is cited twice.", f"{w}.image_id")
        seen_img.add(iid)
        row = insp.get((iid, reg["sha256"]))
        if row is None or row["ts"] < run["created_at"]:
            return research._fail("image_not_inspected", f"{w}.image_id {iid!r} was not inspected by you in this request (no inspect_image result for these bytes is recorded "
                                  "for THIS request; an inspection made in another request, or one recorded before requests were tracked, does not count). Call inspect_image first.",
                                  f"{w}.image_id")
        why, obs = r.get("why_relevant"), r.get("observations")
        feats = r.get("visual_features")
        if not isinstance(why, str) or not 20 <= len(why.strip()) <= 400:
            return research._fail("too_short", f"{w}.why_relevant must be 20-400 characters on why this ad matters for the merchant's product.", f"{w}.why_relevant")
        if not isinstance(obs, str) or not 15 <= len(obs.strip()) <= 1200:
            return research._fail("too_short", f"{w}.observations must describe what you saw in the image (15-1200 characters).", f"{w}.observations")
        if not isinstance(feats, list) or not 1 <= len(feats) <= 6 or any(not isinstance(f, str) or not 3 <= len(f.strip()) <= 120 for f in feats):
            return research._fail("bad_references", f"{w}.visual_features must be 1-6 short text items (3-120 characters) naming visual features worth taking as a principle.",
                                  f"{w}.visual_features")
        if basis == "reach_ranked" and reach_view(ads[no])["state"] != "reported":
            return research._fail("reach_ranking_unavailable", f"{w} cites ad {no}, which carries no reported reach, so it cannot be a reach-ranked selection.", f"{w}.ad_no", reach_gate=gate)
        if not row.get("delivered_at"):   # a capability prediction (image_part_sent) is not delivery: only a model request that carried these exact pixels, then its response, is
            return research._fail("image_not_delivered", f"{w}.image_id {iid!r} was inspected, but no model request that carried its pixels and was answered is recorded for this "
                                  "inspection (the inspection result reaches you only with your NEXT response; a text-only fallback or a failed request never delivers it), so it is not "
                                  "verified visual evidence.", f"{w}.image_id",
                                  hint="Call inspect_image on the image, then save the research in a LATER step (never in the same tool-call batch as inspect_image). If your model "
                                       "cannot receive images, save a blocker without references instead.")
        out_refs.append({"ad_no": no, "source_ad_id": ads[no]["ad_archive_id"], "source_url": ads[no].get("source_url"), "image_id": iid, "image_no": reg["image_no"],
                         "image_source": reg["source_field"], "sha256": reg["sha256"], "bytes": reg["bytes"], "width": reg["width"], "height": reg["height"], "host": reg["host"],
                         "retrieved_at": _iso(reg["fetched_at"]), "inspected_at": _iso(row["ts"]), "inspection_sha256": row["sha256"], "inspection_request_id": row["request_id"],
                         "inspection_run_id": row["run_id"], "delivery": "image_part_sent",
                         "delivery_confirmed": True, "delivered_at": _iso(row["delivered_at"]), "counts_as_verified_evidence": True, "why_relevant": why.strip(), "visual_features": [f.strip() for f in feats],
                         "model_observations": obs.strip(), "model_uncertainties": str(r.get("uncertainties") or "").strip()[:600]})
    status = "blocked" if not refs else ("complete" if not missing else "partial")
    cited = sorted({r["ad_no"] for r in out_refs})
    if refs and gate["state"] != "enabled":
        missing.append(f"reach ranking was unavailable ({gate['state']}): the selection is by relevance only")
    pid = "adpkg-" + uuid.uuid4().hex[:10]
    ident = {"agent_id": agent_id, "company_id": run["company_id"], "company_name": run["company_name"], "conversation_id": run["conversation_id"], "request_id": run["request_id"],
             "run_id": rid, "message_id": run["message_id"], "country": run["country"], "media_type": run["media_type"], "source": SOURCE}
    considered = [{"ad_no": n, "source_ad_id": r["ad_archive_id"], "source_url": r.get("source_url"), "advertiser": (r.get("advertiser") or {}).get("name"),
                   "text": (r.get("text") or "")[:160] or None, "image_count": len(r.get("images") or []), "card_count": len(r.get("cards") or []),
                   "campaign_id": (r.get("campaign") or {}).get("campaign_id"), "reach_state": reach_view(r)["state"], "detail_level": r.get("detail_level"),
                   "platforms": r.get("platforms"), "excluded": exclusion(r)}
                  for n, r in ads.items()]
    excluded_ads = [{"ad_no": n, "source_ad_id": r["ad_archive_id"], "reason": exclusion(r), "platforms": r.get("platforms")} for n, r in ads.items() if exclusion(r)]
    cited_view = [public_ad(n, ads[n], regs, groups, True) for n in cited]
    body = {"cited_ads": cited_view, "references": out_refs}
    try:
        with core.db() as d:
            d.execute("INSERT INTO ad_packages(package_id, run_id, agent_id, company_id, conversation_id, request_id, status, summary, selection_basis, blocker, limitations, "
                      "reach_gate, references_json, ads_considered, call_accounting, identity, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (pid, rid, agent_id, run["company_id"], run["conversation_id"], run["request_id"], status, summary, basis, blocker, lim, json.dumps(gate), json.dumps(body),
                       json.dumps(considered), json.dumps(_accounting(rid)), json.dumps(ident), time.time()))
    except Exception as ex:   # includes a concurrent second save (UNIQUE run_id)
        with core.db() as d:
            again = d.execute("SELECT package_id FROM ad_packages WHERE run_id=?", (rid,)).fetchone()
        if again:
            return research._fail("package_already_saved", f"This request already saved its research package ({again['package_id']}).", package_id=again["package_id"])
        return research._fail("storage_error", f"The package could not be saved ({type(ex).__name__}). Nothing was published.", hint="Report this as a blocker.")
    return _with_allowance({"ok": True, "package_id": pid, "status": status, "missing": missing, "references_saved": len(out_refs), "independent_ads_cited": len(cited),
                            "ads_recorded": len(ads), "excluded_ads": excluded_ads, "campaigns_cited": len({(ads[n].get("campaign") or {}).get("campaign_id") or f"ad-{n}" for n in cited}),
                            "reach_gate": gate, "retrieve": f"/api/ads/packages/{pid}",
                            "note": "Saved, and shown to the user as a card under your reply. Nothing was published. Mention it in one short sentence, say whether reach ranking was available and, if status is partial or blocked, what is missing."}, run)


def read_package(agent_id, args):
    _, e = _prepare(agent_id, "read_ad_research", args, need_run=False)
    if e:
        return e
    pid = args.get("package_id")
    if pid is None:
        rows = [p for p in list_packages(agent_id)]
        return {"ok": True, "packages": rows, "note": "Stored data only; no request was made."}
    if not isinstance(pid, str) or not re.fullmatch(r"adpkg-[0-9a-f]{10}", pid):
        return research._fail("bad_argument", "package_id must be an id returned by save_ad_research or read_ad_research.", "package_id")
    p = get_package(pid)
    if not p or p["identity"]["agent_id"] != agent_id:
        return research._fail("unknown_package", f"No saved package {pid!r} for this specialist.", "package_id")
    return {"ok": True, "package": p, "note": "Stored data only; no request was made."}


# ---------------- read API (SQLite only; no provider request) ----------------
def _package(r):
    body = json.loads(r["references_json"])
    ads = json.loads(r["ads_considered"])
    cited = body["cited_ads"]
    camp = {}
    for x in cited:
        c = x["campaign"]["campaign_id"]
        if c:
            camp.setdefault(c, []).append(x["ad_no"])
    return {"package_id": r["package_id"], "status": r["status"], "created_at": r["created_at"], "identity": json.loads(r["identity"]), "summary": r["summary"],
            "selection_basis": r["selection_basis"], "blocker": r["blocker"], "limitations": r["limitations"], "reach_gate": json.loads(r["reach_gate"]),
            "cited_ads": cited, "references": body["references"], "ads_considered": ads, "campaigns_cited": camp,
            "counts": {"ads_recorded": len(ads), "ads_excluded": sum(1 for a in ads if a.get("excluded")), "independent_ads_cited": len(cited), "references": len(body["references"]),
                       "campaigns_cited": len({x["campaign"]["campaign_id"] or f"ad-{x['ad_no']}" for x in cited}),
                       "cards_in_cited_ads": sum(x["card_count"] for x in cited)},
            "call_accounting": json.loads(r["call_accounting"]),
            "retrieval_note": "Stored data only. Signed CDN URLs and credentials are never part of a package; images are managed IDs served by /api/ads/images/<run_id>/<image_id>."}


def get_package(package_id):
    with core.db() as d:
        r = d.execute("SELECT * FROM ad_packages WHERE package_id=?", (package_id,)).fetchone()
    return _package(r) if r else None


def list_packages(agent_id=None):
    with core.db() as d:
        rows = d.execute("SELECT * FROM ad_packages" + (" WHERE agent_id=?" if agent_id else "") + " ORDER BY created_at", (agent_id,) if agent_id else ()).fetchall()
    return [{"package_id": r["package_id"], "agent_id": r["agent_id"], "request_id": r["request_id"], "run_id": r["run_id"], "status": r["status"], "created_at": r["created_at"],
             "summary": r["summary"][:200], "selection_basis": r["selection_basis"], "reach_gate_state": json.loads(r["reach_gate"])["state"]} for r in rows]


def run_view(run_id):
    with core.db() as d:
        r = d.execute("SELECT * FROM ad_runs WHERE run_id=?", (run_id,)).fetchone()
        if not r:
            return None
        images = [dict(x) for x in d.execute("SELECT image_id, ad_archive_id, ad_no, image_no, source_field, sha256, bytes, width, height, content_type, host, fetched_at "
                                             "FROM ad_images WHERE run_id=?", (run_id,))]
        pk = [x[0] for x in d.execute("SELECT package_id FROM ad_packages WHERE run_id=?", (run_id,))]
    ads = _load_ads(run_id)
    return {"run_id": run_id, "agent_id": r["agent_id"], "company_id": r["company_id"], "conversation_id": r["conversation_id"], "request_id": r["request_id"], "scope": r["scope"],
            "country": r["country"], "media_type": r["media_type"], "created_at": r["created_at"], "calls": _accounting(run_id)["calls"], "accounting": _accounting(run_id),
            "ads_recorded": len(ads), "images": images, "package_ids": pk, "reach_gate": reach_gate(list(ads.values())), "allowance": allowance_view(run_id)}


def list_runs(agent_id=None):
    with core.db() as d:
        rows = d.execute("SELECT run_id, agent_id, scope, created_at FROM ad_runs" + (" WHERE agent_id=?" if agent_id else "") + " ORDER BY created_at",
                         (agent_id,) if agent_id else ()).fetchall()
    return [{"run_id": r["run_id"], "agent_id": r["agent_id"], "scope": r["scope"], "created_at": r["created_at"], "allowance": allowance_view(r["run_id"])} for r in rows]


def allowances():
    with core.db() as d:
        return [dict(r) for r in d.execute("SELECT * FROM ad_allowance ORDER BY scope")]


def image_file(run_id, image_id):
    """(bytes, content_type) of one managed ad image, or None. Both ids are validated and resolved through the database; no path comes from the caller."""
    if not (isinstance(run_id, str) and re.fullmatch(r"adrun-[0-9a-f]{10}", run_id) and isinstance(image_id, str) and re.fullmatch(r"ad-\d{1,24}-\d{1,3}", image_id)):
        return None
    with core.db() as d:
        r = d.execute("SELECT path, format FROM ad_images WHERE run_id=? AND image_id=?", (run_id, image_id)).fetchone()
    if not r:
        return None
    p = image_dir(run_id) / r["path"]
    try:   # the type comes from what the file DECODED as, never from the provider's header
        return p.read_bytes(), {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp", "GIF": "image/gif"}.get(r["format"], "application/octet-stream")
    except OSError:
        return None
