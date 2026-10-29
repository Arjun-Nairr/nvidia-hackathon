"""Shared logic: company data, role rules, create_agent, agent registry, Hermes runner.

Imported by the web server AND by the Hermes plugin (inside the Hermes process), so the
model only *requests* things and this code decides what is granted.
"""
import base64, contextlib, hashlib, io, json, os, re, sqlite3, time
from app import logbook, timing, roles, turn_state
from pathlib import Path

ROOT = Path(os.environ.get("ECOM_APP_ROOT") or Path(__file__).resolve().parent.parent)
RUNTIME = ROOT / "runtime"
HERMES_ROOT = RUNTIME / "hermes_home"          # private Hermes home for this project
DB_PATH = RUNTIME / "app.db"
COMPANY_ID = "default"                         # one company only; bound by the application, never by the model
COMPANY_PATH = RUNTIME / "company.json"        # the single saved company context (private runtime state; absent until onboarding)
COMPANY_LOCK_PATH = RUNTIME / "company.lock"   # OS-level lock file guarding every read-merge-write of company.json (server + Hermes workers)
COMPANY_LOCK_TIMEOUT = 10.0                    # seconds a save waits for another process's save before reporting an explicit error
HERMES_EXE = os.environ.get("HERMES_EXE") or str(Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / "bin" / "hermes.exe")
HERMES_PY = os.environ.get("HERMES_PY") or str(Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / "hermes-agent" / "venv" / "Scripts" / "python.exe")

# One company. field -> (section it is exposed under, required, max length)
COMPANY_FIELDS = {
    "name": ("profile", True, 120),
    "products": ("products", True, 1500),
    "customers": ("customers", True, 1500),
    "goal": ("goal", True, 1500),
    "website": ("profile", False, 200),
    "brand": ("brand", False, 1500),
    "competitors": ("competitors", False, 1500),
}
COMPANY_LABELS = {"name": "company name", "products": "products or product categories", "customers": "target customers",
                  "goal": "business goal", "website": "website", "brand": "brand guidance", "competitors": "known competitors"}
REQUIRED_FIELDS = [f for f, v in COMPANY_FIELDS.items() if v[1]]
COMPANY_SECTIONS = ["profile", "products", "customers", "goal", "brand", "competitors"]
ESSENTIAL_SECTIONS = ["profile", "products", "customers", "goal"]    # always granted to a specialist; main chooses the optional ones
PLACEHOLDERS = {"unknown", "n/a", "na", "none", "tbd", "tba", "?", "??", "-", "--", "idk", "not sure", "don't know", "dont know", "unsure",
                "no idea", "later", "todo", "null", "nothing"}

# Predefined per-role creation guidance + eligible tools. The model generates company-specific content;
# application code enforces which tools are granted.
ROLES = {
    "market_analysis": {
        "creation_guidance": (
            "The backend already provides this role's foundation: fixed responsibilities and a tested baseline skill "
            f"({roles.BASELINE_SKILL_NAME}: evidence vs assumptions, competitor comparisons, handling missing information, an action-oriented "
            "output format). Do NOT rewrite or duplicate the baseline. You add what is specific to THIS company: a short name, an objective "
            "that states what the analyst should achieve for this merchant, company-specific instructions (use the merchant's own words for "
            "products, customers and goal; name only competitors the merchant actually gave you), and OPTIONALLY up to 3 complementary custom skills for "
            "this company's needs (for example a review routine for its named competitors or its price tiers); omit skills when the baseline plus your instructions are enough. Instructions must match the tools you "
            "request: WITHOUT the four marketplace_* tools, say that live market research is NOT connected (the analyst works only from "
            "company context and what the user tells it); WITH them, say it may research Facebook Marketplace read-only within a backend "
            "allowance it cannot change, has no other live research, must label anything unsourced as an assumption and never "
            "invents competitor prices, news or customer facts. Do not invent facts about the company; "
            "if something is not in the company context, leave it out or tell the analyst it is unknown."),
        "eligible_tools": {
            "read_company_context": {"toolset": "ecom_company", "approval": "none",
                                      "what": "Read the company context sections granted to this agent."},
            "memory": {"toolset": "memory", "approval": "none",
                       "what": "The agent's own persistent memory (separate per specialist)."},
            "skills": {"toolset": "skills", "approval": "none",
                       "what": "The agent's own skill facilities (view and refine its own skills)."},
            "inspect_image": {"toolset": "ecom_images", "approval": "none",
                              "what": "Look at a registered image by its image ID: the actual pixels are attached so the agent can report visible observations."},
            "read_catalogue": {"toolset": "ecom_catalogue", "approval": "none",
                               "what": "Read the merchant's catalogue: supplied product facts (specifications, declared price/currency, image ID)."},
            "read_recorded_evidence": {"toolset": "ecom_evidence", "approval": "none",
                                       "what": "Search the RECORDED Marketplace listings (replayed sample, no live search) and read one listing's details."},
            "save_listing_draft": {"toolset": "ecom_drafts", "approval": "none",
                                   "what": "Save one evidence-backed listing draft; the backend validates the product facts and every reference. Nothing is published."},
            "marketplace_locate": {"toolset": "ecom_mp_locate", "approval": "none",
                                   "what": "Facebook Marketplace location lookup (read-only, counted against a backend allowance)."},
            "marketplace_search": {"toolset": "ecom_mp_search", "approval": "none",
                                   "what": "Facebook Marketplace listing search for a located place (read-only, counted)."},
            "marketplace_item": {"toolset": "ecom_mp_item", "approval": "none",
                                 "what": "Details of one listing found by a search of the same request (read-only, counted)."},
            "marketplace_photo": {"toolset": "ecom_mp_photo", "approval": "none",
                                  "what": "Download one listing photo found in this request so inspect_image can show it (read-only, counted)."},
        },
        # the backend ALWAYS grants these (validated requests are unioned with them), so a specialist can read its company context,
        # load its baseline/custom skills (skill_view) and keep its own memory whatever main requested; eligible minus mandatory = optional
        "mandatory_tools": ["read_company_context", "memory", "skills"],
        # a tool that works only on results of another tool is useless without it: such selections are refused (never silently extended, no tool is invented)
        "requires": {"marketplace_search": ["marketplace_locate"], "marketplace_item": ["marketplace_search"], "marketplace_photo": ["marketplace_item"],
                     "save_listing_draft": ["read_catalogue"]},
        "not_connected": ["web_search", "web_scraping", "email", "social_posting", "image_generation", "scheduling"],
        "approval_requirements": [
            {"action": "read company context / use own memory and skills", "requirement": "none"},
            {"action": "publish, post, send messages or change anything externally",
             "requirement": "user confirmation required; no such tool is granted"},
            {"action": "Facebook Marketplace read-only research (locate/search/item/photo)",
             "requirement": "only with the granted marketplace_* tools, inside a manual request, within a finite backend allowance; no confirmation per read"},
            {"action": "other live web/competitor research, seller contact", "requirement": "not connected"},
        ],
    },
}
_MA = ROLES["market_analysis"]["eligible_tools"]
ROLES["social_media"] = {
    "creation_guidance": (
        "The backend already provides this role's foundation: fixed responsibilities and a tested baseline skill "
        f"({roles.SOCIAL_BASELINE_SKILL_NAME}: supplied facts vs creative choices, responsible use of references, use of the merchant's product photos, a brief "
        "checklist, an output format). Do NOT rewrite or duplicate it. You add what is specific to THIS company: a short name, an objective that states what "
        "promotional creative the specialist should produce for this merchant (use the merchant's own words for products, customers and goal), "
        "company-specific instructions (brand tone only as the merchant gave it; never invent brand rules, offers or claims), and OPTIONALLY up to 3 complementary custom "
        "skills for this company's channel or product type (omit skills when the baseline plus your instructions are enough). Include \"brand\" in company_context_refs when the company has brand guidance, so the specialist can "
        "read it. Instructions must match the tools you request: WITHOUT the fb_* ad tools say that Facebook ad research is NOT connected for this specialist "
        "(it works from the company context, the catalogue and what the user supplies and produces text creative briefs and copy); WITH them (request all of "
        "fb_ads_find_advertiser, fb_ads_search, fb_ad_detail, fb_ad_image, save_ad_research, read_ad_research, plus inspect_image and read_catalogue) say that it may "
        "research US Facebook IMAGE ads read-only inside a manual request, within a backend allowance it cannot change, that it chooses the queries, advertisers "
        "and images itself, that reported reach is used only when the backend says it is available, and that it has no Marketplace data. Image or flyer generation "
        "is connected ONLY with the flyer tools (request all of generate_flyer, read_flyer, inspect_flyer, review_flyer, finalize_flyer, plus inspect_image and read_catalogue): "
        "it may then generate ONE flyer image per manual request from the merchant's own catalogue photographs with Gemini, look at that image's actual pixels, review it against "
        "the product photographs, the required text/price and the layout, make at most ONE specific correction (a second and last paid attempt) and select one final candidate; "
        "its reviews are fallible agent reviews, never human approval. Without inspect_flyer/review_flyer/finalize_flyer a generated flyer stays UNCHECKED. "
        "Without generate_flyer, say image or flyer generation is NOT connected. Nothing can be posted in any case. Do not claim capabilities it does not have; "
        "do not invent facts about the company."),
    "eligible_tools": {**{k: _MA[k] for k in ("read_company_context", "memory", "skills", "inspect_image", "read_catalogue")},
                       "fb_ads_find_advertiser": {"toolset": "ecom_fb_advertiser", "approval": "none",
                                                  "what": "Find Facebook Ad Library advertisers (pages) by name (read-only, US, counted against a backend allowance)."},
                       "fb_ads_search": {"toolset": "ecom_fb_search", "approval": "none",
                                         "what": "Search US Facebook IMAGE ads by keyword or for an advertiser found in this request (read-only, counted)."},
                       "fb_ad_detail": {"toolset": "ecom_fb_detail", "approval": "none",
                                        "what": "Details of one ad that a search of this request returned: text, cards, image references, campaign, reach fields (read-only, counted)."},
                       "fb_ad_image": {"toolset": "ecom_fb_image", "approval": "none",
                                       "what": "Download one image of an ad found in this request so inspect_image can show its pixels (read-only, counted separately)."},
                       "save_ad_research": {"toolset": "ecom_fb_save", "approval": "none",
                                            "what": "Save ONE research package: your source-linked ad references, your observations of images you inspected and the reach-gate state. Nothing is published."},
                       "read_ad_research": {"toolset": "ecom_fb_read", "approval": "none",
                                            "what": "Read this specialist's saved ad research packages (stored data only; no new request is made)."},
                       "generate_flyer": {"toolset": "ecom_flyer_generate", "approval": "none",
                                          "what": "Generate ONE flyer image with Gemini from the product's registered merchant photographs and your prompt (one paid attempt), or - from a "
                                                  "defective, reviewed first candidate - ONE specific correction (the second and last paid attempt of the request). Needs a configured "
                                                  "Gemini key and real supplied photographs."},
                       "read_flyer": {"toolset": "ecom_flyer_read", "approval": "none",
                                      "what": "Read this specialist's saved flyers: status, candidates, reviews and final selection (stored data only; no generation or provider request)."},
                       "inspect_flyer": {"toolset": "ecom_flyer_inspect", "approval": "none",
                                         "what": "Look at the actual pixels of a generated candidate of this request, with the merchant's photographs of the product, to review it (no provider request)."},
                       "review_flyer": {"toolset": "ecom_flyer_review", "approval": "none",
                                        "what": "Save your review of an inspected candidate: product appearance, required text/price, layout/readability, defects with specific corrections "
                                                "and uncertainty. A fallible agent review, bound to the candidate's hash."},
                       "finalize_flyer": {"toolset": "ecom_flyer_final", "approval": "none",
                                          "what": "Select ONE candidate of this request as the final flyer with a short rationale. Nothing is published or approved."}},
    "mandatory_tools": ["read_company_context", "memory", "skills"],
    "requires": {"fb_ad_detail": ["fb_ads_search"], "fb_ad_image": ["fb_ad_detail"], "save_ad_research": ["fb_ads_search"],
                 "generate_flyer": ["read_catalogue", "inspect_image"], "inspect_flyer": ["generate_flyer"], "review_flyer": ["inspect_flyer"], "finalize_flyer": ["generate_flyer"]},
    "not_connected": ["social_posting", "instagram", "email", "web_search", "web_scraping", "scheduling", "marketplace_research"],
    "approval_requirements": [
        {"action": "read company context / read the catalogue / inspect registered images / use own memory and skills", "requirement": "none"},
        {"action": "publish, post, send messages or change anything externally", "requirement": "user confirmation required; no such tool is granted"},
        {"action": "US Facebook image-ad research (fb_* tools)", "requirement": "only with the granted fb_* tools, inside a manual request, within a finite backend "
                                                                                 "allowance; no confirmation per read; no Marketplace, Instagram or video data"},
        {"action": "flyer generation (generate_flyer)", "requirement": "only with the granted generate_flyer tool, inside a manual request, at most TWO paid Gemini attempts per "
                                                                         "request (initial + one reviewed correction; backend-enforced), needs a configured key; the result is "
                                                                         "agent-reviewed (fallible) or UNCHECKED; nothing is posted"},
    ],
}
PROVIDERS = ("openai-codex", "nebius-token-factory")   # the only two supported
# (provider, model) pairs with LIVE proof that image pixels in a tool result reach the model through our worker (HANDOUT, 'Image inspection').
# Hermes does not know these models as vision-capable (catalog miss), and without a declared capability it replaces tool-result images with a
# text summary, so profile_config() declares it per exact model. ECOM_VISION_MODELS="provider:model,..." adds pairs for isolated diagnostics.
VISION_VERIFIED = {("openai-codex", "gpt-5.6-terra")}
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
IMAGE_FORMATS = ("JPEG", "PNG", "WEBP", "GIF")
MAX_IMAGE_BYTES, MAX_IMAGE_EDGE = 8_000_000, 1568
NEBIUS_DEFAULT_MODEL = "nvidia/Nemotron-3.5-Super-VL"  # the candidate verified 2026-10-27 (research/nebius-compat-check-20261027.md); LLM_MODEL, when set, still overrides it
MARKETPLACE_TOOLS = ("marketplace_locate", "marketplace_search", "marketplace_item", "marketplace_photo")   # live research (app/research.py)
AD_TOOLS = ("fb_ads_find_advertiser", "fb_ads_search", "fb_ad_detail", "fb_ad_image", "save_ad_research", "read_ad_research")   # Facebook ad research (app/ads.py)
AD_RESEARCH_TOOLS = AD_TOOLS[:4]   # the tools that spend scraper attempts / image downloads (a specialist holding any of them gets the research-turn limits)
FLYER_TOOLS = ("generate_flyer", "read_flyer", "inspect_flyer", "review_flyer", "finalize_flyer")   # flyer generation and review (app/flyer.py): generate_flyer spends a paid Gemini attempt
MAIN_TOOLSETS = ["ecom_company", "ecom_agents"]
def _iterations(name, default):
    """Operator cap on agent iterations per turn (each is one model request; an exhausted turn adds one summary request). Anything not a whole number 1-40
    keeps the default. It is read from the SERVER's environment only: the model and the chat API cannot change it."""
    try:
        v = int(os.environ.get(name, ""))
    except ValueError:
        return default
    return v if 1 <= v <= 40 else default


# a research turn makes provider calls and downloads; 14 iterations (+1 summary request) stays under 16 model requests on its own. A bounded demonstration that
# also spends model requests on creating the specialist lowers both caps (ECOM_CHAT_MAX_ITERATIONS, ECOM_RESEARCH_MAX_ITERATIONS) so the SUM stays inside its bound.
RESEARCH_TURN_TIMEOUT, RESEARCH_MAX_ITERATIONS = 600, _iterations("ECOM_RESEARCH_MAX_ITERATIONS", 14)
CHAT_MAX_ITERATIONS = _iterations("ECOM_CHAT_MAX_ITERATIONS", 12)
# an ad-research turn is longer (searches, details, up to 4 downloads and as many inspections, then the package): 20 iterations (+1 summary request)
AD_MAX_ITERATIONS = _iterations("ECOM_AD_MAX_ITERATIONS", 20)
# a specialist that holds BOTH ad research and generate_flyer also inspects its merchant photos, generates, reviews and may correct once: a longer turn
FLYER_MAX_ITERATIONS = _iterations("ECOM_FLYER_MAX_ITERATIONS", 40)
MAX_SKILLS, MAX_TEXT = 3, 8000


def ca_env():
    """TLS trust for Hermes subprocesses: certifi + the Windows root store (needed behind TLS-scanning antivirus such as
    Avast, whose root is only in the Windows store). Verification stays ON. Public certs only, written to runtime/."""
    import ssl
    out = RUNTIME / "ca_bundle.pem"
    try:
        if not out.exists():
            import certifi
            pems = [Path(certifi.where()).read_text(encoding="utf-8")]
            for store in ("ROOT", "CA"):
                for der, enc, _trust in ssl.enum_certificates(store):
                    if enc == "x509_asn":
                        pems.append(ssl.DER_cert_to_PEM_cert(der))
            RUNTIME.mkdir(parents=True, exist_ok=True)
            out.write_text("\n".join(pems), encoding="utf-8")
        return {"SSL_CERT_FILE": str(out), "REQUESTS_CA_BUNDLE": str(out)}
    except Exception:  # non-Windows or certifi missing: leave Hermes' defaults
        return {}


def _blank_company():
    return {**{f: "" for f in COMPANY_FIELDS}, "updated_at": None, "updated_by": None}


def _parse_company(raw):
    if not isinstance(raw, dict):
        raise ValueError("saved company data is not a JSON object")
    c = _blank_company()
    c.update({k: raw[k] for k in c if k in raw})
    return c


def load_company():
    """The single saved company context. Blank (all fields empty) until onboarding; there is no built-in fixture.
    A reader can hit the file for a moment while a writer swaps it in (Windows refuses to open it then), so a refusal is retried briefly."""
    for attempt in range(50):
        try:
            return _parse_company(json.loads(COMPANY_PATH.read_text(encoding="utf-8")))
        except FileNotFoundError:
            break
        except PermissionError:
            time.sleep(0.01)
        except (OSError, ValueError):
            break
    return _blank_company()


if os.name == "nt":
    import msvcrt

    def _try_lock(f):
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)

    def _unlock(f):
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _try_lock(f):
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(f):
        fcntl.flock(f, fcntl.LOCK_UN)


@contextlib.contextmanager
def company_lock():
    """Exclusive cross-process lock for the whole read-merge-write of company.json. The server and every Hermes worker are separate
    processes, so a thread lock is not enough. It is an OS file lock: released automatically if its holder dies. Raises TimeoutError."""
    RUNTIME.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + COMPANY_LOCK_TIMEOUT
    with open(COMPANY_LOCK_PATH, "a+b") as f:
        while True:
            try:
                _try_lock(f)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("another save of the company details is still in progress")
                time.sleep(0.01)
        try:
            yield
        finally:
            _unlock(f)


def _read_company_for_update():
    """Strict read inside the lock: an absent file is a blank start; an unreadable or corrupt one raises instead of being overwritten."""
    try:
        return _parse_company(json.loads(COMPANY_PATH.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return _blank_company()


def _write_company(c):
    """Durable atomic replace (call only while holding company_lock). Cleans its temp file on failure."""
    tmp = COMPANY_PATH.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(c, indent=1))
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(100):   # Windows: the swap is refused for a moment while a reader has the file open
            try:
                os.replace(tmp, COMPANY_PATH)
                return
            except PermissionError:
                if attempt == 99:
                    raise
                time.sleep(0.02)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def company_status(c=None):
    c = c or load_company()
    missing = [f for f in REQUIRED_FIELDS if not str(c.get(f) or "").strip()]
    return {"complete": not missing, "missing": missing, "missing_labels": [COMPANY_LABELS[f] for f in missing],
            "required": REQUIRED_FIELDS, "optional": [f for f in COMPANY_FIELDS if f not in REQUIRED_FIELDS], "labels": COMPANY_LABELS}


def update_company(fields, source="form"):
    """The ONLY writer of the company context (validation and storage in _update_company). The logbook records a save that did not come through main's update_company tool (the
    web form, onboarding); a save made by main is already recorded as that tool's own call event, with the same result."""
    r = _update_company(fields, source)
    if source != "main":
        logbook.emit("context.save", "success" if r.get("ok") else "failure", agent_id=None if source == "onboarding" else "operator", inputs={"source": source, "fields": fields},
                     result={k: r.get(k) for k in ("ok", "code", "error", "changed", "complete")})
    return r


def _update_company(fields, source="form"):
    """Used by both the web form and main's update_company tool (same validation and storage).
    Partial update: only the keys given change. An empty string clears an optional field. Returns {ok, company, changed, ...} or err()."""
    if not isinstance(fields, dict) or not fields:
        return err("empty_update", "Provide at least one company field to update.", "fields", list(COMPANY_FIELDS))
    unknown = [k for k in fields if k not in COMPANY_FIELDS]
    if unknown:
        return err("unknown_field", f"Unknown company field(s): {unknown}.", "fields", list(COMPANY_FIELDS))
    clean = {}
    for k, v in fields.items():
        if not isinstance(v, str):
            return err("bad_value", f"{k} must be text.", k)
        v = " ".join(v.split()) if k in ("name", "website") else v.strip()
        _, required, limit = COMPANY_FIELDS[k]
        if len(v) > limit:
            return err("too_long", f"{COMPANY_LABELS[k]} is {len(v)} characters; the limit is {limit}.", k)
        if v.lower().strip(" .!") in PLACEHOLDERS:
            return err("placeholder_value", f"{COMPANY_LABELS[k]} cannot be a placeholder like {v!r}. Only store what the user actually said; "
                       "leave a field empty if it is unknown.", k, hint="Ask the user instead of guessing.")
        if not v and required:
            return err("required_field_empty", f"{COMPANY_LABELS[k]} is required and cannot be cleared.", k)
        if k == "website" and v and not re.fullmatch(r"(https?://)?[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,}(/\S*)?", v):
            return err("bad_website", "website must look like a domain or URL, for example example.com.", k)
        clean[k] = v
    try:
        with company_lock():   # the whole read-merge-write is one cross-process transaction: no lost updates
            cur = _read_company_for_update()
            changed = [k for k, v in clean.items() if cur.get(k) != v]
            cur.update(clean)
            if changed:
                cur["updated_at"], cur["updated_by"] = time.time(), source
                _write_company(cur)
    except (OSError, ValueError) as e:   # includes lock timeout; never report an unsaved change as saved
        why = "another save was still in progress" if isinstance(e, TimeoutError) else f"{type(e).__name__}: {e}"
        return {**err("company_storage_error", f"The company details could NOT be saved ({why}). Nothing was changed.", hint="Try again."),
                "retryable": True}
    st = company_status(cur)
    return {"ok": True, "changed": changed, "company": {k: cur[k] for k in COMPANY_FIELDS}, "complete": st["complete"],
            "missing": st["missing"], "missing_labels": st["missing_labels"]}


def db():
    RUNTIME.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.executescript("""
      CREATE TABLE IF NOT EXISTS agents(agent_id TEXT PRIMARY KEY, name TEXT, role TEXT, company_id TEXT,
        objective TEXT, instructions TEXT, context_refs TEXT, skills TEXT, granted_tools TEXT, approvals TEXT,
        conversation_id TEXT, state TEXT, created_at REAL);
      CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id TEXT, who TEXT,
        content TEXT, tools TEXT, ts REAL);
      CREATE TABLE IF NOT EXISTS agent_config_log(id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id TEXT, ts REAL, request_id TEXT, requested TEXT, applied TEXT);
      CREATE TABLE IF NOT EXISTS image_inspections(id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id TEXT, image_id TEXT, kind TEXT,
        sha256 TEXT, width INTEGER, height INTEGER, ts REAL);
      CREATE TABLE IF NOT EXISTS listing_drafts(draft_id TEXT PRIMARY KEY, agent_id TEXT, conversation_id TEXT, product_id TEXT, status TEXT,
        title TEXT, description TEXT, visual_brief TEXT, rationale TEXT, limitations TEXT, missing TEXT, merchant_snapshot TEXT,
        product_snapshot TEXT, listing_evidence TEXT, image_evidence TEXT, created_at REAL);
      CREATE TABLE IF NOT EXISTS research_allowance(scope TEXT PRIMARY KEY, api_max INTEGER NOT NULL, image_max INTEGER NOT NULL,
        api_used INTEGER NOT NULL DEFAULT 0, image_used INTEGER NOT NULL DEFAULT 0, created_at REAL);
      CREATE TABLE IF NOT EXISTS research_runs(run_id TEXT PRIMARY KEY, agent_id TEXT, conversation_id TEXT, request_id TEXT, message_id INTEGER,
        scope TEXT, api_max INTEGER, image_max INTEGER, created_at REAL, UNIQUE(agent_id, request_id));
      CREATE TABLE IF NOT EXISTS research_calls(id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, kind TEXT, params TEXT, params_key TEXT,
        status TEXT, outcome TEXT, http_status INTEGER, credits_charged REAL, credits_remaining REAL, ms INTEGER, error TEXT, result TEXT, ts REAL);
      CREATE TABLE IF NOT EXISTS research_listings(run_id TEXT, listing_id TEXT, record TEXT, first_call INTEGER, retrieved_at TEXT,
        PRIMARY KEY(run_id, listing_id));
      CREATE TABLE IF NOT EXISTS research_photos(run_id TEXT, listing_id TEXT, image_id TEXT, sha256 TEXT, bytes INTEGER, width INTEGER, height INTEGER,
        content_type TEXT, format TEXT, host TEXT, fetched_at REAL, path TEXT, PRIMARY KEY(run_id, listing_id));
      CREATE TABLE IF NOT EXISTS ad_allowance(scope TEXT PRIMARY KEY, api_max INTEGER NOT NULL, image_max INTEGER NOT NULL,
        api_used INTEGER NOT NULL DEFAULT 0, image_used INTEGER NOT NULL DEFAULT 0, created_at REAL);
      CREATE TABLE IF NOT EXISTS ad_runs(run_id TEXT PRIMARY KEY, agent_id TEXT, company_id TEXT, company_name TEXT, conversation_id TEXT, request_id TEXT,
        message_id INTEGER, scope TEXT, api_max INTEGER, image_max INTEGER, media_type TEXT, country TEXT, created_at REAL, UNIQUE(agent_id, request_id));
      CREATE TABLE IF NOT EXISTS ad_calls(id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, kind TEXT, endpoint TEXT, params TEXT, params_key TEXT,
        status TEXT, outcome TEXT, http_status INTEGER, credits_charged REAL, credits_remaining REAL, ms INTEGER, error TEXT, result TEXT, ts REAL);
      CREATE TABLE IF NOT EXISTS ad_advertisers(run_id TEXT, advertiser_no INTEGER, page_id TEXT, record TEXT, first_call INTEGER,
        PRIMARY KEY(run_id, advertiser_no), UNIQUE(run_id, page_id));
      CREATE TABLE IF NOT EXISTS ad_records(run_id TEXT, ad_no INTEGER, ad_archive_id TEXT, record TEXT, first_call INTEGER, retrieved_at TEXT,
        PRIMARY KEY(run_id, ad_no), UNIQUE(run_id, ad_archive_id));
      CREATE TABLE IF NOT EXISTS ad_images(run_id TEXT, image_id TEXT, ad_archive_id TEXT, ad_no INTEGER, image_no INTEGER, source_field TEXT, sha256 TEXT,
        bytes INTEGER, width INTEGER, height INTEGER, content_type TEXT, format TEXT, host TEXT, fetched_at REAL, path TEXT, PRIMARY KEY(run_id, image_id));
      CREATE TABLE IF NOT EXISTS ad_packages(package_id TEXT PRIMARY KEY, run_id TEXT UNIQUE, agent_id TEXT, company_id TEXT, conversation_id TEXT, request_id TEXT,
        status TEXT, summary TEXT, selection_basis TEXT, blocker TEXT, limitations TEXT, reach_gate TEXT, references_json TEXT, ads_considered TEXT,
        call_accounting TEXT, identity TEXT, created_at REAL);
      CREATE TABLE IF NOT EXISTS flyer_allowance(scope TEXT PRIMARY KEY, attempts_max INTEGER NOT NULL, attempts_used INTEGER NOT NULL DEFAULT 0, created_at REAL);
      CREATE TABLE IF NOT EXISTS flyer_runs(run_id TEXT PRIMARY KEY, agent_id TEXT, company_id TEXT, company_name TEXT, conversation_id TEXT, request_id TEXT,
        message_id INTEGER, product_id TEXT, scope TEXT, attempts_final_max INTEGER, final_candidate_id TEXT, created_at REAL, UNIQUE(agent_id, request_id));
      CREATE TABLE IF NOT EXISTS flyer_attempts(candidate_id TEXT PRIMARY KEY, run_id TEXT, attempt_no INTEGER, status TEXT, outcome TEXT, prompt TEXT, context_text TEXT,
        product_json TEXT, inputs_json TEXT, references_json TEXT, provider TEXT, model TEXT, request_json TEXT, inputs_synthetic INTEGER, http_status INTEGER, error TEXT,
        usage TEXT, interaction_id TEXT, ms INTEGER, out_path TEXT, out_sha256 TEXT, out_bytes INTEGER, out_width INTEGER, out_height INTEGER, out_mime TEXT,
        created_at REAL, dispatched_at REAL, finished_at REAL, UNIQUE(run_id, attempt_no));
      CREATE TABLE IF NOT EXISTS flyer_reviews(review_id TEXT PRIMARY KEY, candidate_id TEXT UNIQUE, run_id TEXT, agent_id TEXT, request_id TEXT, sha256 TEXT, width INTEGER,
        height INTEGER, inspection_id INTEGER, delivery TEXT, verified INTEGER, verdict TEXT, checks_json TEXT, defects_json TEXT, uncertainties TEXT, summary TEXT,
        refs_json TEXT, created_at REAL);""")
    for table, cols in (("flyer_attempts", ("predecessor_id", "corrections_json")), ("flyer_runs", ("selection_rationale", "selected_at", "research_json"))):
        have = [r[1] for r in c.execute(f"PRAGMA table_info({table})")]
        for col in cols:   # ticket 5: the correction link and the explicit final selection (additive; old rows stay NULL)
            if col not in have:
                try:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT")
                except sqlite3.OperationalError:   # another process added it first
                    pass
    if "meta" not in [r[1] for r in c.execute("PRAGMA table_info(messages)")]:   # routing metadata (added later; existing rows keep NULL)
        c.execute("ALTER TABLE messages ADD COLUMN meta TEXT")
    cols = [r[1] for r in c.execute("PRAGMA table_info(listing_drafts)")]
    for col in ("evidence_source", "research_run_id", "request_id"):   # which evidence a draft used (additive; old rows stay NULL = recorded sample)
        if col not in cols:
            try:
                c.execute(f"ALTER TABLE listing_drafts ADD COLUMN {col} TEXT")
            except sqlite3.OperationalError:   # another process added it first
                pass
    if "message_id" not in cols:   # the user message of the turn that saved the draft (INTEGER, like the run tables)
        try:
            c.execute("ALTER TABLE listing_drafts ADD COLUMN message_id INTEGER")
        except sqlite3.OperationalError:   # another process added it first
            pass
    if "selected_location_call" not in [r[1] for r in c.execute("PRAGMA table_info(research_runs)")]:   # the lookup the specialist currently relies on (additive)
        try:
            c.execute("ALTER TABLE research_runs ADD COLUMN selected_location_call INTEGER")
        except sqlite3.OperationalError:   # another process added it first
            pass
    for col in ("delivered_at", "boundary_at"):   # P1: the pixels were in an actual model request / a model response followed (hooks in app/hermes_plugin.py; NULL = not established)
        if col not in [r[1] for r in c.execute("PRAGMA table_info(image_inspections)")]:
            try:
                c.execute(f"ALTER TABLE image_inspections ADD COLUMN {col} REAL")
            except sqlite3.OperationalError:   # another process added it first
                pass
    for col in ("delivery", "request_id", "run_id", "detail"):   # how the image was sent; the backend-supplied request and run that inspected it (additive; old rows stay NULL = unknown/unbound)
        if col not in [r[1] for r in c.execute("PRAGMA table_info(image_inspections)")]:
            try:
                c.execute(f"ALTER TABLE image_inspections ADD COLUMN {col} TEXT")
            except sqlite3.OperationalError:   # another process added it first
                pass
    return c


def err(code, message, field=None, allowed=None, hint=None):
    """Structured corrective error (string 'error' keeps Hermes tool convention)."""
    return {"ok": False, "error": message, "code": code, "field": field, "allowed_values": allowed, "hint": hint}


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:30]


def _similar(a, b):
    wa, wb = set(re.findall(r"[a-z]{3,}", a.lower())), set(re.findall(r"[a-z]{3,}", b.lower()))
    return len(wa & wb) / max(1, len(wa | wb))


def validate_create_agent(a):
    """Return (clean_args, None) or (None, error_dict). Pure function, no side effects."""
    if not isinstance(a, dict):
        return None, err("bad_request", "Arguments must be an object.")
    role = a.get("role")
    if role not in ROLES:
        return None, err("unsupported_role", f"Unsupported role {role!r}.", "role", sorted(ROLES),
                         "Use one of allowed_values; no other roles exist.")
    name = (a.get("name") or "").strip()
    if not 2 <= len(name) <= 60 or not _slug(name):
        return None, err("bad_name", "name must be 2-60 characters with letters or digits.", "name")
    for f in ("objective", "instructions"):
        v = (a.get(f) or "").strip()
        if len(v) < 40:
            return None, err("too_short", f"{f} must be company-specific and at least 40 characters.", f,
                             hint="Generate it from the company context (read_company_context).")
        if len(v) > MAX_TEXT:
            return None, err("too_long", f"{f} exceeds {MAX_TEXT} characters.", f)
    refs = a.get("company_context_refs") or []
    bad = [r for r in refs if r not in COMPANY_SECTIONS] if isinstance(refs, list) else [refs]
    if not isinstance(refs, list) or bad:
        return None, err("bad_context_refs", f"Invalid company_context_refs {bad!r}.", "company_context_refs", COMPANY_SECTIONS,
                         f"Pass section names; {ESSENTIAL_SECTIONS} are always granted by the backend.")
    refs = sorted(set(refs) | set(ESSENTIAL_SECTIONS))
    skills, e = validate_skills(role, a.get("skills"))
    if e:
        return None, e
    tools, e = validate_tools(role, a.get("requested_tools"))
    if e:
        return None, e
    return {"role": role, "name": name, "objective": a["objective"].strip(), "instructions": a["instructions"].strip(),
            "refs": refs, "skills": skills, "tools": tools}, None   # validated above, THEN the mandatory foundation


_FRONTMATTER = re.compile(r"\A---[ \t]*\r?\n.*?\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)


def _skill_body(content):
    """A model that rewrites a skill usually starts from skill_view's output, which already has a frontmatter block; _skill_md writes the only one, so a leading block is dropped."""
    return _FRONTMATTER.sub("", content.strip(), count=1).strip()


def validate_skills(role, skills):
    """Custom skills are OPTIONAL: None or [] means the baseline skill plus the customized instructions. -> (clean list, None) or (None, error)."""
    skills = skills or []
    if not isinstance(skills, list) or len(skills) > MAX_SKILLS:
        return None, err("bad_skills", f"Custom skills are optional: omit them or provide at most {MAX_SKILLS} as [{{name, content}}].", "skills")
    for s in skills:
        sn = (s.get("name") or "") if isinstance(s, dict) else ""
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,40}", sn):
            return None, err("bad_skill_name", f"Skill name {sn!r} must be lowercase letters/digits/hyphens.", "skills[].name")
        c = _skill_body(s.get("content") or "")
        if len(c) < 40 or len(c) > MAX_TEXT:
            return None, err("bad_skill_content", f"Skill {sn!r} content must be 40-{MAX_TEXT} characters.", "skills[].content")
        fnd = roles.FOUNDATIONS[role]
        if sn == fnd["baseline_name"] or _similar(c, fnd["baseline"]) >= 0.6:
            return None, err("duplicate_baseline_skill", f"Skill {sn!r} duplicates the baseline skill {fnd['baseline_name']!r}, which the "
                             "backend already provides.", "skills[]", hint="Write a complementary skill specific to this company instead.")
    if len({s["name"] for s in skills}) != len(skills):
        return None, err("bad_skills", "Skill names must be unique.", "skills[].name")
    return [{"name": s["name"], "content": _skill_body(s["content"])} for s in skills], None


def validate_tools(role, requested):
    """Optional eligible tools for `role`, plus the mandatory foundation. Refuses tools of other roles and selections whose prerequisites are missing.
    -> (sorted granted tool list, None) or (None, error)."""
    eligible = ROLES[role]["eligible_tools"]
    req = requested or []
    if not isinstance(req, list):
        return None, err("bad_tools", "requested_tools must be a list of tool names.", "requested_tools", sorted(eligible))
    bad = [t for t in req if t not in eligible]
    if bad:
        nc = [t for t in bad if t in ROLES[role]["not_connected"]]
        hint = ("Those tools are not connected in this increment (live research/posting/email are later work). "
                if nc else "") + "Request only tools from allowed_values."
        return None, err("tool_not_permitted", f"Tools not permitted for role {role}: {bad}.", "requested_tools",
                         sorted(eligible), hint)
    tools = sorted(set(req) | set(ROLES[role]["mandatory_tools"]))
    missing = {t: [n for n in need if n not in tools] for t, need in ROLES[role]["requires"].items() if t in tools}
    missing = {t: m for t, m in missing.items() if m}
    if missing:
        return None, err("tool_dependency", "Incomplete tool selection: " + "; ".join(f"{t} requires {', '.join(m)}" for t, m in sorted(missing.items())) + ".",
                         "requested_tools", sorted(eligible), "Add the missing tools (they are eligible for this role) or remove the tools that need them. Nothing was created or changed.")
    return tools, None




def profile_config():
    """config.yaml shared by main and specialists: selected provider/model, our plugin, tools always sent directly,
    and no adoption of the user's Codex CLI login (single-use refresh tokens would be stolen from it)."""
    c = llm_config()
    extra = {tuple(x.split(":", 1)) for x in os.environ.get("ECOM_VISION_MODELS", "").split(",") if ":" in x}
    cfg = {"model": {"provider": c["provider"], "default": c["model"]},
           "plugins": {"enabled": ["ecom-agents"]},
           "tools": {"tool_search": {"enabled": "off"}},
           "auth": {"adopt_external_logins": False},
           # Hermes' automatic skill review runs a background model request after a turn with 10+ tool iterations. A research turn has that many
           # and it would be an uncounted model request; skills are still managed explicitly through the skills tool.
           "skills": {"creation_nudge_interval": 0}}
    if (c["provider"], c["model"]) in (VISION_VERIFIED | extra):   # per exact model: any other model keeps Hermes' own (text-only) default
        cfg["providers"] = {c["provider"]: {"models": {c["model"]: {"supports_vision": True}}}}
    if os.environ.get("ECOM_SINGLE_ATTEMPT") == "1":   # isolated probes only: fewer automatic model requests (api_max_retries=1, no auto-recovery ladder, no memory-review request). It does NOT disable Hermes' primary-transport recovery replay
        cfg["agent"] = {"api_max_retries": 1, "auto_recovery_cycles": 0}
        cfg["memory"] = {"nudge_interval": 0}
    return cfg


def sync_profiles():
    """Make every existing profile (and the private root) use the selected provider/model. Other config keys are kept."""
    import yaml
    want = profile_config()
    targets = [HERMES_ROOT] + sorted(p for p in (HERMES_ROOT / "profiles").glob("*") if p.is_dir())
    for d in targets:
        f = d / "config.yaml"
        cur = yaml.safe_load(f.read_text(encoding="utf-8")) if f.exists() else {}
        cur = cur if isinstance(cur, dict) else {}
        new = {**cur, **{k: ({**cur.get(k, {}), **v} if isinstance(v, dict) and isinstance(cur.get(k), dict) else v)
                         for k, v in want.items()}}
        if new != cur:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(yaml.safe_dump(new), encoding="utf-8")
    refresh_specialist_souls()


def refresh_specialist_souls():
    """Rebuild each EXISTING specialist's SOUL.md from its registry row, so a changed platform foundation (for example the reply rule) reaches profiles created earlier. Only SOUL.md is
    rewritten, and only when its text differs: the registry row, custom and own skills, memory, sessions and history are never touched, no profile is created, and a changed SOUL.md makes
    the worker clear the saved system prompt (prompt_stamp), so the next turn runs on it with the conversation intact. -> the agent ids that were rewritten."""
    done = []
    with db() as d:
        rows = [dict(r) for r in d.execute("SELECT agent_id, name, role, objective, instructions, granted_tools FROM agents")]
    company = load_company()["name"]
    for r in rows:
        f = HERMES_ROOT / "profiles" / r["agent_id"] / "SOUL.md"
        if not f.parent.is_dir() or (r["role"] or "market_analysis") not in roles.FOUNDATIONS:
            continue
        new = build_soul({"name": r["name"], "role": r["role"], "objective": r["objective"], "instructions": r["instructions"], "tools": json.loads(r["granted_tools"] or "[]")}, company)
        if not f.exists() or f.read_text(encoding="utf-8") != new:
            f.write_text(new, encoding="utf-8")
            done.append(r["agent_id"])
    return done


def image_roots():
    """Directories holding registered images (file name = image ID). Default: the private Marketplace diagnostic photos, whose IDs are
    the listing IDs. ECOM_IMAGE_DIRS (os.pathsep-separated) overrides, for isolated tests and diagnostics."""
    env = os.environ.get("ECOM_IMAGE_DIRS")
    base = [Path(p) for p in env.split(os.pathsep) if p] if env else [RUNTIME / "marketplace_check" / "images", ROOT / "tests" / "fixtures" / "demo_images"]
    ad_run = getattr(turn_state, "ad_run_id", None)   # ad images downloaded by THIS request's ad-research run (backend-set, never model-supplied)
    if ad_run and re.fullmatch(r"adrun-[0-9a-f]{10}", str(ad_run)):
        return [RUNTIME / "ad_research" / ad_run / "images"] + [r for r in base if r != RUNTIME / "marketplace_check" / "images"]
    run = getattr(turn_state, "run_id", None)   # photos downloaded by THIS request's research run (backend-set, never model-supplied) take precedence
    if run and re.fullmatch(r"run-[0-9a-f]{10}", str(run)):
        # in a live run the old diagnostic photo cache is not visible: a recorded photo must never be inspected as if it had just been retrieved
        return [RUNTIME / "research" / run / "images"] + [r for r in base if r != RUNTIME / "marketplace_check" / "images"]
    return base


def merchant_image_roots():
    """Directories holding the merchant's OWN registered photographs (file name = image ID): ECOM_IMAGE_DIRS, else the demo fixture folder. Unlike image_roots() this
    never includes Marketplace diagnostic photos or ad-research images, so a competitor image can never be resolved as a merchant photo."""
    env = os.environ.get("ECOM_IMAGE_DIRS")
    return [Path(p) for p in env.split(os.pathsep) if p] if env else [ROOT / "tests" / "fixtures" / "demo_images"]


def prepare_image(image_id):
    """Resolve a registered image ID to verified, model-ready pixels BEFORE any model call. Never takes a path or URL.
    Returns {ok, image_id, width, height, sent_width, sent_height, format, source_bytes, sha256, data_url} or a corrective error
    (bad_image_id | image_not_found | image_too_large | image_unreadable | image_unsupported) that carries the image_id."""
    def bad(code, msg, hint="Do not describe or guess this image: report that it could not be inspected."):
        return {**err(code, msg, "image_id", hint=hint), "image_id": image_id if isinstance(image_id, str) else None}
    if not isinstance(image_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", image_id):
        return bad("bad_image_id", "image_id must be a registered image ID (1-64 letters, digits, '-' or '_'), not a path or URL.")
    path = next((p for r in image_roots() for e in IMAGE_EXTS for p in [r / f"{image_id}{e}"] if p.is_file()), None)
    if path is None:
        return bad("image_not_found", f"No registered image with ID {image_id!r}.")
    try:
        size = path.stat().st_size
        if size > MAX_IMAGE_BYTES:
            return bad("image_too_large", f"Image {image_id!r} is {size} bytes; the limit is {MAX_IMAGE_BYTES}.")
        raw = path.read_bytes()
    except OSError as e:
        return bad("image_unreadable", f"Image {image_id!r} could not be read ({type(e).__name__}).")
    return model_ready(image_id, raw)


def model_ready(image_id, raw):
    """Verified, model-ready pixels from raw image bytes (full decode, permitted type, bounded edge, re-encoded JPEG data URL). Same result and error shapes as
    prepare_image; the caller has already decided WHICH bytes these are (a registered file, or a managed flyer candidate that passed its integrity check)."""
    def bad(code, msg, hint="Do not describe or guess this image: report that it could not be inspected."):
        return {**err(code, msg, "image_id", hint=hint), "image_id": image_id if isinstance(image_id, str) else None}
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(raw))
        fmt = im.format
        im.load()                                   # full decode: truncated/corrupt files fail here, not at the provider
    except ImportError:
        return bad("image_unsupported", "Image decoding (Pillow) is not available in this runtime.")
    except Exception as e:
        return bad("image_unreadable", f"Image {image_id!r} could not be decoded ({type(e).__name__}); it is corrupt, truncated or not an image.")
    if fmt not in IMAGE_FORMATS:
        return bad("image_unsupported", f"Image {image_id!r} has unsupported format {fmt!r}.")
    w, h = im.size
    if im.mode in ("RGBA", "LA", "P"):
        rgba = im.convert("RGBA")
        out = Image.new("RGB", rgba.size, "white")
        out.paste(rgba, mask=rgba.split()[-1])
    else:
        out = im.convert("RGB")
    if max(w, h) > MAX_IMAGE_EDGE:
        out.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
    buf = io.BytesIO()
    out.save(buf, "JPEG", quality=88)
    return {"ok": True, "image_id": image_id, "width": w, "height": h, "sent_width": out.width, "sent_height": out.height, "format": fmt,
            "source_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "data_url": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")}


def build_soul(c, company_name):
    held = c.get("tools", [])
    live = any(t in held for t in MARKETPLACE_TOOLS)
    recorded = "read_recorded_evidence" in held
    sources = ("the merchant's supplied catalogue facts (`read_catalogue`)" + (" and the live Marketplace research you did in THIS request" if live else "")
               + (" and the recorded Marketplace listings (`read_recorded_evidence`, a replayed sample, not live)" if recorded else ""))
    drafting = (f"You can write ONE listing draft with `save_listing_draft` from {sources}. You choose which listings are comparable; many are unrelated or "
                "search-only. Cite only listing IDs and image IDs you actually used, and only inspect_image results you really saw. Never add specifications, "
                "materials, discounts, delivery terms, performance or competitor-sales claims that the supplied facts do not contain. If a fact or image is "
                "missing, say so or save a partial draft. Nothing is published.\n"
                + ("When you hold both live research and recorded evidence, pass evidence_source explicitly (live_research or recorded_sample); never present "
                   "recorded listings as fresh research.\n" if live and recorded else "")) if "save_listing_draft" in held else ""
    research = ("You can research Facebook Marketplace for the merchant, read-only and only while answering a manual request: `marketplace_locate` (a place), "
                "`marketplace_search` (listings for a located place), `marketplace_item` (details of a listing a search of this request returned) and "
                "`marketplace_photo` (one listing photo; then `inspect_image` shows it). Every call is counted against a finite backend allowance that you "
                "cannot change, reset or extend (the `allowance` field of each result shows what is left), so spend it on purpose. YOU choose the queries, "
                "the comparables, the details and the photos. Results are often irrelevant or empty: judge them yourself and change the query, filters or "
                "place instead of repeating a search. Use only what the tools returned; prices are asking prices, not sales. Read the catalogue first and "
                "use its merchant facts (including its market location when it has one). If a tool fails, a photo is missing or the allowance is used up, "
                "say so and save an honest partial draft or report the blocker. You cannot contact sellers or publish.\n") if live else ""
    limits = ("Facebook Marketplace research is connected through your marketplace_* tools. Web access, other scraping, posting, email and seller contact "
              "are NOT connected. " if live else "Live market research, web access, scraping, posting and email are NOT connected. ")
    role = c.get("role") or "market_analysis"   # a dict without a role is an analyst (stored/legacy shape)
    fnd = roles.FOUNDATIONS[role]
    social = role == "social_media"
    ads = social and any(t in held for t in AD_TOOLS)
    if social and ads:   # ad research is connected through the fb_* tools this specialist was granted; generation is a later ticket
        limits = ("Facebook ad research is connected through your fb_* tools (US image ads, read-only). Image or flyer generation is NOT connected yet, and nothing "
                  "can be posted or published. Marketplace data, Instagram, other web access or scraping, email and scheduling are NOT connected. Your outputs are "
                  "text: research findings, creative briefs, copy and visual direction. If asked for an image file or a published post, say plainly that you "
                  "cannot produce or publish it. ")
    reviewing = social and all(t in held for t in ("inspect_flyer", "review_flyer"))   # the review/correction tools (V2-05)
    if social and "generate_flyer" in held:   # generation is connected through generate_flyer (ads or not); posting never
        limits = limits.replace("Image or flyer generation is NOT connected yet, and nothing can be posted or published.",
                                "Flyer generation is connected only through your flyer tools (generate_flyer, inspect_flyer, review_flyer, finalize_flyer: one initial image and at most "
                                "one reviewed correction per request), and nothing can be posted or published." if reviewing else
                                "Flyer generation is connected only through your generate_flyer tool (one image per request, UNCHECKED), and nothing can be posted or published.")
        if not ads:
            limits = (("Flyer generation is connected through your flyer tools (one Gemini image per request from the merchant's own photographs, reviewed by you from its actual "
                       "pixels, with at most one correction). ") if reviewing else
                      ("Flyer generation is connected through your generate_flyer tool (one Gemini image per request from the merchant's own photographs, saved UNCHECKED). ")
                      ) + "Facebook ad research, Marketplace data, Instagram, other web access or scraping, email, scheduling and posting are NOT connected. "
    elif social and not ads:   # honest capability statement for the role when no ad tool was granted
        limits = ("Facebook ad research and image or flyer generation are NOT connected yet, and nothing can be posted or published. Web access, scraping, "
                  "email and scheduling are NOT connected either. Your outputs are text: creative briefs, copy and visual direction. If asked for an image file "
                  "or a published post, say plainly that you cannot produce or publish it. ")
    ad_research = ("You can research US Facebook IMAGE ads for the merchant, read-only and only while answering a manual request: `fb_ads_find_advertiser` "
                   "(advertisers by name), `fb_ads_search` (ads by keyword, or the ads of an advertiser found in this request), `fb_ad_detail` (details of an ad "
                   "a search of this request returned: text, cards, image references, campaign, any reach fields), `fb_ad_image` (one image of such an ad; then "
                   "`inspect_image` shows its pixels) and `save_ad_research` (ONE package of your source-linked references and what you actually saw; "
                   "`read_ad_research` reads saved packages without any new request). Every provider call and image download is counted against a finite backend "
                   "allowance that you cannot change or reset (the `allowance` field of each result shows what is left), so spend it on purpose. YOU choose the "
                   "queries, advertisers, details and images. Results are often unrelated or empty: judge them yourself, change the query instead of repeating "
                   "it, and report an honest blocker if nothing relevant exists. Use only what the tools returned. Ads that share a campaign_id belong to one "
                   "campaign, which is not proof of an identical creative; cards are variants of one ad, not separate ads. Read each ad's `reach` and the "
                   "`reach_gate`: rank by reach ONLY when the gate says ranking is enabled and name its metric and geography; otherwise choose by relevance and say "
                   "that reach ranking was unavailable. Never substitute impressions, spend, likes, how long an ad ran or its position in the results for reach, and "
                   "never say an ad worked, sold or converted. Describe an ad image only after inspect_image showed you its pixels. Take principles from "
                   "references, never copy another advertiser's wording or imagery. You cannot contact advertisers or publish anything.\n") if ads else ""
    flyer = ("You can generate ONE flyer image per manual request with `generate_flyer`: choose a catalogue product (`read_catalogue`), select 1-3 of THAT product's "
             "registered merchant photograph ids (the real supplied photographs: Gemini receives exactly those), look at them with `inspect_image`, and write a prompt "
             "with the exact text, price and layout to show, using only the supplied product facts (the backend appends the facts it holds). Competitor ad images may be "
             "cited with `reference_ad_image_ids` as provenance only: they are never sent to Gemini and the product in the flyer is always the merchant's. You get ONE paid "
             "attempt per request: a failed, corrupt or uncertain attempt consumes it and is never repeated, so write the prompt carefully. If it reports a missing key, "
             "missing photographs or provenance, tell the user what to set up and do not retry. The saved flyer is UNCHECKED: nobody has reviewed that it matches the "
             "product, price or text, so never call it approved, verified or accurate. `read_flyer` reads saved flyers. Nothing is posted.\n") if social and "generate_flyer" in held else ""
    if reviewing and flyer:
        flyer = flyer.replace("You get ONE paid attempt per request: a failed, corrupt or uncertain attempt consumes it and is never repeated, so write the prompt carefully.",
                              "You get ONE initial paid attempt per request, and a verified review that found defects permits ONE correction (below): a failed, corrupt or uncertain "
                              "attempt consumes its slot and is never repeated, so write the prompt carefully.")
        flyer += ("REVIEW AND AT MOST ONE CORRECTION. After `generate_flyer` succeeds, look at the saved image's ACTUAL pixels with `inspect_flyer(candidate_id)`: it attaches the "
                  "candidate first and then the merchant's photographs of the product. The images reach you with your NEXT message, so call `review_flyer` in a LATER response, never in "
                  "the same tool-call batch as `inspect_flyer` (that review is refused). Record what you saw with `review_flyer`: three checks - product_appearance (does the product "
                  "match the merchant's photographs: colour, pattern, proportions), required_text_price (is every required word and the declared price present and exact) and "
                  "layout_readability - each pass, fail or uncertain with what you observed; for every failed check give a defect with a specific correction; list what you are "
                  "unsure of; echo the candidate_sha256 you were shown. A review counts only when the pixels were delivered to you: otherwise it is stored unverified and the "
                  "result stays UNCHECKED, so never describe an image you could not see. If a verified review found defects you may make ONE correction: `generate_flyer` with "
                  "`previous_candidate_id` and `corrections` ([{defect_no, instruction}] naming recorded defects). That is the second and last paid attempt of the request; the "
                  "backend re-uses the original photographs, facts and prompt (you cannot change them) and sends the previous draft as the image to correct. There is no second "
                  "correction. Inspect and review the corrected candidate too, then choose ONE final candidate with `finalize_flyer` (it need not be the newest; give a short "
                  "rationale). A passing review is an 'agent review passed': a fallible automated check, never human approval and never a guarantee that the product is reproduced "
                  "exactly. If defects remain, say they are unresolved and that the flyer is an unapproved draft. If no valid candidate exists, report the blocker; do not invent a "
                  "review.\n")
    catalogue = ("Use `read_catalogue` for the merchant's supplied product facts (name, specifications, declared price and currency, image ID). Copy them "
                 "exactly and never add to them.\n") if social and "read_catalogue" in held else ""
    vision = ("You can look at images with `inspect_image(image_id)`: it attaches the actual pixels of a registered image ID. Report observations per "
              "image_id: visible features, readable text, and what you are unsure of. Anything not directly visible (fabric composition, quality, "
              "authenticity, sales performance) is unverified; never describe an image that failed to load.\n") if "inspect_image" in c.get("tools", []) else ""
    return (f"# {c['name']}\nRole: {fnd['label']} specialist for {company_name}.\n\n"
            f"## Core responsibilities (fixed by the platform)\n{fnd['responsibilities']}\n"
            f"## Objective (set for this company)\n{c['objective']}\n\n## Company-specific instructions\n{c['instructions']}\n\n"
            "## Limits (enforced by the platform)\n" + limits + "You can "
            "read the company context you were granted, keep your own memory and manage your own skills. Say plainly when you lack evidence or "
            "live access instead of inventing data. You cannot create agents or take external actions. Read the company context for current "
            "company details: it can be edited after you were created. Only the operator, in Customize mode, can change your objective, instructions, custom skills and optional tools; "
            "you cannot give yourself tools or change your role.\n"
            + research + vision + drafting + catalogue + ad_research + flyer + fnd["start"] + "\n" + roles.REPLY_STYLE)


def _skill_md(name, content):
    desc = next((l.strip(" #*-") for l in content.splitlines() if l.strip()), name)[:200].replace("\n", " ")
    return f"---\nname: {name}\ndescription: {json.dumps(desc)}\nversion: 1.0.0\n---\n\n{content.strip()}\n"


def _write_profile(agent_id, c, conv_id):
    # Hermes resolves the profiles directory from HERMES_HOME. Outside the project home (e.g. a script calling create_agent in-process) it would
    # silently create the profile in the USER'S OWN Hermes installation, so refuse unless HERMES_HOME is inside this project's private home.
    try:
        Path(os.environ.get("HERMES_HOME") or "").resolve().relative_to(HERMES_ROOT.resolve())
        if not os.environ.get("HERMES_HOME"):
            raise ValueError
    except (ValueError, OSError):
        raise RuntimeError("refusing to create a profile: HERMES_HOME is not inside this project's private Hermes home "
                           f"({HERMES_ROOT}); it would be created in another Hermes installation")
    from hermes_cli.profiles import create_profile  # only importable inside the Hermes runtime
    pdir = create_profile(agent_id, no_alias=True, no_skills=True, description=f"{c['role']} specialist: {c['name']}")
    (pdir / "SOUL.md").write_text(build_soul(c, load_company()["name"]), encoding="utf-8")
    fnd = roles.FOUNDATIONS[c["role"]]
    for name, content in [(fnd["baseline_name"], fnd["baseline"])] + [(x["name"], x["content"]) for x in c["skills"]]:
        d = pdir / "skills" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(_skill_md(name, content), encoding="utf-8")
    import yaml
    (pdir / "config.yaml").write_text(yaml.safe_dump(profile_config()), encoding="utf-8")
    plug = HERMES_ROOT / "profiles" / "main" / "plugins" / "ecom-agents"
    if plug.exists():
        import shutil
        shutil.copytree(plug, pdir / "plugins" / "ecom-agents", dirs_exist_ok=True)
    return pdir


def create_agent(args):
    """The create_agent tool body. Company comes from application context (env), not from the model."""
    st = company_status()
    if not st["complete"]:   # backend authority: no creation until the essentials exist (main is told what to ask for)
        return err("company_incomplete", "Cannot create a specialist yet: the company context is missing " + ", ".join(st["missing_labels"]) + ".",
                   "company", st["missing"], "Ask the user for exactly these items in short questions, save their answers with update_company "
                   "(only what they actually said), then create the specialist.")
    with timing.span("create_agent.validate"):
        c, e = validate_create_agent(args)
    if e:
        return e
    agent_id = _slug(c["name"])
    conv_id = f"conv-{agent_id}"
    granted = c["tools"]  # validated request + the role's mandatory tools; the registry row, the response and run_turn's toolsets all use this list
    approvals = ROLES[c["role"]]["approval_requirements"]
    pdir = HERMES_ROOT / "profiles" / agent_id
    existed = pdir.exists()
    d = db()
    d.execute("BEGIN IMMEDIATE")   # one write lock for the whole creation: the server and every Hermes worker are separate processes, so concurrent requests for the same role serialize HERE
    try:
        same = d.execute("SELECT agent_id, name FROM agents WHERE role=?", (c["role"],)).fetchone()
        if same:   # at most ONE specialist per role: never overwrite it, never create a second profile
            d.rollback()
            return {**err("role_exists", f"This business already has a {c['role']} specialist: {same['name']!r} (agent_id {same['agent_id']!r}). Only one specialist per role is allowed, "
                          "so nothing was created or changed.", "role", hint=f"Tell the user to open the chat of {same['agent_id']} and use it; its objective, instructions, skills and tools "
                          "are changed there in Customize mode, not by creating another."), "agent_id": same["agent_id"]}
        if d.execute("SELECT 1 FROM agents WHERE agent_id=?", (agent_id,)).fetchone() or agent_id == "main":
            d.rollback()
            return err("name_taken", f"An agent with id {agent_id!r} already exists.", "name", hint="Choose a different name.")
        try:
            with timing.span("create_agent.write_profile"):  # nested inside the create_agent tool duration
                _write_profile(agent_id, c, conv_id)
        except Exception as ex:  # surface as corrective error, never raise into the agent loop; a half-written profile of THIS request is removed
            d.rollback()
            if not existed:
                import shutil
                shutil.rmtree(pdir, ignore_errors=True)
            return err("profile_creation_failed", f"{type(ex).__name__}: {ex}")
        with timing.span("create_agent.registry_insert"):
            d.execute("INSERT INTO agents VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (agent_id, c["name"], c["role"], COMPANY_ID, c["objective"], c["instructions"], json.dumps(c["refs"]),
                       json.dumps(c["skills"]), json.dumps(granted), json.dumps(approvals), conv_id, "idle", time.time()))
        d.commit()
    except BaseException:
        d.rollback()
        if not existed:
            import shutil
            shutil.rmtree(pdir, ignore_errors=True)
        raise
    finally:
        d.close()
    return {"ok": True, "agent_id": agent_id, "conversation_id": conv_id, "granted_tools": granted,
            "approval_requirements": approvals, "state": "idle", "context_refs": c["refs"],
            "skills": [roles.FOUNDATIONS[c["role"]]["baseline_name"]] + [x["name"] for x in c["skills"]]}


# ---------- ticket 04: operator-authorized customization of an EXISTING specialist
CUSTOMIZE_FIELDS = ("objective", "instructions", "skills", "remove_skills", "add_tools", "remove_tools")


def is_granted(agent_id, tool):
    """Live registry check used at execution time: a removed tool is refused by the backend even when a stale schema or the model still offers it."""
    with db() as d:
        r = d.execute("SELECT granted_tools FROM agents WHERE agent_id=?", (agent_id,)).fetchone()
    return bool(r) and tool in json.loads(r["granted_tools"])


def customization_log(agent_id, limit=10):
    with db() as d:
        return [{"ts": x["ts"], "request_id": x["request_id"], "applied": json.loads(x["applied"])}
                for x in d.execute("SELECT ts, request_id, applied FROM agent_config_log WHERE agent_id=? ORDER BY id DESC LIMIT ?", (agent_id, limit))]


def _settle_staging(pdir, referenced):
    """Settle the staging folder of removed skills; -> names that still need recovery. A staged skill the saved configuration still REFERENCES while its active folder has no SKILL.md is an
    unresolved recovery copy (a failed restore): it is put back when the place is free, otherwise it is kept untouched and reported. Everything else is garbage of a successful removal and is
    deleted (read-only files included). Never raises. Recovery copies stay outside skills/, so Hermes never loads them; the rule reads only the disk and the registry, so it survives a restart."""
    import shutil, stat

    def writable_then_retry(fn, path, exc_info):
        os.chmod(path, stat.S_IWRITE)
        fn(path)
    root, pending = pdir / ".customize-staging", []
    try:
        for batch in sorted(root.iterdir()) if root.is_dir() else []:
            for f in sorted(batch.iterdir()) if batch.is_dir() else []:
                active = pdir / "skills" / f.name
                if f.name in referenced and not (active / "SKILL.md").exists():
                    try:
                        if active.exists():
                            raise FileExistsError(str(active))
                        os.replace(f, active)
                        continue
                    except OSError:
                        pending.append(f.name)
                        continue
                shutil.rmtree(f, onerror=writable_then_retry, ignore_errors=False) if f.is_dir() else f.unlink(missing_ok=True)
            if batch.is_dir() and not any(batch.iterdir()):
                batch.rmdir()
        if root.is_dir() and not any(root.iterdir()):
            root.rmdir()
    except OSError:
        pass
    return pending


def customize_agent(agent_id, changes, request_id=None):
    """The ONLY way an existing specialist's configuration changes: objective, instructions, custom skills and optional tools, as a PARTIAL update (anything not named is kept).
    Authorization is NOT decided here: the caller (the customize_specialist tool) runs only in a turn the operator marked as Customize mode. Everything is validated before anything is
    written; the registry row, SOUL.md and the custom skill files change together or not at all. Identity, role, company facts, foundations, mandatory tools, providers, limits stay."""
    if not isinstance(changes, dict) or not changes:
        return err("empty_update", f"Send at least one of: {', '.join(CUSTOMIZE_FIELDS)}.", "fields", list(CUSTOMIZE_FIELDS))
    bad = sorted(k for k in changes if k not in CUSTOMIZE_FIELDS)
    if bad:
        return err("forbidden_field", f"These fields cannot be changed here: {bad}. Nothing was changed.", "fields", list(CUSTOMIZE_FIELDS),
                   "Identity, role, company facts and context, approvals, providers, credentials, paid limits and posting permissions are fixed by the platform; tools are changed with "
                   "add_tools/remove_tools from the role's eligible list, skills with skills/remove_skills.")
    if not agent_id or agent_id == "main":
        return err("not_customizable", "Only a specialist can be customized.", "agent_id")
    with db() as d:
        r = d.execute("SELECT * FROM agents WHERE agent_id=?", (agent_id,)).fetchone()
    if not r or r["role"] not in ROLES:
        return err("unknown_agent", f"Unknown specialist {agent_id!r}.", "agent_id")
    role, new = r["role"], {}
    for f in ("objective", "instructions"):
        if f in changes:
            v = changes[f].strip() if isinstance(changes[f], str) else ""
            if len(v) < 40:
                return err("too_short", f"{f} must be company-specific and at least 40 characters.", f)
            if len(v) > MAX_TEXT:
                return err("too_long", f"{f} exceeds {MAX_TEXT} characters.", f)
            new[f] = v
    pdir = HERMES_ROOT / "profiles" / agent_id
    custom_now = json.loads(r["skills"])
    unresolved = _settle_staging(pdir, {x["name"] for x in custom_now})   # first put back / keep any recovery copy of a registered skill; clean only genuine garbage
    if unresolved:
        return err("recovery_required", f"The saved skill(s) {unresolved} of this specialist are registered but their files are missing from its active skills folder; the only copy is preserved in "
                   f"{pdir / '.customize-staging'}. Nothing was changed. Free the place (skills/{unresolved[0]}) or restore the folder from there, then customize again.", "skills", unresolved)
    custom = list(custom_now)
    if "remove_skills" in changes:
        rm = changes["remove_skills"]
        if not isinstance(rm, list) or any(not isinstance(n, str) for n in rm):
            return err("bad_skills", "remove_skills must be a list of custom skill names.", "remove_skills")
        unknown = [n for n in rm if n not in {x["name"] for x in custom}]
        if unknown:
            return err("unknown_skill", f"Not custom skills of this specialist (the baseline and the specialist's own skills cannot be removed here): {unknown}.", "remove_skills", [x["name"] for x in custom])
        custom = [x for x in custom if x["name"] not in rm]
    if "skills" in changes:
        ups, e = validate_skills(role, changes["skills"])
        if e:
            return e
        names_now = {x["name"] for x in custom_now}
        taken = [x["name"] for x in ups if x["name"] not in names_now and (pdir / "skills" / x["name"]).exists()]
        if taken:
            return err("skill_name_taken", f"A skill named {taken} already exists in this specialist's own skills; choose another name.", "skills[].name")
        by_name = {x["name"]: x for x in custom}
        for x in ups:
            by_name[x["name"]] = x
        custom = list(by_name.values())
        if len(custom) > MAX_SKILLS:
            return err("bad_skills", f"At most {MAX_SKILLS} custom skills are allowed; remove one first (remove_skills).", "skills")
    granted = json.loads(r["granted_tools"])
    if "add_tools" in changes or "remove_tools" in changes:
        add, rm = changes.get("add_tools") or [], changes.get("remove_tools") or []
        if not isinstance(add, list) or not isinstance(rm, list) or any(not isinstance(t, str) for t in [*add, *rm]):
            return err("bad_tools", "add_tools and remove_tools must be lists of tool names.", "add_tools", sorted(ROLES[role]["eligible_tools"]))
        mand = [t for t in rm if t in ROLES[role]["mandatory_tools"]]
        if mand:
            return err("mandatory_tool", f"Mandatory tools cannot be removed: {mand}.", "remove_tools")
        absent = [t for t in rm if t not in granted]
        if absent:
            return err("tool_not_granted", f"Not currently granted, so it cannot be removed: {absent}.", "remove_tools", granted)
        optional = (set(granted) - set(ROLES[role]["mandatory_tools"]) | set(add)) - set(rm)
        granted_new, e = validate_tools(role, sorted(optional))
        if e:
            return e
        granted = granted_new
    applied = {}
    if new.get("objective") not in (None, r["objective"]):
        applied["objective"] = new["objective"]
    if new.get("instructions") not in (None, r["instructions"]):
        applied["instructions"] = new["instructions"]
    if custom != custom_now:
        applied["skills"] = [x["name"] for x in custom]
    if granted != json.loads(r["granted_tools"]):
        applied["granted_tools"] = granted
    kept = [f for f in ("objective", "instructions", "skills", "granted_tools") if f not in applied]
    if not applied:
        return {"ok": True, "agent_id": agent_id, "applied": {}, "kept": kept, "note": "Nothing differed from the saved configuration, so nothing was changed."}
    company = load_company()["name"]
    soul = build_soul({"name": r["name"], "role": role, "objective": new.get("objective", r["objective"]), "instructions": new.get("instructions", r["instructions"]), "tools": granted}, company)
    # Files and registry change together or not at all. A removed skill is first MOVED to a staging folder OUTSIDE skills/ (a rename is atomic and works even when the skill holds a
    # read-only file), so once the move succeeded Hermes can no longer see it; every later step can still be rolled back, and a failure at any step restores the previous state explicitly.
    import shutil
    stage = pdir / ".customize-staging" / str(time.time_ns())
    gone = [x["name"] for x in custom_now if x["name"] not in {y["name"] for y in custom}]
    undo, moved, made = [], [], []   # undo: (file, previous bytes or None); moved: staged skill folders; made: skill folders created by this call
    d = db()
    d.execute("BEGIN IMMEDIATE")
    try:
        for n in gone:
            if (pdir / "skills" / n).exists():
                stage.mkdir(parents=True, exist_ok=True)
                os.replace(pdir / "skills" / n, stage / n)
                moved.append(n)
        soul_f = pdir / "SOUL.md"
        undo.append((soul_f, soul_f.read_bytes() if soul_f.exists() else None))
        soul_f.write_text(soul, encoding="utf-8")
        for x in custom:
            if x not in custom_now:
                folder = pdir / "skills" / x["name"]
                if not folder.exists():
                    made.append(folder)
                f = folder / "SKILL.md"
                undo.append((f, f.read_bytes() if f.exists() else None))
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(_skill_md(x["name"], x["content"]), encoding="utf-8")
        d.execute("UPDATE agents SET objective=?, instructions=?, skills=?, granted_tools=? WHERE agent_id=?",
                  (new.get("objective", r["objective"]), new.get("instructions", r["instructions"]), json.dumps(custom), json.dumps(granted), agent_id))
        d.execute("INSERT INTO agent_config_log(agent_id, ts, request_id, requested, applied) VALUES(?,?,?,?,?)",
                  (agent_id, time.time(), request_id, json.dumps(changes), json.dumps(applied)))
        d.commit()
    except Exception as ex:
        d.rollback()
        stuck = []
        for f, old in reversed(undo):
            try:
                if old is None:
                    f.unlink(missing_ok=True)
                elif not (f.exists() and f.read_bytes() == old):   # a file this call never managed to change needs no restore
                    f.write_bytes(old)
            except OSError as e:
                stuck.append(f"{f.name}: {e}")
        for folder in made:
            try:
                shutil.rmtree(folder)
            except OSError as e:
                stuck.append(f"{folder.name}: {e}")
        for n in reversed(moved):
            try:
                os.replace(stage / n, pdir / "skills" / n)
            except OSError as e:
                stuck.append(f"{n}: {e}")
        _settle_staging(pdir, {x["name"] for x in custom_now})   # a copy that could not be put back is still referenced, so it is kept
        return err("customization_failed", f"{type(ex).__name__}: {ex}. The configuration was not changed."
                   + (f" WARNING: restoring some files failed ({'; '.join(stuck)}); check this specialist's profile folder." if stuck else ""))
    finally:
        d.close()
    _settle_staging(pdir, {x["name"] for x in custom})   # best effort: the removed skills are already inactive, whatever remains here is never loaded
    return {"ok": True, "agent_id": agent_id, "applied": applied, "kept": kept, "granted_tools": granted, "custom_skills": [x["name"] for x in custom],
            "takes_effect": "from the next message of this specialist (this turn keeps running on the previous configuration)"}


def read_company_context(section=None, agent_id=None):
    """Company context. Main sees everything plus what is missing; a specialist only sees the sections granted at creation."""
    co = load_company()
    is_main = not agent_id or agent_id == "main"
    allowed = list(COMPANY_SECTIONS)
    if not is_main:
        with db() as d:
            r = d.execute("SELECT context_refs FROM agents WHERE agent_id=?", (agent_id,)).fetchone()
        allowed = json.loads(r["context_refs"]) if r else []
    if section and section not in COMPANY_SECTIONS:
        return err("bad_section", f"Unknown section {section!r}.", "section", COMPANY_SECTIONS)
    if section and section not in allowed:
        return err("section_not_granted", f"Section {section!r} was not granted to this agent.", "section", allowed)
    want = [section] if section else allowed
    out = {"ok": True}
    for f, (sec, _, _) in COMPANY_FIELDS.items():
        if sec in want:
            out.setdefault(sec, {})[f] = co[f] or None   # None = unknown; never guess it
    if is_main:
        st = company_status(co)
        out.update(complete=st["complete"], missing=st["missing"], missing_labels=st["missing_labels"],
                   note="Empty/None means the user has not provided it. Do not invent company facts, competitors, prices or customers.")
    return out


# ---------- Hermes runner (used by the web server) ----------

def load_secrets():
    """secrets/local.env values; non-empty process env vars for the same keys override (used by plumbing tests)."""
    env, p = {}, ROOT / "secrets" / "local.env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                if v.strip():
                    env[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("LLM_PROVIDER", "LLM_MODEL", "NEBIUS_API_KEY", "NEBIUS_MODEL", "NEBIUS_BASE_URL"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def llm_config():
    """Selected provider/model. No defaults between providers: a missing/invalid choice is an error, never a fallback."""
    sec = load_secrets()
    prov, model = sec.get("LLM_PROVIDER", ""), sec.get("LLM_MODEL", "")
    if prov == "nebius-token-factory":
        model = model or sec.get("NEBIUS_MODEL") or NEBIUS_DEFAULT_MODEL
    return {"provider": prov, "model": model}


LOGIN_CMD = "login_codex.bat"
_auth_cache = {}


def llm_problem():
    """None if the selected provider looks usable, else a message telling the user exactly what to fix."""
    c, sec = llm_config(), load_secrets()
    if c["provider"] not in PROVIDERS:
        return f"LLM_PROVIDER in secrets/local.env must be one of {', '.join(PROVIDERS)} (got {c['provider'] or 'nothing'!r})."
    if c["provider"] == "nebius-token-factory":
        return None if sec.get("NEBIUS_API_KEY") else "NEBIUS_API_KEY is missing. Put it in secrets/local.env (see secrets/local.env.template)."
    err = codex_auth_error()
    if err:
        return f"ChatGPT/Codex subscription is not signed in for this project ({err}). Run {LOGIN_CMD} in the project folder."
    return None if c["model"] else "LLM_MODEL is not set in secrets/local.env. List the models your subscription offers with: list_models.bat"


def codex_auth_error():
    """None if the project's Codex login exists, else a short reason. Uses Hermes' own read-only status path
    (no token refresh, no auth-store write, no external-login adoption, no subprocess); workers refresh tokens when they use them.
    Cached: 10 min when signed in, 3 s when not (so the UI recovers right after login_codex.bat)."""
    hit = _auth_cache.get("codex")
    if hit and time.time() - hit[0] < (600 if hit[1] is None else 3):
        return hit[1]
    saved = os.environ.get("HERMES_HOME")
    os.environ["HERMES_HOME"] = str(HERMES_ROOT)   # never inspect any Hermes home other than this project's
    try:
        import sys
        agent_dir = str(Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / "hermes-agent")
        if agent_dir not in sys.path:
            sys.path.insert(0, agent_dir)
        from hermes_cli.auth import resolve_codex_runtime_credentials
        resolve_codex_runtime_credentials(read_only=True)
        res = None
    except Exception as e:
        res = (str(e).splitlines() or [type(e).__name__])[0][:160]
    finally:
        if saved is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = saved
    _auth_cache["codex"] = (time.time(), res)
    return res


def run_turn(agent_id, message, timeout=300, conv_override=None, route=None, request_id=None, customize=False):
    """Run one chat turn on the agent's long-lived Hermes worker (started on first use). Returns dict(text, tools, error).
    customize=True is the OPERATOR's Customize mode for this one turn (set by the server from the request, never by a model): only then is the customize_specialist tool offered."""
    from app import workers
    sec = load_secrets()
    if agent_id == "main":
        toolsets, conv = MAIN_TOOLSETS, "main-conversation"
    else:
        with db() as d:
            r = d.execute("SELECT granted_tools, conversation_id, role FROM agents WHERE agent_id=?", (agent_id,)).fetchone()
        if not r:
            return {"text": "", "tools": [], "error": f"unknown agent {agent_id!r}"}
        tools = json.loads(r["granted_tools"])
        eligible = ROLES.get(r["role"], ROLES["market_analysis"])["eligible_tools"]   # the agent's OWN role decides what its stored grants mean
        toolsets = [eligible[t]["toolset"] for t in tools] + (["ecom_customize"] if customize else [])
        conv = r["conversation_id"]
        if any(t in MARKETPLACE_TOOLS or t in AD_RESEARCH_TOOLS or t == "generate_flyer" for t in tools):
            timeout = max(timeout, RESEARCH_TURN_TIMEOUT)
    pt = {}  # parent-side stage durations (ms), only used when ECOM_TIMING=1
    t = time.perf_counter()
    problem = llm_problem()
    pt["auth_check_ms"] = round((time.perf_counter() - t) * 1000, 1)
    if problem:
        return {"text": "", "tools": [], "error": problem}
    cfg = llm_config()
    env = {**os.environ, **({k: v for k, v in sec.items() if k.startswith("NEBIUS_")} if cfg["provider"] == "nebius-token-factory" else {}),
           "HERMES_HOME": str(HERMES_ROOT / "profiles" / agent_id), "ECOM_APP_ROOT": str(ROOT),
           **ca_env(), "ECOM_AGENT_ID": agent_id, "ECOM_COMPANY_ID": COMPANY_ID, "PYTHONUTF8": "1", "ECOM_LOGBOOK": "1" if logbook.enabled() else "0"}
    for k in logbook.DB_ENV_VARS:   # only the server's single writer holds the logbook database credential, even when it came from the process environment
        env.pop(k, None)
    sig = (cfg["provider"], cfg["model"], tuple(toolsets), conv_override or conv)  # any change restarts this agent's worker
    req = {"op": "turn", "message": message, "toolsets": toolsets, "conversation": conv_override or conv,
           "provider": cfg["provider"], "model": cfg["model"], "route": route, "request_id": request_id, "customize": bool(customize and agent_id != "main"),
           "max_iterations": (FLYER_MAX_ITERATIONS if "generate_flyer" in tools and any(t in AD_RESEARCH_TOOLS for t in tools)
                              else AD_MAX_ITERATIONS if any(t in AD_RESEARCH_TOOLS for t in tools)
                              else RESEARCH_MAX_ITERATIONS if any(t in MARKETPLACE_TOOLS for t in tools) or "generate_flyer" in tools
                              else CHAT_MAX_ITERATIONS) if agent_id != "main" else CHAT_MAX_ITERATIONS}
    t = time.perf_counter()
    try:
        r, spawned = workers.run(agent_id, sig, env, req, timeout)
    except workers.WorkerError as e:
        return {"text": "", "tools": [], "error": str(e)}
    pt["worker_request_ms"], pt["worker_spawned_this_turn"] = round((time.perf_counter() - t) * 1000, 1), spawned
    if timing.ENABLED and r.get("timing"):
        r["timing"]["parent"] = pt
    return r
