"""B-1430 audit (2026-11-02 IST): every REAL entry sizing site uses real (Kotak) exposure only. deployed_notional()
counts paper-only rows (paper positions the real gate refused), so no function that places a real entry may read it;
the real-size helpers must give the same qty whether or not paper-only notional is open."""
import ast
import inspect
import os
import tempfile
import textwrap
from contextlib import closing

import main

# Every function that places a real entry order: long intraday (incl. chan_gap/chan_kalman long), short (incl. the
# chan_gap short batch, which mirrors via _maybe_place_real_short_entry), swing, swing-short, option strike / index
# mirror, straddle.
REAL_ENTRY_FUNCS = (
    "_maybe_place_real_entry", "_maybe_place_real_short_entry", "_maybe_place_real_swing_entry",
    "_maybe_place_real_swing_short_entry", "_real_fo_buy_contract", "_maybe_place_real_fo_option_entry",
    "_straddle_signal_core", "_real_intraday_qty_basis", "_real_qty_by_risk", "_real_swing_qty_by_risk",
)


def _calls(fn_name):
    tree = ast.parse(textwrap.dedent(inspect.getsource(getattr(main, fn_name))))
    return {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}


def test_no_real_entry_site_reads_deployed_notional():
    for name in REAL_ENTRY_FUNCS:
        assert "deployed_notional" not in _calls(name), f"{name} sizes real money off paper-only notional"


def test_intraday_entries_size_through_real_basis():
    for name in ("_maybe_place_real_entry", "_maybe_place_real_short_entry"):
        assert "_real_intraday_qty_basis" in _calls(name)
    for name in ("_maybe_place_real_swing_entry", "_maybe_place_real_swing_short_entry"):
        assert "_real_swing_qty_by_risk" in _calls(name)


def test_chan_gap_short_batch_mirrors_through_real_short_entry():
    assert "_maybe_place_real_short_entry" in _calls("_run_chan_gap_short_scan")


def test_real_qty_unchanged_by_paper_only_notional(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr(main, "DB_PATH", path)
    main.init_db()
    monkeypatch.setattr(main, "_refresh_real_capital_cache", lambda: None)
    monkeypatch.setattr(main, "get_scheduler_capital_inr", lambda: 9621.06)
    monkeypatch.setattr(main, "_swing_stopout_cluster", lambda conn: False)
    with closing(main.get_db()) as conn:
        before = (main._real_qty_by_risk(365.50, 383.03, 1.0, short=True),
                  main._real_qty_by_risk(365.50, 348.0, 1.0),
                  main._real_swing_qty_by_risk(conn, "X.NS", 365.50, 348.0),
                  main._real_swing_qty_by_risk(conn, "X.NS", 365.50, 383.03, short=True))
        today = main.ist_now().strftime("%Y-%m-%d")
        for tbl, status in (("signal_state", "long"), ("signal_state_short", "short")):
            conn.execute(
                f"INSERT INTO {tbl} (symbol, day, status, entry_price, stop_loss, initial_stop_loss, target, qty, "
                "entry_ts, fx_to_inr, interval) VALUES ('PAPERONLY.NS', ?, ?, 650.0, 640.0, 640.0, 700.0, 10, ?, 1.0, '5m')",
                (today, status, main.time.time()))
        conn.commit()
        assert main.deployed_notional(conn) > 6000
        after = (main._real_qty_by_risk(365.50, 383.03, 1.0, short=True),
                 main._real_qty_by_risk(365.50, 348.0, 1.0),
                 main._real_swing_qty_by_risk(conn, "X.NS", 365.50, 348.0),
                 main._real_swing_qty_by_risk(conn, "X.NS", 365.50, 383.03, short=True))
    assert before == after
    assert before[0] == 2  # DABUR short numbers
