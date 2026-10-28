"""Regression: the API must deliver LARGE response bodies (the managed flyer image is ~3 MB). On Windows loopback one big wfile.write stalled ~19 s and then reset the connection after ~3.2 MB, so a saved
flyer image could not be retrieved through GET /api/flyers/images/<id>. No model, provider, credential or runtime: a temporary app root and a stand-in route on the real handler class (app.server.H.send).
  venv-python tests/server_send_test.py"""
import hashlib, http.client, os, sys, tempfile, threading, time
from http.server import ThreadingHTTPServer
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="send-test-")
os.environ["ECOM_APP_ROOT"] = TMP   # nothing of the real project runtime is touched
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import server  # noqa: E402

BIG = bytes((i * 7) % 251 for i in range(4_500_000))   # 4.5 MB, not compressible by accident, bigger than the observed failure point


class Route(server.H):
    def _get(self):
        if self.path == "/big":
            return self.send(200, BIG, "image/jpeg")
        return self.send(200, {"ok": True})

    def log_message(self, *a):
        pass


srv = ThreadingHTTPServer(("127.0.0.1", 0), Route)
threading.Thread(target=srv.serve_forever, daemon=True).start()
port = srv.server_address[1]
results = []


def get(path, timeout=40):
    t = time.time()
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        c.request("GET", path)
        r = c.getresponse()
        body = r.read()
        return r.status, body, time.time() - t, None
    except Exception as e:
        return None, b"", time.time() - t, type(e).__name__
    finally:
        c.close()


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{detail}]"), flush=True)


st, body, secs, err = get("/big")
check("S-1 a 4.5 MB response arrives complete and byte-identical, without a stall or a reset", st == 200 and hashlib.sha256(body).digest() == hashlib.sha256(BIG).digest() and secs < 10, (st, len(body), round(secs, 1), err))
st, body, secs, err = get("/small")
check("S-2 an ordinary small JSON response is unchanged", st == 200 and body == b'{"ok": true}', (st, body, err))
srv.shutdown()
print(f"{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
