"""Scripted stand-in for ScrapeCreators' Marketplace endpoints and a photo CDN. PLUMBING TESTS ONLY: payloads are invented in the documented shape
(see tests/marketplace_check_test.py) and say nothing about real Marketplace inventory. Never report a result from it as live retrieval.
Usage: python tests/mock_scrapecreators.py [port]
Control (POST /control, JSON): {"first": "irrelevant"|"empty"|"relevant", "item_fail": [ids], "photo_fail": [ids], "photo_html": [ids], "drop": ["search", "item", ...],
  "search_status": 500, "delay_ms": 0, "item_override": {"<id>": "wrong:<other id>" | "no_id" | "no_id_no_url" | "no_id_other_url:<other id>" | "url_other:<other id>" (id kept, URL names
  another listing) | "id_other:<other id>" (URL kept, id names another listing)}, "search_url_override": {"<id>": "<other id>"} (that search row keeps its id but its
  URL names another listing),
  "api_redirect": "<host>" (every API endpoint answers 302 to http://<host>:PORT/leak/<kind>), "photo_redirect": {"<id>": "<absolute url>"}}.
  A location query containing 'austin' answers with Austin coordinates (distinct from Dallas).
  GET /stats -> {"requests": [{kind, path, params, has_key}], "counts": {...}}; /leak/* requests are logged with kind 'leak' (has_key shows a forwarded credential)."""
import io, json, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

LOCK = threading.Lock()
LOG = []
DEFAULT_CTL = {"first": "irrelevant", "item_fail": [], "photo_fail": [], "photo_html": [], "drop": [], "search_status": None, "delay_ms": 0,
               "item_override": {}, "search_url_override": {}, "api_redirect": None, "photo_redirect": {}}
CTL = dict(DEFAULT_CTL)
PORT = 8790

UNRELATED = [("8001", "Used mountain bike 21 speed", 90), ("8002", "Set of 4 truck tires", 300), ("8003", "Dining chair oak", 20)]
RELEVANT = [("9001", "Queen comforter set new in bag", 45, "Brand new queen comforter set, still sealed in the original bag. 7 pieces. Smoke free home."),
            ("9002", "Quilted bedspread coverlet 90x96 oatmeal", 60, "New quilted coverlet, oatmeal colour with a diamond stitch pattern, 90 x 96 in. Never used."),
            ("9003", "Bedding set king 7 piece", 55, "King size bedding set, 7 pieces, new with tags."),
            ("9004", "Cotton quilt set queen", 70, "Queen quilt set with two shams, new, bought as a gift and never opened.")]
COLORS = {"9001": (200, 90, 60), "9002": (222, 209, 186), "9003": (70, 90, 150), "9004": (120, 160, 110)}


def png(lid):
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (240, 180), COLORS.get(lid, (128, 128, 128))).save(b, "PNG")
    return b.getvalue()


def raw_search_item(lid, title, price):
    return {"id": lid, "url": f"https://www.facebook.com/marketplace/item/{lid}/", "title": title, "price": {"formatted_amount": f"${price}", "amount": price},
            "location": {"city": "Dallas", "state": "TX", "display_name": "Dallas, TX"},
            "primary_photo": {"id": f"p{lid}", "url": f"http://127.0.0.1:{PORT}/cdn/{lid}.png?oh=PRIVATE-SIGNED-{lid}&oe=1"},
            "category_id": "c", "is_live": True, "is_sold": False, "delivery_types": ["IN_PERSON"]}


def raw_item(lid):
    row = next((r for r in RELEVANT if r[0] == lid), None) or next((u for u in UNRELATED if u[0] == lid), None)
    if not row:
        return None
    desc = row[3] if len(row) > 3 else "Used item, works fine."
    return {"success": True, "credits_charged": 1, "credits_remaining": 900, "id": lid, "url": f"https://www.facebook.com/marketplace/item/{lid}/", "title": row[1],
            "description": desc, "price": {"formatted_amount_zeros_stripped": f"${row[2]}", "amount": row[2], "currency": "USD"}, "location_text": "Dallas, TX",
            "location": {"latitude": 32.7, "longitude": -96.8}, "attributes": [{"attribute_name": "Condition", "value": "new", "label": "New"}],
            "photos": [{"id": f"p{lid}", "url": f"http://127.0.0.1:{PORT}/cdn/{lid}.png?oh=PRIVATE-SIGNED-{lid}&oe=1", "width": 240, "height": 180,
                        "accessibility_caption": "A bed with bedding"}],
            "seller": {"id": f"S-{lid}", "name": "Private Person", "profile_picture": "https://cdn.example/x.jpg"}, "creation_time": 1760000000}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj, ctype="application/json"):
        raw = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        if self.path == "/control":
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            with LOCK:
                if body.get("reset"):   # a fresh scenario: empty request log AND default behaviour
                    LOG.clear()
                    CTL.clear()
                    CTL.update(DEFAULT_CTL)
                CTL.update({k: v for k, v in body.items() if k in DEFAULT_CTL})
            return self._send(200, CTL)
        self._send(404, {"error": "not found"})

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == "/stats":
            with LOCK:
                counts = {}
                for r in LOG:
                    counts[r["kind"]] = counts.get(r["kind"], 0) + 1
                return self._send(200, {"requests": list(LOG), "counts": counts, "total": len(LOG), "control": dict(CTL)})
        kind = {"/v1/facebook/marketplace/location/search": "location", "/v1/facebook/marketplace/search": "search",
                "/v1/facebook/marketplace/item": "item"}.get(u.path) or ("cdn" if u.path.startswith("/cdn/") else "leak" if u.path.startswith("/leak/") else None)
        if kind is None:
            return self._send(404, {"error": "not found"})
        with LOCK:
            LOG.append({"kind": kind, "path": u.path, "params": q, "has_key": "x-api-key" in {k.lower() for k in self.headers.keys()}, "at": time.time()})
        if CTL["delay_ms"]:
            time.sleep(CTL["delay_ms"] / 1000)
        if kind in CTL["drop"]:   # the connection is closed without any answer: the outcome is unknown to the caller
            self.connection.close()
            return
        if kind == "leak":   # a redirect target: answers like a valid location lookup so an unguarded client would "succeed"
            return self._send(200, {"success": True, "credits_charged": 1, "credits_remaining": 1, "locations": []})
        if CTL["api_redirect"] and kind in ("location", "search", "item"):
            self.send_response(302)
            self.send_header("Location", f"http://{CTL['api_redirect']}:{PORT}/leak/{kind}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if kind == "location":
            austin = "austin" in q.get("query", "").lower()
            return self._send(200, {"success": True, "credits_charged": 1, "credits_remaining": 950,
                                    "locations": [{"name": "Austin, Texas" if austin else "Dallas, Texas", "subtitle": "City", "multi_line_address": [], "page_id": "2" if austin else "1",
                                                   "latitude": 30.2672 if austin else 32.7774, "longitude": -97.7431 if austin else -96.7977,
                                                   "city": "Austin" if austin else "Dallas", "postal_code": "78701" if austin else "75201"}]})
        if kind == "search":
            if CTL["search_status"]:
                return self._send(CTL["search_status"], {"success": False, "error": "upstream unavailable"})
            qs = q.get("query", "").lower()
            if any(w in qs for w in ("comforter", "bedding", "duvet")):
                rows = [raw_search_item(r[0], r[1], r[2]) for r in RELEVANT]
            elif CTL["first"] == "empty":
                rows = []
            elif CTL["first"] == "relevant":
                rows = [raw_search_item(r[0], r[1], r[2]) for r in RELEVANT]
            else:
                rows = [raw_search_item(*r) for r in UNRELATED]
            for r in rows:
                if r["id"] in CTL["search_url_override"]:
                    r["url"] = f"https://www.facebook.com/marketplace/item/{CTL['search_url_override'][r['id']]}/"
            return self._send(200, {"success": True, "credits_charged": 1, "credits_remaining": 940, "has_next_page": bool(rows), "cursor": "CUR-" + qs[:8], "listings": rows})
        if kind == "item":
            lid = q.get("id", "")
            if lid in CTL["item_fail"]:
                return self._send(500, {"success": False, "error": "item service error"})
            it = raw_item(lid)
            spec = CTL["item_override"].get(lid)
            if it and spec:
                kindo, _, arg = spec.partition(":")
                if kindo == "wrong":
                    it = raw_item(arg)
                elif kindo == "url_other":
                    it = {**it, "url": f"https://www.facebook.com/marketplace/item/{arg}/"}
                elif kindo == "id_other":
                    it = {**it, "id": arg}
                else:
                    it = dict(it)
                    it.pop("id", None)
                    if kindo in ("no_id_no_url", "no_id_other_url"):
                        it.pop("url", None)
                    if kindo == "no_id_other_url":
                        it["url"] = f"https://www.facebook.com/marketplace/item/{arg}/"
            return self._send(200, it) if it else self._send(404, {"success": False, "error": "item not found"})
        if kind == "cdn":
            lid = u.path.rsplit("/", 1)[-1].split(".")[0]
            if lid in CTL["photo_redirect"]:
                self.send_response(302)
                self.send_header("Location", CTL["photo_redirect"][lid])
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if lid in CTL["photo_fail"]:
                return self._send(404, b"gone", "text/plain")
            if lid in CTL["photo_html"]:
                return self._send(200, b"<html>login</html>", "text/html")
            return self._send(200, png(lid), "image/png")


if __name__ == "__main__":
    PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8790
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
