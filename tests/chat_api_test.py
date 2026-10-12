"""Backend chat-API tests against tests/ui_test_server.py (fake turns, no model). Run from a COPY of the project:
UI_TEST_I_AM_A_COPY=1 venv-python tests/chat_api_test.py"""
import http.server, json, os, subprocess, sys, threading, time, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if os.environ.get("UI_TEST_I_AM_A_COPY") != "1":
    sys.exit("Refusing to run: set UI_TEST_I_AM_A_COPY=1 and run from a COPY of the project.")
sys.path.insert(0, str(ROOT))
PORT = 8810
results = []


def check(name, ok, detail=""):
    ok = bool(ok); results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{str(detail)[:300]}]"), flush=True)


def call(path, body=None, raw=None, port=PORT):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, headers={"Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=60); return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def rows(a): return len(call(f"/api/chat/{a}")[1])
def fake_calls(): return len((ROOT / "runtime/fake_calls.log").read_text().splitlines()) if (ROOT / "runtime/fake_calls.log").exists() else 0


def burst(agent, msgs):   # all requests released at the same instant
    out, gate = [None] * len(msgs), threading.Barrier(len(msgs))
    def go(i, m):
        gate.wait(); out[i] = call(f"/api/chat/{agent}", m)
    ts = [threading.Thread(target=go, args=(i, m)) for i, m in enumerate(msgs)]
    [t.start() for t in ts]; [t.join() for t in ts]
    return out


srv = subprocess.Popen([sys.executable, "tests/ui_test_server.py", str(PORT)], cwd=ROOT, env={**os.environ, "PYTHONUTF8": "1", "ECOM_CLASSIFIER": "off"},
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(60):
        try: call("/api/status"); break
        except Exception: time.sleep(0.5)

    # 1. rapid duplicates with different ids while a turn runs
    r0, c0 = rows("spec-a"), fake_calls()
    res = burst("spec-a", [{"message": "SLOW one", "request_id": f"d{i}"} for i in range(6)])
    codes = sorted(s for s, _ in res)
    check("6 simultaneous sends: exactly one accepted, five rejected 409 agent_busy", codes == [200] + [409] * 5 and
          all(b.get("code") == "agent_busy" for s, b in res if s == 409), res)
    check("rejected duplicates added no transcript row and ran nothing", rows("spec-a") - r0 == 2 and fake_calls() - c0 == 1, (rows("spec-a") - r0, fake_calls() - c0))

    # 2. same request id twice at once
    r0, c0 = rows("spec-a"), fake_calls()
    res = burst("spec-a", [{"message": "SLOW same", "request_id": "same-1"}] * 3)
    check("same request id sent 3x at once: one runs, others duplicate_in_flight", sorted(s for s, _ in res) == [200, 409, 409] and
          {b.get("code") for s, b in res if s == 409} <= {"duplicate_in_flight", "agent_busy"}, res)
    check("...and only 2 rows added", rows("spec-a") - r0 == 2 and fake_calls() - c0 == 1)

    # 3. completed request replayed on retry
    r0, c0 = rows("spec-a"), fake_calls()
    s, b = call("/api/chat/spec-a", {"message": "SLOW same", "request_id": "same-1"})
    check("retry of a COMPLETED request returns its stored result, runs nothing, adds no rows",
          s == 200 and b.get("replayed") and b["ok"] and rows("spec-a") == r0 and fake_calls() == c0, (s, b))

    # 4. rejected inputs
    r0 = rows("spec-b")
    cases = [("empty", {"message": "   "}, 400, "empty_message"), ("too long", {"message": "x" * 8001}, 413, "message_too_long")]
    for label, body, st, code in cases:
        s, b = call("/api/chat/spec-b", body)
        check(f"{label} message -> {st} {code}", s == st and b.get("code") == code and b["ok"] is False and isinstance(b["error"], str), (s, b))
    s, b = call("/api/chat/spec-b", raw=b"{not json")
    check("invalid JSON -> 400 invalid_request", s == 400 and b.get("code") == "invalid_request", (s, b))
    s, b = call("/api/chat/nope", {"message": "hi"})
    check("unknown agent -> 404 unknown_agent", s == 404 and b.get("code") == "unknown_agent", (s, b))
    check("no rejected request created a transcript row", rows("spec-b") == r0)

    # 5. backend exception inside the turn: visible error, agent not stuck
    s, b = call("/api/chat/spec-b", {"message": "BOOM", "request_id": "boom-1"})
    check("exception in a turn -> 200 ok:false with explicit backend error, saved as error row",
          s == 200 and b["ok"] is False and "Backend error" in b["error"] and call("/api/chat/spec-b")[1][-1]["who"] == "error", (s, b))
    check("agent is idle again and accepts the next message", call("/api/agents/spec-b")[1]["state"] == "idle" and call("/api/chat/spec-b", {"message": "after boom"})[1]["ok"])

    # 6. failed turn is NOT replayed on retry with the same id
    c0 = fake_calls()
    call("/api/chat/spec-b", {"message": "ERR please", "request_id": "err-1"}); call("/api/chat/spec-b", {"message": "ERR please", "request_id": "err-1"})
    check("a failed turn retried with the same id runs again (not replayed)", fake_calls() - c0 == 2)

    # 7. activity labels + status
    s, b = call("/api/chat/spec-b", {"message": "CREATE it"})
    labels = [(a["label"], a["status"]) for a in b["activity"]]
    check("activity: readable labels + statuses, raw kept", labels == [("Reading company context", "ok"), ("Creating specialist", "error")]
          and b["activity"][1]["input"] and b["activity"][1]["output"], labels)
    h = call("/api/chat/spec-b")[1]
    check("history returns activity for saved rows", h[-1]["activity"] and h[-1]["activity"][0]["label"] == "Reading company context")

    # 8. /api/state and independent agents
    res = {}
    t = threading.Thread(target=lambda: res.update(a=call("/api/chat/spec-a", {"message": "SLOW state"})))
    t.start(); time.sleep(1.5)
    st = call("/api/state")[1]
    sb = call("/api/chat/spec-b", {"message": "meanwhile"})
    check("/api/state shows only the busy agent; another agent still answers", "spec-a" in st and "spec-b" not in st and sb[0] == 200 and sb[1]["ok"], (st, sb))
    t.join()
    check("/api/state clears when the turn ends", call("/api/state")[1] == {})

    # 9. unexpected backend failure -> structured 500 (in-process server with chat() broken)
    from app import server
    server.chat = lambda *a: (_ for _ in ()).throw(RuntimeError("db exploded"))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 8811), server.H); threading.Thread(target=httpd.serve_forever, daemon=True).start()
    s, b = call("/api/chat/spec-a", {"message": "hi"}, port=8811)
    check("unexpected backend exception -> 500 internal_error that warns the message may be recorded",
          s == 500 and b.get("code") == "internal_error" and "may or may not" in b["error"], (s, b))
    httpd.shutdown()
finally:
    srv.terminate()
print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if results and all(results) else 1)
