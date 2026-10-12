"""Opt-in diagnostics. Enable with ECOM_TIMING=1 in the server's environment; unset it to disable (all calls become no-ops).
Tag: ecomtiming. Records stage names, durations, counts and numeric usage only - never prompts, replies, tool arguments,
credentials or tokens. Records go to runtime/timing.jsonl."""
import json, os, time
from contextlib import contextmanager
from pathlib import Path

ENABLED = os.environ.get("ECOM_TIMING") == "1"
TAG = "ecomtiming"
T0, WALL0 = time.perf_counter(), time.time()   # first import in a worker process ~= worker start
events = []                                      # per-process; the worker returns it with its result
LOG = Path(__file__).resolve().parent.parent / "runtime" / "timing.jsonl"


def now_ms():
    return round((time.perf_counter() - T0) * 1000, 1)


def mark(stage, **kw):
    if ENABLED:
        events.append({"stage": stage, "at_ms": now_ms(), **kw})


@contextmanager
def span(stage, **kw):
    if not ENABLED:
        yield {}
        return
    t, extra = time.perf_counter(), dict(kw)
    try:
        yield extra
    finally:
        events.append({"stage": stage, "at_ms": round((t - T0) * 1000, 1), "ms": round((time.perf_counter() - t) * 1000, 1), **extra})


def log(rec):
    if ENABLED:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"tag": TAG, "ts": round(time.time(), 3), **rec}) + "\n")


def register_hooks(ctx):
    """Hermes plugin hooks: per model request and per tool execution (observers only)."""
    if not ENABLED:
        return
    num = lambda d, *ks: {k: d.get(k) for k in ks if isinstance(d.get(k), (int, float))}

    def pre_api(**kw):
        req = kw.get("request") or {}
        mark("api_start", n=kw.get("api_call_count"), messages=kw.get("message_count"), tools=kw.get("tool_count"),
             approx_input_tokens=kw.get("approx_input_tokens"), api_mode=kw.get("api_mode"),
             stream_param=req.get("stream") if isinstance(req, dict) else None,
             reasoning=req.get("reasoning") if isinstance(req, dict) else None)

    def post_api(**kw):
        first, start = kw.get("first_chunk_at"), kw.get("started_at")
        usage = kw.get("usage") if isinstance(kw.get("usage"), dict) else {}
        mark("api_end", n=kw.get("api_call_count"), ms=round((kw.get("api_duration") or 0) * 1000, 1),
             ttfb_ms=round((first - start) * 1000, 1) if first and start else None, finish=kw.get("finish_reason"),
             tool_calls=kw.get("assistant_tool_call_count"), out_chars=kw.get("assistant_content_chars"), usage=num(usage, *usage.keys()))

    def post_tool(**kw):
        mark("tool", name=kw.get("tool_name"), ms=kw.get("duration_ms"), status=kw.get("status"))

    for name, fn in (("pre_api_request", pre_api), ("post_api_request", post_api), ("post_tool_call", post_tool),
                     ("pre_llm_call", lambda **kw: mark("turn_start")), ("post_llm_call", lambda **kw: mark("turn_end"))):
        ctx.register_hook(name, fn)
