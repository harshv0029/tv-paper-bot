"""Tests for swing-position dashboard visibility and reconcile safety
(2026-09-30, explicit user finding after an audit of swing/futures/
options auto-heal coverage: "Have you check auto heal for Swing, Future,
Options... You are not understanding it").

Two gaps closed here, both real_positions_swing's exact mirror of bugs
already found and fixed for real_positions_short earlier the same
session:

1. get_real_open_positions() never SELECTed from real_positions_swing at
   all - a real swing position fell through to the "kotak_untracked"
   fallback with no strategy shown, even though the swing entry flow
   already sets one.
2. _reconcile_real_positions_core's `our_trdsyms` exclusion set (used to
   decide what's "untracked" and thus eligible for the scheduled
   adopt="*" job) never excluded swing's own trading symbols - since
   swing trades the same nse_cm segment as intraday equity, an orphaned
   swing position risked being auto-adopted into the WRONG table
   (real_positions, the intraday one) by the unattended cron job.

Swing auto-adopt itself (computing a correct ATR-based stop for a
position with no known paper origin) is explicitly NOT built here - see
the reconcile function's own comment for why that's scoped out
separately from the misadoption-prevention fix.

Run: pytest tests/test_swing_position_visibility_and_reconcile.py -v
"""
import os
import tempfile
from contextlib import closing
from unittest.mock import patch

import main


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    return path


def _insert_real_position_swing(conn, symbol="RELIANCE.NS", entry_price=2500.0, qty=2,
                                 stop_loss=2400.0, sl_order_id="SL-1", strategy="orb-swing-gap-and-go"):
    conn.execute(
        "INSERT INTO real_positions_swing (symbol, kotak_trading_symbol, qty, entry_price, "
        "entry_order_id, opened_at, day, stop_loss, sl_order_id, sl_trigger_price, strategy) VALUES "
        "(?, ?, ?, ?, 'E1', ?, ?, ?, ?, ?, ?)",
        (symbol, symbol.replace(".NS", "-EQ"), qty, entry_price,
         main.time.time(), main.ist_now().strftime("%Y-%m-%d"), stop_loss, sl_order_id, stop_loss, strategy),
    )
    conn.commit()


# ---- get_real_open_positions: swing visibility -----------------------------

def test_swing_position_appears_with_its_own_strategy_and_side():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_real_position_swing(conn)
    with patch("main.fetch_ohlc", side_effect=Exception("no network in test")):
        result = main.get_real_open_positions()
    assert result["count"] == 1
    pos = result["open_real_positions"][0]
    assert pos["symbol"] == "RELIANCE.NS"
    assert pos["strategy"] == "orb-swing-gap-and-go"
    assert pos["side"] == "swing"
    assert pos["source"] == "bot_tracked"
    assert pos["target_price"] is None
    assert pos["target_status"] is None


def test_swing_position_pnl_uses_standard_long_math():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_real_position_swing(conn, entry_price=2500.0, qty=2)
    import pandas as pd
    fake_df = pd.DataFrame({"Close": [2550.0]})
    with patch("main.fetch_ohlc", return_value=fake_df):
        result = main.get_real_open_positions()
    pos = result["open_real_positions"][0]
    assert pos["current_price"] == 2550.0
    assert pos["unrealized_pnl_inr"] == 100.0  # (2550-2500)*2


def test_swing_position_not_duplicated_as_kotak_untracked():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_real_position_swing(conn)
    fake_kotak_neo = __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock()
    fake_kotak_neo.positions.return_value = {"data": [
        {"exSeg": "nse_cm", "trdSym": "RELIANCE-EQ", "flBuyQty": "2", "flSellQty": "0", "buyAmt": "5000.0"},
    ]}
    with patch.dict("sys.modules", {"kotak_neo": fake_kotak_neo}), \
         patch("main.fetch_ohlc", side_effect=Exception("no network")):
        result = main.get_real_open_positions()
    assert result["count"] == 1
    assert result["open_real_positions"][0]["source"] == "bot_tracked"


# ---- _reconcile_real_positions_core: swing misadoption prevention ---------

def _still_open_long(trd_sym="RELIANCE-EQ", qty="2"):
    return {"data": [{"exSeg": "nse_cm", "trdSym": trd_sym, "flBuyQty": qty, "flSellQty": "0",
                       "buyAmt": str(2500.0 * float(qty))}]}


def test_swing_position_is_excluded_from_untracked_so_it_cannot_be_misadopted():
    # The core bug: without the exclusion fix, this exact scenario would
    # have listed RELIANCE-EQ in `untracked` and, on a scheduled adopt="*"
    # run, swept it into `real_positions` (the WRONG, intraday table).
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_real_position_swing(conn)
    with patch("kotak_neo.positions", return_value=_still_open_long()), \
         patch("kotak_neo.limits", return_value={"Net": "1000"}), \
         patch("kotak_neo.order_report", return_value={"data": []}):
        result = main._reconcile_real_positions_core(adopt="*")
    assert result["untracked_open_positions_count"] == 0
    assert result["adopted_count"] == 0
    with closing(main.get_db()) as conn:
        # Still only tracked in real_positions_swing - never copied into
        # real_positions by the adopt pass.
        assert conn.execute("SELECT 1 FROM real_positions WHERE symbol = 'RELIANCE.NS'").fetchone() is None
        assert conn.execute("SELECT 1 FROM real_positions_swing WHERE symbol = 'RELIANCE.NS'").fetchone() is not None


def test_swing_qty_is_corrected_against_kotaks_own_truth():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_real_position_swing(conn, qty=3)
    with patch("kotak_neo.positions", return_value=_still_open_long(qty="2")), \
         patch("kotak_neo.limits", return_value={"Net": "1000"}), \
         patch("kotak_neo.order_report", return_value={"data": []}):
        result = main._reconcile_real_positions_core(adopt=None)
    assert result["qty_corrected_count"] == 1
    with closing(main.get_db()) as conn:
        row = conn.execute("SELECT qty FROM real_positions_swing WHERE symbol = 'RELIANCE.NS'").fetchone()
    assert row["qty"] == 2


def test_swing_ghost_position_is_removed_when_kotak_shows_it_closed():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_real_position_swing(conn)
    with patch("kotak_neo.positions", return_value={"data": []}), \
         patch("kotak_neo.limits", return_value={"Net": "1000"}), \
         patch("kotak_neo.order_report", return_value={"data": []}):
        result = main._reconcile_real_positions_core(adopt=None)
    assert result["removed_ghost_count"] == 1
    with closing(main.get_db()) as conn:
        assert conn.execute("SELECT 1 FROM real_positions_swing WHERE symbol = 'RELIANCE.NS'").fetchone() is None


def test_swing_position_with_a_sign_mismatch_is_treated_as_a_ghost():
    # Kotak shows this trading symbol as a SHORT now, not the long swing
    # position this app tracks - same "sign must match" discipline as the
    # long/short mirrors, not silently corrected to a nonsense long qty.
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_real_position_swing(conn)
    with patch("kotak_neo.positions", return_value={"data": [
        {"exSeg": "nse_cm", "trdSym": "RELIANCE-EQ", "flBuyQty": "0", "flSellQty": "2"},
    ]}), \
         patch("kotak_neo.limits", return_value={"Net": "1000"}), \
         patch("kotak_neo.order_report", return_value={"data": []}):
        result = main._reconcile_real_positions_core(adopt=None)
    assert result["removed_ghost_count"] == 1
    with closing(main.get_db()) as conn:
        assert conn.execute("SELECT 1 FROM real_positions_swing WHERE symbol = 'RELIANCE.NS'").fetchone() is None
