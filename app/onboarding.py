"""Minimal onboarding (batch A, tickets 01 + 02): ONE prepared demo website snapshot -> main's summary + five questions -> the operator's answers -> the existing shared
company context -> chat unlock. Backend-owned and UI-independent; the plain form in app/static only displays this state.

States (one row, persisted in SQLite): no row = not_started -> awaiting_source -> awaiting_answers -> ready.
Chat and the manual company-save route are refused until ready (app/server.py asks chat_blocked()), EXCEPT on an existing business that has not started onboarding (see _existing_business):
a fresh installation starts locked, an existing one stays usable until the operator explicitly starts onboarding.
Main is asked through the existing Hermes worker (core.run_turn, own conversation, NO route: create_agent and update_company stay refused), never scripted here.
Model output is validated; a failure is stored and reported, never retried automatically. Results are persisted, so reload/restart/repeat never calls the model again."""
import hashlib, json, os, re, threading, time
from pathlib import Path
from app import core

DEMO_URL = "https://northloom-demo.example.com"      # the ONE registered demo source (a reserved example domain: no real website exists or is fetched)
SNAPSHOT_ID = "northloom-demo-2026-10"
NOTICE = ("Prepared demo material: this is a locally saved, fictional website snapshot for the Northloom Demo Studio demo. No real website is fetched or implied.")
CONV = "onboarding-main"                             # main's separate Hermes conversation for these two turns (keeps the ordinary main chat history clean)
TOPICS = ("products", "customers", "goal", "brand", "other")
N_QUESTIONS = 5
TURN_TIMEOUT = 240
ROLES = [{"role": "market_analysis", "name": "Market analyst",
          "what": "Looks at competitor products, prices and listings and recommends changes to your products or offers. Today it works from Facebook Marketplace research and listing drafts."},
         {"role": "social_media", "name": "Social-media specialist",
          "what": "Researches US Facebook image ads, then creates and reviews a promotional flyer from your own product photographs. Nothing is posted."}]
_lock = threading.Lock()   # one onboarding model call at a time: a repeated or concurrent submit finds the stored result instead of calling the model again

_SCHEMA = ("CREATE TABLE IF NOT EXISTS onboarding(id INTEGER PRIMARY KEY CHECK (id = 1), state TEXT, url TEXT, snapshot_id TEXT, snapshot_sha256 TEXT, summary TEXT, "
           "questions_json TEXT, answers_json TEXT, correction TEXT, context_json TEXT, provenance_json TEXT, error TEXT, created_at REAL, updated_at REAL)")


def snapshot_path():
    return Path(os.environ.get("ECOM_ONBOARDING_SNAPSHOT") or core.ROOT / "app" / "demo_snapshots" / "northloom-demo.example.com.txt")   # env override: isolated tests only


def _row():
    with core.db() as d:
        d.execute(_SCHEMA)
        r = d.execute("SELECT * FROM onboarding WHERE id=1").fetchone()
    return dict(r) if r else None


def _save(**cols):
    cols["updated_at"] = time.time()
    with core.db() as d:
        d.execute(_SCHEMA)
        if d.execute("SELECT 1 FROM onboarding WHERE id=1").fetchone():
            d.execute("UPDATE onboarding SET " + ", ".join(f"{k}=?" for k in cols) + " WHERE id=1", tuple(cols.values()))
        else:
            cols.setdefault("created_at", time.time())
            d.execute("INSERT INTO onboarding(id, " + ", ".join(cols) + ") VALUES(1, " + ", ".join("?" for _ in cols) + ")", tuple(cols.values()))


def _existing_business():
    """The compatibility rule: a runtime already holds a business when it has a saved company name, a specialist, or any chat message. Start-up creates none of these
    (profiles, config files, the lock file and empty tables do not count), so a fresh installation is never mistaken for an existing one."""
    if os.environ.get("ECOM_ASSUME_EXISTING_RUNTIME") == "1":   # test copies only: older suites start on an empty runtime and predate onboarding; never set in a real run
        return True
    if core.load_company().get("name", "").strip():
        return True
    with core.db() as d:
        return bool(d.execute("SELECT 1 FROM agents LIMIT 1").fetchone() or d.execute("SELECT 1 FROM messages LIMIT 1").fetchone())


def chat_blocked():
    """True until onboarding is complete. With no row it is true only for a fresh installation; an existing business is never blocked until it starts onboarding."""
    r = _row()
    return r["state"] != "ready" if r else not _existing_business()


def _fail(code, message, status, retryable=False, **extra):
    return status, {"ok": False, "code": code, "error": message, "retryable": retryable, **extra}


def status():
    r = _row()
    if not r:
        fresh = not _existing_business()
        return {"ok": True, "state": "not_started", "chat_unlocked": not fresh, "required": fresh, "registered_url": DEMO_URL, "notice": NOTICE}
    out = {"ok": True, "state": r["state"], "chat_unlocked": r["state"] == "ready", "registered_url": DEMO_URL, "notice": NOTICE, "url": r["url"], "error": r["error"]}
    if r["state"] in ("awaiting_answers", "ready"):
        out.update(summary=r["summary"], questions=json.loads(r["questions_json"]), snapshot_id=r["snapshot_id"])
    if r["state"] == "ready":
        out.update(answers=json.loads(r["answers_json"]), correction=r["correction"] or "", context=json.loads(r["context_json"]), provenance=json.loads(r["provenance_json"]),
                   roles=ROLES, roles_note="Saving your answers created no specialist. Ask the main agent in chat for the one you want.")
    return out


def start():
    if _row():   # already started: read-only, so it never waits behind a running model call
        return 200, status()
    with _lock:
        if not _row():
            _save(state="awaiting_source")
        return 200, status()


def normalize_url(u):
    u = (u or "").strip() if isinstance(u, str) else ""
    if not u or len(u) > 200:
        return None
    if not re.match(r"https?://", u, re.I):
        u = "https://" + u
    m = re.fullmatch(r"https?://([A-Za-z0-9.-]+)(?::443)?/?", u, re.I)
    return f"https://{m.group(1).lower()}" if m else None


def _json_object(text):
    """The first JSON object in the model's reply (tolerates a code fence or a short lead-in); None when there is none."""
    s = (text or "").strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s)
    i = s.find("{")
    if i < 0:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(s[i:])
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def _ask_main(message):
    """ONE turn on main's existing Hermes worker. No route is passed, so create_agent and update_company are refused for this turn (fail closed)."""
    r = core.run_turn("main", message, timeout=TURN_TIMEOUT, conv_override=CONV)
    if r.get("error"):
        return None, r["error"]
    return r.get("text") or "", None


def _text(v, lo, hi):
    return isinstance(v, str) and lo <= len(v.strip()) <= hi


def validate_source_output(obj):
    """-> (summary, questions, None) or (None, None, why). Exactly five questions with ids q1..q5, 2-4 options each, at least one goal question."""
    if not isinstance(obj, dict) or set(obj) - {"summary", "questions"}:
        return None, None, "the reply must be one JSON object with only 'summary' and 'questions'"
    if not _text(obj.get("summary"), 60, 900):
        return None, None, "'summary' must be 60-900 characters"
    qs = obj.get("questions")
    if not isinstance(qs, list) or len(qs) != N_QUESTIONS:
        return None, None, f"'questions' must be a list of exactly {N_QUESTIONS}"
    clean = []
    for n, q in enumerate(qs, 1):
        if not isinstance(q, dict) or set(q) != {"id", "topic", "question", "options"}:
            return None, None, f"question {n} must have exactly id, topic, question and options"
        if q["id"] != f"q{n}" or q["topic"] not in TOPICS or not _text(q["question"], 10, 200):
            return None, None, f"question {n} has a bad id, topic or text"
        opts = q["options"]
        if (not isinstance(opts, list) or not 2 <= len(opts) <= 4 or any(not _text(o, 2, 80) for o in opts)
                or len({o.strip().lower() for o in opts}) != len(opts)):
            return None, None, f"question {n} needs 2-4 distinct short options"
        if re.search(r"password|credit card|card number|api key|social security|bank account", q["question"], re.I):
            return None, None, f"question {n} asks for sensitive data"
        clean.append({"id": q["id"], "topic": q["topic"], "question": q["question"].strip(), "options": [o.strip() for o in opts]})
    if not any(q["topic"] == "goal" for q in clean):
        return None, None, "at least one question must have topic 'goal'"
    return obj["summary"].strip(), clean, None


SOURCE_PROMPT = (
    "[ONBOARDING TASK: SOURCE SUMMARY]\n"
    "You are the main agent onboarding the demo operator's business. Below is a PREPARED DEMO WEBSITE SNAPSHOT: fictional demonstration material saved locally, NOT fetched from a live "
    "website. Use ONLY this text. Do not call any tool. Do not invent facts, prices, availability or goals.\n"
    "Reply with ONE JSON object and nothing else:\n"
    '{"summary": "<60-900 characters: what the business is and offers, from the snapshot only, saying it comes from the prepared demo snapshot>", '
    '"questions": [{"id": "q1", "topic": "products|customers|goal|brand|other", "question": "<10-200 characters>", "options": ["<2-80 chars>", "..."]}, ...]}\n'
    f"Rules: exactly {N_QUESTIONS} questions with ids q1..q{N_QUESTIONS}; each has 2-4 short, distinct answer options that follow from the snapshot (the operator can also write their own "
    "answer, so do not add an 'other' option); at least one question has topic \"goal\" and asks what the operator wants their specialists to help with (never state a goal as a fact); "
    "ask about the products, the customers and the brand tone where the snapshot allows; never ask for passwords, payment or other sensitive data.\n"
    "SNAPSHOT (url {url}):\n---\n{text}\n---")


def submit_source(url):
    with _lock:
        r = _row()
        if not r:
            return _fail("not_started", "Onboarding has not been started. Start it first.", 409)
        nurl = normalize_url(url)
        if r["state"] == "ready":
            return _fail("already_ready", "Onboarding is already complete.", 409)
        if r["state"] == "awaiting_answers":   # stored result: no model call
            return (200, {**status(), "replayed": True}) if nurl == r["url"] else _fail("source_already_set", f"The source for this onboarding is already set ({r['url']}).", 409)
        if nurl != DEMO_URL:
            return _fail("unknown_source", f"Only the prepared demo website {DEMO_URL} is available in this demo. Nothing is fetched from other addresses.", 404, registered_url=DEMO_URL)
        try:
            raw = snapshot_path().read_bytes()
            text = raw.decode("utf-8")
        except (OSError, ValueError) as e:
            return _fail("snapshot_missing", f"The prepared demo snapshot could not be read ({type(e).__name__}).", 500)
        reply, e = _ask_main(SOURCE_PROMPT.replace("{url}", DEMO_URL).replace("{text}", text))
        if e:
            _save(error=f"The main agent could not answer: {e}"[:400])
            return _fail("generation_failed", f"The main agent could not read the snapshot ({e}). Nothing was saved; you can submit the link again.", 502, retryable=True)
        summary, questions, why = validate_source_output(_json_object(reply))
        if why:
            _save(error=f"Unusable model output: {why}"[:400])
            return _fail("invalid_model_output", f"The main agent's reply was not usable ({why}). Nothing was saved; you can submit the link again.", 502, retryable=True)
        _save(state="awaiting_answers", url=DEMO_URL, snapshot_id=SNAPSHOT_ID, snapshot_sha256=hashlib.sha256(raw).hexdigest(), summary=summary,
              questions_json=json.dumps(questions), error=None)
        return 200, status()


# ---------------------------------------------------------------- ticket 02: answers + corrections -> the existing shared company context -> chat unlock
CONTEXT_PROMPT = (
    "[ONBOARDING TASK: CONTEXT]\n"
    "You are the main agent. Combine the PREPARED DEMO SNAPSHOT facts with the operator's answers into the shared company context. Do not call any tool. Do not invent facts, prices, "
    "availability, goals or competitors; leave a field \"\" if neither the snapshot nor the operator says it. Do NOT write a goal: the backend takes goals only from the operator's own answers.\n"
    'Reply with ONE JSON object and nothing else, with exactly these text fields: {"name": "...", "products": "...", "customers": "...", "brand": "...", "competitors": ""}\n'
    "- name and products come from the snapshot unless the operator's answers or correction change them. customers and brand use the operator's answers where given, otherwise the snapshot. "
    "competitors only if the operator named some. If the operator corrected your summary, honour the correction over the snapshot.\n"
    "SUMMARY YOU GAVE: {summary}\nANSWERS (JSON): {answers}\nOPERATOR CORRECTION: {correction}\nSNAPSHOT (url {url}):\n---\n{text}\n---")


def validate_answers(questions, body):
    """-> (resolved answers in question order, correction, None) or (None, None, why). Every question needs exactly one of a listed option (choice) or a write-in."""
    if not isinstance(body, dict) or not isinstance(body.get("answers"), dict):
        return None, None, "send {\"answers\": {\"q1\": {\"choice\": 0} or {\"write_in\": \"...\"}, ...}, \"correction\": \"optional\"}"
    given, corr = body["answers"], body.get("correction", "")
    if not isinstance(corr, str) or len(corr.strip()) > 600:
        return None, None, "the correction must be text of at most 600 characters"
    if set(given) - {q["id"] for q in questions}:
        return None, None, "unknown question id in answers"
    out = []
    for q in questions:
        a = given.get(q["id"])
        if not isinstance(a, dict) or len(a) != 1 or next(iter(a)) not in ("choice", "write_in"):
            return None, None, f"question {q['id']} needs exactly one of 'choice' or 'write_in'"
        if "choice" in a:
            c = a["choice"]
            if isinstance(c, bool) or not isinstance(c, int) or not 0 <= c < len(q["options"]):
                return None, None, f"question {q['id']}: 'choice' must be the index of a listed option"
            out.append({"id": q["id"], "topic": q["topic"], "question": q["question"], "answer": q["options"][c], "kind": "option"})
        else:
            w = a["write_in"]
            w = " ".join(w.split()) if isinstance(w, str) else ""
            if not 2 <= len(w) <= 400 or w.lower().strip(" .!") in core.PLACEHOLDERS:
                return None, None, f"question {q['id']}: the write-in must be 2-400 characters of real text, not a placeholder"
            out.append({"id": q["id"], "topic": q["topic"], "question": q["question"], "answer": w, "kind": "write_in"})
    return out, " ".join(corr.split()), None


def validate_context_output(obj):
    """-> (fields, None) or (None, why). Main supplies name/products/customers/brand/competitors; any goal or website it adds is ignored (the backend owns those)."""
    if not isinstance(obj, dict):
        return None, "the reply must be one JSON object"
    extra = set(obj) - {"name", "products", "customers", "brand", "competitors", "goal", "website"}
    if extra:
        return None, f"unexpected field(s): {sorted(extra)}"
    fields = {}
    for k in ("name", "products", "customers", "brand", "competitors"):
        v = obj.get(k, "")
        if not isinstance(v, str):
            return None, f"'{k}' must be text"
        fields[k] = v.strip()
    missing = [k for k in ("name", "products", "customers") if not fields[k]]
    if missing:
        return None, f"empty required field(s): {missing}"
    return fields, None


def _provenance(resolved, fields, correction):
    """Conservative attribution. Main saw the snapshot AND every operator answer and correction, and its reply is not traceable field by field, so each field it supplied is labelled
    as combined (never source-only). Only the goal and the link are known exactly; the answers and correction themselves are stored word for word."""
    combined = "combined by main from the prepared demo snapshot and your answers or correction; may differ from the snapshot"
    pv = {"source": "prepared demo snapshot (fictional, saved locally, nothing was fetched)", "operator_input": "your answers and correction, kept word for word",
          "name": combined, "products": combined, "customers": combined, "brand": combined,
          "competitors": "named by you in your answers or correction, and combined by main" if fields.get("competitors") else "not provided",
          "goal": "your own answer (verbatim)", "website": "the registered demo link you entered"}
    if correction:
        pv["summary_correction"] = "your free text; main was told to honour it over the snapshot"
    return pv


def submit_answers(body):
    with _lock:
        r = _row()
        if not r:
            return _fail("not_started", "Onboarding has not been started. Start it first.", 409)
        if r["state"] == "awaiting_source":
            return _fail("wrong_state", "Submit the website link first; there are no questions to answer yet.", 409)
        questions = json.loads(r["questions_json"])
        resolved, correction, why = validate_answers(questions, body)
        if why:
            return _fail("invalid_answers", f"Your answers were not accepted ({why}). Nothing was saved.", 400)
        if r["state"] == "ready":   # idempotent: the same answers return the stored result; different answers are refused (no second model call, no rewrite)
            same = resolved == json.loads(r["answers_json"]) and correction == (r["correction"] or "")
            return (200, {**status(), "replayed": True}) if same else _fail("already_completed", "Onboarding is already complete; these answers differ from the saved ones and were not applied.", 409)
        try:
            raw = snapshot_path().read_bytes()
            text = raw.decode("utf-8")
        except (OSError, ValueError) as e:
            return _fail("snapshot_missing", f"The prepared demo snapshot could not be read ({type(e).__name__}).", 500)
        if hashlib.sha256(raw).hexdigest() != r["snapshot_sha256"]:
            return _fail("snapshot_changed", "The prepared snapshot changed after the questions were generated; start over is not supported in this demo.", 409)
        msg = (CONTEXT_PROMPT.replace("{summary}", r["summary"]).replace("{answers}", json.dumps(resolved, ensure_ascii=False))
               .replace("{correction}", correction or "(none)").replace("{url}", DEMO_URL).replace("{text}", text))
        reply, e = _ask_main(msg)
        if e:
            _save(error=f"The main agent could not answer: {e}"[:400])
            return _fail("generation_failed", f"The main agent could not combine your answers ({e}). Nothing was saved and chat stays locked; you can submit again.", 502, retryable=True)
        fields, why = validate_context_output(_json_object(reply))
        if why:
            _save(error=f"Unusable model output: {why}"[:400])
            return _fail("invalid_model_output", f"The main agent's reply was not usable ({why}). Nothing was saved and chat stays locked; you can submit again.", 502, retryable=True)
        goal = "; ".join(a["answer"] for a in resolved if a["topic"] == "goal")   # goals come ONLY from the operator's answers, never from the model or the source
        fields = {**fields, "goal": goal, "website": DEMO_URL}
        saved = core.update_company(fields, source="onboarding")
        if not saved.get("ok"):
            storage = saved.get("code") == "company_storage_error"
            _save(error=f"Company context not saved: {saved.get('error')}"[:400])
            return _fail("context_not_saved", f"The company context was not saved ({saved.get('error')}). Chat stays locked; " + ("try again." if storage else "you can submit again."),
                         503 if storage else 502, retryable=True)
        _save(state="ready", answers_json=json.dumps(resolved), correction=correction, context_json=json.dumps(fields), provenance_json=json.dumps(_provenance(resolved, fields, correction)), error=None)
        return 200, status()
