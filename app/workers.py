"""Backend-owned Hermes workers: one process per active profile, started lazily on first use, reused for later turns,
turns serialized per agent, all stopped when the server exits. Local only: no queue, pool framework or remote services."""
import atexit, json, queue, subprocess, threading, time
from app import core, logbook


class WorkerError(Exception):
    def __init__(self, msg, sent=True):
        super().__init__(msg)
        self.sent = sent  # False: the request never reached the worker (safe to retry on a fresh one)


class Worker:
    def __init__(self, agent_id, sig, env):
        self.agent_id, self.sig, self.turns, self.started = agent_id, sig, 0, time.time()
        self.lock, self.q, self.next_id, self.ready = threading.Lock(), queue.Queue(), 1, None
        log_dir = core.RUNTIME / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log = log_dir / f"worker-{agent_id}.log"
        if log.exists() and log.stat().st_size > 1_000_000:
            log.write_text("", encoding="utf-8")
        self.proc = subprocess.Popen([core.HERMES_PY, "-m", "app.worker"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=open(log, "ab"), cwd=str(core.ROOT), env={**env, "ECOM_SPAWN_WALL": repr(time.time())},
                                     text=True, encoding="utf-8", bufsize=1)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for raw in self.proc.stdout:
            try:
                obj = json.loads(raw)
            except ValueError:
                continue  # protocol lines are JSON; anything else is ignored
            if obj.get("event") == "ready":
                self.ready = obj
            elif obj.get("event") == "log":   # execution-logbook rows from the worker's hooks (best effort; never a turn result)
                logbook.accept(obj.get("rows"))
            else:
                self.q.put(obj)
        self.q.put(None)  # EOF: worker exited

    def alive(self):
        return self.proc.poll() is None

    def request(self, req, timeout):
        with self.lock:
            while not self.q.empty():  # drop anything left over from an abandoned request
                self.q.get_nowait()
            rid, self.next_id = self.next_id, self.next_id + 1
            try:
                self.proc.stdin.write(json.dumps({**req, "id": rid}) + "\n")
                self.proc.stdin.flush()
            except (OSError, ValueError) as e:
                self.stop()
                raise WorkerError(f"worker was not reachable ({type(e).__name__})", sent=False)
            end = time.time() + timeout
            while True:
                try:
                    obj = self.q.get(timeout=max(0.1, end - time.time()))
                except queue.Empty:
                    self.stop()
                    raise WorkerError(f"The turn timed out after {timeout:.0f}s and its worker was stopped. The next message starts a fresh "
                                      "worker from saved history; the interrupted turn is NOT replayed (it may have partly run).")
                if obj is None:
                    code = self.proc.poll()
                    raise WorkerError(f"The Hermes worker exited during the turn (exit code {code}). The next message starts a fresh "
                                      "worker from saved history; the interrupted turn is NOT replayed (it may have partly run).")
                if obj.get("id") == rid:
                    self.turns += 1
                    return obj["result"]

    def stop(self):
        try:
            if self.alive():
                try:
                    self.proc.stdin.write('{"op":"shutdown"}\n'); self.proc.stdin.flush()
                    self.proc.wait(timeout=3)
                except Exception:
                    pass
            if self.alive():
                self.proc.kill()
                self.proc.wait(timeout=5)
        except Exception:
            pass


_workers, _mgr = {}, threading.Lock()


def _get(agent_id, sig, env):
    with _mgr:
        w = _workers.get(agent_id)
        if w and (not w.alive() or w.sig != sig):   # died while idle, or provider/model/toolsets/conversation changed
            w.stop()
            w = None
        spawned = w is None
        if spawned:
            core.sync_profiles()  # make profile config.yaml match the selected provider/model before the new worker reads it
            w = _workers[agent_id] = Worker(agent_id, sig, env)
        return w, spawned


def run(agent_id, sig, env, req, timeout):
    """Send one turn to the agent's worker (spawning it if needed). Returns (result, spawned). Raises WorkerError."""
    w, spawned = _get(agent_id, sig, env)
    try:
        return w.request(req, timeout), spawned
    except WorkerError as e:
        if e.sent:
            raise
        w, spawned = _get(agent_id, sig, env)   # request never left: safe to retry once on a replacement
        return w.request(req, timeout), True


def status():
    with _mgr:
        return [{"agent_id": a, "pid": w.proc.pid, "alive": w.alive(), "turns": w.turns, "age_s": round(time.time() - w.started),
                 "provider": w.sig[0], "model": w.sig[1]} for a, w in _workers.items()]


def stop_all():
    with _mgr:
        for w in list(_workers.values()):
            w.stop()
        _workers.clear()


atexit.register(stop_all)
