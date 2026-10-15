"""Scripted stand-in for Google's Gemini Interactions endpoint. PLUMBING TESTS ONLY: the payloads follow the contract read from Google's official API reference
and image-generation guide on 2026-10-13 (POST /v1beta/interactions, x-goog-api-key, input[] text/image blocks, response_format, store; response status,
steps[].content[] image blocks, usage totals), but every image it returns is a GENERATED PLACEHOLDER. It says nothing about real Gemini output quality,
fidelity, cost or availability. Never report a result from it as real Gemini proof.
Usage: python tests/mock_gemini.py [port]
Control (POST /control, JSON; {"reset": true} first clears the log and behaviour):
  "mode": "ok" | "refuse" (HTTP 400) | "auth" (401) | "rate" (429) | "server" (500) | "failed" (status failed) | "no_image" | "two_images" | "corrupt" (undecodable bytes)
          | "bad_base64" | "wrong_mime" (JPEG bytes labelled image/png) | "uri_only" | "tiny" (8x8 image) | "drop" (connection closed, no answer) | "redirect" (302)
          | MALFORMED 200 bodies: "toplevel_list" (a JSON array), "steps_int" (steps: 1), "steps_item_int" (steps: [1]), "content_int" (model_output content: 1),
            "content_item_str" (content: ["x"]), "usage_str" (usage: "lots")
          | ECHOED-KEY responses (the stand-in puts its sentinel key into provider text): "echo_text" (completed, text only), "echo_status" (status string), "echo_id"
            (valid image, interaction id), "echo_mime" (image labelled image/<key>)
  "delay_ms": 0
  "colors": [[r,g,b], ...]  successful generations return SOLID control colours in this order (cycling; a known-control image the scripted reviewer can judge from its
            pixels). Default: seeded placeholders.
GET /stats -> {"requests": [{path, has_key, key_in_query, model, store, response_format, text, images: [{mime_type, sha256, bytes}], n_input}], "total": n}"""
import base64, hashlib, io, json, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOCK = threading.Lock()
LOG = []
CTL = {"mode": "ok", "delay_ms": 0, "colors": None, "n_ok": 0}
KEY = "TEST-GEMINI-KEY-SENTINEL"


def solid(color, size=(800, 1000), fmt="JPEG"):
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", size, tuple(color)).save(b, fmt)
    return b.getvalue()


def placeholder(seed, size=(800, 1000), fmt="JPEG"):
    from PIL import Image, ImageDraw
    r = int(hashlib.sha256(seed).hexdigest()[:2], 16)
    im = Image.new("RGB", size, (30 + r % 120, 90 + (r * 3) % 120, 200 - r % 100))
    if min(size) > 100:
        ImageDraw.Draw(im).rectangle([40, 40, size[0] - 40, size[1] - 40], outline=(255, 255, 255), width=6)
    b = io.BytesIO()
    im.save(b, fmt)
    return b.getvalue()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        raw = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path.startswith("/stats"):
            with LOCK:
                return self._send(200, {"requests": list(LOG), "total": len(LOG), "control": dict(CTL)})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if self.path == "/control":
            with LOCK:
                if body.get("reset"):
                    LOG.clear()
                    CTL.update({"mode": "ok", "delay_ms": 0, "colors": None, "n_ok": 0})
                CTL.update({k: v for k, v in body.items() if k in ("mode", "delay_ms", "colors")})
            return self._send(200, CTL)
        inputs = body.get("input") if isinstance(body.get("input"), list) else []
        imgs, text = [], ""
        for b in inputs:
            if isinstance(b, dict) and b.get("type") == "image":
                raw = base64.b64decode(b.get("data") or "")
                imgs.append({"mime_type": b.get("mime_type"), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
            elif isinstance(b, dict) and b.get("type") == "text":
                text += b.get("text") or ""
        with LOCK:
            LOG.append({"path": self.path.split("?")[0], "has_key": self.headers.get("x-goog-api-key") == KEY, "key_in_query": "key=" in self.path,
                        "content_type": self.headers.get("Content-Type"), "model": body.get("model"), "store": body.get("store"), "response_format": body.get("response_format"),
                        "text": text, "images": imgs, "n_input": len(inputs), "extra_fields": sorted(set(body) - {"model", "input", "response_format", "store"})})
        if CTL["delay_ms"]:
            time.sleep(CTL["delay_ms"] / 1000)
        if self.path.split("?")[0] != "/v1beta/interactions":
            return self._send(404, {"error": {"code": 404, "message": "not found"}})
        mode = CTL["mode"]
        if mode == "drop":
            self.connection.close()
            return
        if mode == "redirect":
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:1/stolen")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if mode == "toplevel_list":
            return self._send(200, [])
        if mode in ("refuse", "auth", "rate", "server"):
            code = {"refuse": 400, "auth": 401, "rate": 429, "server": 500}[mode]
            return self._send(code, {"error": {"code": code, "message": f"scripted {mode} (key was TEST-GEMINI-KEY-SENTINEL)"}})
        seed = (text + "".join(i["sha256"] for i in imgs)).encode()
        out = {"id": "interaction-" + hashlib.sha256(seed).hexdigest()[:12], "object": "interaction", "model": body.get("model"), "status": "completed",
               "usage": {"total_input_tokens": 1200 + 800 * len(imgs), "total_output_tokens": 1120, "total_thought_tokens": 64, "total_tokens": 2384 + 800 * len(imgs)}}
        def img(data, mime="image/jpeg"):
            return {"type": "image", "data": base64.b64encode(data).decode(), "mime_type": mime}
        good = placeholder(seed)
        if CTL.get("colors"):
            with LOCK:
                good = solid(CTL["colors"][CTL["n_ok"] % len(CTL["colors"])])
                CTL["n_ok"] += 1
        steps = [{"type": "user_input", "content": [{"type": "text", "text": "(echo)"}]}]
        content = [{"type": "text", "text": "Here is the flyer."}, img(good)]
        if mode == "failed":
            out.update(status="failed", errors=[{"code": "internal", "message": "scripted generation failure"}])
        elif mode == "no_image":
            content = [{"type": "text", "text": "I can't create that image."}]
        elif mode == "two_images":
            content = [img(good), img(placeholder(seed + b"2"))]
        elif mode == "corrupt":
            content = [img(good[: len(good) // 3])]
        elif mode == "bad_base64":
            content = [{"type": "image", "data": "@@@not-base64@@@", "mime_type": "image/jpeg"}]
        elif mode == "wrong_mime":
            content = [img(good, "image/png")]
        elif mode == "uri_only":
            content = [{"type": "image", "uri": "https://example.invalid/generated.jpg", "mime_type": "image/jpeg"}]
        elif mode == "tiny":
            content = [img(placeholder(seed, (8, 8)))]
        elif mode == "echo_text":
            content = [{"type": "text", "text": "I cannot help. Your key is " + KEY + " (echoed by the provider)."}]
        elif mode == "echo_status":
            out["status"] = "failed " + KEY
        elif mode == "echo_id":
            out["id"] = "interaction-" + KEY
        elif mode == "echo_mime":
            content = [img(good, "image/" + KEY)]
        steps.append({"type": "model_output", "content": content})
        out["steps"] = steps
        if mode == "steps_int":
            out["steps"] = 1
        elif mode == "steps_item_int":
            out["steps"] = [1]
        elif mode == "content_int":
            steps[1]["content"] = 1
        elif mode == "content_item_str":
            steps[1]["content"] = ["not-an-object"]
        elif mode == "usage_str":
            out["usage"] = "lots"
        self._send(200, out)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 8794), H).serve_forever()
