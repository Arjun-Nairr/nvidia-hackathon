"""Live Nebius check (needs the real key in secrets/local.env): lists NVIDIA models, then does one tool-calling round trip
with NEBIUS_MODEL. Prints no secrets. Run: python scripts/check_nebius.py"""
import json, sys, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import core

sec = core.load_secrets()
if not sec.get("NEBIUS_API_KEY"):
    sys.exit("NEBIUS_API_KEY is missing. Put it in secrets/local.env (template: secrets/local.env.template).")
base = sec.get("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1")
model = sec.get("NEBIUS_MODEL") or core.DEFAULT_MODEL


def call(path, body=None):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": "Bearer " + sec["NEBIUS_API_KEY"], "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=120).read())


ids = sorted(m["id"] for m in call("/models")["data"])
nv = [i for i in ids if "nvidia" in i.lower() or "nemotron" in i.lower()]
print("NVIDIA models on this account:", nv or "none found")
if model not in ids:
    sys.exit(f"Configured NEBIUS_MODEL {model!r} not in the list. Set NEBIUS_MODEL in secrets/local.env to one of the above.")
r = call("/chat/completions", {"model": model, "max_tokens": 200, "messages": [{"role": "user", "content": "Call the ping tool."}],
        "tools": [{"type": "function", "function": {"name": "ping", "description": "ping", "parameters": {"type": "object", "properties": {}}}}]})
msg = r["choices"][0]["message"]
print("model:", model, "| tool call returned:", bool(msg.get("tool_calls")))
