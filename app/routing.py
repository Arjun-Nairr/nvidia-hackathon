"""Pre-request routing for MAIN chat (backend-owned, UI-independent). Real Laya ('typed-decisions' checkpoint) runs in a separate
long-lived process under .venv-laya; this module builds the question set, calls it, and maps Laya's answers to one of six outcomes:
create_market_agent | create_social_agent | existing_agent_task | business_query | clarification | out_of_scope | unsupported_role.
Laya's probabilities are reported as returned (the checkpoint's own warning: confidence is not calibrated for our domain); the
thresholds below are tuned heuristics from observed predictions, not calibrated probabilities. Classification failure raises
ClassifierError - it never silently bypasses routing. ECOM_CLASSIFIER=off is an explicit TEST-ONLY seam."""
import json, os, queue, subprocess, threading, time
from pathlib import Path
from app import core

LAYA_PY = Path(os.environ.get("ECOM_LAYA_PY") or core.ROOT / ".venv-laya" / "Scripts" / "python.exe")   # env override only for failure tests
HF_CACHE = Path(os.environ.get("ECOM_HF_CACHE") or core.RUNTIME / "hf_cache")   # env override only for tests that run from a copy
T_SOCIAL, T_SOCIAL_MARGIN = 0.55, 0.30   # V2-01: the social role must be clearly ahead of the analyst role (tuned on the small table, not calibrated)
T_UNRELATED, T_AGREE, T_CREATE, T_ROLE, T_ROLE_MARGIN, T_BUSINESS, T_BUSINESS_SURE = 0.60, 0.60, 0.50, 0.40, 0.10, 0.55, 0.62   # tuned heuristics on a 33-case table, NOT calibrated      # tuned heuristics (see HANDOUT.md), not calibrated probabilities
MAX_HISTORY, MAX_TURN_CHARS = 2, 160   # Laya cost grows with state length (it re-reads the state per question), so history is kept short
OUTCOMES = ("create_market_agent", "create_social_agent", "existing_agent_task", "business_query", "clarification", "out_of_scope", "unsupported_role")
CREATE_OUTCOMES = {"market_analysis": "create_market_agent", "social_media": "create_social_agent"}   # supported roles; classification only guides, the backend grants
ROLE_LABEL = {"social_media": "social media", "email": "email", "other_role": "that kind of"}


class ClassifierError(Exception):
    pass


class LayaClient:
    """One Laya process, loaded once on first use (or prewarmed) and reused for every request."""
    def __init__(self):
        self.lock, self.proc, self.q, self.ready, self.next_id, self.started = threading.Lock(), None, queue.Queue(), None, 1, 0.0
        self.calls = 0

    def _spawn(self):
        if not LAYA_PY.exists():
            raise ClassifierError(f"Laya is not installed: {LAYA_PY} is missing. Create it with: python -m venv .venv-laya && .venv-laya\\Scripts\\python.exe -m pip install laya")
        (core.RUNTIME / "logs").mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "HF_HUB_CACHE": str(HF_CACHE), "PYTHONUTF8": "1", "HF_HUB_DISABLE_TELEMETRY": "1", **core.ca_env()}
        self.q, self.ready, self.started = queue.Queue(), None, time.time()
        self.proc = subprocess.Popen([str(LAYA_PY), "-I", str(core.ROOT / "app" / "laya_worker.py")], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=open(core.RUNTIME / "logs" / "laya.log", "ab"), text=True, encoding="utf-8", bufsize=1, env=env, cwd=str(core.ROOT))
        threading.Thread(target=self._read, args=(self.proc, self.q), daemon=True).start()

    @staticmethod
    def _read(proc, q):
        for raw in proc.stdout:
            try:
                q.put(json.loads(raw))
            except ValueError:
                pass
        q.put(None)

    def _wait_ready(self, timeout):
        end = time.time() + timeout
        while self.ready is None:
            try:
                obj = self.q.get(timeout=max(0.1, end - time.time()))
            except queue.Empty:
                raise ClassifierError(f"Laya did not finish loading within {timeout:.0f}s (see runtime/logs/laya.log). Try again in a moment.")
            if obj is None:
                raise ClassifierError("The Laya process exited while loading (see runtime/logs/laya.log).")
            if obj.get("event") == "ready":
                self.ready = obj

    def warm(self):
        """Load the model now (called in a background thread at server start). Safe to call repeatedly."""
        with self.lock:
            if self.proc is None or self.proc.poll() is not None:
                self._spawn()
            self._wait_ready(600)

    def classify(self, state, questions, timeout=30):
        with self.lock:
            t0 = time.perf_counter()
            if self.proc is None or self.proc.poll() is not None:
                self._spawn()
            cold = self.ready is None
            self._wait_ready(600)
            wait_ms = (time.perf_counter() - t0) * 1000
            rid, self.next_id = self.next_id, self.next_id + 1
            try:
                self.proc.stdin.write(json.dumps({"id": rid, "op": "classify", "state": state, "questions": questions}) + "\n")
                self.proc.stdin.flush()
            except (OSError, ValueError) as e:
                self.proc = None
                raise ClassifierError(f"The Laya process is not reachable ({type(e).__name__}); it will be restarted on the next message.")
            end = time.time() + timeout
            while True:
                try:
                    obj = self.q.get(timeout=max(0.1, end - time.time()))
                except queue.Empty:
                    self.stop()
                    raise ClassifierError(f"Laya did not answer within {timeout:.0f}s; it was stopped and will restart on the next message.")
                if obj is None:
                    self.proc = None
                    raise ClassifierError("The Laya process exited during classification; it will be restarted on the next message.")
                if obj.get("id") == rid:
                    break
            if "error" in obj:
                raise ClassifierError("Laya failed: " + obj["error"])
            self.calls += 1
            res = obj["result"]
            res["meta"] = {"round_trip_ms": round((time.perf_counter() - t0) * 1000, 1), "wait_for_load_ms": round(wait_ms, 1),
                           "first_call_after_start": cold, "load_ms": self.ready.get("load_ms"), "laya": self.ready.get("laya"), "device": self.ready.get("device")}
            return res

    def stop(self):
        try:
            if self.proc and self.proc.poll() is None:
                self.proc.kill()
        except Exception:
            pass
        self.proc = None


client = LayaClient()
_warm_error = [None]


def prewarm():
    try:
        client.warm()
    except Exception as e:
        _warm_error[0] = str(e)


def status():
    if explicit_off():
        return {"state": "off (test only)"}
    if _warm_error[0]:
        return {"state": "error", "error": _warm_error[0]}
    ready = client.ready
    return {"state": "ready" if ready else "loading", **({"load_ms": ready.get("load_ms"), "laya": ready.get("laya"), "calls": client.calls} if ready else {})}


# ---------------- question set + decision rules ----------------
# What the real checkpoint did well/badly (see HANDOUT.md): it separates create-vs-other, business-vs-unrelated and the agent role when
# the state is SHORT; it cannot tell mixed requests apart, cannot identify which existing agent is meant (the 'none' option never wins),
# and a previous assistant message that says "created" pulls unrelated replies toward create_agent. So: Laya answers small questions on a
# minimal state; the previous assistant message is only shown for short agreements; existing agents are matched by name in the backend;
# mixed requests are caught by classifying each clause separately.
import re

def domain_question(company):
    """Anchored to the saved company when it is known (observed: a generic 'the user's business' wording gave flat probabilities)."""
    name, prod = (company.get("name") or "").strip(), (company.get("products") or "").strip()
    desc = f"the user's business ({name}: {prod[:70]})" if name and prod else (f"the user's business ({name})" if name else "the user's business")
    return {"type": "choice", "instructions": "Is the request about the user's own business?",
            "criteria": {"business": f"about {desc}: what it sells, to whom, its name or website, prices, competitors, or its assistant agents",
                         "unrelated": "not about that: general knowledge, entertainment, coding or personal chat"}}


ANSWER = {"type": "choice", "instructions": "What is the reply?",
          "criteria": {"answer": "an answer to the question", "something_else": "a new request or a different topic"}}
T_ANSWER = 0.60
AGREE = {"type": "noul", "instructions": "Is the request only a short agreement such as yes, ok, sure or go ahead?"}
KIND = {"type": "choice", "instructions": "What does the request ask for?",
        "criteria": {"create_agent": "create or add a new agent, or say yes to creating one",
                     "other_request": "ask a question or give a task",
                     "unclear": "too vague to tell"}}
ROLE = {"type": "choice", "instructions": "What kind of agent is wanted? If the request is just yes, use the previous assistant message.",
        "criteria": {"market_analysis": "competitor or pricing analysis", "social_media": "social media or Instagram", "email": "email or newsletters",
                     "other_role": "any other kind of agent"}}
SPLIT = re.compile(r"\s*(?:;|[.?!]\s+(?=[A-Za-z])|,?\s+and\s+also\s+|,?\s+also\s+|,?\s+and\s+then\s+|,?\s+as\s+well\s+as\s+|,\s+and\s+(?=(?:write|tell|make|create|compare|show|find|give|help|draft|set|add)\b))", re.I)


CONJ = re.compile(r"(?:;|,?\s+and\s+also\s+|,?\s+also\s+|,?\s+and\s+then\s+|,?\s+as\s+well\s+as\s+|,\s+and\s+(?=(?:write|tell|make|create|compare|show|find|give|help|draft|set|add)\b))", re.I)


def clauses(message):
    """(parts, joined_by_conjunction). A second sentence ('...? Can you make one?') often just continues the first, so only a
    conjunction ('and also', 'and then', ';') makes any difference in clause categories count as a mixed request."""
    parts = [c.strip(" ,.") for c in SPLIT.split(message) if c and len(c.split()) >= 3]
    return (parts[:3] if len(parts) > 1 else [message]), bool(CONJ.search(message))


def _probs(ans):
    return {k: round(float(v), 4) for k, v in (ans.get("probabilities") or {}).items()}


def _top2(p):
    r = sorted(p.items(), key=lambda kv: -kv[1])
    return r[0], (r[1] if len(r) > 1 else (None, 0.0))


def match_agent(message, agents):
    """Backend name match (case-insensitive): full name, agent id, or the distinctive tail of the name (e.g. 'competitor analyst')."""
    m = message.lower()
    hits = []
    for a in agents:
        name = a["name"].lower()
        tail = " ".join(name.split()[1:]) if len(name.split()) > 2 else name
        if name in m or a["agent_id"] in m or (tail != name and tail in m):
            hits.append(a)
    return hits[0] if len(hits) == 1 else None


def _meta(raw):
    u = raw.get("usage") or {}
    return {**raw["meta"], "model_ms": raw["elapsed_ms"], "state_tokens": u.get("state_tokens"), "truncated": u.get("truncated")}


def _category(ans):   # domain+kind answers for one clause
    """create | unrelated | other for one clause/message from a domain+kind answer set."""
    if ans["domain"]["probabilities"]["unrelated"] >= T_UNRELATED:
        return "unrelated"
    return "create" if ans["kind"]["probabilities"]["create_agent"] >= T_CREATE else "other"


def explicit_off():
    return os.environ.get("ECOM_CLASSIFIER") == "off"   # test seam only; recorded in the route metadata


def route(message, history, agents, company):
    if explicit_off():
        return {"outcome": "classifier_off_test_only", "handled_locally": False, "allow_create_agent": True,
                "context": "", "classifier": {"name": "OFF (ECOM_CLASSIFIER=off, test only)"}}
    metas, probs, rule, calls = [], {}, "", 0
    prev = next((h for h in reversed(history) if h["speaker"] == "assistant"), None)
    DOM = domain_question(company)

    def ask(state, q):
        nonlocal calls
        raw = client.classify(state, q); calls += 1; metas.append(_meta(raw)); return raw["answers"]

    outcome, role, agent = "clarification", None, None
    parts, by_conj = clauses(message)
    mixed = False
    if len(parts) > 1:   # mixed-request check: Laya cannot flag 'two requests' itself, so each clause is categorised on its own
        # a short or anaphoric fragment ("Can you make one?") only continues the previous clause; it is not a second request
        real = [c for c in parts if len(c.split()) > 3 and not re.match(r"(can|could|would|will)\s+you\b.*\b(it|one|ones|that|this|them)\b", c, re.I)] or parts
        cats = [_category(ask({"request": c}, {"domain": DOM, "kind": KIND})) for c in real]
        probs["clause_categories"] = cats
        if len(set(cats)) > 1 and (by_conj or "unrelated" in cats):
            mixed, rule = True, f"mixed request: clauses classified {cats}"
    status = core.company_status(company)
    onboarding = not status["complete"]
    # main's most recent open question within the bounded history (a local out-of-scope reply in between must not hide it)
    prev_q = next((h for h in reversed(history) if h["speaker"] == "assistant" and h["text"].rstrip().endswith("?")), None)
    # words that name this system itself (its agents) or the company: a deterministic business signal Laya's domain question under-weights
    lexical = bool(re.search(r"\b(agents?|specialists?|analysts?)\b", message, re.I)) or bool(
        company.get("name") and company["name"].lower() in message.lower())
    short = len(message.split()) <= 8
    refers_back = bool(re.search(r"\b(it|its|they|them|their|that|this|those|these|one|ones|there)\b", message, re.I))   # needs an antecedent
    a = ask({"request": message}, {"domain": DOM, "agree": AGREE, "kind": KIND}) if not mixed else None
    if a and short and refers_back and prev and _probs(a["domain"])["unrelated"] >= T_UNRELATED:   # 'thanks! what can it do?' needs its antecedent
        a["domain"] = ask({"request": message, "previous_assistant_message": prev["text"][:150]}, {"domain": DOM})["domain"]
    if a:
        pd, pk, p_agree = _probs(a["domain"]), _probs(a["kind"]), round(float(a["agree"]["noul"]), 4)
        probs.update({"domain": pd, "kind": pk, "agreement": p_agree})
        if p_agree >= T_AGREE and prev:      # a short reply: only now may the previous assistant message influence classification
            ctx = {"request": message, "previous_assistant_message": prev["text"][:150]}
            a2 = ask(ctx, {"kind": KIND, "role": ROLE}); pk, pr = _probs(a2["kind"]), _probs(a2["role"])
            probs.update({"kind_with_previous_message": pk, "role": pr})
            if pk["create_agent"] >= T_CREATE:
                outcome, role, rule = _role_outcome(pr)
            else:
                rule = "short agreement, but the previous assistant message was not a creation offer"
        elif prev_q and pk["create_agent"] < T_CREATE and len(message.split()) <= 40 and _is_answer(ask, message, prev_q, probs):
            outcome, rule = "business_query", f"reply to main's question (answer probability {probs['answer_to_previous_question']:.2f}); company profile " + \
                ("incomplete (onboarding)" if onboarding else "complete")
        elif pd["unrelated"] >= T_UNRELATED:
            outcome, rule = "out_of_scope", f"domain=unrelated ({pd['unrelated']:.2f})"
        elif pk["create_agent"] >= T_CREATE and len(message.split()) <= 3:
            rule = "create request with no detail about the kind of agent (3 words or fewer)"
        elif pk["create_agent"] >= T_CREATE:
            a2 = ask({"request": message}, {"role": ROLE}); pr = _probs(a2["role"]); probs["role"] = pr
            outcome, role, rule = _role_outcome(pr)
        else:
            hit = match_agent(message, agents)
            if hit:
                outcome, agent, rule = "existing_agent_task", hit["agent_id"], f"names existing agent {hit['agent_id']} (backend name match); kind other_request {pk['other_request']:.2f}"
            elif (pd["business"] >= T_BUSINESS or lexical) and (pk["other_request"] >= T_CREATE or pd["business"] >= T_BUSINESS_SURE or onboarding):
                outcome, rule = "business_query", f"domain=business ({pd['business']:.2f}{', named agents/company' if lexical else ''}), kind other_request {pk['other_request']:.2f}" + (", company profile incomplete (onboarding)" if onboarding else "")
            else:
                rule = f"kind not decisive (create {pk['create_agent']:.2f}, other {pk['other_request']:.2f}, unclear {pk['unclear']:.2f})"
    return _result(outcome, rule, role, agent, probs, metas, calls, agents, company, status)


def _is_answer(ask, message, prev, probs):
    """Is `message` an answer to main's last question? Asked on {question, reply} only: a reply like 'Women aged 25-40 in the UK' has no
    business words of its own, while an unrelated request ('write me a poem') is not an answer (observed 15/16 on a small table)."""
    p = _probs(ask({"question": prev["text"][:150], "reply": message}, {"answer": ANSWER})["answer"])
    probs["answer_to_previous_question"] = p.get("answer", 0.0)
    return p.get("answer", 0.0) >= T_ANSWER


def _role_outcome(pr):
    (r, p1), (r2, p2) = _top2(pr)
    if r == "market_analysis" and p1 >= T_ROLE:
        return "create_market_agent", r, f"create request, role=market_analysis ({p1:.2f})"
    if r == "social_media" and p1 >= T_SOCIAL and p1 - p2 >= T_SOCIAL_MARGIN:   # a close call between roles never grants creation by itself
        return "create_social_agent", r, f"create request, role=social_media ({p1:.2f}, margin {p1 - p2:.2f})"
    if r not in CREATE_OUTCOMES and p1 >= T_ROLE and p1 - p2 >= T_ROLE_MARGIN:
        return "unsupported_role", r, f"create request, role={r} ({p1:.2f})"
    return "clarification", None, f"create request but role not decisive (top {r} {p1:.2f}, next {r2} {p2:.2f})"


def _result(outcome, rule, role, agent, probs, metas, calls, agents, company, status):
    company_name = company.get("name") or "your business"
    r = {"outcome": outcome, "domain": "out_of_scope" if outcome == "out_of_scope" else "ecommerce", "role": role, "agent_id": agent,
         "decision_rule": rule, "probabilities": probs,
         "classifier": {"name": "laya typed-decisions", **(metas[0] if metas else {}), "model_ms": round(sum(m["model_ms"] for m in metas), 1), "calls": calls,
                        "truncated": any(m.get("truncated") for m in metas)}}
    by_id = {x["agent_id"]: x for x in agents}
    r["handled_locally"] = outcome in ("out_of_scope", "unsupported_role", "clarification", "existing_agent_task")
    r["allow_create_agent"] = outcome in CREATE_OUTCOMES.values()
    names = ", ".join(f"{x['name']} ({x['agent_id']}, role {x.get('role') or 'unknown'})" for x in agents) or "none yet"
    if outcome == "out_of_scope":
        r["reply"] = (f"That looks outside what I can help with here. I'm set up for {company_name}: company details, products, pricing, competitors, "
                      "and creating or using specialist agents. Ask me something along those lines.")
    elif outcome == "unsupported_role":
        r["reply"] = (f"A {ROLE_LABEL[role]} agent isn't available yet. Right now I can create a market-analysis specialist (competitor and pricing analysis) "
                      "or a social-media specialist (promotional creative briefs and copy, with read-only US Facebook image-ad research when it is granted; image generation and posting are not connected yet). "
                      "Would you like one of those?")
    elif outcome == "existing_agent_task":
        x = by_id.get(agent)
        r["reply"] = (f"That sounds like a task for {x['name'] if x else agent}. Open its chat from the list on the left and ask it directly. "
                      "I can't pass work to other agents yet, and I did not create anything.")
    elif outcome == "clarification":
        r["reply"] = ("I'm not sure what you'd like me to do. Do you want to (1) tell me about your company, (2) create a market-analysis or a "
                      f"social-media specialist, or (3) work with an existing agent? Existing agents: {names}.")
    prof = ("The company profile is COMPLETE." if status["complete"] else
            "The company profile is INCOMPLETE. Still missing: " + ", ".join(status["missing_labels"]) + ". Ask concise questions for them (one or "
            "two at a time), and when the user answers, save exactly what they said with update_company. Never invent or guess values.")
    if outcome == "business_query":
        r["context"] = ("[Routing context from the app backend - trusted] The request was classified as business_query (domain: ecommerce). create_agent is NOT "
                        f"available for this request; do not create agents. update_company is available to save facts the user states. {prof} "
                        f"Answer the user's message above using read_company_context. Existing specialists: {names}.")
    elif outcome in CREATE_OUTCOMES.values():
        want = role or next(k for k, v in CREATE_OUTCOMES.items() if v == outcome)
        r["context"] = (f"[Routing context from the app backend - trusted] The request was classified as {outcome}. create_agent is permitted for this "
                        f"request, only for role {want}, and the backend refuses it until the company profile has every required detail. "
                        f"{prof} Existing specialists: {names}. If one of them already has role {want}, tell the user and point them to it instead of "
                        "creating a duplicate, unless the user explicitly asks for another one. Follow the user's message above; generate the "
                        "company-specific details only from the saved company context.")
    return r
