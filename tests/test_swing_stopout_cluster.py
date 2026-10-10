import json
import sqlite3
import main


def _conn(pnls):
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE trades (ts REAL, symbol TEXT, action TEXT, qty REAL, price REAL, fx_to_inr REAL, strategy TEXT, raw_payload TEXT)")
    for i, p in enumerate(pnls):
        c.execute("INSERT INTO trades VALUES (?, 'X', 'sell', 1, 1, 1, ?, ?)", (i, main.SWING_STRATEGY_TAG, json.dumps({"gross_pnl_native": p})))
    return c


def test_cluster_true_after_three_losers_in_five():
    assert main._swing_stopout_cluster(_conn([1, -1, -2, 3, -4])) is True


def test_cluster_false_with_two_losers_or_short_history():
    assert main._swing_stopout_cluster(_conn([1, -1, 2, 3, -4])) is False
    assert main._swing_stopout_cluster(_conn([-1, -1, -2])) is False
