"""Scripted stand-in for ScrapeCreators' Facebook Ad Library endpoints and an ad-image CDN. PLUMBING TESTS ONLY: every payload is INVENTED in the documented
shape (research/v2-integration-feasibility.md section 2: list rows snake_case, detail camelCase, snapshot.images/cards, collation_id, reach fields). It says
nothing about real US ad inventory, real reach fields or real card schemas. Never report a result from it as live retrieval.
Usage: python tests/mock_fb_ads.py [port]
Control (POST /control, JSON; {"reset": true} first clears log + behaviour):
  "first": "irrelevant" | "empty" | "relevant"  what a keyword search WITHOUT a textile word answers (a query with a textile word always gets relevant ads)
  "reach": "absent" | "ambiguous" | "present" | "impressions"   absent: every reach field null (the documented examples); ambiguous: a bare reach_estimate
           (list + detail) with no meaning; present: aaa_info.eu_total_reach on DETAIL responses only (list endpoints keep nulls) - each ad its own value;
           impressions: reach fields null but impressions_with_index and spend filled (a metric that is NOT reach)
  "detail_fail": [ids], "image_fail": [ids] (404), "image_html": [ids], "drop": ["advertiser"|"search"|"detail"|"cdn"] (connection closed, no answer),
  "search_status": 500, "delay_ms": 0, "api_redirect": "<host>", "image_redirect": {"<image key>": "<absolute url>"},
  "detail_override": {"<ad id>": "wrong:<other id>" | "url_other:<other id>" | "page_other:<page id>" | "no_id"},
  "include_video": true (one VIDEO ad is added to keyword results), "dup_rows": true (the first row is repeated), "no_id_row": true (one row without ad_archive_id),
  "never_relevant": true (even a textile query gets what "first" says: unrelated ads or nothing)
GET /stats -> {"requests": [{kind, path, params, has_key}], "counts": {...}, "total": n}; /leak/* requests are logged as 'leak' (has_key shows a forwarded credential)."""
import io, json, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

LOCK = threading.Lock()
LOG = []
DEFAULT_CTL = {"first": "irrelevant", "reach": "absent", "detail_fail": [], "image_fail": [], "image_html": [], "drop": [], "search_status": None, "delay_ms": 0,
               "api_redirect": None, "image_redirect": {}, "detail_override": {}, "include_video": False, "dup_rows": False, "no_id_row": False, "never_relevant": False}
CTL = dict(DEFAULT_CTL)
PORT = 8792
TEXTILE = ("coverlet", "quilt", "comforter", "bedding", "duvet", "bedspread", "linen", "blanket")

PAGES = {"1001": ("Harbor Home Linens", "Home goods store", 52000), "1003": ("Northwind Beds", "Furniture store", 18000),
         "1002": ("Quick Auto Parts", "Auto parts", 9000), "1004": ("Slice Pizza Co", "Restaurant", 31000)}
# ad id -> (page, headline, body, [image colour...] , card titles, collation_id, collation_count, relevant)
ADS = {
    "1100000000000001": ("1001", "Queen quilted coverlet", "Soft layered comfort for every bedroom. Quilted coverlet in oatmeal.", [(222, 209, 186)], [], "5000000000000001", 2, True),
    "1100000000000002": ("1001", "Coverlet in sage", "The same coverlet range in sage green. Shop the quilted collection.", [(150, 175, 140)], [], "5000000000000001", 2, True),
    "1100000000000003": ("1001", "Bedding sets", "Bedding sets for every bedroom: sheets, quilts and pillow shams.", [], ["Quilt set", "Sheet set", "Pillow shams"], "5000000000000002", 1, True),
    "1100000000000004": ("1003", "Comforter set", "A queen comforter set with two shams. Simple, warm and easy to wash.", [(70, 90, 150)], [], None, None, True),
    "1200000000000001": ("1002", "Brake pads", "Brake pads for most cars. Fit in minutes.", [(90, 90, 90)], [], None, None, False),
    "1200000000000002": ("1004", "Two for one pizza", "Order tonight, any large pizza.", [(200, 60, 40)], [], None, None, False),
}
VIDEO = ("1300000000000001", ("1001", "Bedding video", "A video of a quilt being made.", [], [], None, None, True))


def png(color):
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (240, 300), color).save(b, "PNG")
    return b.getvalue()


def img_obj(aid, n):
    base = f"http://127.0.0.1:{PORT}/cdn/{aid}-{n}.png?oh=PRIVATE-SIGNED-{aid}-{n}&oe=1"
    return {"original_image_url": base, "resized_image_url": base.replace(".png", "-r.png"), "watermarked_resized_image_url": None, "image_crops": []}


def snapshot(aid, row, video=False):
    page, headline, body, colors, cards, *_ = row
    return {"page_name": PAGES.get(page, ("?",))[0], "title": headline, "body": {"text": body}, "caption": "example.com", "link_url": f"https://example.com/shop?utm=x&ad={aid}",
            "link_description": None, "cta_text": "Shop now", "cta_type": "SHOP_NOW", "display_format": "VIDEO" if video else ("MULTI_IMAGES" if cards else "IMAGE"),
            "images": [img_obj(aid, i + 1) for i in range(len(colors))],
            "cards": [{"title": t, "body": f"{t} from the range", "cta_text": "Shop now", **img_obj(aid, len(colors) + i + 1)} for i, t in enumerate(cards)],
            "extra_images": [], "videos": [{"video_hd_url": "https://video.example/x.mp4"}] if video else []}


def list_row(aid, row, video=False):
    page = row[0]
    return {"ad_archive_id": aid, "page_id": page, "page_name": PAGES[page][0], "is_active": True, "start_date": 1757000000, "end_date": None,
            "publisher_platform": ["FACEBOOK", "INSTAGRAM"], "collation_id": row[5], "collation_count": row[6], "total_active_time": 1814400,
            "entity_type": "PERSON_PROFILE", "page_like_count": PAGES[page][2], "targeted_or_reached_countries": ["US"],
            "reach_estimate": (11000 + int(aid[-1]) * 500) if CTL["reach"] == "ambiguous" else None,
            "impressions_with_index": ({"impressions_text": "1K-5K", "impressions_index": 3} if CTL["reach"] == "impressions" else {"impressions_text": None, "impressions_index": -1}),
            "spend": ({"lower_bound": 100, "upper_bound": 199} if CTL["reach"] == "impressions" else None), "currency": "USD" if CTL["reach"] == "impressions" else None,
            "snapshot": snapshot(aid, row, video)}


def detail_obj(aid, row, video=False):
    page = row[0]
    o = {"success": True, "credits_charged": 1, "credits_remaining": 880, "adArchiveID": int(aid), "pageID": page, "pageName": PAGES[page][0],
         "url": f"https://www.facebook.com/ads/library?id={aid}", "isActive": True, "startDate": 1757000000, "collationID": row[5], "collationCount": row[6],
         "publisherPlatform": ["FACEBOOK"], "reachEstimate": (11000 + int(aid[-1]) * 500) if CTL["reach"] == "ambiguous" else None,
         "impressionsWithIndex": ({"impressions_text": "1K-5K", "impressions_index": 3} if CTL["reach"] == "impressions" else {"impressions_text": None, "impressions_index": -1}),
         "spend": ({"lower_bound": 100, "upper_bound": 199} if CTL["reach"] == "impressions" else None),
         "aaa_info": ({"eu_total_reach": 20000 + int(aid[-1]) * 7000, "age_country_gender_reach_breakdown": []} if CTL["reach"] == "present" else {"eu_total_reach": None}),
         "snapshot": snapshot(aid, row, video)}
    return o


def find_row(aid):
    if aid == VIDEO[0]:
        return VIDEO[1], True
    return (ADS.get(aid), False)


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
                if body.get("reset"):
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
        kind = {"/v1/facebook/adLibrary/search/companies": "advertiser", "/v1/facebook/adLibrary/company/ads": "company", "/v1/facebook/adLibrary/search/ads": "search",
                "/v1/facebook/adLibrary/ad": "detail"}.get(u.path) or ("cdn" if u.path.startswith("/cdn/") else "leak" if u.path.startswith("/leak/") else None)
        if kind is None:
            return self._send(404, {"error": "not found"})
        with LOCK:
            LOG.append({"kind": kind, "path": u.path, "params": q, "has_key": "x-api-key" in {k.lower() for k in self.headers.keys()}, "at": time.time()})
        if CTL["delay_ms"]:
            time.sleep(CTL["delay_ms"] / 1000)
        group = "search" if kind in ("company", "search") else kind
        if kind in CTL["drop"] or group in CTL["drop"]:   # the connection closes with no answer: the outcome is unknown to the caller
            self.connection.close()
            return
        if kind == "leak":
            return self._send(200, {"success": True, "credits_charged": 1, "credits_remaining": 1, "searchResults": []})
        if CTL["api_redirect"] and kind in ("advertiser", "company", "search", "detail"):
            self.send_response(302)
            self.send_header("Location", f"http://{CTL['api_redirect']}:{PORT}/leak/{kind}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if kind == "advertiser":
            qs = q.get("query", "").lower()
            rows = [(p, v) for p, v in PAGES.items() if any(w in v[0].lower() for w in qs.split()) or qs in v[0].lower()]
            return self._send(200, {"success": True, "credits_charged": 1, "credits_remaining": 950,
                                    "searchResults": [{"page_id": p, "name": v[0], "category": v[1], "likes": v[2], "verification": "BLUE_VERIFIED", "entity_type": "PERSON_PROFILE",
                                                       "ig_username": None, "ig_followers": None, "page_alias": v[0].replace(" ", "").lower(), "page_is_deleted": False,
                                                       "image_uri": "https://scontent.example/p.jpg"} for p, v in rows]})
        if kind in ("company", "search"):
            if CTL["search_status"]:
                return self._send(CTL["search_status"], {"success": False, "error": "upstream unavailable"})
            if kind == "company":
                page = q.get("pageId", "")
                rows = [(a, r) for a, r in ADS.items() if r[0] == page]
                key = "results"
            else:
                qs = q.get("query", "").lower()
                key = "searchResults"
                if not CTL["never_relevant"] and (any(w in qs for w in TEXTILE) or CTL["first"] == "relevant"):
                    rows = [(a, r) for a, r in ADS.items() if r[7]]
                elif CTL["first"] == "empty":
                    rows = []
                else:
                    rows = [(a, r) for a, r in ADS.items() if not r[7]]
            out = [list_row(a, r) for a, r in rows]
            if CTL["include_video"] and kind == "search":
                out.append(list_row(VIDEO[0], VIDEO[1], video=True))
            if CTL["dup_rows"] and out:
                out.append(dict(out[0]))
            if CTL["no_id_row"] and out:
                bad = dict(out[0])
                bad.pop("ad_archive_id")
                out.append(bad)
            body = {"success": True, "credits_charged": 1, "credits_remaining": 940, key: out, "cursor": ("CUR-" + q.get("query", q.get("pageId", ""))[:8]) if out else None}
            if kind == "search":
                body["searchResultsCount"] = len(out)
            return self._send(200, body)
        if kind == "detail":
            aid = q.get("id", "")
            if aid in CTL["detail_fail"]:
                return self._send(500, {"success": False, "error": "detail service error"})
            row, video = find_row(aid)
            if not row:
                return self._send(404, {"success": False, "error": "ad not found"})
            o = detail_obj(aid, row, video)
            spec = CTL["detail_override"].get(aid)
            if spec:
                k, _, arg = spec.partition(":")
                if k == "wrong":
                    r2, v2 = find_row(arg)
                    o = detail_obj(arg, r2, v2)
                elif k == "url_other":
                    o["url"] = f"https://www.facebook.com/ads/library?id={arg}"
                elif k == "page_other":
                    o["pageID"] = arg
                elif k == "no_id":
                    o.pop("adArchiveID", None)
                    o.pop("url", None)
            return self._send(200, o)
        if kind == "cdn":
            key = u.path.rsplit("/", 1)[-1].replace(".png", "")
            if key in CTL["image_redirect"]:
                self.send_response(302)
                self.send_header("Location", CTL["image_redirect"][key])
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if key in CTL["image_fail"]:
                return self._send(404, b"gone", "text/plain")
            if key in CTL["image_html"]:
                return self._send(200, b"<html>login</html>", "text/html")
            aid, n = key.rsplit("-", 1)
            row, _ = find_row(aid.replace("-r", ""))
            colors = (row[3] if row else []) or [(60 + 40 * i, 120, 200 - 30 * i) for i in range(1, 8)]   # card-only ads: a distinct colour per card
            return self._send(200, png(colors[(int(n) - 1) % len(colors)] if n.isdigit() else colors[0]), "image/png")


if __name__ == "__main__":
    PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8792
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
