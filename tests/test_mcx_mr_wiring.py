"""B-1270: MCX cells are gated by the main-calling replay (`_mr`) rows; donchian cl (0.820) is unwired; entry never leaves a stop-less position unretried."""
import os
import tempfile
from contextlib import closing

import main
import strategy_registry as sr

DON = "donchian_breakout__cl__long__1d__atrnone__v1"
CELLS = {"sma_crossover__gc__long__1d__atrnone__v1": 2.287, "supertrend__gc__long__1d__atrnone__v1": 2.346,
         "bollinger_mean_reversion__si__long__1d__atrnone__v1": 2.496, "supertrend__cl__long__1d__atrnone__v1": 1.432,
         "rsi_reversal__ng__long__1d__atrnone__v1": 1.525, "bollinger_mean_reversion__ng__short__1d__atrnone__v1": 1.881,
         "keltner_channel_breakout__ng__short__1d__atrnone__v1": 1.500}


def _row(name):
    return next((x for x in sr.REGISTRY if x.name == name), None)


def test_eight_mr_rows_registered_and_research_rows_kept():
    for t, p in list(CELLS.items()) + [(DON, 0.820)]:
        mr = _row(main._mcx_replay_row_name(t))
        assert mr is not None and abs(mr.metrics.pfnet - p) < 1e-9
        assert _row(t) is not None  # research row never deleted/overwritten
        if t != DON:  # unwired: no mapping at all, so the gate fails closed
            assert main._STRATEGY_TAG_TO_REGISTRY_NAME[t] == mr.name


def test_donchian_unwired_but_registered_and_gate_closed():
    assert DON not in {c[0] for c in main._MCX_DAILY_CELLS}
    assert not main._is_strategy_viable_for_real_money(DON, check_switch=False)
    assert set(CELLS) <= {c[0] for c in main._MCX_DAILY_CELLS}
    for t in CELLS:
        assert main._is_strategy_viable_for_real_money(t, check_switch=False)


def _patch(monkeypatch, statuses, calls, closed):
    import kotak_real_fo_orders as kfo
    monkeypatch.setattr(main, "_day_open_capital_inr", lambda c: 1e9)
    monkeypatch.setattr(main, "_real_fo_today_spent_inr", lambda c: 0.0)
    monkeypatch.setattr(main, "_real_loss_budget", lambda c: {"ok": True, "real_pnl_today": 0.0, "detail": ""})
    monkeypatch.setattr(main, "_log_real_fo_attempt", lambda *a, **k: None)
    monkeypatch.setattr(main.time, "sleep", lambda s: None)
    # B-1418: with sleep stubbed, the 60 s failed-SL retry window spun flat out on a wall clock and printed millions of
    # lines once the status list ran out (filled the disk twice on 2026-10-29). These tests check the unwind decision only.
    monkeypatch.setattr(main, "FO_ENTRY_SL_FAIL_RETRY_WINDOW_S", 0.0)
    monkeypatch.setattr(kfo, "check_margin_affordable", lambda **k: {"ok": True})
    monkeypatch.setattr(kfo, "place_real_fo_entry", lambda *a, **k: {"ok": True, "order_id": "E1"})
    it = iter(statuses)

    def sync(conn, leg, reason=""):
        calls.append(reason)
        return next(it)
    monkeypatch.setattr(main, "_sync_real_fo_option_sl", sync)
    monkeypatch.setattr(main, "_close_real_fo_option_leg", lambda conn, row, why: closed.append(why))


def _buy():
    fd, p = tempfile.mkstemp(suffix=".db"); os.close(fd)
    main.DB_PATH = p; main.init_db()
    c = {"kotak_trading_symbol": "GOLDM26NOVFUT", "instrument_token": "1", "exchange_segment": "mcx_fo",
         "expiry": "2099-01-01", "strike": 100000, "lot_size": 100, "premium": 100.0}
    with closing(main.get_db()) as conn:
        main._real_fo_buy_contract(conn, "GOLDM:CALL", "GOLDM", c, "t", "single_leg_mcx_t", "r")


def test_entry_retries_sl_while_position_invisible_then_places(monkeypatch):
    calls, closed = [], []
    _patch(monkeypatch, ["fresh_entry_awaiting_position", "fresh_entry_awaiting_position", "placed"], calls, closed)
    _buy()
    assert len(calls) == 3 and not closed


def test_entry_still_invisible_not_unwound_and_failed_sl_unwinds(monkeypatch):
    calls, closed = [], []
    _patch(monkeypatch, ["fresh_entry_awaiting_position"] * (main.FO_ENTRY_SL_RETRIES + 1), calls, closed)
    _buy()
    assert len(calls) == main.FO_ENTRY_SL_RETRIES + 1 and not closed  # cannot unwind an unseen position; tick + 180s cut back it up
    calls, closed = [], []
    _patch(monkeypatch, ["fresh_entry_awaiting_position", "sl_failed"], calls, closed)
    _buy()
    assert len(closed) == 1 and "could not be placed" in closed[0]
