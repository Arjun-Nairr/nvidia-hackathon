"""List ChatGPT/Codex models offered to the project's signed-in subscription (live catalog only; never guesses)."""
import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import core
os.environ["HERMES_HOME"] = str(core.HERMES_ROOT)
os.environ.update(core.ca_env())
sys.path.insert(0, str(Path(os.environ["LOCALAPPDATA"]) / "hermes" / "hermes-agent"))
from hermes_cli.auth import resolve_codex_runtime_credentials
from hermes_cli.codex_models import _fetch_models_from_api

try:
    token = resolve_codex_runtime_credentials()["api_key"]
except Exception as e:
    sys.exit(f"Not signed in: {e}\nRun login_codex.bat first.")
ids = _fetch_models_from_api(token)
if not ids:
    sys.exit("The live catalog returned no models for this account (not guessing). Try again or check the subscription.")
print("Models offered by your subscription (set one as LLM_MODEL in secrets/local.env):")
for i in ids:
    print("  ", i)
