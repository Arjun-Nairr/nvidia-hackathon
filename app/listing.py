"""One evidence-backed listing draft (ticket 04): catalogue facts + RECORDED Marketplace evidence + inspected images -> a saved draft.

Backend-owned and UI-independent. Imported by the Hermes plugin (tools) and the web server (read API). Nothing here scrapes, calls a model or
publishes. Trust rules: the specialist's identity, product facts, listing facts, source URLs, retrieval times and image hashes are all derived
HERE from the catalogue file, the recorded-evidence file and the inspection log; the model supplies only text and references, and every
reference is validated before anything is stored.
"""
import hashlib, json, os, re, time, uuid
from pathlib import Path
from app import ads, core, research, turn_state

DEFAULT_CATALOGUE = core.ROOT / "tests" / "fixtures" / "demo_catalogue.json"       # FICTIONAL demo merchant (labelled inside the file)
DEFAULT_EVIDENCE = core.ROOT / "tests" / "fixtures" / "marketplace_sample.json"    # redacted live Dallas sample (ticket 02), replayed
TITLE_MAX, TEXT_MAX = 100, 1500


def _path(env, default):
    return Path(os.environ.get(env) or default)


def _load(path, what):
    try:
        raw = path.read_bytes()
        return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest(), None
    except FileNotFoundError:
        return None, None, core.err(f"{what}_missing", f"No {what} file is configured/available ({path.name}).")
    except (OSError, ValueError) as e:
        return None, None, core.err(f"{what}_unreadable", f"The {what} file could not be read ({type(e).__name__}).")


# ---------------- catalogue ----------------
def product_images(p):
    """The product's registered images, in order: `images` (a list of {image_id, kind, provenance...} or bare ids) when present, else the V1 single `image`."""
    out, seen = [], set()
    items = p.get("images") if isinstance(p.get("images"), list) and p["images"] else [p.get("image")]
    for it in items:
        d = {"image_id": it} if isinstance(it, str) else it if isinstance(it, dict) else {}
        iid = str(d.get("image_id") or "").strip()
        if iid and iid not in seen:
            seen.add(iid)
            out.append({**d, "image_id": iid})
    return out


def product_missing(p):
    """Required supplied facts that are absent from a catalogue product."""
    miss = []
    if not str(p.get("name") or "").strip():
        miss.append("name")
    if not isinstance(p.get("specifications"), dict) or not p["specifications"]:
        miss.append("specifications")
    pr = p.get("price") if isinstance(p.get("price"), dict) else {}
    if not isinstance(pr.get("amount"), (int, float)) or isinstance(pr.get("amount"), bool):
        miss.append("price.amount")
    if not str(pr.get("currency") or "").strip():
        miss.append("price.currency")
    if not product_images(p):
        miss.append("image.image_id")
    return miss


def _norm_name(s):
    return " ".join(re.sub(r"\(.*?\)", " ", str(s or "")).lower().replace("&", " and ").translate({ord(c): " " for c in ".,;:!?'\"-_/"}).split())


def catalogue():
    """The configured catalogue, but only for the company it belongs to: fictional demo facts are never supplied to another merchant."""
    data, sha, e = _load(_path("ECOM_CATALOGUE_FILE", DEFAULT_CATALOGUE), "catalogue")
    if e:
        return None, e
    if not isinstance(data, dict) or not isinstance(data.get("products"), list) or not isinstance(data.get("merchant"), dict):
        return None, core.err("catalogue_invalid", "The catalogue file must contain a merchant object and a products list.")
    company = _norm_name(core.load_company().get("name"))
    owner = _norm_name(data["merchant"].get("company_name") or data["merchant"].get("name"))
    if not company:
        return None, core.err("company_missing", "No company is saved yet, so it cannot be checked that the catalogue belongs to it. Nothing was supplied.")
    if not owner or owner != company:
        return None, core.err("catalogue_company_mismatch", f"The configured catalogue belongs to {data['merchant'].get('name')!r}, not to this company "
                              f"({core.load_company().get('name')!r}). No product facts are supplied for a different merchant.",
                              hint="Tell the user that this company has no catalogue yet (a catalogue file for it must be configured: ECOM_CATALOGUE_FILE).")
    return {**data, "_sha256": sha, "_file": _path("ECOM_CATALOGUE_FILE", DEFAULT_CATALOGUE).name}, None


def read_catalogue(product_id=None):
    cat, e = catalogue()
    if e:
        return e
    prods = [p for p in cat["products"] if isinstance(p, dict)]
    out = []
    for p in prods:
        imgs = product_images(p)
        out.append({**p, "missing_facts": product_missing(p), "image_inspectable": bool(imgs) and _cached(imgs[0]["image_id"]),
                    "images": [{**i, "inspectable": _cached(i["image_id"])} for i in imgs]})
    if product_id is not None:
        out = [p for p in out if p.get("product_id") == product_id]
        if not out:
            return core.err("unknown_product", f"No catalogue product {product_id!r}.", "product_id", [p.get("product_id") for p in prods],
                            "Ask the user which product they mean.")
    return {"ok": True, "demo": bool(cat.get("demo")), "notice": cat.get("notice"), "merchant": cat["merchant"], "products": out,
            "note": "Facts here are the merchant's supplied facts; anything not listed is unknown. Do not add specifications, materials, discounts or delivery terms."}


# ---------------- recorded Marketplace evidence (replayed; no scraping) ----------------
def evidence(source="recorded_sample", run_id=None):
    """Evidence for drafts: the RECORDED sample file, or one live research run's own records. They are never mixed or substituted."""
    if source == "live_research":
        if not run_id:
            return None, core.err("no_live_research", "No Marketplace research was performed for this request, so there is no live evidence.")
        ev = research.run_evidence(run_id)
        if not ev["by_id"]:
            return None, core.err("no_live_evidence", "This request's research run holds no listings yet.")
        return ev, None
    path = _path("ECOM_EVIDENCE_FILE", DEFAULT_EVIDENCE)
    data, sha, e = _load(path, "evidence")
    if e:
        return None, e
    if not isinstance(data, dict) or not isinstance(data.get("listings"), list):
        return None, core.err("evidence_invalid", "The recorded evidence file must contain a listings list.")
    byid = {str(l["listing_id"]): l for l in data["listings"] if isinstance(l, dict) and l.get("listing_id")}
    return {"data": data, "by_id": byid, "sha256": sha, "file": path.name, "source": "recorded_sample", "run_id": None}, None


def _cached(image_id):
    return any((r / f"{image_id}{x}").is_file() for r in core.image_roots() for x in core.IMAGE_EXTS)


PHOTO_REFS_MAX, DESC_MAX = 12, 800


def _support(l):
    """The recorded content of one listing that the specialist can read AND that a saved draft keeps. Explicit whitelist (no manual review notes,
    seller fields, coordinates or other raw payload). Used by the read tool and by save_draft so what was exposed is what is persisted."""
    desc = l.get("description") if isinstance(l.get("description"), str) else ""
    ph = [p for p in (l.get("photos") or []) if isinstance(p, dict)]
    return {"description": desc[:DESC_MAX] or None, "description_truncated": len(desc) > DESC_MAX, "photo_count": len(ph),
            "photos": [{"photo_id": None if p.get("id") is None else str(p["id"]), "width": p.get("width"), "height": p.get("height"), "caption": p.get("caption")}
                       for p in ph[:PHOTO_REFS_MAX]]}


def _summary(l):
    pr = l.get("price") if isinstance(l.get("price"), dict) else {}
    loc = l.get("location") if isinstance(l.get("location"), dict) else {}
    return {"listing_id": str(l["listing_id"]), "title": l.get("title"), "price": {"amount": pr.get("amount"), "currency": pr.get("currency"), "formatted": pr.get("formatted")},
            "condition": l.get("condition"), "location": loc.get("display_name") or loc.get("text"),
            "detail_level": "detailed" if (l.get("description") or l.get("photos")) else "search_only",
            "image_cached": _cached(str(l["listing_id"])), "retrieved_at": l.get("retrieved_at")}


def read_recorded_evidence(query=None, detailed_only=False, cached_images_only=False, limit=20, listing_id=None):
    ev, e = evidence()
    if e:
        return e
    if listing_id is not None:
        l = ev["by_id"].get(str(listing_id))
        if not l:
            return core.err("unknown_listing", f"No recorded listing {listing_id!r}.", "listing_id")
        s = _summary(l)
        seller = l.get("seller") if isinstance(l.get("seller"), dict) else {}
        return {"ok": True, "listing": {**s, "source_url": l.get("source_url"), **_support(l), "seller_ref": seller.get("id"),
                                        "retrieval": "recorded live sample (replayed); not re-fetched"}}
    rows = [_summary(l) for l in ev["data"]["listings"] if isinstance(l, dict) and l.get("listing_id")]
    if query:
        q = str(query).lower()
        rows = [r for r in rows if q in (r["title"] or "").lower() or q in ((ev["by_id"][r["listing_id"]].get("description")) or "").lower()]
    if detailed_only:
        rows = [r for r in rows if r["detail_level"] == "detailed"]
    if cached_images_only:
        rows = [r for r in rows if r["image_cached"]]
    try:
        limit = max(1, min(int(limit), 40))
    except (TypeError, ValueError):
        limit = 20
    return {"ok": True, "source": "recorded Marketplace sample (Dallas, TX; replayed, no live search)", "total_recorded": len(ev["data"]["listings"]),
            "matches": len(rows), "returned": min(limit, len(rows)), "listings": rows[:limit],
            "note": "Relevance is YOUR judgement: the sample contains unrelated and search-only listings. 'image_cached' listings can be viewed with inspect_image(listing_id). "
                    "Prices are what sellers asked, not sales or demand."}


# ---------------- inspection log (trusted: written by the inspect_image tool, never by the model) ----------------
DELIVERY = ("image_part_sent", "text_fallback", "unknown")


def record_inspection(agent_id, prepared, delivery="unknown"):
    """Log that this agent's inspect_image prepared this image. `delivery` is what Hermes' own gate decided for the active provider/model:
    image_part_sent = the image part goes with the tool result; text_fallback = only a text summary does; unknown = not determined.
    It records how the image was SENT, never that the model understood it."""
    ev, _ = evidence()
    cat, _ = catalogue()
    iid = prepared["image_id"]
    live = research.photo_registered(getattr(turn_state, "run_id", None), iid)   # downloaded by this request's research run
    ad = ads.image_registered(getattr(turn_state, "ad_run_id", None), iid)         # downloaded by this request's Facebook ad-research run
    kind = ("live_ad_image" if ad else "live_listing_photo" if live else "recorded_listing_photo" if ev and iid in ev["by_id"] else
            "catalogue_image" if cat and any(iid in [i["image_id"] for i in product_images(p)] for p in cat["products"] if isinstance(p, dict)) else "other")
    # Trusted ownership: the request id and the run that downloaded the image come from the backend's turn state, never from the model. Ad evidence (ads.save_package)
    # accepts only an inspection bound to ITS request and run; rows written before this column existed stay unbound (NULL) and never count there.
    run_id = getattr(turn_state, "ad_run_id", None) if ad else getattr(turn_state, "run_id", None) if live else None
    with core.db() as d:
        cur = d.execute("INSERT INTO image_inspections(agent_id, image_id, kind, sha256, width, height, ts, delivery, request_id, run_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (agent_id, iid, kind, prepared["sha256"], prepared["width"], prepared["height"], time.time(), delivery if delivery in DELIVERY else "unknown",
                         getattr(turn_state, "request_id", None), run_id))
    return cur.lastrowid   # the caller may register it for hook-confirmed delivery (flyer.expect_delivery)


# ---------------- claim guards (heuristic; documented limits) ----------------
_DISCOUNT = re.compile(r"(\d+\s*%\s*off|\bdiscount\w*|\bon sale\b|\bsale price\b|\bclearance\b|\bmarkdown\b|\bwas\s*\$|\bsave\s*\$|\bcoupon\w*|\bpromo\w*|"
                       r"\blimited[- ]time\b|\bspecial offer\b|\bbuy one\b|\bdeal\b)", re.I)
_DELIVERY = re.compile(r"\b(free shipping|free delivery|ships? (?:free|fast|within|in|today)|fast shipping|same[- ]day|next[- ]day|overnight|delivered|delivery|"
                       r"shipping|arrives?|pick[- ]?up)\b", re.I)
_PERFORMANCE = re.compile(r"(\bbest[- ]?sell\w*|\btop[- ]rated|#\s?1\b|\bnumber one\b|\bsold out\b|\bselling fast\b|\bhigh demand\b|\bin demand\b|\bpopular\b|"
                          r"\bcustomer favou?rite|\baward[- ]winning|\bguaranteed?\b|\bhypoallergenic\b|\bcertified\b|\borganic\b|\beco[- ]friendly\b)", re.I)
_SALES_CLAIM = re.compile(r"\b(sold|sales|sells?|selling|best[- ]?sell\w*|popular|in demand|demand|revenue|conversions?|bestseller)\b", re.I)
_MATERIAL = re.compile(r"\b(cotton|linen|polyester|microfiber|microfibre|silk|satin|bamboo|wool|cashmere|feather|velvet|flannel|fleece|rayon|nylon|"
                       r"sateen|percale|jersey|tencel|viscose|acrylic|leather|memory foam|latex|sherpa|chenille)\b", re.I)
_SIZE = re.compile(r"\b(twin xl|twin|queen|california king|cal king|super king|king)\b", re.I)
# Stated price: [lead word] [currency mark] amount [currency mark]. Recognised marks are a bounded list (symbols, ISO codes, a few words); a bare number
# with no mark or lead word (dimension, quantity, percentage, year) is never read as a price. ponytail: a fixed list, extend _CODES when a catalogue needs more.
_CODES = "USD|EUR|GBP|INR|CAD|AUD|NZD|JPY|CNY|CHF|MXN|SGD|HKD|SEK|NOK|DKK|AED"
_DOLLAR = {"USD", "CAD", "AUD", "NZD", "MXN", "SGD", "HKD"}          # what a bare "$" may mean
_MARKS = {"$": _DOLLAR, "US$": {"USD"}, "CA$": {"CAD"}, "C$": {"CAD"}, "AU$": {"AUD"}, "A$": {"AUD"}, "NZ$": {"NZD"}, "\u20ac": {"EUR"}, "\u00a3": {"GBP"},
          "\u00a5": {"JPY", "CNY"}, "\u20b9": {"INR"}, "RS": {"INR"}, "RS.": {"INR"}, "DOLLAR": _DOLLAR, "DOLLARS": _DOLLAR, "EURO": {"EUR"}, "EUROS": {"EUR"},
          "RUPEE": {"INR"}, "RUPEES": {"INR"}}
_PRICE = re.compile(
    r"(?P<lead>\b(?:price[ds]?|costs?)\b(?:\s+(?:is|of|at))?\s*[:=-]?\s*)?"
    rf"(?:(?P<pre>(?<![A-Za-z])(?:US|CA|AU|NZ|C|A)?\$|[\u20ac\u00a3\u00a5\u20b9]|\b(?:{_CODES})\b|\bRs\.?)\s?)?"
    r"(?P<amt>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:[.,]\d{1,2})?)(?!\d)"
    rf"(?:\s?(?P<post>\b(?:{_CODES})\b|\b(?:dollars?|euros?|rupees?)\b|[\u20ac\u00a3\u00a5\u20b9$](?!\s?\d)))?", re.I)


def _spec_text(p):
    return (p.get("name", "") + " " + json.dumps(p.get("specifications", {}))).lower()


def _num(s):
    return float(s.replace(",", "") if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", s) else s.replace(",", "."))


def price_problem(text, p, where):
    """First stated price whose amount or currency differs from the catalogue's declared price, or None."""
    amount, cur = float(p["price"]["amount"]), str(p["price"]["currency"]).strip().upper()
    for m in _PRICE.finditer(text):
        marks = [x for x in (m.group("pre"), m.group("post")) if x]
        if not marks and not m.group("lead"):
            continue                                                     # a bare number: dimension, quantity, percentage, year
        said = m.group(0).strip()
        for mk in marks:
            k = mk.upper().replace(" ", "")
            if cur not in _MARKS.get(k, {k}):
                return f"{where} states a price ({said!r}) in a currency other than the declared {amount:g} {cur}."
        if abs(_num(m.group("amt")) - amount) > 0.005:
            return f"{where} states a price ({said!r}) that differs from the declared price {amount:g} {cur}."
    return None


def copy_problem(text, p, where):
    """First unsupported claim in merchant-facing copy, or None."""
    for rx, why in ((_DISCOUNT, "a discount/promotion claim"), (_DELIVERY, "a shipping, delivery or pick-up promise"), (_PERFORMANCE, "an unsupported performance/popularity/certification claim")):
        m = rx.search(text)
        if m:
            return f"{where} contains {why} ({m.group(0)!r}); the catalogue supplies no such fact."
    spec = _spec_text(p)
    for m in (_MATERIAL.finditer(text) if where in ("title", "description") else ()):   # the brief may name a styling texture/backdrop
        if m.group(0).lower() not in spec:
            return f"{where} names a material ({m.group(0)!r}) that is not in the supplied specifications."
    why = price_problem(text, p, where)
    if why:
        return why
    if where in ("title", "description"):
        sizes = {m.group(0).lower() for m in _SIZE.finditer(spec)}
        for m in _SIZE.finditer(text):
            if m.group(0).lower() not in sizes and not any(m.group(0).lower() in s for s in sizes):
                return f"{where} mentions size {m.group(0)!r}, which does not match the product's supplied size."
    return None


# ---------------- save / read ----------------
def _txt(v, lo, hi, field):
    v = v.strip() if isinstance(v, str) else ""
    if len(v) < lo:
        return None, core.err("too_short", f"{field} must be at least {lo} characters of text.", field)
    if len(v) > hi:
        return None, core.err("too_long", f"{field} exceeds {hi} characters.", field)
    return v, None


def save_draft(agent_id, a):
    """Validate and persist ONE draft. Returns {ok, draft_id, status, missing, ...} or a corrective error (nothing saved)."""
    if not isinstance(a, dict):
        return core.err("bad_request", "Arguments must be an object.")
    with core.db() as d:   # trusted identity: a REGISTERED specialist that actually holds this grant (tool exposure is not the only gate)
        ag = d.execute("SELECT conversation_id, granted_tools FROM agents WHERE agent_id=?", (agent_id,)).fetchone()
    if not ag:
        return core.err("unknown_agent", f"Draft saving needs a registered specialist; {agent_id!r} is not one.")
    grants = json.loads(ag["granted_tools"] or "[]")
    if "save_listing_draft" not in grants:
        return core.err("not_granted", "This specialist was not granted save_listing_draft.")
    can_live, can_rec = any(t in grants for t in research.TOOLS), "read_recorded_evidence" in grants
    want = a.get("evidence_source")
    if want not in (None, "live_research", "recorded_sample"):
        return core.err("bad_evidence_source", "evidence_source must be live_research or recorded_sample.", "evidence_source", ["live_research", "recorded_sample"])
    if want is None:
        if can_live and can_rec:
            return core.err("evidence_source_required", "You hold both live research and recorded evidence: say which one this draft is based on.", "evidence_source",
                            ["live_research", "recorded_sample"], "Recorded listings are a replayed sample and are never fresh research.")
        want = "live_research" if can_live else "recorded_sample"
    if (want == "live_research" and not can_live) or (want == "recorded_sample" and can_live and not can_rec):
        return core.err("evidence_source_not_granted", f"This specialist cannot use {want} evidence.", "evidence_source")
    run = research.run_for(agent_id, getattr(turn_state, "request_id", None)) if want == "live_research" else None
    cat, e = catalogue()
    if e:
        return e
    products = {p.get("product_id"): p for p in cat["products"] if isinstance(p, dict)}
    pid = a.get("product_id")
    if pid not in products:
        return core.err("unknown_product", f"Unknown product_id {pid!r}.", "product_id", sorted(x for x in products if x), "Ask the user which product to write for.")
    prod = products[pid]
    miss = product_missing(prod)
    if miss:
        return core.err("product_facts_missing", f"The catalogue is missing required facts for {pid}: {miss}. A draft cannot be written without them.", "product_id",
                        hint="Tell the user which product facts are missing; do not guess them.")
    title, e = _txt(a.get("title"), 10, TITLE_MAX, "title")
    if e: return e
    desc, e = _txt(a.get("description"), 80, TEXT_MAX, "description")
    if e: return e
    brief, e = _txt(a.get("visual_brief"), 80, TEXT_MAX, "visual_brief")
    if e: return e
    limits = a.get("limitations")
    limits = limits.strip()[:600] if isinstance(limits, str) else ""
    for where, text in (("title", title), ("description", desc), ("visual_brief", brief)):
        why = copy_problem(text, prod, where)
        if why:
            return core.err("unsupported_claim", why, where, hint="Use only the supplied product facts; remove or reword the claim.")
    ev, e = evidence(want, run["run_id"] if run else None)
    if e:
        return e
    rat = a.get("rationale")
    if not isinstance(rat, list) or not 1 <= len(rat) <= 8:
        return core.err("bad_rationale", "rationale must be a list of 1-8 entries {claim, listing_ids, image_ids}.", "rationale")
    obs_in = a.get("image_observations") or []
    if not isinstance(obs_in, list) or len(obs_in) > 6:
        return core.err("bad_observations", "image_observations must be a list of at most 6 entries {image_id, observations, uncertainties}.", "image_observations")
    with core.db() as d:
        seen = {r["image_id"]: dict(r) for r in d.execute("SELECT * FROM image_inspections WHERE agent_id=? ORDER BY id", (agent_id,))}   # latest inspection wins
    obs, used_images = {}, set()
    for o in obs_in:
        iid = o.get("image_id") if isinstance(o, dict) else None
        text = o.get("observations") if isinstance(o, dict) else None
        if not isinstance(iid, str) or iid not in seen:
            return core.err("image_not_inspected", f"Image {iid!r} was not inspected by you (no inspect_image result is recorded). Call inspect_image first.",
                            "image_observations", sorted(seen))
        if not isinstance(text, str) or len(text.strip()) < 15:
            return core.err("too_short", f"The observations for image {iid} must describe what you saw (15+ characters).", "image_observations")
        obs[iid] = {"observations": text.strip()[:1200], "uncertainties": str(o.get("uncertainties") or "").strip()[:600]}
    claims, listing_ids = [], []
    for r in rat:
        if not isinstance(r, dict) or not isinstance(r.get("claim"), str) or not 10 <= len(r["claim"].strip()) <= 400:
            return core.err("bad_rationale", "Each rationale entry needs a claim of 10-400 characters.", "rationale")
        lids, iids = r.get("listing_ids") or [], r.get("image_ids") or []
        if not isinstance(lids, list) or not isinstance(iids, list) or not (lids or iids):
            return core.err("bad_rationale", "Each rationale entry must cite at least one listing_id or image_id.", "rationale")
        for lid in lids:
            if str(lid) not in ev["by_id"]:
                return core.err("unknown_listing", f"Rationale cites listing {lid!r}, which is not in the recorded evidence.", "rationale[].listing_ids")
        for iid in iids:
            if iid not in obs:
                return core.err("image_not_observed", f"Rationale cites image {iid!r} but image_observations has no entry for it.", "rationale[].image_ids")
        m = _SALES_CLAIM.search(r["claim"])
        if m:
            return core.err("unsupported_claim", f"A rationale claim talks about sales/demand/popularity ({m.group(0)!r}); the evidence shows asking prices and photos only.", "rationale[].claim")
        claims.append({"claim": r["claim"].strip(), "listing_ids": [str(x) for x in lids], "image_ids": list(iids)})
        listing_ids += [str(x) for x in lids]
        used_images.update(iids)
    for iid in obs:                                   # an observation of an inspected image the rationale never cites is still evidence the agent used
        used_images.add(iid)
    listing_ids = sorted(set(listing_ids))
    listing_snaps = []
    for lid in listing_ids:
        l = ev["by_id"][lid]
        s = _summary(l)
        seller = l.get("seller") if isinstance(l.get("seller"), dict) else {}
        listing_snaps.append({**s, "source_url": l.get("source_url"), "seller_ref": seller.get("id"), "supporting": _support(l),   # the content the specialist read
                              "identity": l.get("identity"),   # live details only: id_match | url_match | unconfirmed_no_id_in_response (None for the recorded sample)
                              "evidence_file": ev["file"], "evidence_sha256": ev["sha256"]})
    recorded_hash = {str(c.get("listing_id")): c.get("sha256") for c in (ev["data"].get("image_checks") or []) if isinstance(c, dict) and c.get("sha256")}
    image_snaps, missing = [], []
    for iid in sorted(used_images):
        row = seen[iid]
        competitor = row["kind"] in ("recorded_listing_photo", "live_listing_photo") or iid in ev["by_id"]   # kind was fixed at inspection time; the evidence in force decides too
        rec = recorded_hash.get(iid) if competitor else None
        if rec and rec != row["sha256"]:   # a replaced/other file attributed to a recorded listing: false provenance is refused, not recorded
            return core.err("image_provenance_mismatch", f"Image {iid} is cited as the photo of recorded listing {iid}, but the inspected file (sha256 {row['sha256'][:8]}...) "
                            f"does not match the hash recorded when that photo was downloaded ({rec[:8]}...). The cached file is not the recorded photo, so what you saw "
                            "cannot be attributed to that listing.", "image_observations", hint="Remove this image from image_observations and rationale, or tell the user the "
                            "cached photo no longer matches the recorded evidence.")
        prov = "not_applicable" if not competitor else "hash_match" if rec else "no_recorded_hash"
        delivery = row.get("delivery") if row.get("delivery") in DELIVERY else "unknown"   # rows written before this field existed read as unknown
        verified = delivery == "image_part_sent" and prov != "no_recorded_hash"
        if delivery != "image_part_sent":
            missing.append(f"image {iid}: its pixels were not delivered to a supported vision path ({'text-only fallback' if delivery == 'text_fallback' else 'delivery status unknown'}); "
                           "its observations are model text only, not verified visual evidence")
        if prov == "no_recorded_hash":
            missing.append(f"image {iid}: no source hash was recorded for this listing photo, so it cannot be verified as that listing's photo")
        image_snaps.append({"image_id": iid, "kind": ("live_listing_photo" if want == "live_research" else "recorded_listing_photo") if competitor else row["kind"],
                            "listing_id": iid if competitor else None, "sha256": row["sha256"], "width": row["width"],
                            "height": row["height"], "inspected_at": row["ts"], "recorded_sha256": rec, "provenance": prov,
                            "matches_recorded_photo_hash": True if prov == "hash_match" else None,   # None = nothing recorded to compare, never a fake match
                            "delivery": delivery, "counts_as_verified_evidence": verified,
                            "model_observations": obs[iid]["observations"], "model_uncertainties": obs[iid]["uncertainties"]})
    competitor_images = [i for i in image_snaps if i["kind"] in ("recorded_listing_photo", "live_listing_photo")]
    if not competitor_images:
        missing.append("no inspected competitor listing photo is cited: visual comparisons are unverified")
    if not any(s["detail_level"] == "detailed" for s in listing_snaps):
        missing.append("only search-only listings are cited (no descriptions or full photo sets were recorded for them)")
    status = "complete" if not missing else "partial"
    did = "draft-" + uuid.uuid4().hex[:10]
    merchant_snap = {"merchant": cat["merchant"], "demo": bool(cat.get("demo")), "notice": cat.get("notice"), "catalogue_file": cat["_file"], "catalogue_sha256": cat["_sha256"]}
    with core.db() as d:
        row = ag
        d.execute("INSERT INTO listing_drafts(draft_id, agent_id, conversation_id, product_id, status, title, description, visual_brief, rationale, limitations, missing, "
                  "merchant_snapshot, product_snapshot, listing_evidence, image_evidence, created_at, evidence_source, research_run_id, request_id, message_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (did, agent_id, row["conversation_id"] if row else None, pid, status, title, desc, brief, json.dumps(claims), limits, json.dumps(missing),
                   json.dumps(merchant_snap), json.dumps(prod), json.dumps(listing_snaps), json.dumps(image_snaps), time.time(), want, run["run_id"] if run else None, *_identity(agent_id)))
    return {"ok": True, "draft_id": did, "status": status, "missing": missing, "product_id": pid, "evidence_source": want, "listings_cited": listing_ids,
            "images_cited": sorted(used_images), "retrieve": f"/api/drafts/{did}",
            "note": "Saved, and shown to the user as a card under your reply. Nothing was published. Mention it in one short sentence and, if status is partial, say what is missing."}


def _identity(agent_id):
    """(request id, message id) of the turn saving a draft: the backend's request id of this turn and the agent's latest user message, exactly as the research, ad and flyer runs record them.
    Never model-supplied; either part is None when unknown."""
    with core.db() as d:
        m = d.execute("SELECT id FROM messages WHERE agent_id=? AND who='user' ORDER BY id DESC LIMIT 1", (agent_id,)).fetchone()
    return getattr(turn_state, "request_id", None), (m["id"] if m else None)


def _draft(r, full):
    d = {"draft_id": r["draft_id"], "agent_id": r["agent_id"], "conversation_id": r["conversation_id"], "product_id": r["product_id"], "status": r["status"],
         "title": r["title"], "created_at": r["created_at"], "missing": json.loads(r["missing"] or "[]"),
         "evidence_source": r["evidence_source"] or "recorded_sample", "research_run_id": r["research_run_id"]}   # rows from before ticket 05 all used the recorded sample
    if full:
        d.update(description=r["description"], visual_brief=r["visual_brief"], rationale=json.loads(r["rationale"]), limitations=r["limitations"],
                 merchant_snapshot=json.loads(r["merchant_snapshot"]), product_snapshot=json.loads(r["product_snapshot"]),
                 listing_evidence=json.loads(r["listing_evidence"]), image_evidence=json.loads(r["image_evidence"]))
    return d


def list_drafts(agent_id=None):
    with core.db() as d:
        rows = d.execute("SELECT * FROM listing_drafts" + (" WHERE agent_id=?" if agent_id else "") + " ORDER BY created_at", (agent_id,) if agent_id else ()).fetchall()
    return [_draft(r, False) for r in rows]


def get_draft(draft_id):
    with core.db() as d:
        r = d.execute("SELECT * FROM listing_drafts WHERE draft_id=?", (draft_id,)).fetchone()
    return _draft(r, True) if r else None
