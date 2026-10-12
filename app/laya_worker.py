"""Long-lived Laya process (runs under .venv-laya, NOT Hermes' Python). Loads the 'typed-decisions' checkpoint ONCE, then answers
typed questions for the backend (app/routing.py). Generic on purpose: it knows nothing about our intents.
Protocol: JSON lines. stdin {"id", "op": "classify"|"shutdown", "state": ..., "questions": {...}}; stdout (protocol only)
{"event":"ready",...} once, then {"id", "result": {"answers", "usage", "elapsed_ms"}} or {"id", "error": "..."}.
Laya's own logging goes to stderr."""
import json, os, sys, time


def main():
    proto = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr

    def send(obj):
        proto.write(json.dumps(obj, default=float) + "\n")
        proto.flush()

    t = time.perf_counter()
    import laya
    t_import = time.perf_counter() - t
    t = time.perf_counter()
    agent = laya.load("typed-decisions")   # fine-tuned typed-decisions checkpoint (README: 0.766 vs 0.36 base on its benchmark)
    send({"event": "ready", "laya": laya.__version__, "import_ms": round(t_import * 1000), "load_ms": round((time.perf_counter() - t) * 1000),
          "device": str(getattr(agent, "device", "?"))})
    for line in sys.stdin:
        if not line.strip():
            continue
        req = json.loads(line)
        if req.get("op") == "shutdown":
            break
        try:
            t = time.perf_counter()
            res = agent.predict(req["state"], req["questions"])
            send({"id": req["id"], "result": {"answers": res["answers"], "usage": res.get("usage"),
                                              "elapsed_ms": round((time.perf_counter() - t) * 1000, 1)}})
        except Exception as e:
            import traceback; traceback.print_exc()
            send({"id": req["id"], "error": f"{type(e).__name__}: {e}"})


if __name__ == "__main__":
    main()
