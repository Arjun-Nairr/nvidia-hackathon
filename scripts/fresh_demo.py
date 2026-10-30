"""Start a FRESH demo (run by fresh_demo.bat before it starts the app the same way run.bat does).
Uses the SAME reset as the in-app Restart demo (app/demo_reset.py): the current progress is archived under runtime/demo_archives/ and cleared; keys, the project login,
catalogue/photos, model settings and paid accounting are kept. The launcher first decides between THREE outcomes for the app's port:
  running    this app answered its status request: the reset goes through that app's Restart demo API (its busy checks and worker shutdown apply); no second app is started.
  absent     the connection was DEFINITELY refused: nothing listens, so the reset runs here. The port is held exclusively during the reset, so an app cannot start on it meanwhile.
  uncertain  a timeout, a reset connection, an HTTP error or a response that is not this app's status: nothing is changed (an app may be running and busy).
Nothing is ever stopped or killed. The ECOM_* settings of this window pass through unchanged.
Exit codes: 0 = reset done, start the app; 2 = nothing more to do (handled by the running app, or cancelled); 1 = failed or uncertain (nothing was changed, or the demo was not restarted).
  python scripts/fresh_demo.py [--yes] [--port 8800]"""
import argparse, json, os, socket, sys, urllib.error, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
QUESTION = "Restart onboarding and clear current demo progress?"
APP_KEYS = {"provider", "model", "company", "classifier", "secrets_file"}   # what this app's /api/status answers with


def probe(port):
    """-> ("running" | "absent" | "uncertain", why). Only a refused connection or this app's own status answer is definite."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=5) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        return "uncertain", f"something on the port answered HTTP {e.code}"
    except urllib.error.URLError as e:
        if isinstance(e.reason, ConnectionRefusedError):
            return "absent", "connection refused"
        return "uncertain", f"the status request failed ({type(e.reason).__name__})"
    except ConnectionRefusedError:
        return "absent", "connection refused"
    except OSError as e:   # timeouts and reset connections: the app may well be running
        return "uncertain", f"the status request failed ({type(e).__name__})"
    try:
        data = json.loads(body)
    except ValueError:
        return "uncertain", "the answer is not this app's status"
    if isinstance(data, dict) and APP_KEYS <= set(data):
        return "running", "this app answered"
    return "uncertain", "the answer is not this app's status"


def claim_port(port):
    """Hold the app's port exclusively for the length of an offline reset: an app that starts meanwhile fails to bind and stops. -> the socket, or None when the port is not free."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if os.name == "nt":
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)   # Windows lets a SO_REUSEADDR server bind next to a plain socket, so be exclusive
        s.bind(("127.0.0.1", port))
    except OSError:
        s.close()
        return None
    return s


def ask(question, yes):
    if yes:
        return True
    try:
        return input(question + " [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def settings():
    """What the new demo will run with, so a missing scope or catalogue setting is visible instead of silently defaulted."""
    out = []
    for k, default in (("ECOM_CATALOGUE_FILE", "the built-in demo catalogue"), ("ECOM_IMAGE_DIRS", "the built-in demo photos"),
                       ("ECOM_RESEARCH_SCOPE", "scope 'default'"), ("ECOM_ADS_SCOPE", "scope 'default'"), ("ECOM_FLYER_SCOPE", "scope 'default'")):
        v = os.environ.get(k)
        out.append(f"  {k} = {v}" if v else f"  {k} is not set in this window: {default} will be used")
    return "\n".join(out) + "\nPaid allowances are never renewed by a restart: a spent scope stays spent."


def via_running_app(port, yes):
    print(f"The demo app is already running at http://127.0.0.1:{port}. A second copy is not started and nothing is stopped.")
    if not ask(QUESTION + " (through the running app)", yes):
        print("Nothing changed. You can also use Restart demo in the app's options menu.")
        return 2
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/demo/reset", data=json.dumps({"confirm": True}).encode(), headers={"Content-Type": "application/json"})
    try:
        body = json.loads(urllib.request.urlopen(req, timeout=900).read())
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read() or b"{}")
        except ValueError:
            body = {"error": f"HTTP {e.code}"}
    except Exception as e:
        print(f"The running app did not answer the restart request ({type(e).__name__}), so it may or may not have restarted. Reload the app in your browser to see; "
              "do not start another copy. Use Restart demo in its options menu if it is still at the old demo.")
        return 1
    if body.get("ok"):
        print(f"Demo restarted. The previous progress is archived in {body['archive']}. Reload the page in your browser.")
        return 2
    print("The demo was NOT restarted: " + str(body.get("error")))
    return 1


def main(argv=None):
    a = argparse.ArgumentParser(description="Restart onboarding and archive the current demo progress, then start the app.")
    a.add_argument("--yes", action="store_true", help="do not ask (tests)")
    a.add_argument("--port", type=int, default=8800, help="the app's port (tests only; fresh_demo.bat always starts the app on 8800)")
    args = a.parse_args(argv)
    state, why = probe(args.port)
    if state == "running":
        return via_running_app(args.port, args.yes)
    if state == "uncertain":
        print(f"Could not tell whether the demo app is running on port {args.port} ({why}). Nothing was changed. "
              "If the app is open, use Restart demo in its options menu; otherwise wait a moment and run fresh_demo.bat again.")
        return 1
    print("Fresh demo. The new demo will start with:\n" + settings())
    if not ask(QUESTION, args.yes):
        print("Nothing changed. To continue the current demo, use run.bat.")
        return 2
    held = claim_port(args.port)
    if held is None:   # the port was free a moment ago: an app is starting right now
        print(f"Port {args.port} was taken just now (an app may be starting). Nothing was changed. Wait for it to open and use Restart demo in its options menu, or run fresh_demo.bat again.")
        return 1
    try:
        from app import demo_reset
        r = demo_reset.reset()   # nothing listens on the port and an app cannot start on it while it is held, so no worker of it is running
    finally:
        held.close()   # released just before fresh_demo.bat starts the app
    if not r["ok"]:
        print("The demo was NOT restarted: " + r["error"])
        return 1
    print(f"Previous progress archived in {r['archive']}. Starting the app at the website step...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
