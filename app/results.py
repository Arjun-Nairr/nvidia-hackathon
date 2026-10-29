"""Saved results as chat cards (UI-02): listing drafts, Facebook ad-research packages and generated flyers, read from what the backend STORED and tied to the conversation message that produced them.

Association is backend-owned and never guessed: a result belongs to the user message whose id the tool run recorded when it was created (research / ad / flyer runs, and the request/message
columns of newer drafts; older drafts are reached through their research run). A message id counts only when that message exists, is a USER message and belongs to the SAME agent; otherwise
the card is returned with message_id None and associated False, and the page lists it separately instead of attaching it to anything. Nothing here parses model prose or picks the
"latest" result. Cards hold only displayable text (no hashes, run/candidate ids, tool payloads or provider data) plus an internal `key`; links are limited to http(s). The text is
returned as stored (plain strings): the page escapes it, nothing is rewritten here.
Read-only: no model, provider or paid call, no accounting change."""
import re
from urllib.parse import urlsplit
from app import ads, core, flyer, listing

STATUS_TEXT = {"agent_review_passed": "Automated review passed - not human approval", "unresolved_issues": "Unapproved draft with unresolved issues", "unchecked": "Not reviewed",
               "awaiting_selection": "Two candidates, none selected as final", "storage_failure": "The saved image failed its integrity check", "failed": "Generation failed",
               "in_progress_or_unknown": "Outcome unknown - it is not repeated automatically", "no_attempt": "No attempt was made"}
SELECTION = {"relevance_only": "Chosen by relevance; reach ranking was not available."}
CHECKS = {"product_appearance": "Product matches the photos", "required_text_price": "Required text and price", "layout_readability": "Layout and readability"}
RESULT_WORD = {"pass": "passed", "fail": "failed", "uncertain": "uncertain"}


def safe_url(u):
    """The URL when it is a plain http(s) link with a host, else None (javascript:, data:, relative and malformed values are never offered as links)."""
    if not isinstance(u, str):
        return None
    u = u.strip()
    if not u or len(u) > 500 or re.search(r"[\s\x00-\x1f\x7f]", u):
        return None
    try:
        p = urlsplit(u)
    except ValueError:
        return None
    return u if p.scheme in ("http", "https") and p.netloc else None


def _text(v, n=600):
    return "" if v is None else str(v).strip()[:n]


def _identity(d, agent_id, request_id, message_id):
    """-> (request_id, message_id or None, associated). The message must be a USER message of this same agent."""
    ok = False
    if isinstance(message_id, int) and not isinstance(message_id, bool):
        m = d.execute("SELECT agent_id, who FROM messages WHERE id=?", (message_id,)).fetchone()
        ok = bool(m and m["agent_id"] == agent_id and m["who"] == "user")
    return request_id, (message_id if ok else None), ok


def _card(kind, key, agent_id, ident, created_at, heading, status, status_text, **parts):
    request_id, message_id, ok = ident
    return {"key": f"{kind}:{key}", "kind": kind, "agent_id": agent_id, "request_id": request_id, "message_id": message_id, "associated": ok, "created_at": created_at,
            "heading": heading, "status": status, "status_text": status_text, "fields": parts.get("fields", []), "issues": parts.get("issues", []), "image": parts.get("image"),
            "error": parts.get("error"), "sources": parts.get("sources", []), "details": parts.get("details", [])}


def _draft_card(d, r):
    full = listing.get_draft(r["draft_id"])
    run = d.execute("SELECT request_id, message_id FROM research_runs WHERE run_id=?", (r["research_run_id"],)).fetchone() if r["research_run_id"] else None
    req, mid = r["request_id"], r["message_id"]
    if mid is None and run:   # drafts saved before the identity columns existed: the research run of the same request carries the identity
        req, mid = run["request_id"], run["message_id"]
    live = full["evidence_source"] == "live_research"
    listings, photos = full["listing_evidence"], [i for i in full["image_evidence"] if "listing_photo" in str(i.get("kind"))]
    sources = []
    for x in listings:
        u = safe_url(x.get("source_url"))
        if u:
            price = x.get("price") or {}
            label = " - ".join(p for p in (_text(x.get("title"), 120), ", ".join(p for p in (_text(price.get("formatted")) if isinstance(price, dict) else "", _text(x.get("location"), 60)) if p)) if p)
            sources.append({"label": label or u, "url": u})
    ps = full["product_snapshot"].get("source_url") if isinstance(full.get("product_snapshot"), dict) else None
    if safe_url(ps):
        sources.append({"label": "Product source (catalogue)", "url": ps})
    claims = [_text(c.get("claim"), 300) for c in full["rationale"] if isinstance(c, dict) and c.get("claim")]
    seen = [f"{_text(i.get('model_observations'), 260)}" for i in photos if i.get("model_observations")]
    details = [{"label": "Evidence", "text": (f"Live Facebook Marketplace research: {len(listings)} listings cited, {len(photos)} photos inspected." if live
                                             else "Recorded sample listings (a replayed sample, not live research).")}]
    if claims:
        details.append({"label": "Why this draft looks the way it does", "text": "\n".join(claims)})
    if seen:
        details.append({"label": "What the competitor photos showed", "text": "\n".join(seen)})
    if full.get("limitations"):
        details.append({"label": "Limitations", "text": _text(full["limitations"], 800)})
    status = full["status"]
    snap = full["merchant_snapshot"] if isinstance(full.get("merchant_snapshot"), dict) else {}
    notice = _text(snap.get("notice"), 500)
    demo = [{"label": "Demonstration", "text": notice or "This draft was made from demonstration data, not a real retail offer."}] if (notice or snap.get("demo")) else []   # the STORED catalogue status, shown whatever the model wrote
    return _card("listing_draft", r["draft_id"], r["agent_id"], _identity(d, r["agent_id"], req, mid), r["created_at"], _text(full["title"], 200) or "Listing draft", status,
                 "Listing draft" if status == "complete" else "Partial listing draft",
                 fields=demo + [{"label": "Description", "text": _text(full["description"], 2000)}, {"label": "Photo direction", "text": _text(full["visual_brief"], 1200)}],
                 issues=[_text(m, 300) for m in full["missing"]], sources=sources, details=details)


def _package_card(d, r):
    full = ads.get_package(r["package_id"])
    run = d.execute("SELECT message_id FROM ad_runs WHERE run_id=?", (r["run_id"],)).fetchone()
    cited = {c.get("source_ad_id"): c for c in full["cited_ads"]}
    lines, learn, sources = [], [], []
    for ref in full["references"]:
        c = cited.get(ref.get("source_ad_id")) or {}
        name = _text((c.get("advertiser") or {}).get("name"), 80) or "Advertiser"
        why = _text(ref.get("why_relevant"), 300)
        lines.append(f"{name}: {why}" if why else name)
        feats = ref.get("visual_features")
        feats = "; ".join(_text(f, 80) for f in feats) if isinstance(feats, list) else _text(feats, 300)
        if feats:
            learn.append(f"{name}: {feats}")
    for c in full["cited_ads"]:
        u = safe_url(c.get("source_url"))
        if u:
            sources.append({"label": f"{_text((c.get('advertiser') or {}).get('name'), 80) or 'Advertiser'} - Facebook Ad Library", "url": u})
    gate = full["reach_gate"]
    basis = SELECTION.get(full["selection_basis"], "Chosen with the reach information the backend allowed." if gate.get("ranking_enabled") else "Chosen by relevance.")
    fields = [{"label": "Summary", "text": _text(full["summary"], 900)}]
    if lines:
        fields.append({"label": "References inspected", "text": "\n".join(lines)})
    fields.append({"label": "Selection", "text": basis})
    details = []
    if learn:
        details.append({"label": "Features worth learning from", "text": "\n".join(learn)})
    if full.get("limitations"):
        details.append({"label": "Limitations", "text": _text(full["limitations"], 800)})
    details.append({"label": "Coverage", "text": f"{full['counts']['ads_recorded']} ads recorded, {full['counts']['references']} inspected in full; reach: {_text(gate.get('reason'), 200) or 'not available'}"})
    return _card("ad_research", r["package_id"], r["agent_id"], _identity(d, r["agent_id"], r["request_id"], run["message_id"] if run else None), r["created_at"], "Facebook ad research",
                 full["status"], "Ad research" if full["status"] == "complete" else "Partial ad research" if full["status"] == "partial" else "Ad research blocked",
                 fields=fields, issues=[f"Blocked: {_text(full['blocker'], 300)}"] if full.get("blocker") else [], sources=sources, details=details)


def _flyer_card(d, s, message_id, created_at):
    st = s["status"]
    img = s.get("image")
    issues = [f"{CHECKS.get(i.get('check'), _text(i.get('check'), 40))}: {_text(i.get('description'), 400)}" for i in s.get("unresolved_issues") or []]
    rv = s.get("review")
    details = []
    if rv:
        for name, c in (rv.get("checks") or {}).items():
            details.append({"label": CHECKS.get(name, name), "text": f"{RESULT_WORD.get(c.get('result'), c.get('result'))}: {_text(c.get('observation'), 400)}"})
        if rv.get("uncertainties"):
            details.append({"label": "What the review could not establish", "text": _text(rv["uncertainties"], 400)})
        if not rv.get("verified"):
            details.append({"label": "Review status", "text": "The image was not confirmed delivered to the reviewing model, so this is not a completed visual review."})
    fin = s.get("final") or {}
    if fin.get("rationale"):
        details.append({"label": "Why this version was chosen", "text": _text(fin["rationale"], 400)})
    if s.get("candidates_total", 0) > 1:
        details.append({"label": "Attempts", "text": f"{s['candidates_total']} versions were generated" + (" (one correction)." if s.get("correction_used") else ".")})
    if s.get("inputs_synthetic"):
        details.append({"label": "Test input", "text": "The inputs were synthetic test stand-ins."})
    damaged = [_text(x.get("problem"), 200) for x in s.get("damaged_candidates") or [] if isinstance(x, dict)]
    if damaged and st != "storage_failure":   # a usable candidate stands, but another saved one failed its integrity check: say so without its internal id (nothing was regenerated or selected)
        issues.append(("Another saved version" if len(damaged) == 1 else f"{len(damaged)} other saved versions") + f" of this flyer failed the integrity check ({'; '.join(dict.fromkeys(damaged))}) and cannot be used. "
                      "It was not generated again and no final version was selected.")
    fields = []
    if st == "agent_review_passed":   # a pass is a fallible automated check, never a statement that nothing is wrong
        fields.append({"label": "Check it yourself", "text": "The automated review can miss problems. Look at the image before using it."})
    if s.get("note") and st in ("unchecked", "awaiting_selection", "storage_failure"):
        fields.append({"label": "Note", "text": _text(re.split(r"\s*Candidate \S+ cannot be used", s["note"])[0], 500)})   # the damaged-candidate sentence (it names an id) is the issue above
    card = _card("flyer", s["flyer_id"], s["agent_id"], (s["request_id"], None, False), created_at, "Generated flyer", st, STATUS_TEXT.get(st, st), fields=fields, issues=issues,
                 image=({"url": img["url"], "width": img.get("width"), "height": img.get("height"), "alt": "Generated flyer"} if img else None), error=_text(s.get("error"), 500) or None, details=details)
    card["_message_id"] = message_id
    return card


def cards(agent_id):
    """Every saved result of one agent as cards, oldest first. See the module docstring for the association rules."""
    out = []
    with core.db() as d:
        for r in d.execute("SELECT * FROM listing_drafts WHERE agent_id=?", (agent_id,)).fetchall():
            out.append(_draft_card(d, r))
        for r in d.execute("SELECT * FROM ad_packages WHERE agent_id=?", (agent_id,)).fetchall():
            out.append(_package_card(d, r))
        runs = {r["run_id"]: r for r in d.execute("SELECT run_id, request_id, message_id, created_at FROM flyer_runs WHERE agent_id=?", (agent_id,)).fetchall()}
        for s in flyer.list_flyers(agent_id):
            run = runs.get(s["flyer_id"])
            c = _flyer_card(d, s, run["message_id"] if run else None, run["created_at"] if run else 0)
            c["request_id"], c["message_id"], c["associated"] = _identity(d, agent_id, run["request_id"] if run else None, c.pop("_message_id"))
            out.append(c)
    return sorted(out, key=lambda c: (c["created_at"] or 0, c["key"]))
