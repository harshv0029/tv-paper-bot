"""B-1622: SL snapshot files are named by the order book's trading day, not by a late run's clock."""
import json, os, subprocess, sys, textwrap
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "kotak_sl_snapshot.py"


def _run(tmp_path, orders):
    bindir = tmp_path / "bin"; bindir.mkdir()
    (tmp_path / "orders.json").write_text(json.dumps({"data": orders}))
    (tmp_path / "union.json").write_text(json.dumps({"rows": [{"kotak_trading_symbol": "UPL-EQ"}]}))
    curl = bindir / "curl"
    curl.write_text(textwrap.dedent(f"""\
        #!/bin/sh
        for a in "$@"; do last="$a"; done
        case "$last" in *tracked-union*) cat {tmp_path}/union.json;; *) cat {tmp_path}/orders.json;; esac
        """))
    curl.chmod(0o755)
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}")
    return subprocess.run([sys.executable, str(SCRIPT), "http://x", "tok"], cwd=tmp_path, env=env,
                          capture_output=True, text=True)


def test_file_named_by_order_day(tmp_path):
    orders = [{"trdSym": "UPL-EQ", "prcTp": "SL-M", "ordDtTm": "16-Nov-2026 09:16:02", "trgPrc": "600"}]
    r = _run(tmp_path, orders)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / "docs/sl_snapshots/2026-11-16.json").exists()
    assert json.loads((tmp_path / "docs/sl_snapshots/2026-11-16.json").read_text())["symbols"]["UPL-EQ"]["sl_order_count_today"] == 1
