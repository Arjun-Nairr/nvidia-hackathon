"""LIVE image-inspection check through a real specialist worker with the real subscription model (openai-codex). Spends SUBSCRIPTION quota
only (no Nebius). Runs in an ISOLATED COPY of the project: it needs runtime/hermes_home/auth.json + config.yaml and secrets/local.env copied
from the real runtime (the launcher does that) and refuses unless the copied login has >= 20 minutes of access-token life (so the copy cannot
trigger a single-use refresh that would invalidate the real login). Target: at most 6 model requests (2 turns, parallel tool calls).
Pixels differ in KNOWN ways that no filename, caption or prompt states. Distinguishing content: image X = green triangle on yellow with the
text 42; image Y = purple circle on white with the text KX9.
  IMAGE_LIVE_I_AM_A_COPY=1 ECOM_TIMING=1 venv-python tests/image_live_check.py [path-to-private-marketplace-photo]"""
import base64, json, os, shutil, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if os.environ.get("IMAGE_LIVE_I_AM_A_COPY") != "1":
    sys.exit("Refusing to run: copy of the project only (IMAGE_LIVE_I_AM_A_COPY=1).")
sys.path.insert(0, str(ROOT))
os.environ["ECOM_TIMING"] = "1"
from PIL import Image, ImageDraw, ImageFont
from app import core

results = []
OUT = ROOT / "image_live_result.json"


def check(name, ok, detail=""):
    ok = bool(ok); results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{str(detail)[:600]}]"), flush=True)


def token_life_seconds():
    best = None

    def walk(o):
        nonlocal best
        if isinstance(o, dict):
            for v in o.values(): walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)
        elif isinstance(o, str) and o.count(".") == 2:
            try:
                pay = json.loads(base64.urlsafe_b64decode(o.split(".")[1] + "=" * (-len(o.split(".")[1]) % 4)))
                if "exp" in pay:
                    life = pay["exp"] - time.time(); best = life if best is None else min(best, life)
            except Exception:
                pass
    walk(json.loads((core.HERMES_ROOT / "auth.json").read_text(encoding="utf-8")))
    return best


cfg, problem, life = core.llm_config(), core.llm_problem(), token_life_seconds()
print(f"provider {cfg['provider']} model {cfg['model']} | login token life: {None if life is None else round(life / 60)} min | problem: {problem}")
if problem or life is None or life < 20 * 60 or cfg["provider"] != "openai-codex":
    sys.exit("NOT RUN: " + (problem or "login token life too short/unknown, or provider is not the subscription provider"))

# ---- controls (neutral names), a corrupt file, and a private Marketplace photo referenced by its source ID
IMG = ROOT / "runtime" / "img_controls"
IMG.mkdir(parents=True, exist_ok=True)
os.environ["ECOM_IMAGE_DIRS"] = str(IMG)
font = ImageFont.load_default(size=56)


def make(path, bg, shape, color, text):
    im = Image.new("RGB", (360, 270), bg)
    d = ImageDraw.Draw(im)
    if shape == "triangle":
        d.polygon([(180, 30), (90, 190), (270, 190)], fill=color)
    else:
        d.ellipse([100, 30, 260, 190], fill=color)
    d.text((130, 200), text, fill=(0, 0, 0), font=font)
    im.save(path)


X, Y = IMG / "x.png", IMG / "y.png"
make(X, (250, 220, 40), "triangle", (20, 150, 40), "42")       # green triangle, yellow background, text 42
make(Y, (255, 255, 255), "circle", (130, 40, 170), "KX9")      # purple circle, white background, text KX9
shutil.copy(X, IMG / "ref-a.png")
shutil.copy(Y, IMG / "ref-b.png")
(IMG / "ref-corrupt.png").write_bytes(X.read_bytes()[:80])
MKT = sys.argv[1] if len(sys.argv) > 1 else None
MKT_ID = None
if MKT and Path(MKT).is_file():
    MKT_ID = Path(MKT).stem                                    # the source listing ID is the file name
    shutil.copy(MKT, IMG / Path(MKT).name)

# ---- company + specialist through the real backend validation (no model needed for creation).
# Hermes resolves profile locations from HERMES_HOME exactly as the worker's env sets it: without it the profile would land in the USER'S real
# Hermes home (core._write_profile now refuses that).
os.environ["HERMES_HOME"] = str(core.HERMES_ROOT / "profiles" / "main")
assert str(core.HERMES_ROOT).startswith(str(ROOT)), "isolated copy required"
core.update_company({"name": "Acme Linens", "products": "Cotton bedding and curtains", "customers": "Home buyers in the US",
                     "goal": "Understand how competing bedding listings present their products"}, source="form")
r = core.create_agent({"role": "market_analysis", "name": "Listing Photo Analyst",
                       "objective": "Help Acme Linens understand how competing bedding listings present their products by inspecting listing photos by image ID.",
                       "instructions": "You analyse competitor listing photos for Acme Linens. Use inspect_image on the image IDs the owner gives you and report what is visible, "
                                       "readable text, and what you cannot verify. Never describe an image that failed to load.",
                       "skills": [{"name": "listing-photo-review", "content": "# Listing photo review\n1. Inspect each image ID with inspect_image.\n"
                                                                        "2. Report visible features, readable text, uncertainties per image_id.\n3. Name what is unverified."}],
                       "requested_tools": ["inspect_image"]})
check("specialist created with inspect_image granted (plus mandatory tools)", r.get("ok") and "inspect_image" in r["granted_tools"], r)
aid = r["agent_id"]
import yaml
pc = yaml.safe_load((core.HERMES_ROOT / "profiles" / aid / "config.yaml").read_text(encoding="utf-8"))
print("profile vision declaration:", pc.get("providers"))


def turn(msg, conv=None):
    t0 = time.time()
    res = core.run_turn(aid, msg, timeout=400, conv_override=conv)
    ev = ((res.get("timing") or {}).get("events")) or []
    n_api = sum(1 for e in ev if e.get("stage") == "api_start")
    ms = [e.get("ms") for e in ev if e.get("stage") == "api_end"]
    calls = [(t.get("name"), t.get("input")) for t in res.get("tools", []) if "input" in t]
    outs = [t for t in res.get("tools", []) if "output" in t]
    return {"wall_s": round(time.time() - t0, 1), "api_requests": n_api, "api_ms": ms, "tool_calls": calls,
            "tool_outputs": [str(o.get("output"))[:260] for o in outs], "text": res.get("text") or "", "error": res.get("error")}


def section(text, a, b):
    """Text between the first mention of id `a` and of id `b` (order-independent), for per-image keyword checks."""
    low = text.lower()
    ia, ib = low.find(a), low.find(b)
    if ia < 0 or ib < 0:
        return "", ""
    return (low[ia:ib], low[ib:]) if ia < ib else (low[ia:], low[ib:ia])


rec = {"provider": cfg["provider"], "model": cfg["model"]}
t1 = turn("Please inspect the images with IDs ref-a and ref-b using your image tool. For each image_id give: visible observations, any readable text, "
          "and anything you are unsure of. Keep it short.")
rec["turn1"] = t1
print(f"\n--- turn 1: {t1['api_requests']} model requests, {t1['wall_s']}s, tools {[c[0] + ':' + json.dumps(c[1]) for c in t1['tool_calls']]}\n{t1['text']}\n")
sa, sb = section(t1["text"], "ref-a", "ref-b")
def inspected(t):   # image IDs the specialist passed to inspect_image (it may also load its skills; that is expected)
    return sorted(json.loads(c[1])["image_id"] for c in t["tool_calls"] if c[0] == "inspect_image")


check("turn 1: the specialist called inspect_image for both IDs through its tool interface", inspected(t1) == ["ref-a", "ref-b"], t1["tool_calls"])
check("turn 1: observations follow the pixels (ref-a: green triangle / yellow / 42; ref-b: purple circle / white / KX9)",
      "triangle" in sa and "42" in sa and "circle" in sb and "kx9" in sb.replace(" ", ""), (sa[:200], sb[:200]))

# swap the pixel contents under the same neutral references; FRESH Hermes session (no memory of turn 1)
shutil.copy(Y, IMG / "ref-a.png")
shutil.copy(X, IMG / "ref-b.png")
ids = ["ref-a", "ref-b"] + ([MKT_ID] if MKT_ID else []) + ["ref-corrupt", "ref-missing"]
t2 = turn("Inspect these image IDs with your image tool: " + ", ".join(ids) + ". For each image_id give visible observations, readable text and "
          "uncertainties; for any that cannot be inspected, say so and why. Then name which successfully inspected image would make the strongest hero "
          "photo for a bedding listing, citing its image_id.", conv="fresh-swap")
rec["turn2"] = t2
print(f"\n--- turn 2 (fresh session, pixels swapped): {t2['api_requests']} model requests, {t2['wall_s']}s\n{t2['text']}\n")
sa, sb = section(t2["text"], "ref-a", "ref-b")
check("turn 2 (fresh session): after the swap the SAME references now follow the NEW pixels (ref-a circle/KX9, ref-b triangle/42)",
      "circle" in sa and "kx9" in sa.replace(" ", "") and "triangle" in sb and "42" in sb, (sa[:200], sb[:240]))
outs = " ".join(t2["tool_outputs"])
check("turn 2: corrupt and missing images failed explicitly in the tool (codes), before any pixels were sent",
      "image_unreadable" in outs and "image_not_found" in outs, t2["tool_outputs"])
low = t2["text"].lower()
check("turn 2: the specialist says the corrupt and missing ones could not be inspected (keyword check; read the quote above)",
      "ref-corrupt" in low and "ref-missing" in low and any(w in low for w in ("could not", "couldn't", "cannot", "can't", "unable", "failed", "not found")), t2["text"][:300])
if MKT_ID:
    ms_low = low[low.find(MKT_ID):] if MKT_ID in low else ""
    check(f"turn 2: the private Marketplace photo is reported under its source ID {MKT_ID} with observations drawn from its pixels",
          MKT_ID in low and len(ms_low) > 60 and any(w in ms_low for w in ("bedding", "bed", "packag", "bag", "comforter", "duvet", "sheet", "fabric")), ms_low[:300])
check("turn 2: it names a hero image by image_id (observations used for a downstream judgement)",
      "hero" in low and any(i in low[low.find("hero"):] for i in ids if i not in ("ref-corrupt", "ref-missing")), low[-300:])
check("turn 2: it inspected every requested ID through the tool", inspected(t2) == sorted(ids), inspected(t2))
total = t1["api_requests"] + t2["api_requests"]
rec["total_model_requests"], rec["total_wall_s"] = total, round(t1["wall_s"] + t2["wall_s"], 1)
check(f"model request budget: {total} <= 6", 0 < total <= 6, total)
check("no turn-level error", not t1["error"] and not t2["error"], (t1["error"], t2["error"]))
OUT.write_text(json.dumps(rec, indent=1), encoding="utf-8")
print(f"\n{sum(results)}/{len(results)} checks passed; model requests {total}; wall {rec['total_wall_s']} s; result in {OUT.name}")
sys.exit(0 if results and all(results) else 1)
