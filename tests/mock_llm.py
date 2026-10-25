"""Scripted OpenAI-compatible server. PLUMBING TESTS ONLY - this is NOT Nebius and must never be reported as a Nebius result.
Usage: python tests/mock_llm.py [port]"""
import base64, hashlib, json, re, sys, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

AGENT_ARGS = {
    "role": "market_analysis", "name": "Northloom Market Analyst",
    "objective": "Monitor Harbor & Pine, Kinfolk Row and Tidewear Co on pricing, launches and promotions against Northloom's $40-180 mid-premium basics and recommend responses that protect the calm, no-hype brand.",
    "instructions": "You are the market analyst for Northloom Apparel (fictional). Compare competitor moves with Northloom's catalogue (Heavy Cotton Tee $38, Waxed Overshirt $145, Field Jacket $178). Live research is not connected: label assumptions, never invent prices.",
    "company_context_refs": ["brand", "competitors"],
    "skills": [{"name": "competitor-review", "content": "# Competitor review\n1. Read competitors and catalogue via read_company_context.\n2. For each competitor list what the user told you changed.\n3. Output: Observation / Assumption / Recommended response."}],
    "requested_tools": ["read_company_context", "memory", "skills"]}


SOCIAL_ARGS = {
    "role": "social_media", "name": "Acme Social Media Specialist",
    "objective": "Turn Acme Linens' supplied product facts and brand direction into accurate promotional creative briefs and copy for its bedding range; nothing is posted.",
    "instructions": "You work for Acme Linens (fictional). Use only supplied product facts and the declared price. Ad research and image generation are not connected; "
                    "you produce text briefs and copy and say plainly what you cannot do.",
    "company_context_refs": ["brand"],
    "skills": [{"name": "feed-flyer-checklist", "content": "# Feed flyer checklist\n1. Confirm the product facts and declared price from the catalogue.\n"
                "2. Choose one main message and the lead photo.\n3. Write two copy options and list what could not be verified."}],
    "requested_tools": ["inspect_image", "read_catalogue"]}

STATS = {"requests": 0, "slow": 0, "last_model": "", "routing_ctx_seen": 0, "image_requests": 0, "last_images": [], "image_log": [], "batches": [], "rejected_image_requests": 0}


def image_parts(msgs):
    """Decode every data-URL image part anywhere in the request messages -> [{sha256, bytes, mime}]. Lets tests prove which pixels reached the model."""
    out = []

    def walk(o):
        if isinstance(o, list):
            for x in o:
                walk(x)
        elif isinstance(o, dict):
            if o.get("type") in ("image_url", "input_image"):
                u = o.get("image_url")
                u = u.get("url") if isinstance(u, dict) else u
                if isinstance(u, str) and u.startswith("data:") and "," in u:
                    raw = base64.b64decode(u.split(",", 1)[1])
                    d = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "mime": u[5:u.index(";")] if ";" in u else ""}
                    try:   # what the pixels ARE (the app re-encodes to JPEG, so the hash differs from the source file): size and mean colour
                        import io as _io
                        from PIL import Image, ImageStat
                        im = Image.open(_io.BytesIO(raw)).convert("RGB")
                        d.update(size=list(im.size), mean=[round(v) for v in ImageStat.Stat(im).mean])
                    except Exception:
                        pass
                    out.append(d)
            for v in o.values():
                if isinstance(v, (list, dict)):
                    walk(v)
    for m in msgs:
        walk(m.get("content"))
    return out



# ---- scripted RESEARCH POLICY (ticket 05 plumbing tests). A user message containing RESEARCH_AGENT makes the mock behave like a small rule-based
# specialist: every next step is chosen from the OBSERVATIONS in the tool results so far (no fixed call sequence), so the tests can show that the
# backend lets an agent adapt. It is a scripted stand-in, NOT a model and never evidence of model quality.
TEXTILE = re.compile(r"(comforter|quilt|coverlet|bedspread|bedding|duvet|blanket|curtain|sheet set)", re.I)
QUERIES = ["queen quilted coverlet", "comforter set", "bedding set"]


def trace_since_last_user(msgs):
    idx = max(i for i, m in enumerate(msgs) if m["role"] == "user")
    calls, out = {}, []
    for m in msgs[idx + 1:]:
        if m["role"] == "assistant":
            for tc in m.get("tool_calls") or []:
                try:
                    calls[tc["id"]] = (tc["function"]["name"], json.loads(tc["function"]["arguments"] or "{}"))
                except ValueError:
                    calls[tc["id"]] = (tc["function"]["name"], {})
        elif m["role"] == "tool":
            name, args = calls.get(m.get("tool_call_id"), (m.get("name"), {}))
            content = m["content"] if isinstance(m["content"], str) else json.dumps(m["content"])
            try:
                res = json.loads(content)
            except ValueError:
                res = {"_text": content}
            out.append((name, args, res if isinstance(res, dict) else {"_list": res}))
    return out


def research_policy(msgs, names):
    tr = trace_since_last_user(msgs)
    say = lambda t: {"text": "[MOCK RESEARCH AGENT] " + t}
    call = lambda n, a: {"call": (n, a)}
    first = lambda n: next((t for t in tr if t[0] == n), None)
    if first("read_catalogue") is None:
        return call("read_catalogue", {})
    cat = first("read_catalogue")[2]
    if not cat.get("ok"):
        return say(f"BLOCKED by the catalogue: {cat.get('code')} - {cat.get('error')}")
    prod, merchant = cat["products"][0], cat["merchant"]
    loc_q = (merchant.get("market") or {}).get("location_query")
    if not loc_q:
        return say("BLOCKED: the catalogue gives no market location")
    locs = [t for t in tr if t[0] == "marketplace_locate"]
    if not locs:
        return call("marketplace_locate", {"query": loc_q})
    if not locs[-1][2].get("ok") or not locs[-1][2].get("locations"):
        return say(f"BLOCKED: location lookup failed ({locs[-1][2].get('code')})")
    searches = [t for t in tr if t[0] == "marketplace_search"]
    relevant = {}
    for _, _, r in searches:
        for l in r.get("listings") or []:
            if TEXTILE.search(l.get("title") or ""):
                relevant.setdefault(str(l["listing_id"]), l)
    if not relevant:
        used = [a.get("query") for _, a, _ in searches]
        if searches and searches[-1][2].get("code") == "allowance_exhausted":
            return say("BLOCKED: the research allowance is exhausted before any relevant listing was found")
        nxt = next((q for q in QUERIES if q not in used), None)
        if not nxt:
            return say("BLOCKED: no relevant listings for the queries tried: " + ", ".join(used))
        return call("marketplace_search", {"query": nxt, "location_no": 1, "condition": "new"})   # chosen from what the previous result showed
    items = {a["listing_id"]: r for n, a, r in tr if n == "marketplace_item"}
    ok_items = [l for l in relevant if items.get(l, {}).get("ok")]
    if len(ok_items) < 2:
        nxt = next((l for l in relevant if l not in items), None)
        if nxt:
            return call("marketplace_item", {"listing_id": nxt})
    chosen = ok_items[:2]
    photos = {a["listing_id"]: r for n, a, r in tr if n == "marketplace_photo"}
    for l in chosen:
        if l not in photos and (items[l]["listing"].get("photo_count") or relevant[l].get("has_photo_reference")):
            return call("marketplace_photo", {"listing_id": l})
    inspected = {a["image_id"]: r for n, a, r in tr if n == "inspect_image"}
    for l in chosen:
        if photos.get(l, {}).get("ok") and l not in inspected:
            return call("inspect_image", {"image_id": l})
    saves = [t for t in tr if t[0] == "save_listing_draft"]
    if not saves:
        if not chosen:
            return say("BLOCKED: no item details could be retrieved for the relevant listings")
        seen = [l for l in chosen if inspected.get(l, {}).get("ok") is not False and l in inspected]
        rat = [{"claim": f"A comparable new listing titled {relevant[l]['title']!r} shows an asking price of ${(relevant[l].get('price') or {}).get('amount')}.",
                "listing_ids": [l], "image_ids": [l] if l in seen else []} for l in chosen]
        spec = prod["specifications"]
        return call("save_listing_draft", {
            "product_id": prod["product_id"], "title": prod["name"] + ", " + spec.get("colour", ""),
            "description": f"A {spec.get('size', '')} quilted coverlet in {spec.get('colour', '')} with a {spec.get('material', '')}. {spec.get('care', '')}. "
                           f"Supplied as {spec.get('pieces', '')}, new. Price: ${prod['price']['amount']:g} {prod['price']['currency']}.",
            "visual_brief": "Shoot the coverlet fully made up on a bed against a plain light wall in daylight, add one close-up of the quilting and a folded stack "
                            "showing the colour. Keep the frame uncluttered so the product is the focus.",
            "rationale": rat, "limitations": "Asking prices only; no sales data. Scripted mock agent.", "evidence_source": "live_research",
            "image_observations": [{"image_id": l, "observations": f"Inspected the downloaded photo of listing {l} (scripted mock observation).",
                                   "uncertainties": "Fine detail not assessed."} for l in seen]})
    r = saves[-1][2]
    return say(f"Saved draft {r.get('draft_id')} status {r.get('status')}" if r.get("ok") else f"Draft NOT saved: {r.get('code')} - {r.get('error')}")


# ---- scripted AD-RESEARCH POLICY (V2-03 plumbing tests). A user message containing AD_AGENT makes the mock behave like a small rule-based social specialist:
# each next step is chosen from the OBSERVATIONS in the tool results so far (no fixed call chain): it refines its query when the results are not about
# textiles, skips ads of an already chosen campaign, and saves a blocked package when nothing relevant exists. Options in the message: FIRST_QUERY:<text>,
# VIA_ADVERTISER (look the advertiser up and search its ads), NO_INSPECT (cites images without inspecting them), UNSUPPORTED_CLAIM (writes a sales claim).
# A scripted stand-in, NOT a model and never evidence of model quality.
AD_QUERIES = ["queen quilted coverlet", "comforter set", "bedding set"]


def ad_policy(msgs, names, user):
    tr = trace_since_last_user(msgs)
    say = lambda t: {"text": "[MOCK AD AGENT] " + t}
    call = lambda n, a: {"call": (n, a)}
    first = lambda n: next((t for t in tr if t[0] == n), None)
    if first("read_catalogue") is None:
        return call("read_catalogue", {})
    m = re.search(r"FIRST_QUERY:(.+?)(?:\s+[A-Z_]{4,}|$)", user)   # option text up to the next ALL-CAPS option word
    wanted = [m.group(1).strip()] if m else []
    searches = [t for t in tr if t[0] == "fb_ads_search"]
    relevant = {}
    for _, _, r in searches:
        for a in r.get("ads") or []:
            if TEXTILE.search((a.get("text") or "") + " " + (a.get("headline") or "")):
                relevant.setdefault(a["ad_no"], a)
    if not relevant:
        used = [a.get("query") for _, a, _ in searches if a.get("query")]
        if searches and searches[-1][2].get("code") == "allowance_exhausted":
            nxt = None
        else:
            nxt = next((q for q in wanted + AD_QUERIES if q not in used), None)
        if nxt:
            return call("fb_ads_search", {"query": nxt})
        saves = [t for t in tr if t[0] == "save_ad_research"]
        if not saves:
            return call("save_ad_research", {"summary": "No relevant US Facebook image ads were found for the merchant's product after the queries tried: " + ", ".join(used) + ".",
                                             "selection_basis": "relevance_only", "references": [],
                                             "blocker": "Searched " + ", ".join(used) + "; the results were unrelated or empty, and the allowance does not allow more searching."})
        r = saves[-1][2]
        return say(f"BLOCKED: no relevant ads. Package {r.get('package_id')} status {r.get('status')}" if r.get("ok") else f"Package NOT saved: {r.get('code')}")
    if "VIA_ADVERTISER" in user and not first("fb_ads_find_advertiser"):
        return call("fb_ads_find_advertiser", {"query": next(iter(relevant.values()))["advertiser"]["name"]})
    fa = first("fb_ads_find_advertiser")
    if fa and fa[2].get("ok") and fa[2].get("advertisers") and not any(a.get("advertiser_no") for _, a, _ in searches):
        return call("fb_ads_search", {"advertiser_no": fa[2]["advertisers"][0]["advertiser_no"]})
    chosen, camps = [], set()
    for no, a in sorted(relevant.items()):
        cid = (a.get("campaign") or {}).get("campaign_id")
        if cid and cid in camps:
            continue
        camps.add(cid) if cid else None
        chosen.append(no)
    chosen = chosen[:2]
    details = {a["ad_no"]: r for n, a, r in tr if n == "fb_ad_detail"}
    for no in chosen:
        if no not in details:
            return call("fb_ad_detail", {"ad_no": no})
    ok = [no for no in chosen if details[no].get("ok")]
    images = {a["ad_no"]: r for n, a, r in tr if n == "fb_ad_image"}
    for no in ok:
        if no not in images and details[no]["ad"].get("images"):
            return call("fb_ad_image", {"ad_no": no, "image_no": details[no]["ad"]["images"][0]["image_no"]})
    got = [no for no in ok if images.get(no, {}).get("ok")]
    inspected = {a["image_id"]: r for n, a, r in tr if n == "inspect_image"}
    if "NO_INSPECT" not in user:
        for no in got:
            if images[no]["image_id"] not in inspected:
                return call("inspect_image", {"image_id": images[no]["image_id"]})
    saves = [t for t in tr if t[0] == "save_ad_research"]
    if not saves:
        last_gate = (details[ok[-1]].get("reach_gate") if ok else None) or {}
        refs = [{"ad_no": no, "image_id": images[no]["image_id"],
                 "why_relevant": f"A comparable quilted bedding ad from {relevant[no]['advertiser']['name']}: its layout shows what shoppers meet for this product type.",
                 "visual_features": ["product shown large against a plain backdrop", "short headline above the product"],
                 "observations": f"Inspected image {images[no]['image_id']} (scripted mock observation of the downloaded ad image).",
                 "uncertainties": "Fine detail and brand colours not assessed."} for no in got]
        if not refs:   # relevant ads were found but no image could be obtained and inspected (allowance, provider failure): an honest blocker, not a package of text
            errs = sorted({str(r.get("code")) for n, a, r in tr if n in ("fb_ad_detail", "fb_ad_image") and r.get("ok") is False})
            return call("save_ad_research", {"summary": "Relevant US Facebook image ads were found but none of their images could be retrieved and inspected, so there is no visual reference.",
                                             "selection_basis": "relevance_only", "references": [],
                                             "blocker": "Image retrieval or detail requests failed or were refused: " + (", ".join(errs) or "no image available") + "."})
        summary = "Researched US Facebook image ads for the merchant's quilted bedding; selected " + str(len(refs)) + " visual references from distinct campaigns."
        if "UNSUPPORTED_CLAIM" in user:
            summary += " The first ad clearly performed well and is a best seller."
        return call("save_ad_research", {"summary": summary, "selection_basis": "reach_ranked" if last_gate.get("ranking_enabled") else "relevance_only", "references": refs,
                                         "limitations": "Scripted mock agent; reach ranking depends on the gate."})
    r = saves[-1][2]
    return say(f"Saved package {r.get('package_id')} status {r.get('status')}" if r.get("ok") else f"Package NOT saved: {r.get('code')} - {r.get('error')}")


# ---- scripted FLYER POLICY (V2-04 plumbing tests). A user message containing FLYER_AGENT makes the mock behave like a small rule-based social specialist: read the
# catalogue, look at the selected merchant photos (unless NO_INSPECT), call generate_flyer ONCE and report exactly what the tool said. Options: PRODUCT:<id>,
# IMAGES:<id>,<id>, TWICE (a second generate_flyer call with the same arguments in the same request). A scripted stand-in, NOT a model.
def flyer_policy(msgs, names, user):
    tr = trace_since_last_user(msgs)
    def call(n, a):
        return {"call": (n, a)}
    cat = next((r for n, a, r in tr if n == "read_catalogue"), None)
    if cat is None:
        return call("read_catalogue", {})
    prods = cat.get("products") or []
    if not prods:
        return {"text": "[MOCK FLYER AGENT] The catalogue has no products: " + str(cat.get("error"))[:200]}
    m = re.search(r"PRODUCT:([\w-]+)", user)
    p = next((x for x in prods if m and x.get("product_id") == m.group(1)), prods[0])
    m = re.search(r"IMAGES:([\w,-]+)", user)
    ids = m.group(1).split(",") if m else [i["image_id"] for i in (p.get("images") or [])][:2]
    inspected = {a.get("image_id") for n, a, r in tr if n == "inspect_image"}
    if "NO_INSPECT" not in user:
        for iid in ids:
            if iid not in inspected:
                return call("inspect_image", {"image_id": iid})
    gens = [t for t in tr if t[0] == "generate_flyer"]
    if not gens:
        pr = p.get("price") or {}
        return call("generate_flyer", {"product_id": p["product_id"], "selected_product_image_ids": ids,
                                       "prompt": f"Create a clean promotional flyer for {p.get('name')}. Headline: {p.get('name')}. Show the price exactly as declared: "
                                                 f"{pr.get('amount')} {pr.get('currency')}. Keep the supplied product photo prominent on a plain backdrop with a short call to action."})
    if "TWICE" in user and len(gens) < 2:
        return call("generate_flyer", gens[0][1])
    r = gens[-1][2]
    return {"text": (f"[MOCK FLYER AGENT] Flyer {r.get('flyer_id')} status {r.get('status')} candidate {r.get('candidate_id')}" if r.get("ok")
                     else f"[MOCK FLYER AGENT] Flyer NOT generated: {r.get('code')} - {str(r.get('error'))[:160]}")}


# ---- scripted REVIEW POLICY (V2-05 plumbing tests). A user message containing REVIEW_AGENT makes the mock behave like a small rule-based social specialist for
# the whole goal: ad research (the ad policy above, until it ends), merchant photo inspection, ONE generate_flyer, inspect_flyer, review_flyer, at most ONE correction
# (generate_flyer with previous_candidate_id) and finalize_flyer. Its content judgement is PIXEL-DRIVEN on purpose: a candidate whose mean colour is strongly red
# (the stand-in Gemini's 'colors' control) is judged to show the wrong price, anything else passes; so the decision can only follow pixels that really reached it.
# Options: SKIP_ADS (no ad research), GENERATE_ANYWAY (generate even when the ad research is blocked), IMAGES:<id>,<id>, NO_CORRECT, PICK_FIRST (finalize the first
# candidate even if a second exists), TRY_THIRD (try a second correction), REVIEW_BLIND (call review_flyer without inspect_flyer), WRONG_HASH (echo a wrong hash),
# NO_FINALIZE, BATCH_REVIEW (inspect_flyer + review_flyer in one assistant message). A scripted stand-in, NOT a model and never evidence of model quality or of real visual accuracy.
def _is_red(img):
    m = (img or {}).get("mean") or [0, 0, 0]
    return m[0] > 150 and m[0] > m[1] + 60


def review_policy(msgs, names, user):
    tr = trace_since_last_user(msgs)
    say = lambda t: {"text": "[MOCK REVIEW AGENT] " + t}
    call = lambda n, a: {"call": (n, a)}
    if "SKIP_ADS" not in user:
        d = ad_policy(msgs, names, user)
        if "call" in d:
            return d
        if "BLOCKED" in d["text"] and "GENERATE_ANYWAY" not in user:
            return say(d["text"].replace("[MOCK AD AGENT] ", "") + " Flyer NOT generated: no relevant ad references were found, so there is nothing to base a flyer on.")
        if "NOT saved" in d["text"]:
            return say(d["text"].replace("[MOCK AD AGENT] ", ""))
    cat = next((r for n, a, r in tr if n == "read_catalogue"), None)
    if cat is None:
        return call("read_catalogue", {})
    prods = cat.get("products") or []
    if not prods:
        return say("Flyer NOT generated: the catalogue has no products: " + str(cat.get("error"))[:160])
    p = prods[0]
    m = re.search(r"IMAGES:([\w,-]+)", user)
    ids = m.group(1).split(",") if m else [i["image_id"] for i in (p.get("images") or [])][:2]
    inspected = {a.get("image_id") for n, a, r in tr if n == "inspect_image"}
    for iid in ids:
        if iid not in inspected:
            return call("inspect_image", {"image_id": iid})
    gens = [t for t in tr if t[0] == "generate_flyer"]
    if not gens:
        pr = p.get("price") or {}
        refs = [x["image_id"] for n, a, r in tr if n == "save_ad_research" for x in (a.get("references") or [])][:2]
        args = {"product_id": p["product_id"], "selected_product_image_ids": ids,
                "prompt": f"Create a clean promotional flyer for {p.get('name')}. Headline: {p.get('name')}. Show the price exactly as declared: {pr.get('amount')} "
                          f"{pr.get('currency')}. Keep the supplied product photo prominent on a plain backdrop with a short call to action."}
        if refs:
            args["reference_ad_image_ids"] = refs
        return call("generate_flyer", args)
    if gens[0][2].get("ok") is not True:
        return say(f"Flyer NOT generated: {gens[0][2].get('code')} - {str(gens[0][2].get('error'))[:160]}")
    # tool results that carried pixels: tool_call_id -> decoded images
    pix, names_by_id = {}, {}
    for mm in msgs[max(i for i, x in enumerate(msgs) if x["role"] == "user") + 1:]:
        if mm["role"] == "assistant":
            for tc in mm.get("tool_calls") or []:
                names_by_id[tc["id"]] = (tc["function"]["name"], json.loads(tc["function"]["arguments"] or "{}"))
        elif mm["role"] == "tool":
            nm, a = names_by_id.get(mm.get("tool_call_id"), (None, {}))
            if nm == "inspect_flyer":
                pix[a.get("candidate_id")] = image_parts([mm])
    cands = []   # candidates in the order generated: (candidate_id, generate result)
    for _, a, r in gens:
        if r.get("ok") is True and r.get("candidate_id") and r["candidate_id"] not in [c[0] for c in cands] and not r.get("cached"):
            cands.append((r["candidate_id"], r))
    reviews = {a.get("candidate_id"): (r, a) for n, a, r in tr if n == "review_flyer" and r.get("code") != "image_not_yet_delivered"}
    seen = {a.get("candidate_id") for n, a, r in tr if n == "inspect_flyer"}
    for cid, r in cands:
        if cid not in reviews:
            if "REVIEW_BLIND" not in user and cid not in seen:
                if "BATCH_REVIEW" in user:   # the defect under test: inspect and a (necessarily blind) review in ONE assistant tool-call batch
                    ok_ = {"result": "pass", "observation": "Fabricated in the same batch as the inspection, before any pixel was delivered (scripted)."}
                    return {"calls": [("inspect_flyer", {"candidate_id": cid}),
                                      ("review_flyer", {"candidate_id": cid, "candidate_sha256": (r.get("image") or {}).get("sha256", ""),
                                                        "checks": {n_: ok_ for n_ in ("product_appearance", "required_text_price", "layout_readability")}, "defects": [],
                                                        "summary": "Scripted same-batch review written without seeing the pixels."})]}
                return call("inspect_flyer", {"candidate_id": cid})
            img = (pix.get(cid) or [None])[0]
            red = _is_red(img)
            sha = "0" * 64 if "WRONG_HASH" in user else (r.get("image") or {}).get("sha256", "")
            if "REVIEW_BLIND" in user and cid not in pix:
                red = False
            ok = {"result": "pass", "observation": "The shown product matches the supplied photographs in colour and form (scripted observation from the delivered pixels)."}
            checks = {"product_appearance": ok, "required_text_price": ok, "layout_readability": ok}
            defects = []
            if red:
                checks["required_text_price"] = {"result": "fail", "observation": "The price shown on the flyer does not match the declared price (scripted observation)."}
                defects = [{"check": "required_text_price", "description": "The price on the flyer is not the declared price.",
                            "correction": "Show the price exactly as declared in the supplied facts and nothing else."}]
            return call("review_flyer", {"candidate_id": cid, "candidate_sha256": sha, "checks": checks, "defects": defects,
                                         "summary": "Scripted review of the candidate pixels: " + ("a defect was found." if red else "no defect observed."),
                                         "uncertainties": "Fine print and fabric texture are not judged."})
    first_rev = reviews.get(cands[0][0]) if cands else None
    if (first_rev and first_rev[0].get("verdict") == "defects_found" and len(cands) == 1 and "NO_CORRECT" not in user and len(gens) == 1):
        ds = first_rev[0].get("defects") or []
        return call("generate_flyer", {"previous_candidate_id": cands[0][0],
                                       "corrections": [{"defect_no": d["defect_no"], "instruction": d.get("correction") or "Show the declared price exactly."} for d in ds]})
    if len(gens) >= 2 and gens[1][2].get("ok") is not True and "wait" not in gens[1][2]:
        pass   # the correction failed: the first candidate stays the draft
    if "TRY_THIRD" in user and len(cands) == 2 and len(gens) == 2 and reviews.get(cands[1][0], ({},))[0].get("verdict") == "defects_found":
        return call("generate_flyer", {"previous_candidate_id": cands[1][0], "corrections": [{"defect_no": 1, "instruction": "Show the declared price exactly."}]})

    def score(c):
        r = (reviews.get(c[0]) or ({},))[0]
        return 0 if r.get("verdict") == "passed" else 1
    pick = cands[0] if ("PICK_FIRST" in user or len(cands) == 1) else sorted(cands, key=score)[0]
    fins = [t for t in tr if t[0] == "finalize_flyer"]
    if not fins and "NO_FINALIZE" not in user:
        return call("finalize_flyer", {"candidate_id": pick[0], "rationale": "Selected the candidate whose review result was best; reviewer decisions are fallible and nobody has approved it."})
    last = (fins[-1][2] if fins else reviews.get(pick[0], ({},))[0]) or {}
    fid = (gens[0][2] or {}).get("flyer_id")
    return say(f"Flyer {fid} status {last.get('status')} candidate {pick[0]}" if last.get("ok", True) else f"Flyer {fid} NOT finalized: {last.get('code')}")


def decide(body):
    STATS["requests"] += 1; STATS["last_model"] = body.get("model", "")
    if body["messages"][-1]["role"] == "user" and "SLOW" in json.dumps(body["messages"][-1]["content"]):
        STATS["slow"] += 1; time.sleep(float(__import__("os").environ.get("MOCK_SLOW_S", "25")))

    msgs, names = body["messages"], [t["function"]["name"] for t in body.get("tools") or []]
    last = msgs[-1]
    imgs = image_parts(msgs)
    STATS["last_images"] = imgs
    STATS["image_requests"] += bool(imgs)
    if imgs:
        STATS["image_log"].append({"request": STATS["requests"], "images": imgs})   # which pixels reached the model, per request (lineage checks)
    _users = [m for m in msgs if m["role"] == "user"]
    if _users and "RESEARCH_AGENT" in json.dumps(_users[-1]["content"]):
        return research_policy(msgs, names)
    if _users and "REVIEW_AGENT" in json.dumps(_users[-1]["content"]):
        u = _users[-1]["content"]
        return review_policy(msgs, names, u if isinstance(u, str) else json.dumps(u))
    if _users and "FLYER_AGENT" in json.dumps(_users[-1]["content"]):
        u = _users[-1]["content"]
        return flyer_policy(msgs, names, u if isinstance(u, str) else json.dumps(u))
    if _users and "AD_AGENT" in json.dumps(_users[-1]["content"]):
        u = _users[-1]["content"]
        return ad_policy(msgs, names, u if isinstance(u, str) else json.dumps(u))
    if last["role"] == "tool":
        return {"text": f"[MOCK LLM] tool finished; images_in_request={len(imgs)}: " + str(last["content"])[:400]}
    user = next((m["content"] for m in reversed(msgs) if m["role"] == "user"), "")
    user = user if isinstance(user, str) else json.dumps(user)
    STATS["routing_ctx_seen"] += ("[Routing context from the app backend" in user)
    sysmsg = msgs[0]["content"] if isinstance(msgs[0]["content"], str) else ""
    if "CALL_TOOL:" in user:   # generic scripted call: CALL_TOOL:{"name": "...", "args": {...}} (tests control the arguments exactly)
        try:
            spec, _ = json.JSONDecoder().raw_decode(user[user.index("CALL_TOOL:") + len("CALL_TOOL:"):].lstrip())
            if spec.get("name") in names:
                return {"call": (spec["name"], spec.get("args", {}))}
            return {"text": f"[MOCK LLM] tool {spec.get('name')} is not available; tools are {names}"}
        except ValueError:
            pass
    if "update_company" in names:   # behave like a model that saves what the user stated (and nothing else)
        import re as _re
        fields = {}
        m = _re.search(r"company is called ([A-Z][\w &'-]+?)[.\n]", user)
        if m: fields["name"] = m.group(1).strip()
        m = _re.search(r"We sell (.+?) to (.+?)[.\n]", user)
        if m: fields.update(products=m.group(1).strip(), customers=m.group(2).strip())
        m = _re.search(r"[Oo]ur goal is (?:to )?(.+?)[.\n]", user)
        if m: fields["goal"] = m.group(1).strip()
        m = _re.search(r"Women aged ([\w -]+ in the UK)", user)
        if m: fields["customers"] = "Women aged " + m.group(1)
        if fields:
            return {"call": ("update_company", fields)}
    if "create_agent" in names and ("create_social_agent" in user or "SOCIAL_ROLE" in user):   # scripted stand-in: a social_media specialist (V2-01)
        return {"call": ("create_agent", SOCIAL_ARGS)}
    if "create_agent" in names and "DEMO_CREATE_RESEARCH" in user:   # the V1 demonstration: main creates a research-capable specialist (scripted stand-in)
        return {"call": ("create_agent", {
            "role": "market_analysis", "name": "Acme Listing Researcher",
            "objective": "Research comparable new bedding on Facebook Marketplace near Dallas and save one accurate, source-linked listing draft for the merchant's catalogue product.",
            "instructions": "You work for Acme Linens, a fictional demo merchant. Research Facebook Marketplace read-only within your backend allowance, choose the comparables "
                            "and photos yourself, use only supplied product facts and say what you could not verify.",
            "skills": [{"name": "marketplace-listing-routine", "content": "# Listing routine\n1. Read the catalogue product.\n2. Locate the market, search, compare, "
                        "inspect the photos you rely on.\n3. Save one draft and report limits."}],
            "requested_tools": ["marketplace_locate", "marketplace_search", "marketplace_item", "marketplace_photo", "inspect_image", "read_catalogue",
                                "save_listing_draft"]})}
    if "create_agent" in names and "BAD_ROLE" in user:
        return {"call": ("create_agent", {**AGENT_ARGS, "role": "seo_expert"})}
    if "create_agent" in names and "BAD_TOOL" in user:
        return {"call": ("create_agent", {**AGENT_ARGS, "requested_tools": ["web_search"]})}
    if "create_agent" in names and "market" in user.lower():
        return {"call": ("create_agent", AGENT_ARGS)}
    if "memory" in names and "remember:" in user.lower():
        return {"call": ("memory", {"action": "add", "target": "user", "content": user.split(":", 1)[1].strip()})}
    if "PURPLE-OTTER" in sysmsg:
        return {"text": "[MOCK LLM] From my memory: you want reports signed off with PURPLE-OTTER."}
    return {"text": f"[MOCK LLM] hello; I can see {len(msgs)} messages and tools {names}"}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(json.dumps(STATS if self.path.startswith("/stats") else {"data": [{"id": "mock"}]}).encode())
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _users = [m for m in body["messages"] if m["role"] == "user"]
        if _users and "LLM_500" in json.dumps(_users[-1]["content"]):   # a provider that answers every request with HTTP 500 (counts retry behaviour)
            STATS["requests"] += 1
            STATS["failed_500"] = STATS.get("failed_500", 0) + 1
            raw = json.dumps({"error": {"message": "scripted server error", "type": "server_error"}}).encode()
            self.send_response(500); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw); return
        if _users and "REJECT_IMAGES" in json.dumps(_users[-1]["content"]) and image_parts(body["messages"]):   # a provider that 400s on list-type tool content
            STATS["rejected_image_requests"] += 1
            raw = json.dumps({"error": {"message": "text is not set", "type": "invalid_request_error"}}).encode()
            self.send_response(400); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw); return
        d, cid, stream = decide(body), "chatcmpl-" + uuid.uuid4().hex[:8], body.get("stream")
        if len(d.get("calls", [])) > 1:
            STATS["batches"].append([c_[0] for c_ in d["calls"]])   # tool-call batches (several calls in ONE assistant message)
        msg = {"role": "assistant", "content": d.get("text")}
        for c_ in ([d["call"]] if "call" in d else d.get("calls", [])):
            msg.setdefault("tool_calls", []).append({"id": "call_" + uuid.uuid4().hex[:6], "type": "function",
                                                     "function": {"name": c_[0], "arguments": json.dumps(c_[1])}})
        fin = "tool_calls" if msg.get("tool_calls") else "stop"
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        if not stream:
            out = {"id": cid, "object": "chat.completion", "created": int(time.time()), "model": body.get("model"),
                   "choices": [{"index": 0, "message": msg, "finish_reason": fin}], "usage": usage}
            raw = json.dumps(out).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw); return
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
        def ev(delta, f=None, u=None):
            c = {"id": cid, "object": "chat.completion.chunk", "created": int(time.time()), "model": body.get("model"),
                 "choices": [{"index": 0, "delta": delta, "finish_reason": f}]}
            if u: c["usage"] = u
            self.wfile.write(b"data: " + json.dumps(c).encode() + b"\n\n"); self.wfile.flush()
        ev({"role": "assistant", "content": ""})
        if d.get("text"): ev({"content": d["text"]})
        for i_, tc in enumerate(msg.get("tool_calls") or []):
            ev({"tool_calls": [{"index": i_, **tc}]})
        ev({}, fin, usage)
        self.wfile.write(b"data: [DONE]\n\n"); self.wfile.flush()


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 8765), H).serve_forever()
