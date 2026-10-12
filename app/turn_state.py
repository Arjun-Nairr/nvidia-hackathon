"""Per-turn routing decision for the main agent's worker process. Set by app/worker.py before each turn, read by the Hermes plugin
hooks (app/hermes_plugin.py). Default (no route) is fail-closed: create_agent is not allowed."""
route = None
request_id = None   # the backend's id of the manual chat request being answered (set by app/worker.py each turn; never model-supplied)
run_id = None       # the research run opened lazily for (agent, request) by app/research.py during this turn
ad_run_id = None    # the Facebook ad-research run opened lazily for (agent, request) by app/ads.py during this turn
vision_probe = None   # set by app/worker.py each turn: callable -> "image_part_sent" | "text_fallback" | "unknown" for the live agent's provider/model


def image_delivery():
    """How an image in a tool result will reach the active model, as Hermes itself decides it. Anything not positively known is 'unknown'."""
    try:
        v = vision_probe() if vision_probe else "unknown"
    except Exception:
        v = "unknown"
    return v if v in ("image_part_sent", "text_fallback") else "unknown"


def create_allowed(role=None):
    """create_agent is allowed only for a request the backend routed to a creation outcome, and (when a role is asked about) only for the role it
    classified. The classifier-off test seam carries no role, so it does not restrict which supported role is requested."""
    if not (route and route.get("allow_create_agent")):
        return False
    routed = route.get("role")
    return role is None or routed is None or role == routed
