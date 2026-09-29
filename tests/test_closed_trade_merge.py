"""Tests for _merge_closed_trades / _closed_trade_merge_key (2026-09-29,
explicit user instruction "Fix now" after a critical review of every trade
taken to date). The original (symbol, rounded exit_time_utc) dedup key let
a position resurrected from a stale state/open_positions.json snapshot on
every restart in a tight redeploy window get re-recorded as a "new" closed
trade each time it re-exited - POLICYBZR.NS was logged as 25 separate
trades on 2026-09-24 with an escalating, made-up pnl_inr, none of which
matched its actual entry/exit prices. The fix keys on
(symbol, IST date, entry_price, exit_reason, qty) instead - but exit_reason
and qty are load-bearing, not just entry_price: a staged-ladder exit
legitimately books T1/T2/trail as separate rows sharing the same symbol/
day/entry_price, and those real legs must never be collapsed."""
import main


def _trade(symbol="ABC.NS", exit_time_utc=1790238350.0, entry_price_native=100.0,
           exit_reason="stop_hit", qty=1.0, pnl_inr=-10.0):
    return {
        "symbol": symbol, "exit_time_utc": exit_time_utc, "entry_price_native": entry_price_native,
        "exit_reason": exit_reason, "qty": qty, "pnl_inr": pnl_inr,
    }


def test_resurrection_storm_duplicates_collapse_to_one():
    # Same symbol/day/entry_price/exit_reason/qty, only exit_time_utc and
    # the (corrupted) pnl_inr differ - exactly the POLICYBZR.NS pattern.
    durable = [
        _trade(symbol="POLICYBZR.NS", exit_time_utc=1790238350.38, entry_price_native=1357.9,
               exit_reason="stop_hit", qty=1.0, pnl_inr=0.0),
        _trade(symbol="POLICYBZR.NS", exit_time_utc=1790238550.18, entry_price_native=1357.9,
               exit_reason="stop_hit", qty=1.0, pnl_inr=-1282.3),
        _trade(symbol="POLICYBZR.NS", exit_time_utc=1790238746.77, entry_price_native=1357.9,
               exit_reason="stop_hit", qty=1.0, pnl_inr=-2564.6),
    ]
    merged = main._merge_closed_trades([], durable)
    assert len(merged) == 1


def test_staged_ladder_legs_are_never_collapsed():
    # Real INFY.NS example: three legs of ONE entry, same symbol/day/
    # entry_price, differing exit_reason (all qty=1.0 here, exit_reason
    # alone must be enough to keep them distinct).
    durable = [
        _trade(symbol="INFY.NS", exit_time_utc=1790577234.98, entry_price_native=991.6,
               exit_reason="staged_leg_T1", qty=1.0, pnl_inr=5.3),
        _trade(symbol="INFY.NS", exit_time_utc=1790577379.43, entry_price_native=991.6,
               exit_reason="staged_leg_T2", qty=1.0, pnl_inr=6.9),
        _trade(symbol="INFY.NS", exit_time_utc=1790582474.16, entry_price_native=991.6,
               exit_reason="stop_hit", qty=1.0, pnl_inr=12.5),
    ]
    merged = main._merge_closed_trades([], durable)
    assert len(merged) == 3
    assert {t["exit_reason"] for t in merged} == {"staged_leg_T1", "staged_leg_T2", "stop_hit"}


def test_staged_ladder_legs_with_same_reason_but_different_qty_stay_distinct():
    # Real PAISALO.NS example: a partial-exit-reallocation split into two
    # differently-sized remainders, both eventually target_hit - same
    # symbol/day/entry_price/exit_reason, but genuinely different qty.
    durable = [
        _trade(symbol="PAISALO.NS", exit_time_utc=1789028110.1, entry_price_native=79.79,
               exit_reason="partial_exit_reallocated", qty=1.872948, pnl_inr=0.0),
        _trade(symbol="PAISALO.NS", exit_time_utc=1789028151.4, entry_price_native=79.79,
               exit_reason="target_hit", qty=1.127052, pnl_inr=-4.89),
    ]
    merged = main._merge_closed_trades([], durable)
    assert len(merged) == 2


def test_true_near_instant_duplicate_collapses():
    # Real HINDUNILVR.NS example: same symbol/day/entry_price/exit_reason/
    # qty/pnl_inr, 0.4 seconds apart - a genuine duplicate write.
    durable = [
        _trade(symbol="HINDUNILVR.NS", exit_time_utc=1788508611.56, entry_price_native=1980.2,
               exit_reason="partial_exit_reallocated", qty=0.505, pnl_inr=0.05),
        _trade(symbol="HINDUNILVR.NS", exit_time_utc=1788508611.96, entry_price_native=1980.2,
               exit_reason="partial_exit_reallocated", qty=0.505, pnl_inr=0.05),
    ]
    merged = main._merge_closed_trades([], durable)
    assert len(merged) == 1


def test_same_entry_price_on_a_different_day_stays_distinct():
    durable = [
        _trade(symbol="ABC.NS", exit_time_utc=1790238350.0, entry_price_native=100.0),  # 2026-09-24 IST
        _trade(symbol="ABC.NS", exit_time_utc=1790324750.0, entry_price_native=100.0),  # next day, IST
    ]
    merged = main._merge_closed_trades([], durable)
    assert len(merged) == 2


def test_db_trades_win_over_durable_on_a_genuine_key_collision():
    durable = [_trade(pnl_inr=-999.0)]
    db = [_trade(pnl_inr=-10.0)]
    merged = main._merge_closed_trades(db, durable)
    assert len(merged) == 1
    assert merged[0]["pnl_inr"] == -10.0


def test_durable_only_and_db_only_entries_both_survive():
    durable = [_trade(symbol="DURABLE_ONLY.NS")]
    db = [_trade(symbol="DB_ONLY.NS")]
    merged = main._merge_closed_trades(db, durable)
    symbols = {t["symbol"] for t in merged}
    assert symbols == {"DURABLE_ONLY.NS", "DB_ONLY.NS"}
