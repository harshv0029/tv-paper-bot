"""Guard against the 2026-10-13 outage (B-892): a heavy synchronous scheduler job on the event loop froze the
whole HTTP server (Render 502). Boots the real app in a subprocess with the swing scan replaced by a 40s
blocking sleep and requires HTTP to answer anyway. Any future heavy sync work added to the scheduler tick
that blocks the loop makes this fail."""
import os
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_http_answers_while_swing_scan_blocks():
    port = _free_port()
    script = textwrap.dedent(f"""
        import time, uvicorn, main
        main._run_swing_scan = lambda conn: time.sleep(40)
        uvicorn.run(main.app, host="127.0.0.1", port={port}, ws="none", log_level="warning")
    """)
    env = dict(os.environ, DB_PATH=os.path.join(tempfile.mkdtemp(), "t.db"))
    for k in ("UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN"):
        env.pop(k, None)
    p = subprocess.Popen([sys.executable, "-c", script], cwd=ROOT, env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ok = False
        deadline = time.time() + 30
        while time.time() < deadline and p.poll() is None:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/strategy-viable-stack", timeout=3).read()
                ok = True
                break
            except Exception:
                time.sleep(1)
        assert ok, "server did not answer within 30s while the swing scan was blocking: event loop is blocked"
    finally:
        p.kill()
