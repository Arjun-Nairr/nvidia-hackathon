"""Long-lived Hermes worker for ONE profile (HERMES_HOME = that profile), driven by app/workers.py.
Protocol: JSON lines. stdin: {"id", "op": "turn"|"ping"|"shutdown", ...}. stdout (protocol only): {"event":"ready",...} once,
then {"id", "result": {...}} per request. Hermes' own prints/logs go to stderr (fd 1 is redirected to fd 2 below).
Imports and the AIAgent are built once and reused; conversation history is re-read from the profile's Hermes SessionDB each
turn (so it is never lost or appended twice). Uses the documented AIAgent library API (`hermes chat -q` hides skill_manage)."""
import hashlib, json, os, sys, time, uuid
from pathlib import Path
from app import timing, turn_state  # imported first: its clock ~= worker start

AGENT_DIR = Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / "hermes-agent"
sys.path.insert(0, str(AGENT_DIR))
LOGIN_HINT = " Run login_codex.bat in the project folder."


def vision_status(agent):
    """Hermes' own gate for letting an image part through a tool result, evaluated for the live agent (the same checks as
    AIAgent._tool_result_content_for_active_model). 'image_part_sent' means the image part goes with the tool result; it does not prove the provider
    accepted it or that the model understood it. Anything unexpected -> 'unknown' (never counted as vision)."""
    try:
        from agent.vision_message_prep import _provider_model_key
        if not agent._model_supports_vision() or not agent._provider_supports_vision_tool_messages():
            return "text_fallback"
        if _provider_model_key(agent) in (getattr(agent, "_no_list_tool_content_models", None) or ()):
            return "text_fallback"
        return "image_part_sent"
    except Exception:
        return "unknown"


def prompt_stamp(toolsets):
    """What a saved Hermes system prompt must still match: this profile's SOUL.md, its skill files and the toolsets of this turn. Hermes reuses the system prompt stored with a saved
    session (and its pinned tool list) for as long as the session lives, so a changed configuration needs this check to take effect."""
    home = Path(os.environ.get("HERMES_HOME") or ".")
    h = hashlib.sha256(("|".join(sorted(toolsets))).encode())
    for f in [home / "SOUL.md", *sorted((home / "skills").glob("*/SKILL.md"))]:
        h.update(str(f.relative_to(home)).encode())
        h.update(f.read_bytes() if f.exists() else b"")
    return h.hexdigest()[:16]


def refresh_stored_prompt(db, sid, conversation, stamp):
    """Smallest supported refresh: when the stamp differs from the one this conversation last ran with, clear the session's STORED system prompt and pinned tool list so Hermes rebuilds
    them from the current SOUL/skills/toolsets on this turn. Messages, memory and the session itself are untouched. Runs only when a new agent is built (between turns, never mid-turn)."""
    f = Path(os.environ.get("HERMES_HOME") or ".") / "prompt_stamps.json"
    try:
        stamps = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        stamps = {}
    if stamps.get(conversation) == stamp:
        return False
    if db.get_messages_as_conversation(sid):   # a continuing conversation: only then is there an older stored prompt to drop
        db.update_system_prompt(sid, None)
        db.update_session_tool_names(sid, None)
        try:
            from agent.prompt_builder import clear_skills_system_prompt_cache
            clear_skills_system_prompt_cache(clear_snapshot=True)   # the skills index cache does not watch the skills folder
        except Exception:
            pass
    stamps[conversation] = stamp
    f.write_text(json.dumps(stamps), encoding="utf-8")
    return True


def main():
    proto = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr  # nothing from Hermes may reach the protocol channel

    def send(obj):
        proto.write(json.dumps(obj) + "\n")
        proto.flush()

    with timing.span("import_hermes"):
        from hermes_state import SessionDB
        from hermes_cli.runtime_provider import resolve_runtime_provider
        from run_agent import AIAgent
    startup = list(timing.events)
    timing.events.clear()
    st = {"agent": None, "sig": None, "db": None, "sid": None, "turns": 0, "inits": 0, "startup": startup,
          "spawn_wall": float(os.environ.get("ECOM_SPAWN_WALL") or time.time())}
    send({"event": "ready", "pid": os.getpid(), "py_startup_ms": round((timing.WALL0 - st["spawn_wall"]) * 1000, 1), "startup": startup})

    def resolve(p):
        try:
            rt = resolve_runtime_provider(requested=p["provider"], target_model=p["model"])  # keeps each provider's auth + api_mode
        except Exception as e:
            raise RuntimeError(f"{p['provider']} sign-in/credential problem: {e}." + (LOGIN_HINT if p["provider"] == "openai-codex" else ""))
        if rt.get("provider") != p["provider"]:  # never run on a different provider than the one selected
            raise RuntimeError(f"Hermes resolved provider {rt.get('provider')!r}, not the selected {p['provider']!r}")
        return rt

    def turn(p):
        timing.events.clear()
        if st["turns"] == 0:
            timing.events.extend(st["startup"])
        t_in = time.perf_counter()
        stamp = prompt_stamp(p["toolsets"])
        sig = (p["provider"], p["model"], tuple(p["toolsets"]), p["conversation"], p.get("max_iterations", 12), stamp)
        created = st["agent"] is None or st["sig"] != sig
        if created:  # first turn (or config changed): build the Hermes runtime once
            if st["db"] is None:
                with timing.span("session_db_open"):
                    st["db"] = SessionDB()
            db = st["db"]
            sid = db.resolve_session_by_title(p["conversation"])
            if not sid:
                sid = f"{p['conversation']}-{uuid.uuid4().hex[:8]}"
                db.create_session(sid, source="tool")
                db.set_session_title(sid, p["conversation"])
            with timing.span("provider_resolve"):
                rt = resolve(p)
            with timing.span("prompt_refresh"):
                refresh_stored_prompt(db, sid, p["conversation"], stamp)
            with timing.span("agent_init") as sp:  # includes plugin discovery/loading and tool schema assembly
                st["agent"] = AIAgent(model=p["model"], api_key=rt.get("api_key"), base_url=rt.get("base_url"), provider=rt.get("provider"),
                                      requested_provider=rt.get("requested_provider"), api_mode=rt.get("api_mode"),
                                      credential_pool=rt.get("credential_pool"), enabled_toolsets=p["toolsets"], max_iterations=p.get("max_iterations", 12),
                                      quiet_mode=True, session_id=sid, session_db=db, platform="tool")
                sp.update(api_mode=st["agent"].api_mode, reasoning_config=str(getattr(st["agent"], "reasoning_config", None)),
                          tool_schemas=len(st["agent"].tools or []))
            st["sig"], st["sid"] = sig, sid
            st["inits"] += 1
        else:  # reuse: re-resolve credentials each turn (Hermes refreshes expiring OAuth tokens here) and adopt a changed key
            with timing.span("provider_resolve"):
                rt = resolve(p)
            a = st["agent"]
            if rt.get("api_key") and (rt["api_key"] != a.api_key or rt.get("base_url") != a.base_url) and hasattr(a, "_adopt_openai_credentials"):
                a._adopt_openai_credentials(rt["api_key"], rt["base_url"], reason="turn_refresh")
        db, sid, agent = st["db"], st["sid"], st["agent"]
        with timing.span("history_load") as sp:
            history = db.get_messages_as_conversation(sid)
            sp["history_messages"] = len(history)
        t_run = time.perf_counter()
        turn_state.route = p.get("route")   # None for specialists (they have no create_agent); main without a route is fail-closed
        turn_state.request_id, turn_state.run_id, turn_state.ad_run_id = p.get("request_id"), None, None   # the backend's manual-request id (research runs are scoped to it)
        turn_state.vision_probe = lambda a=agent: vision_status(a)
        turn_state.customize = bool(p.get("customize"))   # the operator's Customize mode, from the backend request only
        try:
            with timing.span("run_conversation"):
                res = agent.run_conversation(p["message"], conversation_history=history)
        except BaseException:
            st["agent"] = None  # do not reuse a possibly half-updated agent; next turn rebuilds from saved history
            raise
        finally:
            turn_state.route = None
            turn_state.request_id = turn_state.run_id = turn_state.ad_run_id = None
            turn_state.vision_probe = None
            turn_state.customize = False
            turn_state.pending_images.clear()
        new = res["messages"][len(history):]
        tools = []
        for m in new:
            for tc in m.get("tool_calls") or []:
                f = tc.get("function") or {}
                tools.append({"name": f.get("name"), "input": f.get("arguments"), "id": tc.get("id")})
            if m.get("role") == "tool":
                tools.append({"name": m.get("name"), "output": str(m.get("content"))[:3000], "id": m.get("tool_call_id")})
        st["turns"] += 1
        out = {"text": res.get("final_response") or "", "tools": tools, "session_id": sid,
               "error": None if res.get("completed", True) and not res.get("failed") else (res.get("error") or "turn did not complete"),
               "worker": {"pid": os.getpid(), "turn_index": st["turns"], "agent_created_this_turn": created, "agent_inits_total": st["inits"]}}
        if timing.ENABLED:
            out["timing"] = {"events": list(timing.events), "pre_run_ms": round((t_run - t_in) * 1000, 1),
                             "turn_ms": round((time.perf_counter() - t_in) * 1000, 1)}
        return out

    for line in sys.stdin:
        if not line.strip():
            continue
        req = json.loads(line)
        op = req.get("op")
        if op == "shutdown":
            break
        if op == "ping":
            send({"id": req["id"], "result": {"pid": os.getpid(), "turns": st["turns"], "agent_inits": st["inits"]}})
            continue
        try:
            result = turn(req)
        except Exception as e:  # report, stay alive; the agent was dropped if the turn itself failed
            import traceback; traceback.print_exc()
            result = {"text": "", "tools": [], "error": f"{type(e).__name__}: {e}"}
        send({"id": req["id"], "result": result})


if __name__ == "__main__":
    main()
