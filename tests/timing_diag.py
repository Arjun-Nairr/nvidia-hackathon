"""Diagnostic set for ecomtiming (live, current provider): 2 simple replies, 1 company-context question, 1 specialist creation.
Starts its own server on port 8804 with ECOM_TIMING=1, sends 4 requests once each (no retries), prints a compact table.
Adds turns to the main conversation and creates ONE agent named 'ECOMTIMING Diagnostic Analyst'. Run with Hermes' venv python."""
import json, os, subprocess, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 8804
ENV = {**os.environ, "ECOM_TIMING": "1", "PYTHONUTF8": "1"}
log = ROOT / "runtime" / "timing.jsonl"
before = log.read_text(encoding="utf-8").count("\n") if log.exists() else 0
srv = subprocess.Popen([sys.executable, "-m", "app.server", str(PORT)], cwd=ROOT, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
PROMPTS = [
    ("simple-1 (cold)", "main", "[ecomtiming] Reply with just the word PONG."),
    ("simple-2", "main", "[ecomtiming] Reply with just the word PING."),
    ("context question", "main", "[ecomtiming] Use the company context: which competitors does the sample company monitor? Answer in one short line."),
    ("create specialist", "main", "[ecomtiming] Create a market analysis specialist named 'ECOMTIMING Diagnostic Analyst' for this company. Keep its objective, instructions and one skill short."),
]
try:
    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/status", timeout=5); break
        except Exception:
            time.sleep(0.5)
    for label, agent, msg in PROMPTS:
        t = time.perf_counter()
        req = urllib.request.Request(f"http://127.0.0.1:{PORT}/api/chat/{agent}", data=json.dumps({"message": msg}).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            r = json.loads(urllib.request.urlopen(req, timeout=600).read())
            print(f"{label}: ok, client wall {time.perf_counter() - t:.1f}s, error={r.get('error')}", flush=True)
        except Exception as e:
            print(f"{label}: FAILED {type(e).__name__}: {e}", flush=True)
            break
finally:
    srv.terminate()
rows = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines()[before:]]
json.dump([r for r in rows if r["kind"] == "chat"], open(ROOT / "runtime" / "timing_diag_last.json", "w"))
print("records:", len(rows))
