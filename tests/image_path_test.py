"""Ticket 03 focused tests for the image-inspection boundary (core.prepare_image + the specialist-only `inspect_image` tool).
Part A/B: pure backend checks (no model, no Hermes process). Part C: SCRIPTED-model plumbing through the real server and Hermes workers:
proves which bytes reach the model request and that grants/isolation hold. Part C is NOT a vision test (a scripted model sees nothing);
real vision evidence is tests/image_live_check.py. Wipes the copy's runtime/ in part C - run ONLY from a COPY:
  IMAGE_PATH_I_AM_A_COPY=1 venv-python tests/image_path_test.py"""
import base64, hashlib, io, json, os, shutil, subprocess, sys, tempfile, time, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if os.environ.get("IMAGE_PATH_I_AM_A_COPY") != "1":
    sys.exit("Refusing to run: set IMAGE_PATH_I_AM_A_COPY=1 and run from a COPY of the project.")
sys.path.insert(0, str(ROOT))
from PIL import Image, ImageDraw
from app import core

results, procs = [], []
MOCK, APP = 8773, 8822


def check(name, ok, detail=""):
    ok = bool(ok); results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{str(detail)[:500]}]"), flush=True)


def save(path, color, size=(120, 90), fmt=None, mode="RGB"):
    im = Image.new(mode, size, color)
    ImageDraw.Draw(im).rectangle([10, 10, 40, 40], fill=(0, 0, 0) if mode == "RGB" else None)
    im.save(path, fmt)


def decode(data_url):
    return Image.open(io.BytesIO(base64.b64decode(data_url.split(",", 1)[1])))


# ================= A. prepare_image =================
D = Path(tempfile.mkdtemp(prefix="img_"))
os.environ["ECOM_IMAGE_DIRS"] = str(D)
save(D / "ref-a.png", (200, 30, 30))
r = core.prepare_image("ref-a")
im = decode(r["data_url"]) if r.get("ok") else None
check("A1 valid PNG: ok, id preserved, original size reported, JPEG data URL whose pixels are the file's pixels",
      r.get("ok") and r["image_id"] == "ref-a" and (r["width"], r["height"]) == (120, 90) and r["format"] == "PNG" and im.format == "JPEG"
      and abs(im.getpixel((100, 70))[0] - 200) < 12 and im.getpixel((100, 70))[1] < 60 and len(r["sha256"]) == 64, r if not r.get("ok") else (r["width"], im.format))
save(D / "ref-a.png", (30, 30, 200))     # SAME id, different pixels
r2 = core.prepare_image("ref-a")
im2 = decode(r2["data_url"])
check("A2 swapping the pixels under the same ID changes what is sent (blue now, not red) and the hash",
      r2["sha256"] != r["sha256"] and im2.getpixel((100, 70))[2] > 150 and im2.getpixel((100, 70))[0] < 60 and r2["data_url"] != r["data_url"])
check("A3 unknown id -> image_not_found, no pixels", core.prepare_image("ref-missing")["code"] == "image_not_found" and "data_url" not in core.prepare_image("ref-missing"))
(D / "ref-trunc.png").write_bytes((D / "ref-a.png").read_bytes()[:70])
(D / "ref-text.jpg").write_text("this is not an image", encoding="utf-8")
(D / "ref-empty.png").write_bytes(b"")
codes = {i: core.prepare_image(i) for i in ("ref-trunc", "ref-text", "ref-empty")}
check("A4 truncated / non-image / empty files -> image_unreadable, explicit, no pixels, no description", all(c["code"] == "image_unreadable" and "data_url" not in c and c["image_id"] == i for i, c in codes.items()), codes)
bad = {i: core.prepare_image(i) for i in ("../ref-a", "a/b", "C:\\x", "https://example.com/x.png", "", "ref a", None, 5, "x" * 80)}
check("A5 paths, URLs, traversal, empty and non-string ids are rejected as bad_image_id", all(c["code"] == "bad_image_id" for c in bad.values()), {k: v["code"] for k, v in bad.items()})
Image.new("RGB", (4000, 2500), (10, 120, 10)).save(D / "ref-big.jpg")
big = core.prepare_image("ref-big")
check("A6 oversized dimensions are downscaled for sending (long edge <= 1568) while the original size is reported",
      big["ok"] and (big["width"], big["height"]) == (4000, 2500) and max(big["sent_width"], big["sent_height"]) <= 1568 and decode(big["data_url"]).size == (big["sent_width"], big["sent_height"]))
Image.new("RGBA", (50, 50), (0, 0, 0, 0)).save(D / "ref-alpha.png")
a = core.prepare_image("ref-alpha")
check("A7 transparent PNG is composed on white, not sent as black", a["ok"] and decode(a["data_url"]).getpixel((10, 10))[0] > 240)
Image.new("RGB", (20, 20), (1, 2, 3)).save(D / "ref-bmp.png", "BMP")
check("A8 a format outside JPEG/PNG/WEBP/GIF is image_unsupported", core.prepare_image("ref-bmp")["code"] == "image_unsupported")
old = core.MAX_IMAGE_BYTES
core.MAX_IMAGE_BYTES = 100
try:
    check("A9 a file over the byte cap is image_too_large before decoding", core.prepare_image("ref-big")["code"] == "image_too_large")
finally:
    core.MAX_IMAGE_BYTES = old
Image.new("RGB", (30, 40), (9, 9, 9)).save(D / "1638806271151287.jpg")
check("A10 a Marketplace-style numeric listing ID resolves and is echoed back as the source ID", core.prepare_image("1638806271151287")["image_id"] == "1638806271151287")
os.environ.pop("ECOM_IMAGE_DIRS")
check("A11 default image roots are the private Marketplace diagnostic folder and the labelled demo-image fixture folder (no env needed)",
      core.image_roots() == [core.RUNTIME / "marketplace_check" / "images", core.ROOT / "tests" / "fixtures" / "demo_images"])

# A12: profile creation can never leave the project's private Hermes home (a stray profile was once created in the user's own Hermes home)
import types
fake = types.ModuleType("hermes_cli.profiles")


def _boom(*a, **k):
    raise AssertionError("create_profile must not be reached")
fake.create_profile = _boom
sys.modules.setdefault("hermes_cli", types.ModuleType("hermes_cli"))
saved_mod, saved_home = sys.modules.get("hermes_cli.profiles"), os.environ.get("HERMES_HOME")
sys.modules["hermes_cli.profiles"] = fake
try:
    res = {}
    for label, home in (("unset", None), ("user's own Hermes home", str(Path(os.environ.get("LOCALAPPDATA", "C:/x")) / "hermes")),
                        ("sibling of the project home", str(core.HERMES_ROOT.parent / "elsewhere"))):
        if home is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = home
        try:
            core._write_profile("guard-test", {"name": "x", "objective": "o" * 50, "instructions": "i" * 50, "skills": [], "tools": []}, "conv-guard-test")
            res[label] = "created"
        except RuntimeError:
            res[label] = "refused"
        except AssertionError:
            res[label] = "REACHED create_profile"
finally:
    if saved_mod is not None:
        sys.modules["hermes_cli.profiles"] = saved_mod
    else:
        sys.modules.pop("hermes_cli.profiles", None)
    if saved_home is not None:
        os.environ["HERMES_HOME"] = saved_home
    else:
        os.environ.pop("HERMES_HOME", None)
check("A12 _write_profile refuses to create a profile when HERMES_HOME is unset, the user's own Hermes home, or outside the project home",
      res == {"unset": "refused", "user's own Hermes home": "refused", "sibling of the project home": "refused"}, res)

# ================= B. plugin tool contract =================
from app import hermes_plugin as hp
os.environ["ECOM_IMAGE_DIRS"] = str(D)
save(D / "ref-b.png", (20, 160, 40))
env = hp._inspect_image({"image_id": "ref-b"})
check("B1 success returns Hermes' multimodal envelope: text note + image_url data URL, meta carries the image_id",
      isinstance(env, dict) and env["_multimodal"] is True and [p["type"] for p in env["content"]] == ["text", "image_url"] and env["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
      and env["meta"]["image_id"] == "ref-b" and "ref-b" in env["content"][0]["text"] and "unverified" in env["content"][0]["text"] and "data:" not in env["text_summary"], env)
out = hp._inspect_image({"image_id": "ref-nope"})
d = json.loads(out)
check("B2 failure is a JSON string with code and image_id, and contains NO image part", isinstance(out, str) and d["ok"] is False and d["code"] == "image_not_found" and d["image_id"] == "ref-nope" and "data:" not in out)
check("B3 malformed args never raise", all(isinstance(hp._inspect_image(x), str) for x in (None, {}, {"image_id": 7}, "x", {"path": "C:/x.png"})))
check("B4 schema accepts only image_id (no path/url parameter)", list(hp.IMAGE_SCHEMA["parameters"]["properties"]) == ["image_id"] and hp.IMAGE_SCHEMA["parameters"]["additionalProperties"] is False)
check("B5 the tool is an OPTIONAL eligible tool of market_analysis (not mandatory), toolset ecom_images",
      "inspect_image" in core.ROLES["market_analysis"]["eligible_tools"] and "inspect_image" not in core.ROLES["market_analysis"]["mandatory_tools"]
      and core.ROLES["market_analysis"]["eligible_tools"]["inspect_image"]["toolset"] == "ecom_images")
s = core.build_soul({"name": "X", "objective": "o" * 50, "instructions": "i" * 50, "tools": ["inspect_image", "memory"]}, "Co")
s2 = core.build_soul({"name": "X", "objective": "o" * 50, "instructions": "i" * 50, "tools": ["memory"]}, "Co")
check("B6 SOUL tells the specialist how to report image observations only when it holds the tool", "inspect_image" in s and "per image_id" in s and "unverified" in s and "inspect_image" not in s2)


# ================= C. scripted-model plumbing through the real server + Hermes workers =================
def call(path, body=None, port=APP):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=600); return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def tool(agent, name, args):
    st, r = call(f"/api/chat/{agent}", {"message": "CALL_TOOL:" + json.dumps({"name": name, "args": args})})
    outs = [t for t in r.get("tools", []) if t.get("name") == name and t.get("output")]
    return (outs[0]["output"] if outs else None), r


def start_server(env):
    p = subprocess.Popen([sys.executable, "-m", "app.server", str(APP)], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(p)
    for _ in range(80):
        try: call("/api/status"); return p
        except Exception: time.sleep(0.5)
    raise RuntimeError("server did not start")


try:
    ENV = {**os.environ, "PYTHONUTF8": "1", "ECOM_CLASSIFIER": "off"}
    for k in ("LLM_PROVIDER", "LLM_MODEL", "NEBIUS_API_KEY", "NEBIUS_BASE_URL", "NEBIUS_MODEL"):
        ENV.pop(k, None)
    shutil.rmtree(ROOT / "runtime", ignore_errors=True)
    IMG = ROOT / "runtime" / "img_controls"
    IMG.mkdir(parents=True)
    ENV["ECOM_IMAGE_DIRS"] = str(IMG)
    save(IMG / "ref-a.png", (200, 30, 30))
    save(IMG / "ref-b.png", (30, 30, 200))
    (IMG / "ref-corrupt.png").write_bytes((IMG / "ref-a.png").read_bytes()[:60])
    (ROOT / "secrets").mkdir(exist_ok=True)
    (ROOT / "secrets" / "local.env").write_text(f"LLM_PROVIDER=nebius-token-factory\nLLM_MODEL=mock-model\nNEBIUS_API_KEY=mock-key\nNEBIUS_BASE_URL=http://127.0.0.1:{MOCK}/v1\n", encoding="utf-8")
    subprocess.run([sys.executable, "scripts/setup.py"], cwd=ROOT, env=ENV, check=True, capture_output=True)
    procs.append(subprocess.Popen([sys.executable, "tests/mock_llm.py", str(MOCK)], cwd=ROOT, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(1)
    srv = start_server(ENV)
    def stats(): return call("/stats", port=MOCK)[1]
    st, r = call("/api/company", {"fields": {"name": "Acme Linens", "products": "Cotton bedding and curtains", "customers": "Home buyers in the US", "goal": "Understand competitor listing photos"}})
    BASE = {"role": "market_analysis", "objective": "Help Acme Linens understand how competing bedding listings present their products so the owner can improve listing photos.",
            "instructions": "You analyse competitor listing photos for Acme Linens. Use inspect_image on image IDs the owner gives you; report only what is visible and label the rest unverified.",
            "skills": [{"name": "listing-photo-review", "content": "# Listing photo review\n1. Inspect each image ID.\n2. Report visible features and readable text.\n3. List what you cannot verify."}]}
    out, r = tool("main", "create_agent", {**BASE, "name": "Photo Analyst", "requested_tools": ["inspect_image"]})
    o = json.loads(out)
    aid = o["agent_id"]
    check("C1 main can request inspect_image: granted with the mandatory tools, in response and registry",
          o["ok"] and sorted(o["granted_tools"]) == ["inspect_image", "memory", "read_company_context", "skills"]
          and sorted(call(f"/api/agents/{aid}")[1]["granted_tools"]) == sorted(o["granted_tools"]), o)
    check("C2 its SOUL carries the image-reporting rule", "inspect_image" in (ROOT / "runtime" / "hermes_home" / "profiles" / aid / "SOUL.md").read_text(encoding="utf-8"))
    out2, r = tool("main", "create_agent", {**BASE, "name": "Plain Analyst", "requested_tools": []})
    pid = json.loads(out2)["agent_id"]
    st, r = call(f"/api/chat/{pid}", {"message": "hi"})
    check("C3 a specialist WITHOUT the grant cannot see or call inspect_image", "inspect_image" not in r["text"] and "not available" in tool(pid, "inspect_image", {"image_id": "ref-a"})[1]["text"])
    st, r = call("/api/chat/main", {"message": "hi"})
    check("C4 main never has inspect_image", "inspect_image" not in r["text"] and "not available" in tool("main", "inspect_image", {"image_id": "ref-a"})[1]["text"])
    st, r = call(f"/api/chat/{aid}", {"message": "hi"})
    check("C5 the granted specialist lists inspect_image among its tools and still has no create_agent/update_company",
          "inspect_image" in r["text"] and "create_agent" not in r["text"] and "update_company" not in r["text"], r["text"])
    out3, r3 = tool("main", "create_agent", {**BASE, "name": "Rogue Analyst", "requested_tools": ["inspect_image", "vision_analyze"]})
    check("C6 vision_analyze (Hermes' built-in, arbitrary path/URL) is NOT an eligible tool", json.loads(out3)["code"] == "tool_not_permitted")
    out, r = tool(aid, "inspect_image", {"image_id": "ref-a"})
    check("C6b with no declared vision capability for the model the pixels are NOT sent, and the tool result says so (honest degrade, no false 'attached')",
          out is not None and "images_in_request=0" in r["text"] and "pixels are not visible" in r["text"] and "attached" not in r["text"].split(":", 1)[-1][:200] and stats()["image_requests"] == 0, r["text"][:300])
    # restart with the DIAGNOSTIC per-model vision declaration (what profile_config() does for verified models)
    srv.terminate(); srv.wait()
    srv = start_server({**ENV, "ECOM_VISION_MODELS": "nebius-token-factory:mock-model"})
    cfg_txt = (ROOT / "runtime" / "hermes_home" / "profiles" / aid / "config.yaml").read_text(encoding="utf-8")
    import yaml
    cfgd = yaml.safe_load(cfg_txt)
    check("C6c profile config declares supports_vision for exactly that provider/model, not globally",
          cfgd["providers"]["nebius-token-factory"]["models"]["mock-model"]["supports_vision"] is True and "supports_vision" not in cfgd["model"], cfg_txt)

    os.environ["ECOM_IMAGE_DIRS"] = str(IMG)
    want_a = hashlib.sha256(base64.b64decode(core.prepare_image("ref-a")["data_url"].split(",", 1)[1])).hexdigest()
    want_b = hashlib.sha256(base64.b64decode(core.prepare_image("ref-b")["data_url"].split(",", 1)[1])).hexdigest()
    out, r = tool(aid, "inspect_image", {"image_id": "ref-a"})
    ims = stats()["last_images"]
    check("C7 the model request that follows the tool call carries exactly ref-a's pixels (bytes identical to prepare_image's JPEG)",
          out is not None and "images_in_request=1" in r["text"] and ims and ims[0]["sha256"] == want_a and ims[0]["mime"] == "image/jpeg", (r["text"][:300], ims))
    # swap contents under the same reference, fresh conversation id context: the request must follow the pixels
    shutil.copy(IMG / "ref-b.png", IMG / "ref-a.png")
    want_a2 = hashlib.sha256(base64.b64decode(core.prepare_image("ref-a")["data_url"].split(",", 1)[1])).hexdigest()
    out, r = tool(aid, "inspect_image", {"image_id": "ref-a"})
    ims = stats()["last_images"]
    check("C8 after the swap the SAME reference sends the NEW pixels (hash changed, equals ref-b's)", want_a2 != want_a and want_a2 == want_b and ims and ims[0]["sha256"] == want_b, (want_a, want_a2, ims))
    n_img = stats()["image_requests"]
    out, r = tool(aid, "inspect_image", {"image_id": "ref-corrupt"})
    d = json.loads(out)
    check("C9 a corrupt file fails explicitly in the tool: structured error, NO image part in the next model request",
          d["ok"] is False and d["code"] == "image_unreadable" and d["image_id"] == "ref-corrupt" and "images_in_request=0" in r["text"] and stats()["image_requests"] == n_img, (d, r["text"][:200]))
    out, r = tool(aid, "inspect_image", {"image_id": "ref-missing"})
    check("C10 a missing image fails explicitly (image_not_found), nothing is sent", json.loads(out)["code"] == "image_not_found" and "images_in_request=0" in r["text"])
    out, r = tool(aid, "inspect_image", {"image_id": "C:/Windows/win.ini"})
    check("C11 a path is rejected as bad_image_id", json.loads(out)["code"] == "bad_image_id")
finally:
    for p in procs:
        p.terminate()
    shutil.rmtree(D, ignore_errors=True)
print(f"\n{sum(results)}/{len(results)} checks passed (parts A/B pure backend; part C scripted plumbing, NOT a vision test)")
sys.exit(0 if results and all(results) else 1)
