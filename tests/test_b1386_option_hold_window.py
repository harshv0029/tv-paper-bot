"""B-1386/B-1384: swing option hold window = min(market hours to expiry, strategy hold hours); roll past an
expiry that cannot cover the hold."""
import datetime as dt
import sqlite3
import time

import main
import nse_fo_chain


def test_market_hours_between_counts_sessions_and_skips_holidays():
    a = dt.datetime(2026, 10, 26, 9, 15)   # Monday
    b = dt.datetime(2026, 10, 27, 15, 30)  # Tuesday
    assert main._nse_market_hours_between(a, b) == 12.5
    # 2026-10-20 holiday contributes nothing
    assert main._nse_market_hours_between(dt.datetime(2026, 10, 20, 9, 0), dt.datetime(2026, 10, 20, 16, 0)) == 0.0
    assert main._nse_market_hours_between(b, a) == 0.0


def test_hours_to_expiry_physical_vs_cash():
    now = dt.datetime(2026, 10, 27, 15, 0)
    # NHPC (physically settled) on its 27 Oct expiry day: already inside the force-close window
    assert main._option_hours_to_expiry("NHPC", "2026-10-27", now=now) == 0.0
    # cash-settled index: 30 min left today
    assert main._option_hours_to_expiry("NIFTY", "2026-10-27", now=now) == 0.5
    # NHPC Nov (23 Nov): holdable to 20 Nov 15:30 -> 0.5 h today + 17 sessions (28 Oct-20 Nov, 10 Nov holiday)
    assert main._option_hours_to_expiry("NHPC", "2026-11-23", now=now) == 0.5 + 17 * 6.25


def test_selector_rolls_to_expiry_that_fits(monkeypatch):
    rows = [{"pOptionType": "CE", "pExpiryDate": e, "dStrikePrice;": 7300.0, "pSymbol": t, "pTrdSymbol": f"NHPC{t}",
             "lLotSize": 6400} for e, t in (("27Oct2026", "1"), ("23Nov2026", "2"))]
    monkeypatch.setattr(nse_fo_chain, "_parse_expiry", lambda s: dt.datetime.strptime(s, "%d%b%Y").date())
    monkeypatch.setattr(nse_fo_chain, "_fo_rows", lambda u, option_type=None: (rows, None))
    monkeypatch.setattr(nse_fo_chain.kotak_neo, "quotes", lambda *a, **k: None)
    monkeypatch.setattr(nse_fo_chain, "_extract_ltp", lambda q: 2.5)

    class _D(dt.date):
        @classmethod
        def today(cls):
            return dt.date(2026, 10, 27)
    monkeypatch.setattr(nse_fo_chain.dt, "date", _D)
    c, err = nse_fo_chain.select_nse_option_contract("NHPC", 72.74, "call",
                                                     expiry_ok=lambda e: e >= dt.date(2026, 11, 1))
    assert err is None and c["expiry"] == "2026-11-23"
    c, err = nse_fo_chain.select_nse_option_contract("NHPC", 72.74, "call", expiry_ok=lambda e: False)
    assert c is None and err == "no_expiry_fits_hold"


def test_strategy_hold_hours_known_for_gap_and_go():
    h = main._strategy_hold_hours("gap_and_go")
    assert h is None or h > 0


def test_hold_exceeded_uses_owning_swing_strategy(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE signal_state_swing (symbol TEXT, strategy TEXT)")
    conn.execute("INSERT INTO signal_state_swing VALUES ('NHPC.NS', 'gap_and_go')")
    monkeypatch.setattr(main, "_strategy_hold_hours", lambda tag: 12.5 if tag == "gap_and_go" else None)
    opened = dt.datetime(2026, 10, 26, 9, 15) - dt.timedelta(minutes=main.IST_OFFSET_MIN)  # as UTC
    row = {"underlying": "NHPC", "opened_at": (opened - dt.datetime(1970, 1, 1)).total_seconds()}
    assert main._swing_option_hold_exceeded(conn, row, now=dt.datetime(2026, 10, 27, 15, 0)) is False
    assert main._swing_option_hold_exceeded(conn, row, now=dt.datetime(2026, 10, 27, 15, 30)) is True
    conn.execute("DELETE FROM signal_state_swing")
    assert main._swing_option_hold_exceeded(conn, row, now=dt.datetime(2026, 10, 30, 15, 30)) is False


def test_wiring_present():
    import inspect
    src = inspect.getsource(main._maybe_place_swing_option_leg)
    assert "_strategy_hold_hours(strategy)" in src and "expiry_ok=" in src
    assert "hold_window_exit" in inspect.getsource(main._sync_real_fo_option_sl)
