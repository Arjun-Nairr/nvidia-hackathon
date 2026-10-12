"""UI/API test server with a FAKE run_turn (no Hermes, no model). Run it only from a COPY of the project: it seeds two fake agents into
that copy's runtime/app.db. Triggers in the message text: SLOW (sleeps 6 s), BOOM (raises inside the backend), ERR (agent-level error),
CREATE (fake create_agent + read_company_context activity), anything else echoes. Every executed turn is appended to runtime/fake_calls.log.
Run: venv python tests/ui_test_server.py [port]"""
import json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if os.environ.get("UI_TEST_I_AM_A_COPY") != "1":
    sys.exit("Refusing to run: set UI_TEST_I_AM_A_COPY=1 and run from a COPY of the project.")
sys.path.insert(0, str(ROOT))
from app import core, server

LOG = ROOT / "runtime" / "fake_calls.log"


def fake_run_turn(agent_id, message, timeout=300, conv_override=None, route=None, request_id=None):
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"agent": agent_id, "message": message[:60], "t": time.time()}) + "\n")
    if "SLOW" in message:
        time.sleep(6)
    if "BOOM" in message:
        raise RuntimeError("simulated backend crash")
    if "ERR" in message:
        return {"text": "", "tools": [], "error": "simulated worker failure"}
    tools = []
    if "CREATE" in message:
        tools = [{"name": "read_company_context", "input": "{}", "id": "c0"}, {"name": "read_company_context", "output": '{"ok": true}', "id": "c0"},
                 {"name": "create_agent", "input": '{"role": "market_analysis"}', "id": "c1"},
                 {"name": "create_agent", "output": '{"ok": false, "error": "Unsupported role", "code": "unsupported_role"}', "id": "c1"}]
    time.sleep(0.2)
    return {"text": f"echo from {agent_id}: {message[:40]}", "tools": tools, "error": None}


core.run_turn = fake_run_turn
(ROOT / "runtime").mkdir(exist_ok=True)
with core.db() as d:
    for aid, name in (("spec-a", "Spec A"), ("spec-b", "Spec B")):
        if not d.execute("SELECT 1 FROM agents WHERE agent_id=?", (aid,)).fetchone():
            d.execute("INSERT INTO agents VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (aid, name, "market_analysis", "northloom", "obj", "instr", '["brand"]', '[{"name":"s","content":"c"}]',
                       '["read_company_context"]', '[{"action":"a","requirement":"none"}]', "conv-" + aid, "idle", time.time()))
server.main(int(sys.argv[1]) if len(sys.argv) > 1 else 8810)
