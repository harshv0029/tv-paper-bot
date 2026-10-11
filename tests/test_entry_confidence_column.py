import strategy_registry as sr
import main


def _m(pf, w, n):
    return sr.Metrics(pfnet=pf, pfgross=pf, win_rate_pct=w, n_trades=n, universe="t")


def test_confidence_monotone_and_breakeven_is_50():
    lo = sr.edge_confidence_pct(_m(1.0, 40.0, 500))
    hi = sr.edge_confidence_pct(_m(1.1, 40.0, 500))
    more_n = sr.edge_confidence_pct(_m(1.1, 40.0, 5000))
    assert abs(lo - 50.0) < 0.5 and hi > lo and more_n > hi


def test_missing_inputs_give_none():
    assert sr.edge_confidence_pct(_m(1.5, None, 100)) is None


def test_trend_confidence_setting_removed():
    assert "min_entry_confidence_pct" not in main.RUNTIME_SETTINGS_META


def test_user_strategy_tag_roundtrip_and_mirrored():
    import main
    assert "user_strategy_tags" in main._GENERIC_MIRROR_TABLES
    import sqlite3
    c = sqlite3.connect(":memory:"); c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE user_strategy_tags (symbol TEXT PRIMARY KEY, strategy TEXT NOT NULL, tagged_at REAL NOT NULL)")
    c.execute("INSERT INTO user_strategy_tags VALUES ('NYKAA','mine',1)")
    c.execute("CREATE TABLE real_trades (strategy TEXT, kotak_trading_symbol TEXT, side TEXT, status TEXT, ts REAL)")
    assert main._recover_strategy_for_untracked_position(c, "NYKAA-EQ", "B") == "user: mine"
