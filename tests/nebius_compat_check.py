"""Bounded NVIDIA/Nebius compatibility probe (2026-10-27): text, tool calling, main agent -> create_agent, specialist -> inspect_image, all through the REAL app and Hermes in an
ISOLATED COPY of the project. The copy never sees the Nebius key: Hermes talks to a local counting proxy (this file) that holds the key, keeps a crash-safe attempt ledger,
and refuses (locally, unbilled) anything that is not one bounded chat request for the probe model. What it ENFORCES: the attempt count (persistent ledger), the model name, max_tokens
and body size, a trip after the first failure, and a refusal of byte-identical requests. What it does NOT: a dollar cap (the input-token estimate is a heuristic; the dollar figures below are
planning bounds), nor Hermes' own transport-recovery replay outside this proxy (an identical request is refused here, but production Hermes would resend it).
  python tests/nebius_compat_check.py selftest   # offline: proxy limits against a scripted upstream (no key, no network)
  python tests/nebius_compat_check.py offline    # offline: the whole staged flow against tests/mock_llm.py (scripted double, NOT Nebius)
  python tests/nebius_compat_check.py offline-reject  # offline: the scripted upstream rejects image content with HTTP 400; the run must FAIL honestly (no text-only replay)
  python tests/nebius_compat_check.py offline-big  # offline: the scripted upstream streams ~900 reasoning deltas before the reply (the shape of the live answer)
  python tests/nebius_compat_check.py live       # PAID: at most 8 billable attempts in total, ever (ledger in .scratch/nebius_compat/); needs secrets/local.env; ALREADY SPENT
  python tests/nebius_compat_check.py continue-offline[-big|-reject]  # offline: image-only continuation against the scripted double (-big: 900 streamed reasoning deltas; -reject: HTTP 400)
  python tests/nebius_compat_check.py continue-live  # PAID: image-only continuation, at most 3 MORE attempts in its OWN ledger (ledger-continuation.jsonl); the original ledger is never touched
Run with the Hermes Python (it has PIL/yaml). Run from the REAL project: it only READS secrets/local.env and demo/v2-06-inputs/, writes only .scratch/nebius_compat/ and a temp copy."""
import base64, copy, hashlib, json, os, shutil, ssl, subprocess, sys, tempfile, threading, time, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REAL = Path(__file__).resolve().parent.parent
EVID = REAL / ".scratch" / "nebius_compat"
MODEL = "nvidia/Nemotron-3.5-Super-VL"
UPSTREAM = "https://api.tokenfactory.nebius.com/v1"
RATE_IN, RATE_OUT = 0.30, 0.90          # USD per million tokens: Nebius model page + release post, read 2026-10-27
MAX_ATTEMPTS, IN_CAP, OUT_CAP, IMG_TOKENS, BODY_CAP = 8, 60_000, 8_000, 6_000, 1_500_000
WORST_CASE = MAX_ATTEMPTS * (IN_CAP * RATE_IN + OUT_CAP * RATE_OUT) / 1e6   # a PLANNING estimate: IN_CAP is checked against a heuristic token estimate, so this is not an enforced dollar cap
CONTINUATION_CAP, CEILING_USD, CONTEXT_TOKENS = 3, 2.0, 1_048_576   # context_length: the account's own model listing (2026-10-27)
IMAGE_ID = "pic-a41f"                   # neutral name: no label tells the model what the photo shows
PORTS = {"app": 8861, "proxy": 8862, "mock": 8863}
KEEP_ENV = ("PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "LOCALAPPDATA", "APPDATA", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "TEMP", "TMP", "USERNAME",
            "PROGRAMDATA", "PROGRAMFILES", "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS", "OS")


# ------------------------------------------------------------------ the counting proxy
class Ledger:
    """JSON lines. A 'start' row is fsynced BEFORE a request is dispatched, so a crash can only over-count. Starts are never removed; a trip row blocks all later dispatch."""
    def __init__(self, path, cap):
        self.path, self.cap, self.lock = Path(path), cap, threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def rows(self):
        return [json.loads(x) for x in self.path.read_text(encoding="utf-8").splitlines() if x.strip()] if self.path.exists() else []

    def add(self, rec):
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": round(time.time(), 3), **rec}) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def starts(self):
        return sum(r["ev"] == "start" for r in self.rows())

    def tripped(self):
        return any(r["ev"] == "trip" for r in self.rows())

    def reserve(self, rec):   # -> (attempt number, None) or (None, reason)
        with self.lock:
            rows = self.rows()
            if any(r["ev"] == "trip" for r in rows):
                return None, "tripped"
            n = sum(r["ev"] == "start" for r in rows)
            if n >= self.cap:
                return None, "cap"
            if any(r["ev"] == "start" and r.get("body_sha") == rec.get("body_sha") for r in rows):
                return None, "replay"
            self.add({"ev": "start", "n": n + 1, **rec})
            return n + 1, None

    def finish(self, n, rec, trip=None):
        with self.lock:
            self.add({"ev": "end", "n": n, **rec})
            if trip:
                self.add({"ev": "trip", "n": n, "why": trip})


def analyse(body):
    """-> (image parts found in the messages, message roles, body with image bytes replaced by a marker). Only hashes of decoded bytes are kept, never the payload."""
    imgs, stripped = [], copy.deepcopy(body)

    def walk(o, role, idx):
        if isinstance(o, list):
            for x in o:
                walk(x, role, idx)
        elif isinstance(o, dict):
            if o.get("type") in ("image_url", "input_image"):
                u = o.get("image_url")
                u = u.get("url") if isinstance(u, dict) else u
                if isinstance(u, str) and u.startswith("data:") and "," in u:
                    raw = base64.b64decode(u.split(",", 1)[1])
                    d = {"role": role, "message": idx, "mime": u[5:u.index(";")] if ";" in u else "", "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                    try:
                        import io
                        from PIL import Image
                        d["size"] = list(Image.open(io.BytesIO(raw)).size)
                    except Exception:
                        pass
                    imgs.append(d)
                    if isinstance(o.get("image_url"), dict):
                        o["image_url"]["url"] = "IMG"
                    else:
                        o["image_url"] = "IMG"
                else:
                    imgs.append({"role": role, "message": idx, "not_a_data_url": True})
            for v in list(o.values()):
                if isinstance(v, (list, dict)):
                    walk(v, role, idx)
    msgs = stripped.get("messages") or []
    for i, m in enumerate(msgs):
        walk(m.get("content"), m.get("role"), i)
    return imgs, [m.get("role") for m in msgs], stripped


def summarize(data, ctype):
    txt = data.decode("utf-8", "replace")
    out = {"usage": None, "finish_reason": None, "tool_calls": [], "text": "", "reasoning_chars": 0, "model": None}
    if "event-stream" in ctype:
        calls = {}
        for line in txt.splitlines():
            if not line.startswith("data:") or line.strip() == "data: [DONE]":
                continue
            try:
                ch = json.loads(line[5:])
            except ValueError:
                continue
            out["usage"] = ch.get("usage") or out["usage"]
            out["model"] = ch.get("model") or out["model"]
            for c in ch.get("choices") or []:
                d = c.get("delta") or {}
                out["text"] += d.get("content") or ""
                out["reasoning_chars"] += len(d.get("reasoning_content") or d.get("reasoning") or "")
                for t in d.get("tool_calls") or []:
                    f = t.get("function") or {}
                    s = calls.setdefault(t.get("index", 0), {"name": "", "args": ""})
                    s["name"] += f.get("name") or ""
                    s["args"] += f.get("arguments") or ""
                out["finish_reason"] = c.get("finish_reason") or out["finish_reason"]
        out["tool_calls"] = [{"name": v["name"], "args_head": v["args"][:400]} for v in calls.values()]
    else:
        try:
            j = json.loads(txt)
        except ValueError:
            return {**out, "unparsed_head": txt[:300]}
        c, m = (j.get("choices") or [{}])[0], (j.get("choices") or [{}])[0].get("message") or {}
        out.update(usage=j.get("usage"), model=j.get("model"), finish_reason=c.get("finish_reason"), text=m.get("content") or "",
                   reasoning_chars=len(m.get("reasoning_content") or m.get("reasoning") or ""),
                   tool_calls=[{"name": (t.get("function") or {}).get("name"), "args_head": ((t.get("function") or {}).get("arguments") or "")[:400]} for t in m.get("tool_calls") or []])
    out["text"] = out["text"][:700]
    return out


class Probe:
    def __init__(self, ledger, upstream, key, model=MODEL, in_cap=IN_CAP, out_cap=OUT_CAP, ctx=None, timeout=120):   # 120 s per attempt: a turn with two sequential attempts stays inside the app's 300 s turn limit, and the proxy gives up before Hermes' own 180 s stale-stream timer
        self.ledger, self.upstream, self.key, self.model = ledger, upstream.rstrip("/"), key, model
        self.in_cap, self.out_cap, self.ctx, self.timeout, self.stage = in_cap, out_cap, ctx, timeout, "-"
        self.server = None

    def redact(self, s):
        return str(s).replace(self.key, "<key>") if self.key else str(s)

    def start(self, port):
        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.server.probe = self
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, code, obj, ctype="application/json"):
        raw = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        for i in range(0, len(raw), 16384):   # NOT one big write: on this Windows machine a single multi-hundred-KB send stalls ~19 s and is then reset, so a long streamed answer never reached Hermes
            self.wfile.write(raw[i:i + 16384])

    def refuse(self, code, why, count=True):   # a LOCAL refusal: nothing was sent upstream, so nothing was billed
        P = self.server.probe
        P.ledger.add({"ev": "refused", "stage": P.stage, "code": code, "why": why})
        self.reply(code, {"error": {"message": "probe refused: " + why, "type": "probe_refused", "code": code}})

    def do_GET(self):   # model discovery by Hermes: answered locally, never forwarded
        self.reply(200, {"object": "list", "data": [{"id": self.server.probe.model, "object": "model"}]})

    def do_POST(self):
        P = self.server.probe
        n = int(self.headers.get("Content-Length") or 0)
        if n > BODY_CAP:
            return self.refuse(413, f"body of {n} bytes exceeds {BODY_CAP}")
        raw = self.rfile.read(n)
        if self.path.split("?")[0].rstrip("/") != "/v1/chat/completions":
            return self.refuse(404, f"only POST /v1/chat/completions is allowed (got {self.path[:60]})")
        try:
            body = json.loads(raw)
        except ValueError:
            return self.refuse(400, "request body is not JSON")
        if body.get("model") != P.model:
            return self.refuse(403, f"model {str(body.get('model'))[:80]!r} is not the probe model {P.model!r} (no other model, no fallback)")
        imgs, roles, stripped = analyse(body)
        est_in = int(len(json.dumps(stripped)) / 2.5) + IMG_TOKENS * len(imgs)   # deliberately pessimistic
        if est_in > P.in_cap:
            return self.refuse(413, f"estimated input {est_in} tokens exceeds the cap {P.in_cap}")
        body["max_tokens"] = min(int(body.get("max_tokens") or P.out_cap), P.out_cap)
        if "max_completion_tokens" in body:
            body["max_completion_tokens"] = min(int(body["max_completion_tokens"] or P.out_cap), P.out_cap)
        body["n"] = 1
        if body.get("stream"):
            body["stream_options"] = {"include_usage": True}
        num, why = P.ledger.reserve({"stage": P.stage, "est_input_tokens": est_in, "max_tokens_sent": body["max_tokens"], "body_bytes": len(raw), "roles": roles,
                                     "body_sha": hashlib.sha256(raw).hexdigest()[:24], "n_tools": len(body.get("tools") or []), "stream": bool(body.get("stream")), "images": imgs, "model": body["model"]})
        if num is None:
            return self.refuse({"cap": 429, "replay": 409}.get(why, 503), {"cap": "attempt allowance spent", "replay": "an identical request was already dispatched; Hermes' automatic replay after a transport error is not allowed"}.get(why, "an earlier failure tripped the probe; no more dispatch"))
        t0, status, data, ctype, err = time.perf_counter(), None, b"", "application/json", None
        try:
            req = urllib.request.Request(P.upstream + "/chat/completions", data=json.dumps(body).encode(), method="POST",
                                         headers={"Authorization": "Bearer " + P.key, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=P.timeout, context=P.ctx) as r:
                status, data, ctype = r.status, r.read(), r.headers.get("Content-Type", ctype)
        except urllib.error.HTTPError as e:
            status, data, ctype = e.code, e.read(), e.headers.get("Content-Type", ctype)
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
        rec = {"stage": P.stage, "latency_s": round(time.perf_counter() - t0, 2), "status": status}
        if err:
            P.ledger.finish(num, {**rec, "error": P.redact(err)[:300]}, trip="transport failure or timeout (outcome uncertain, counted as billed)")
            return self.reply(502, {"error": {"message": "probe transport failure", "type": "probe_transport"}})
        s = summarize(data, ctype)
        if status != 200:
            rec["error_body_head"] = P.redact(data.decode("utf-8", "replace"))[:500]
        P.ledger.finish(num, {**rec, **s}, trip=None if status == 200 else f"HTTP {status}")
        self.reply(status, data, ctype)


# ------------------------------------------------------------------ helpers shared by the modes
def http(port, path, body=None, timeout=900):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
    def parse(raw):
        try:
            return json.loads(raw or b"{}")
        except ValueError:
            return {"_raw": raw.decode("utf-8", "replace")[:400]}   # e.g. a streamed (SSE) reply
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, parse(r.read())
    except urllib.error.HTTPError as e:
        return e.code, parse(e.read())


def read_key():
    for line in (REAL / "secrets" / "local.env").read_text(encoding="utf-8").splitlines():
        if line.startswith("NEBIUS_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def tls_ctx():
    ca = REAL / "runtime" / "ca_bundle.pem"   # the project's own public-cert bundle (verification stays ON)
    return ssl.create_default_context(cafile=str(ca)) if ca.exists() else ssl.create_default_context()


def fingerprint():
    """What must not change in the real project: hashes only, nothing printed."""
    out = {}
    for rel in ("secrets/local.env", "runtime/company.json", "runtime/app.db", "runtime/hermes_home/auth.json", "runtime/hermes_home/profiles/main/config.yaml"):
        f = REAL / rel
        out[rel] = hashlib.sha256(f.read_bytes()).hexdigest()[:16] if f.exists() else None
    prof = REAL / "runtime" / "hermes_home" / "profiles"
    out["profiles"] = sorted(p.name for p in prof.iterdir()) if prof.exists() else []
    return out


def cost(rows):
    """Measured cost from returned usage + a conservative bound for attempts without usage (uncertain outcomes)."""
    ends = {r["n"]: r for r in rows if r["ev"] == "end"}
    pt = ct = 0
    unknown = 0
    for r in rows:
        if r["ev"] != "start":
            continue
        u = (ends.get(r["n"]) or {}).get("usage")
        if u:
            pt += u.get("prompt_tokens", 0)
            ct += u.get("completion_tokens", 0)
        else:
            unknown += 1
    measured = (pt * RATE_IN + ct * RATE_OUT) / 1e6
    bound = measured + unknown * (IN_CAP * RATE_IN + OUT_CAP * RATE_OUT) / 1e6
    return {"prompt_tokens": pt, "completion_tokens": ct, "measured_usd": round(measured, 6), "attempts_without_usage": unknown, "upper_bound_usd": round(bound, 6)}


# ------------------------------------------------------------------ offline self-test of the proxy limits
def selftest():
    sys.path.insert(0, str(REAL / "tests"))
    tmp = Path(tempfile.mkdtemp(prefix="nebius-selftest-"))
    results = []

    def check(name, ok, detail=""):
        results.append(bool(ok))
        print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{str(detail)[:500]}]"), flush=True)
    mock = subprocess.Popen([sys.executable, str(REAL / "tests" / "mock_llm.py"), str(PORTS["mock"])], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.2)
    key = "SECRET-KEY-SHOULD-NEVER-APPEAR"
    try:
        led = Ledger(tmp / "ledger.jsonl", 3)
        P = Probe(led, f"http://127.0.0.1:{PORTS['mock']}/v1", key, in_cap=2000, out_cap=100)
        P.start(PORTS["proxy"])

        def post(body, path="/v1/chat/completions"):
            return http(PORTS["proxy"], path, body, timeout=60)
        msg = lambda t: [{"role": "user", "content": t}]
        base = {"model": MODEL, "messages": msg("hello")}
        st, r = post({**base, "max_tokens": 99999})
        row = [x for x in led.rows() if x["ev"] == "start"][-1]
        check("S1 a normal request is forwarded; the ledger START row names the clamped max_tokens (100, not 99999)", st == 200 and row["max_tokens_sent"] == 100 and led.starts() == 1, (st, row))
        st, r = post({**base, "model": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"})
        check("S2 another model is refused locally (403) and is NOT counted", st == 403 and led.starts() == 1, (st, r))
        st, r = post({**base, "messages": msg("x" * 20000)})
        check("S3 an oversized request is refused locally (413) and is NOT counted", st == 413 and led.starts() == 1, (st, r))
        st, r = post(base, "/v1/embeddings")
        check("S4 any other endpoint is refused locally (404), not counted", st == 404 and led.starts() == 1, (st, r))
        st, r = http(PORTS["proxy"], "/v1/models")
        check("S5 model discovery is answered locally with only the probe model", st == 200 and [m["id"] for m in r["data"]] == [MODEL], (st, r))
        st, r = post({**base, "stream": True, "n": 5})
        row = [x for x in led.rows() if x["ev"] == "start"][-1]
        check("S6 a streaming request still works (mock replays SSE) and 'n' is forced to 1", st == 200 and led.starts() == 2 and row["stream"], (st, row))
        st, _ = post({**base, "messages": msg("seven a")})
        st2, r2 = post({**base, "messages": msg("seven b")})
        check("S7 the third attempt is allowed and the FOURTH is refused locally (429) at cap 3; starts stay 3", st == 200 and st2 == 429 and led.starts() == 3, (st, st2, r2))
        P.stop()
        led2 = Ledger(tmp / "ledger.jsonl", 3)
        P2 = Probe(led2, f"http://127.0.0.1:{PORTS['mock']}/v1", key, in_cap=2000, out_cap=100)
        P2.start(PORTS["proxy"])
        st, r = post(base)
        check("S8 after a proxy restart (crash) the spent allowance is still spent: the ledger is on disk", st == 429 and led2.starts() == 3, (st, r))
        P2.stop()
        led3 = Ledger(tmp / "ledger3.jsonl", 8)
        P3 = Probe(led3, f"http://127.0.0.1:{PORTS['mock']}/v1", key, in_cap=2000, out_cap=100)
        P3.start(PORTS["proxy"])
        st, r = post({**base, "messages": msg("LLM_500 please")})
        st2, r2 = post(base)
        check("S9 an upstream HTTP 500 is relayed, counted as ONE attempt, and trips the probe: the next request is refused (503) instead of replayed",
              st == 500 and st2 == 503 and led3.starts() == 1 and led3.tripped(), (st, st2, led3.rows()))
        img = base64.b64encode(b"\x89PNG-not-really").decode()
        body = {**base, "messages": [{"role": "user", "content": [{"type": "text", "text": "look"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64," + img}}]}]}
        led4 = Ledger(tmp / "ledger4.jsonl", 8)
        P3.stop()
        P4 = Probe(led4, f"http://127.0.0.1:{PORTS['mock']}/v1", key, in_cap=20000, out_cap=100)
        P4.start(PORTS["proxy"])
        st, r = post(body)
        row = [x for x in led4.rows() if x["ev"] == "start"][-1]
        check("S10 an image part is detected and recorded as a hash + size (never the payload) in the ledger", st == 200 and row["images"] and row["images"][0]["sha256"] == hashlib.sha256(b"\x89PNG-not-really").hexdigest()
              and img not in json.dumps(led4.rows()), (st, row))
        allrows = "".join((tmp / n).read_text(encoding="utf-8") for n in ("ledger.jsonl", "ledger3.jsonl", "ledger4.jsonl"))
        check("S11 the credential appears in no ledger row and in no client-visible response", key not in allrows and key not in json.dumps(r), "")
        P4.stop()
        # a long streamed answer (the live image answer was ~900 reasoning deltas, 200+ KB): the proxy used to write it with ONE send, which stalled ~19 s and was then reset on this machine
        events = b"".join(b"data: " + json.dumps({"model": MODEL, "choices": [{"index": 0, "delta": {"reasoning_content": "think think "}}]}).encode() + b"\n\n" for _ in range(3000))
        events += b"data: " + json.dumps({"model": MODEL, "choices": [{"index": 0, "delta": {"content": "done"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 2}}).encode() + b"\n\ndata: [DONE]\n\n"

        class Big(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Content-Length", str(len(events)))
                self.end_headers()
                for i in range(0, len(events), 16384):
                    self.wfile.write(events[i:i + 16384])
        up = ThreadingHTTPServer(("127.0.0.1", PORTS["mock"] + 5), Big)
        threading.Thread(target=up.serve_forever, daemon=True).start()
        P5 = Probe(Ledger(tmp / "ledger5.jsonl", 8), f"http://127.0.0.1:{PORTS['mock'] + 5}/v1", key, in_cap=60000)
        P5.start(PORTS["proxy"])
        t0 = time.time()
        got = ""
        try:   # the client Hermes uses (openai SDK / httpx), with an image-sized request: a plain urllib reader did NOT show the stall
            from openai import OpenAI
            pic = base64.b64encode(os.urandom(300000)).decode()
            big = [{"role": "user", "content": [{"type": "text", "text": "look"}, {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + pic}}]}]
            stream = OpenAI(base_url=f"http://127.0.0.1:{PORTS['proxy']}/v1", api_key="x", max_retries=0, timeout=60).chat.completions.create(model=MODEL, messages=big, stream=True)
            got = "".join((c.choices[0].delta.content or "") for c in stream if c.choices)
        except Exception as e:
            got = repr(e)
        P5.stop()
        up.shutdown()
        check(f"S15 a {len(events) // 1024} KB streamed reply to an image-sized request is read whole by the openai client and promptly (<10 s) through the proxy (one big send stalled ~19 s and was reset)", got == "done" and time.time() - t0 < 10, (got[:200], round(time.time() - t0, 1)))
        led6 = Ledger(tmp / "ledger6.jsonl", 8)
        P6 = Probe(led6, f"http://127.0.0.1:{PORTS['mock']}/v1", key, in_cap=2000, out_cap=100)
        P6.start(PORTS["proxy"])
        a1, _ = post({**base, "messages": msg("replay probe")})
        a2, r2 = post({**base, "messages": msg("replay probe")})
        a3, _ = post({**base, "messages": msg("another request")})
        P6.stop()
        check("S16 a byte-identical request is refused locally (409, not counted): Hermes replays the last request after a transport error even with api_max_retries=1, which would bill it twice; a different request still passes",
              (a1, a2, a3) == (200, 409, 200) and led6.starts() == 2, (a1, a2, a3, r2))
        sys.path.insert(0, str(REAL))
        from app import core
        saved = os.environ.pop("ECOM_SINGLE_ATTEMPT", None)
        plain = core.profile_config()
        os.environ["ECOM_SINGLE_ATTEMPT"] = "1"
        single = core.profile_config()
        os.environ.pop("ECOM_SINGLE_ATTEMPT")
        if saved:
            os.environ["ECOM_SINGLE_ATTEMPT"] = saved
        check("S13 the normal profile configuration is unchanged (no 'agent'/'memory' keys); only ECOM_SINGLE_ATTEMPT=1 adds api_max_retries=1, auto_recovery_cycles=0 and no memory nudge",
              "agent" not in plain and "memory" not in plain and single["agent"] == {"api_max_retries": 1, "auto_recovery_cycles": 0} and single["memory"] == {"nudge_interval": 0}
              and {k: v for k, v in single.items() if k not in ("agent", "memory")} == plain, (plain, single))
        import re
        missing = sorted({a for a in re.findall(r"core\.(\w+)", (REAL / "scripts" / "check_nebius.py").read_text(encoding="utf-8")) if not hasattr(core, a)})
        check("S14 scripts/check_nebius.py only uses attributes that exist in app.core (it used core.DEFAULT_MODEL, which does not exist, so it crashed whenever NEBIUS_MODEL was unset)", not missing, missing)
        per, tot = doc_bound(0.017233, CONTINUATION_CAP)
        refused = False
        try:
            assert_budget(1.2)
        except SystemExit:
            refused = True
        check("S17 the continuation's dollar bound uses documented limits only (context window x input rate + max_tokens x output rate per attempt): 3 attempts on top of the $0.017233 already spent stay under the $2 ceiling, and a larger prior spend is refused before any call",
              0.3 < per < 0.33 and tot < CEILING_USD and refused and CONTINUATION_CAP == 3, (per, tot, refused))
        orig = tmp / "orig-ledger.jsonl"
        Ledger(orig, 8).add({"ev": "start", "n": 1})
        before_hash = hashlib.sha256(orig.read_bytes()).hexdigest()
        cl = Ledger(tmp / "cont-ledger.jsonl", CONTINUATION_CAP)
        P7 = Probe(cl, f"http://127.0.0.1:{PORTS['mock']}/v1", key, in_cap=2000, out_cap=100)
        P7.start(PORTS["proxy"])
        codes = [post({**base, "messages": msg(f"continuation {i}")})[0] for i in range(4)]
        P7.stop()
        check("S18 the continuation ledger is a separate file with its own cap of 3 (4th request refused 429) and leaves the original ledger byte-identical",
              codes == [200, 200, 200, 429] and cl.starts() == 3 and hashlib.sha256(orig.read_bytes()).hexdigest() == before_hash and cl.path != orig, (codes, cl.starts()))
        words = [w for g in GROUPS.values() for w in g]
        shown = " ".join([CONT_MESSAGE, IMAGE_ID, *CONT_COMPANY.values(), *[str(v) for v in CONT_AGENT.values()]]).lower()
        leaked = [w for w in words if w in shown]
        check("S19 the continuation prompt, image id, company context and specialist text contain none of the words the answer is scored on (so the answer cannot come from text)", not leaked, leaked)
        calls, bad = hermes_calls("x API call #1: model=m provider=p in=5392 out=65 total=5457 latency=2.9s\nWARNING agent.stream_diag: Stream exhausted on attempt 1/1\n")
        calls2, bad2 = hermes_calls("INFO conversation_loop: API call #2: model=m in=6621 out=918 total=7539 latency=4s\n")
        check("S20 the Hermes log parser reads token counts of API calls and flags stream/transport failure lines", calls == [(5392, 65)] and len(bad) == 1 and calls2 == [(6621, 918)] and not bad2, (calls, bad, calls2, bad2))
        real_secrets = core.load_secrets
        try:
            core.load_secrets = lambda: {"LLM_PROVIDER": "nebius-token-factory"}
            fallback = core.llm_config()["model"]
            core.load_secrets = lambda: {"LLM_PROVIDER": "nebius-token-factory", "LLM_MODEL": "gpt-5.6-terra", "NEBIUS_MODEL": MODEL}
            overridden = core.llm_config()["model"]
            core.load_secrets = lambda: {"LLM_PROVIDER": "openai-codex", "LLM_MODEL": "gpt-5.6-terra"}
            active = core.llm_config()
        finally:
            core.load_secrets = real_secrets
        tmpl = (REAL / "secrets" / "local.env.template").read_text(encoding="utf-8")
        check("S21 the Nebius fallback model is the verified candidate (core default and tracked template), the active ChatGPT configuration is unchanged, and LLM_MODEL still overrides NEBIUS_MODEL",
              core.NEBIUS_DEFAULT_MODEL == MODEL and fallback == MODEL and f"NEBIUS_MODEL={MODEL}" in tmpl and "nemotron-3-super-120b" not in tmpl and overridden == "gpt-5.6-terra"
              and active == {"provider": "openai-codex", "model": "gpt-5.6-terra"}, (fallback, overridden, active))
        check("S12 planning estimate at the caps (8 x (60k in + 8k out) at $0.30/$0.90 per million) is far below the $2 task ceiling (a heuristic estimate, NOT an enforced dollar cap)", WORST_CASE < 0.25, WORST_CASE)
    finally:
        mock.terminate()
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\nSELFTEST {sum(results)}/{len(results)} (planning estimate ${WORST_CASE:.3f}; documented-limit bound for a 3-attempt continuation ${doc_bound(0, CONTINUATION_CAP)[1]:.3f})")
    return all(results)


# ------------------------------------------------------------------ the staged flow in an isolated copy
GROUPS = {   # concrete things that are visible in the photo and in NO text supplied to the model
    "bird": ("bird", "pheasant", "partridge", "fowl", "peacock", "turkey", "rooster"),
    "colour chart": ("colour chart", "color chart", "colorchecker", "colour checker", "color checker", "swatch", "calibration", "colour target", "color target", "color card", "colour card"),
    "grey backdrop": ("grey", "gray"),
    "red striped border": ("stripe", "striped", "vine", "leaf", "leaves"),
    "floral": ("floral", "flower", "rose", "bloom", "blossom", "peony"),
    "quilted stitching": ("quilt", "stitch", "wavy line", "curved line"),
}


def score_description(text):
    t = text.lower()
    hit = [g for g, words in GROUPS.items() if any(w in t for w in words)]
    return hit, (bool({"bird", "colour chart"} & set(hit)) and len(hit) >= 3)


STAGES = {   # live message, offline (scripted double) message
    "s1_text": ("Reply with one short friendly sentence saying hello to the operator. Do not use any tools for this.", "hello"),
    "s2_tool": ("Use your read_company_context tool to look up our saved company name and what we sell, then tell me both in one sentence.",
                'CALL_TOOL:{"name": "read_company_context", "args": {}}'),
    "s3a_create": ("Please create our social-media specialist now. Name it 'Harbor Loom Social'. Objective: describe our product photos accurately so we can write promotional copy. "
                   "Instructions: describe only what is visible in an image and say what you are unsure of. Grant it only the inspect_image tool beyond the standard ones and give it no custom "
                   "skills. Then confirm in one sentence what you created.", "create_social_agent please"),
    "s3b_inspect": (f"Call inspect_image with image_id '{IMAGE_ID}'. Then describe in four to six short sentences the concrete things you can see in that image: objects, colours, patterns, "
                    "any text or equipment. Do not guess about anything you cannot see.", 'CALL_TOOL:{"name": "inspect_image", "args": {"image_id": "' + IMAGE_ID + '"}}'),
}


def run(mode):
    live = mode == "live"
    EVID.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    if live:
        led = Ledger(EVID / "ledger-live.jsonl", MAX_ATTEMPTS)
        if led.rows():
            sys.exit("REFUSED: the live ledger already has rows (a live run was started before). The allowance is per TASK; delete nothing and ask for renewed authorization.")
        key = read_key()
        if not key:
            sys.exit("REFUSED: NEBIUS_API_KEY not found in secrets/local.env")
        ctx = tls_ctx()
        # pre-flight, no inference: the model must be listed for this account (and show whatever pricing metadata the listing carries)
        rq = urllib.request.Request(UPSTREAM + "/models?verbose=true", headers={"Authorization": "Bearer " + key})
        with urllib.request.urlopen(rq, timeout=60, context=ctx) as r:
            listing = json.loads(r.read())
        entry = next((m for m in listing.get("data", []) if m.get("id") == MODEL), None)
        print("PREFLIGHT model listed:", bool(entry), "| listing pricing fields:", json.dumps({k: v for k, v in (entry or {}).items() if "pric" in k.lower() or "context" in k.lower() or "modal" in k.lower() or "vision" in k.lower()})[:400])
        if not entry:
            sys.exit(f"STOP before inference: {MODEL} is not in this account's model list.")
        upstream, pre = UPSTREAM, {"listed": True, "listing_fields": {k: v for k, v in entry.items() if k not in ("id",)}}
    else:
        tmpl = Path(tempfile.mkdtemp(prefix="nebius-offline-ledger-"))
        led, key, ctx, upstream, pre = Ledger(tmpl / "ledger.jsonl", MAX_ATTEMPTS), "offline-dummy-key", None, f"http://127.0.0.1:{PORTS['mock']}/v1", {}
    before = fingerprint()
    dst = Path(tempfile.mkdtemp(prefix="nebius-compat-"))
    shutil.copytree(REAL / "app", dst / "app", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(REAL / "scripts", dst / "scripts", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    imgs = dst / "imgs"
    imgs.mkdir()
    shutil.copy(REAL / "demo" / "v2-06-inputs" / "images" / "quilt-view-02.jpg", imgs / f"{IMAGE_ID}.jpg")
    assert not (dst / "secrets").exists() and not (dst / "runtime").exists()
    env = {k: os.environ[k] for k in KEEP_ENV if k in os.environ}
    env.update(PYTHONUTF8="1", ECOM_CLASSIFIER="off", ECOM_ASSUME_EXISTING_RUNTIME="1", ECOM_SINGLE_ATTEMPT="1", HERMES_STREAM_RETRIES="0", HERMES_STREAM_STALE_TIMEOUT="600", ECOM_CHAT_MAX_ITERATIONS="4",
               ECOM_IMAGE_DIRS=str(imgs), ECOM_VISION_MODELS=f"nebius-token-factory:{MODEL}", LLM_PROVIDER="nebius-token-factory", LLM_MODEL=MODEL, NEBIUS_MODEL=MODEL,
               NEBIUS_API_KEY="local-proxy-token", NEBIUS_BASE_URL=f"http://127.0.0.1:{PORTS['proxy']}/v1")
    procs, report = [], {"mode": mode, "model": MODEL, "stages": [], "started": stamp}
    P = Probe(led, upstream, key, ctx=ctx)

    def stage_ok(name, ok, why):
        report["stages"].append({"stage": name, "pass": bool(ok), "why": why})
        print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{str(why)[:700]}]"), flush=True)
        return bool(ok)

    def chat(agent, key_):
        P.stage = key_
        msg = STAGES[key_][0 if live else 1] + (" REJECT_IMAGES" if mode == "offline-reject" and key_ == "s3b_inspect" else " BIG_REASONING" if mode == "offline-big" and key_ == "s3b_inspect" else "")   # scripted upstream answers 400 to list-type image content
        st, r = http(PORTS["app"], f"/api/chat/{agent}", {"message": msg, "request_id": f"nc-{key_}-{stamp}"})
        return st, r

    try:
        if not live:
            procs.append(subprocess.Popen([sys.executable, str(REAL / "tests" / "mock_llm.py"), str(PORTS["mock"])], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            time.sleep(1.2)
        P.start(PORTS["proxy"])
        subprocess.run([sys.executable, "scripts/setup.py"], cwd=dst, env=env, check=True, capture_output=True)
        import yaml
        cfg = yaml.safe_load((dst / "runtime" / "hermes_home" / "profiles" / "main" / "config.yaml").read_text(encoding="utf-8"))
        report["main_config"] = {"provider": cfg["model"]["provider"], "model": cfg["model"]["default"], "agent": cfg.get("agent"), "memory": cfg.get("memory"),
                                 "vision_declared": cfg.get("providers")}
        print("ISOLATED CONFIG", json.dumps(report["main_config"]))
        procs.append(subprocess.Popen([sys.executable, "-m", "app.server", str(PORTS["app"])], cwd=dst, env=env, stdout=open(dst / "server.log", "wb"), stderr=subprocess.STDOUT))
        for _ in range(80):
            try:
                http(PORTS["app"], "/api/status", timeout=5)
                break
            except Exception:
                time.sleep(0.5)
        st, co = http(PORTS["app"], "/api/company", {"fields": {"name": "Harbor Loom Co (synthetic demo)", "products": "Hand-block-printed cotton quilts and throws (synthetic demo)",
                                                                 "customers": "US home-textile shoppers (synthetic demo)", "goal": "Present our quilts clearly and accurately to shoppers"}})
        assert st == 200, co
        print(f"READY; ledger starts so far {led.starts()} (cap {MAX_ATTEMPTS}); planning estimate ${WORST_CASE:.3f} (heuristic, not an enforced dollar cap; task ceiling $2)")
        ok = True
        # ---- stage 1: text
        st, r = chat("main", "s1_text")
        ok = stage_ok("STAGE 1 text (main agent, no tool needed)", st == 200 and r.get("ok") and r.get("text", "").strip(), {"http": st, "error": r.get("error"), "text": r.get("text", "")[:300]})
        report["s1"] = {"text": r.get("text", "")[:400], "tools": [t.get("name") for t in r.get("tools", [])]}
        # ---- stage 2: tool calling
        if ok:
            st, r = chat("main", "s2_tool")
            tools = r.get("tools", [])
            out = next((t.get("output", "") for t in tools if t.get("name") == "read_company_context" and t.get("output")), "")
            fine = st == 200 and r.get("ok") and "Harbor Loom" in out and r.get("text", "").strip() and (not live or "Harbor Loom" in r["text"])
            report["s2"] = {"text": r.get("text", "")[:400], "tools": [t.get("name") for t in tools]}
            ok = stage_ok("STAGE 2 tool calling (read_company_context -> result -> final answer)", fine, {"http": st, "error": r.get("error"), "tool_output_head": out[:200], "text": r.get("text", "")[:300]})
        # ---- stage 3a: main creates the specialist through create_agent
        agent = None
        if ok:
            st, r = chat("main", "s3a_create")
            made = next((json.loads(t["output"]) for t in r.get("tools", []) if t.get("name") == "create_agent" and t.get("output", "").startswith("{")), {})
            ags = http(PORTS["app"], "/api/agents")[1]
            ags = ags if isinstance(ags, list) else ags.get("agents", [])
            spec = [a for a in ags if a.get("role") == "social_media"]
            agent = spec[0]["agent_id"] if len(spec) == 1 else None
            fine = st == 200 and r.get("ok") and made.get("ok") and agent and "inspect_image" in spec[0]["granted_tools"] and (not live or len(ags) == 1)
            report["s3a"] = {"create_result": {k: made.get(k) for k in ("ok", "agent_id", "code", "error", "granted_tools")}, "agents": [{k: a.get(k) for k in ("agent_id", "name", "role", "granted_tools")} for a in ags],
                             "text": r.get("text", "")[:400]}
            ok = stage_ok("STAGE 3a main creates one bounded specialist through the real create_agent tool", fine, {"http": st, "error": r.get("error"), "create": made, "agents": len(ags)})
            if ok:
                cfgf = dst / "runtime" / "hermes_home" / "profiles" / agent / "config.yaml"
                sc = yaml.safe_load(cfgf.read_text(encoding="utf-8"))
                report["specialist_config"] = {"provider": sc["model"]["provider"], "model": sc["model"]["default"], "agent": sc.get("agent")}
                ok = stage_ok("STAGE 3a' the new specialist profile is also retry-limited (api_max_retries=1) on the probe model", sc["model"]["provider"] == "nebius-token-factory" and sc["model"]["default"] == MODEL
                              and (sc.get("agent") or {}).get("api_max_retries") == 1, report["specialist_config"])
        # ---- stage 3b: the specialist inspects the real image
        if ok:
            expect = json.loads(subprocess.run([sys.executable, "-c", "import json;from app import core;r=core.prepare_image(%r);import base64,hashlib;raw=base64.b64decode(r['data_url'].split(',',1)[1]);"
                                                "print(json.dumps({'ok':r['ok'],'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'w':r.get('width'),'h':r.get('height')}))" % IMAGE_ID],
                                               cwd=dst, env=env, capture_output=True, text=True, check=True).stdout.strip().splitlines()[-1])
            st, r = chat(agent, "s3b_inspect")
            tools = r.get("tools", [])
            rows = led.rows()
            starts = [x for x in rows if x["ev"] == "start" and x.get("stage") == "s3b_inspect"]
            ends = {x["n"]: x for x in rows if x["ev"] == "end"}
            carried = [x for x in starts if any(i.get("sha256") == expect["sha256"] for i in x["images"])]
            last = ends.get(starts[-1]["n"]) if starts else None
            hit, good = score_description(r.get("text", ""))
            delivered = bool(carried) and all((ends.get(x["n"]) or {}).get("status") == 200 for x in carried)
            report["s3b"] = {"expected_image": expect, "request_images": [{"attempt": x["n"], "images": x["images"]} for x in starts if x["images"]], "tool_result_head": str(tools)[:600],
                             "answer": r.get("text", ""), "groups_hit": hit, "scored_ok": good, "delivered": delivered}
            ok = stage_ok("STAGE 3b-1 inspect_image ran and the next request carried the image bytes (sha256 equal to the app's prepared image) to the endpoint, which answered 200",
                          st == 200 and r.get("ok") and expect["ok"] and delivered, {"http": st, "error": r.get("error"), "expected": expect, "request_images": report["s3b"]["request_images"], "tools": [t.get("name") for t in tools], "last": last})
            if ok and live:
                ok = stage_ok("STAGE 3b-2 the final answer states concrete visible details (>=3 detail groups incl. an image-only fact: bird or colour chart)", good, {"groups": hit, "answer": r.get("text", "")[:500]})
    except Exception as e:
        import traceback
        traceback.print_exc()
        stage_ok("HARNESS", False, f"{type(e).__name__}: {e}")
    finally:
        for p in procs:
            p.terminate()
        P.stop()
        time.sleep(1)
    rows = led.rows()
    report.update(ledger=rows, cost=cost(rows), attempts=led.starts(), refused=sum(x["ev"] == "refused" for x in rows), tripped=led.tripped(),
                  all_passed=bool(report["stages"]) and all(s["pass"] for s in report["stages"]), real_unchanged=(before == fingerprint()), workdir=str(dst), upstream_pricing=pre)
    if live and not report["all_passed"] and not led.tripped():
        led.add({"ev": "trip", "why": "a stage failed: stop live testing, diagnose offline, ask for renewed authorization"})
    out = EVID / f"{mode}-result-{stamp}.json"
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"\n{mode.upper()} attempts={report['attempts']}/{MAX_ATTEMPTS} refused_locally={report['refused']} cost={report['cost']} real_project_unchanged={report['real_unchanged']}\nEVIDENCE {out}")
    for s in report["stages"]:
        print(("PASS" if s["pass"] else "FAIL"), s["stage"])
    shutil.copy(dst / "server.log", EVID / f"{mode}-server-{stamp}.log") if (dst / "server.log").exists() else None
    if all(report["stages"][i]["pass"] for i in range(len(report["stages"]))) or not live:
        shutil.rmtree(dst, ignore_errors=True)
    return report["all_passed"] and report["real_unchanged"]



# ------------------------------------------------------------------ the image-only continuation (separate ledger, at most CONTINUATION_CAP more attempts)
def doc_bound(prior_usd, attempts):
    """-> (per-attempt, total) dollar upper bound from DOCUMENTED limits only: an input cannot exceed the model's context window (CONTEXT_TOKENS, account listing) and the proxy sets
    max_tokens <= OUT_CAP (a parameter the endpoint is expected to honour). Independent of any heuristic token estimate; it is a bound under those provider-side assumptions."""
    per = (CONTEXT_TOKENS * RATE_IN + OUT_CAP * RATE_OUT) / 1e6
    return per, prior_usd + attempts * per


def assert_budget(prior_usd, attempts=CONTINUATION_CAP):
    per, total = doc_bound(prior_usd, attempts)
    if total > CEILING_USD:
        sys.exit(f"REFUSED: previous spend ${prior_usd:.4f} + {attempts} x ${per:.4f} documented-limit bound = ${total:.4f} exceeds the ${CEILING_USD:.2f} ceiling")
    return per, total


CONT_MESSAGE = (f"Call inspect_image with image_id '{IMAGE_ID}'. Then describe, in four to six short sentences, the concrete things you can see in that image. "
                "Do not guess about anything you cannot see.")
CONT_COMPANY = {"name": "Harbor Loom Co (synthetic demo)", "products": "Printed home textiles (synthetic demo)", "customers": "US home-textile shoppers (synthetic demo)",
                "goal": "Present our products clearly and accurately to shoppers"}
CONT_AGENT = {"role": "social_media", "name": "Harbor Loom Social", "objective": "Describe our product photos accurately so we can write promotional copy.",
              "instructions": "You work for Harbor Loom Co, a synthetic demo merchant. Describe only what is visible in an image and say what you are unsure of.",
              "company_context_refs": ["brand"], "requested_tools": ["inspect_image"], "skills": []}


def hermes_calls(log_text):
    """[(in, out)] of the 'API call #N' lines Hermes wrote for the conversation; and whether any stream/transport failure line exists."""
    import re
    calls = [(int(a), int(b)) for a, b in re.findall(r"API call #\d+:.*? in=(\d+) out=(\d+)", log_text)]
    bad = [x for x in log_text.splitlines() if any(k in x for k in ("Stream exhausted", "API call failed", "ReadError", "Transient", "primary_recovery"))]
    return calls, bad


def run_image(mode):
    live = mode == "continue-live"
    variant = mode.replace("continue-offline", "").strip("-")   # "", "big", "reject"
    EVID.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    orig_ledger = EVID / "ledger-live.jsonl"
    orig_hash = hashlib.sha256(orig_ledger.read_bytes()).hexdigest() if orig_ledger.exists() else None
    prior = cost(Ledger(orig_ledger, MAX_ATTEMPTS).rows())["measured_usd"] if live else 0.0
    if live:
        led = Ledger(EVID / "ledger-continuation.jsonl", CONTINUATION_CAP)
        if led.rows():
            sys.exit("REFUSED: the continuation ledger already has rows. One continuation only; delete nothing and ask for renewed authorization.")
        per, total = assert_budget(prior)
        key = read_key()
        if not key:
            sys.exit("REFUSED: NEBIUS_API_KEY not found in secrets/local.env")
        ctx = tls_ctx()
        rq = urllib.request.Request(UPSTREAM + "/models?verbose=true", headers={"Authorization": "Bearer " + key})
        with urllib.request.urlopen(rq, timeout=60, context=ctx) as r:
            entry = next((m for m in json.loads(r.read()).get("data", []) if m.get("id") == MODEL), None)
        if not entry:
            sys.exit(f"STOP before inference: {MODEL} is not in this account's model list.")
        print(f"PREFLIGHT listed; context_length={entry.get('context_length')}; pricing={json.dumps(entry.get('pricing'))[:200]}; previous measured spend ${prior:.6f}; "
              f"documented-limit bound {CONTINUATION_CAP} x ${per:.4f} -> combined <= ${total:.4f} (ceiling ${CEILING_USD:.2f})")
        if entry.get("context_length") != CONTEXT_TOKENS:
            sys.exit(f"STOP: the listing's context_length {entry.get('context_length')} differs from the documented {CONTEXT_TOKENS} the bound uses")
        upstream = UPSTREAM
    else:
        tmpl = Path(tempfile.mkdtemp(prefix="nebius-offline-ledger-"))
        led, key, ctx, upstream = Ledger(tmpl / "ledger.jsonl", CONTINUATION_CAP), "offline-dummy-key", None, f"http://127.0.0.1:{PORTS['mock']}/v1"
        per, total = assert_budget(0.0)
    assert led.path != orig_ledger
    before = fingerprint()
    dst = Path(tempfile.mkdtemp(prefix="nebius-compat-"))
    shutil.copytree(REAL / "app", dst / "app", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(REAL / "scripts", dst / "scripts", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    imgs = dst / "imgs"
    imgs.mkdir()
    src_image = REAL / "demo" / "v2-06-inputs" / "images" / "quilt-view-02.jpg"
    shutil.copy(src_image, imgs / f"{IMAGE_ID}.jpg")
    assert not (dst / "secrets").exists() and not (dst / "runtime").exists()
    env = {k: os.environ[k] for k in KEEP_ENV if k in os.environ}
    env.update(PYTHONUTF8="1", ECOM_CLASSIFIER="off", ECOM_ASSUME_EXISTING_RUNTIME="1", ECOM_SINGLE_ATTEMPT="1", HERMES_STREAM_RETRIES="0", HERMES_STREAM_STALE_TIMEOUT="600", ECOM_CHAT_MAX_ITERATIONS="4",
               ECOM_IMAGE_DIRS=str(imgs), ECOM_VISION_MODELS=f"nebius-token-factory:{MODEL}", LLM_PROVIDER="nebius-token-factory", LLM_MODEL=MODEL, NEBIUS_MODEL=MODEL,
               NEBIUS_API_KEY="local-proxy-token", NEBIUS_BASE_URL=f"http://127.0.0.1:{PORTS['proxy']}/v1")
    procs, report = [], {"mode": mode, "model": MODEL, "stages": [], "started": stamp, "setup": "specialist created by a LOCAL core.create_agent call (test setup, NOT model-created); the model-created path passed in the earlier run",
                         "previous_measured_usd": prior, "doc_bound_per_attempt_usd": round(per, 4), "doc_bound_combined_usd": round(total, 4)}
    P = Probe(led, upstream, key, ctx=ctx)
    P.stage = "cont_image"

    def stage_ok(name, ok, why):
        report["stages"].append({"stage": name, "pass": bool(ok), "why": why})
        print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{str(why)[:900]}]"), flush=True)
        return bool(ok)
    agent = None
    try:
        if not live:
            procs.append(subprocess.Popen([sys.executable, str(REAL / "tests" / "mock_llm.py"), str(PORTS["mock"])], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            time.sleep(1.2)
        P.start(PORTS["proxy"])
        subprocess.run([sys.executable, "scripts/setup.py"], cwd=dst, env=env, check=True, capture_output=True)
        procs.append(subprocess.Popen([sys.executable, "-m", "app.server", str(PORTS["app"])], cwd=dst, env=env, stdout=open(dst / "server.log", "wb"), stderr=subprocess.STDOUT))
        for _ in range(80):
            try:
                http(PORTS["app"], "/api/status", timeout=5)
                break
            except Exception:
                time.sleep(0.5)
        st, co = http(PORTS["app"], "/api/company", {"fields": CONT_COMPANY})
        assert st == 200, co
        made = json.loads(subprocess.run([sys.executable, "-c", "import json,sys;from app import core;print(json.dumps(core.create_agent(json.loads(sys.argv[1]))))", json.dumps(CONT_AGENT)],
                                         cwd=dst, env={**env, "HERMES_HOME": str(dst / "runtime" / "hermes_home" / "profiles" / "main"), "ECOM_APP_ROOT": str(dst), "ECOM_AGENT_ID": "main"},   # what the main worker's environment is
                                         capture_output=True, text=True, check=True).stdout.strip().splitlines()[-1])
        agent = made.get("agent_id")
        ok = stage_ok("SETUP (local core.create_agent, not a model call) one social_media specialist with inspect_image", made.get("ok") and agent and "inspect_image" in made.get("granted_tools", []), made)
        expect = json.loads(subprocess.run([sys.executable, "-c", "import json;from app import core;r=core.prepare_image(%r);import base64,hashlib;raw=base64.b64decode(r['data_url'].split(',',1)[1]);"
                                            "print(json.dumps({'ok':r['ok'],'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'w':r.get('width'),'h':r.get('height')}))" % IMAGE_ID],
                                           cwd=dst, env=env, capture_output=True, text=True, check=True).stdout.strip().splitlines()[-1])
        src_sha = hashlib.sha256(src_image.read_bytes()).hexdigest()
        print(f"READY; continuation ledger starts so far {led.starts()} (cap {CONTINUATION_CAP}); documented-limit bound combined ${total:.4f}")
        if ok:
            msg = CONT_MESSAGE + (" REJECT_IMAGES" if variant == "reject" else " BIG_REASONING" if variant == "big" else "") if not live else CONT_MESSAGE
            if not live and variant == "":
                msg = 'CALL_TOOL:{"name": "inspect_image", "args": {"image_id": "' + IMAGE_ID + '"}}'
            elif not live:
                msg = 'CALL_TOOL:{"name": "inspect_image", "args": {"image_id": "' + IMAGE_ID + '"}}' + (" REJECT_IMAGES" if variant == "reject" else " BIG_REASONING")
            st, r = http(PORTS["app"], f"/api/chat/{agent}", {"message": msg, "request_id": f"nc-cont-{stamp}"})
            tools = r.get("tools", [])
            rows = led.rows()
            starts = [x for x in rows if x["ev"] == "start"]
            ends = {x["n"]: x for x in rows if x["ev"] == "end"}
            carried = [x for x in starts if any(i.get("sha256") == expect["sha256"] for i in x["images"])]
            delivered = bool(carried) and all((ends.get(x["n"]) or {}).get("status") == 200 for x in carried) and all(any(i.get("role") == "tool" for i in x["images"]) for x in carried)
            insp = next((t for t in tools if t.get("name") == "inspect_image" and t.get("output")), None)
            ok = stage_ok("C1 the specialist itself called inspect_image and it prepared the image",
                          bool(insp) and not str(insp.get("output", "")).startswith('{"ok": false'), {"http": st, "tools": [t.get("name") for t in tools], "error": r.get("error")})
            ok = stage_ok("C2 the outgoing request carried the image bytes (sha256 equal to the app's prepared image) in the tool message and the endpoint answered 200",
                          ok and delivered, {"expected": expect, "attempts": [{"n": x["n"], "images": x["images"], "status": (ends.get(x["n"]) or {}).get("status")} for x in starts]})
            hl = dst / "runtime" / "hermes_home" / "profiles" / agent / "logs" / "agent.log"
            calls, bad = hermes_calls(hl.read_text(encoding="utf-8", errors="replace") if hl.exists() else "")
            last_end = ends.get(carried[-1]["n"]) if carried else None
            lu = (last_end or {}).get("usage") or {}
            reached = (st == 200 and r.get("ok") and r.get("text", "").strip() and not bad and calls and (lu.get("prompt_tokens"), lu.get("completion_tokens")) == calls[-1]
                       and not any(x["ev"] == "refused" and "identical" in x.get("why", "") for x in rows))
            ok = stage_ok("C3 the response reached Hermes and the application: the app turn is ok with a final answer, Hermes logged no stream/transport failure or recovery, its last API call's token counts equal the endpoint's usage, and no replay was attempted",
                          ok and reached, {"http": st, "error": r.get("error"), "hermes_calls": calls, "ledger_usage": lu, "failure_lines": bad[:3], "text_head": r.get("text", "")[:200]})
            import sqlite3
            con = sqlite3.connect(dst / "runtime" / "app.db")
            con.row_factory = sqlite3.Row
            irow = [dict(x) for x in con.execute("SELECT agent_id,image_id,kind,sha256,width,height,delivery,boundary_at,delivered_at FROM image_inspections WHERE agent_id=? AND image_id=?", (agent, IMAGE_ID))]
            con.close()
            ok = stage_ok("C4 the inspection record shows hook-confirmed delivery: one row for this agent and image, source sha256 equal to the sample file, delivery 'image_part_sent' and delivered_at set by the post-response hook",
                          ok and len(irow) == 1 and irow[0]["sha256"] == src_sha and irow[0]["delivery"] == "image_part_sent" and bool(irow[0]["delivered_at"]) and bool(irow[0]["boundary_at"]), irow)
            hit, good = score_description(r.get("text", ""))
            report["image"] = {"expected": expect, "source_sha256": src_sha, "inspection_rows": irow, "answer": r.get("text", ""), "groups_hit": hit, "scored_ok": good, "hermes_calls": calls,
                               "request_images": [{"attempt": x["n"], "images": x["images"]} for x in carried]}
            if live:
                ok = stage_ok("C5 the final answer states concrete image-only details (>=3 detail groups incl. bird or colour chart); id and prompt are neutral", ok and good, {"groups": hit, "answer": r.get("text", "")[:600]})
    except Exception as e:
        import traceback
        traceback.print_exc()
        stage_ok("HARNESS", False, f"{type(e).__name__}: {e}")
    finally:
        for p in procs:
            p.terminate()
        P.stop()
        time.sleep(1)
        if agent:
            hl = dst / "runtime" / "hermes_home" / "profiles" / agent / "logs" / "agent.log"
            if hl.exists():
                shutil.copy(hl, EVID / f"{mode}-agent-{stamp}.log")
        if (dst / "server.log").exists():
            shutil.copy(dst / "server.log", EVID / f"{mode}-server-{stamp}.log")
    rows = led.rows()
    c = cost(rows)
    report.update(ledger=rows, cost=c, attempts=led.starts(), refused=sum(x["ev"] == "refused" for x in rows), tripped=led.tripped(), combined_usage_estimate_usd=round(prior + c["upper_bound_usd"], 6),
                  all_passed=bool(report["stages"]) and all(s["pass"] for s in report["stages"]), real_unchanged=(before == fingerprint()),
                  original_ledger_unchanged=(orig_hash == (hashlib.sha256(orig_ledger.read_bytes()).hexdigest() if orig_ledger.exists() else None)))
    if live and not report["all_passed"] and not led.tripped():
        led.add({"ev": "trip", "why": "a stage failed: stop live testing, diagnose offline, ask for renewed authorization"})
    out = EVID / f"{mode}-result-{stamp}.json"
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"\n{mode.upper()} attempts={report['attempts']}/{CONTINUATION_CAP} refused_locally={report['refused']} cost={c} combined_estimate=${report['combined_usage_estimate_usd']} "
          f"real_project_unchanged={report['real_unchanged']} original_ledger_unchanged={report['original_ledger_unchanged']}\nEVIDENCE {out}")
    for st_ in report["stages"]:
        print(("PASS" if st_["pass"] else "FAIL"), st_["stage"][:110])
    shutil.rmtree(dst, ignore_errors=True)
    return report["all_passed"] and report["real_unchanged"] and report["original_ledger_unchanged"]


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "selftest":
        sys.exit(0 if selftest() else 1)
    if mode in ("offline", "live", "offline-reject", "offline-big"):
        sys.exit(0 if run(mode) else 1)
    if mode in ("continue-live", "continue-offline", "continue-offline-big", "continue-offline-reject"):
        sys.exit(0 if run_image(mode) else 1)
    sys.exit(__doc__)
