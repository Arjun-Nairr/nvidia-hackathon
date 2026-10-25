"""V2-06 live-test readiness check. READ-ONLY and OFFLINE: no network, no provider call, no database write; prints presence/validity only, never a secret value.

  python scripts/v2_06_readiness.py [--catalogue FILE] [--images DIR] [--env FILE]

Defaults are the private, git-ignored input location demo/v2-06-inputs/ (catalogue.json + images/). Exit 0 only when every REQUIRED item passes.
It reuses the backend's own validators (listing.product_missing, flyer._is_synthetic / _provenance_missing, the merchant-image loader rules), so what it accepts is
what generate_flyer will accept."""
import argparse, json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import core, flyer, listing  # noqa: E402  (pure helpers only; importing them opens no database and makes no request)

PHOTO_MIN, PHOTO_MAX = 2, 3   # the V2 brief: 2-3 actual supplied photographs (the backend sends at most 3 per request)


def env_file(p):
    out = {}
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def git(*a):
    r = subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalogue", default=str(ROOT / "demo" / "v2-06-inputs" / "catalogue.json"))
    ap.add_argument("--images", default=str(ROOT / "demo" / "v2-06-inputs" / "images"))
    ap.add_argument("--env", default=str(ROOT / "secrets" / "local.env"))
    a = ap.parse_args(argv)
    rows = []   # (required, ok, name, detail)

    def add(req, ok, name, detail=""):
        rows.append((req, bool(ok), name, detail))

    env = env_file(Path(a.env))
    # ---- credentials and model configuration (presence only)
    add(True, bool(env.get("GEMINI_API_KEY")), "GEMINI_API_KEY set in the ignored env file", "" if env.get("GEMINI_API_KEY") else "field missing or empty")
    add(False, bool(env.get("GEMINI_MODEL")), "GEMINI_MODEL explicit", f"effective: {env.get('GEMINI_MODEL') or flyer.MODEL_DEFAULT} ({'explicit' if env.get('GEMINI_MODEL') else 'code default'})")
    add(False, True, "GEMINI_IMAGE_SIZE", f"effective: {env.get('GEMINI_IMAGE_SIZE') or '2K'}")
    add(True, bool(env.get("SCRAPECREATORS_API_KEY")), "SCRAPECREATORS_API_KEY set", "")
    prov, model = env.get("LLM_PROVIDER") or "openai-codex", env.get("LLM_MODEL") or ""
    add(True, prov in core.PROVIDERS and bool(model), "reasoning provider/model selected", f"{prov} / {model or 'LLM_MODEL missing'}")
    add(False, (prov, model) in core.VISION_VERIFIED, "image-in-tool-result delivery has LIVE evidence for this pair",
        "yes (V1 inspect_image, 2026-10-10)" if (prov, model) in core.VISION_VERIFIED else "NO live evidence for this provider/model")
    ign = [git("check-ignore", "-q", str(Path(a.env)))[0] == 0]
    add(True, ign[0], "env file is git-ignored", "")
    # ---- merchant catalogue
    cpath = Path(a.catalogue)
    cat, prod, ok_cat = None, None, False
    if not cpath.exists():
        add(True, False, "catalogue file present", f"missing: {cpath}")
    else:
        try:
            cat = json.loads(cpath.read_text(encoding="utf-8"))
            ok_cat = isinstance(cat, dict) and isinstance(cat.get("products"), list) and isinstance(cat.get("merchant"), dict)
        except ValueError:
            pass
        add(True, ok_cat, "catalogue file parses (merchant object + products list)", str(cpath))
    if ok_cat:
        add(True, bool(str(cat["merchant"].get("name") or cat["merchant"].get("company_name") or "").strip()), "merchant name present",
            "must equal the demo company's saved name (checked at run time)")
        add(True, not cat.get("demo") and not cat.get("_template"), "catalogue is not the demo fixture or the template", "")
        prod = next((p for p in cat["products"] if isinstance(p, dict) and not listing.product_missing(p)), None)
        first = next((p for p in cat["products"] if isinstance(p, dict)), None)
        add(True, prod is not None, "one product with every required fact (name, specifications, price, currency, image)",
            "" if prod else (f"missing for {first.get('product_id')!r}: {listing.product_missing(first)}" if first else "no product"))
    # ---- merchant photographs
    imgs_dir = Path(a.images)
    tracked = git("ls-files", "--error-unmatch", str(cpath))[0] == 0 if cpath.exists() else False
    add(True, git("check-ignore", "-q", str(cpath))[0] == 0 and not tracked, "catalogue location is git-ignored and untracked", str(cpath))
    add(True, git("check-ignore", "-q", str(imgs_dir / "x.jpg"))[0] == 0 and not git("ls-files", str(imgs_dir))[1], "photo folder is git-ignored and untracked", str(imgs_dir))
    if prod is not None:
        ims = listing.product_images(prod)
        add(True, PHOTO_MIN <= len(ims) <= PHOTO_MAX, f"{PHOTO_MIN}-{PHOTO_MAX} photographs registered for the product", f"{len(ims)} registered")
        for im in ims:
            iid = im["image_id"]
            path = next((p for e in core.IMAGE_EXTS for p in [imgs_dir / f"{iid}{e}"] if p.is_file()), None)
            if path is None:
                add(True, False, f"photo {iid}: file present in the photo folder", f"no {iid}.jpg/.png/.webp in {imgs_dir}")
                continue
            ok, detail = True, ""
            try:
                from PIL import Image
                raw = path.read_bytes()
                im_ = Image.open(path)
                fmt = im_.format
                im_.load()
                ok = fmt in flyer.IN_FORMATS and len(raw) <= core.MAX_IMAGE_BYTES
                detail = f"{fmt} {im_.width}x{im_.height} {len(raw)} bytes"
            except Exception as e:
                ok, detail = False, f"unreadable ({type(e).__name__})"
            add(True, ok, f"photo {iid}: decodes as JPEG/PNG/WEBP within {core.MAX_IMAGE_BYTES} bytes", detail)
            miss = flyer._provenance_missing(im)
            add(True, not miss, f"photo {iid}: provenance owner/date/usage_statement", "" if not miss else f"missing {miss}")
            add(True, not flyer._is_synthetic(cat, im), f"photo {iid}: not marked synthetic/illustration/placeholder", "")
    width = max((len(r[2]) for r in rows), default=10)
    for req, ok, name, detail in rows:
        print(f"{'PASS   ' if ok else ('BLOCKED' if req else 'note   ')} {name.ljust(width)}  {detail}".rstrip())
    bad = [r for r in rows if r[0] and not r[1]]
    print(f"\n{'READY' if not bad else 'NOT READY'}: {len(bad)} required item(s) outstanding. No network, provider or database call was made.")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
