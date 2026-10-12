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

STATS = {"requests": 0, "slow": 0, "last_model": "", "routing_ctx_seen": 0, "image_requests": 0, "last_images": [], "image_log": []}


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
        d, cid, stream = decide(body), "chatcmpl-" + uuid.uuid4().hex[:8], body.get("stream")
        msg = {"role": "assistant", "content": d.get("text")}
        if "call" in d:
            msg["tool_calls"] = [{"id": "call_" + uuid.uuid4().hex[:6], "type": "function",
                                  "function": {"name": d["call"][0], "arguments": json.dumps(d["call"][1])}}]
        fin = "tool_calls" if "call" in d else "stop"
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
        if "call" in d:
            tc = msg["tool_calls"][0]; tc = {"index": 0, **tc}
            ev({"tool_calls": [tc]})
        ev({}, fin, usage)
        self.wfile.write(b"data: [DONE]\n\n"); self.wfile.flush()


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 8765), H).serve_forever()
