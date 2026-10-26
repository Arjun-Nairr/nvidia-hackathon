"""TEST-ONLY helper for suites written before one-specialist-per-role: while a second agent of a role is created, the existing same-role registry rows carry a temporary label,
so those older tests can still build two agents of one role (granted vs ungranted comparisons). The product code has no such bypass and tests/specialist_config_test.py proves the rule."""
import contextlib, sqlite3
from pathlib import Path


@contextlib.contextmanager
def second_of_role(root, role):
    if not role:
        yield
        return
    db = Path(root) / "runtime" / "app.db"
    with sqlite3.connect(db, timeout=30) as c:
        held = [r[0] for r in c.execute("SELECT agent_id FROM agents WHERE role=?", (role,))]
        c.execute("UPDATE agents SET role=role||'~held' WHERE role=?", (role,))
    try:
        yield
    finally:
        with sqlite3.connect(db, timeout=30) as c:
            c.executemany("UPDATE agents SET role=? WHERE agent_id=?", [(role, a) for a in held])
