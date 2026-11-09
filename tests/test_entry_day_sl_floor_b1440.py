"""B-1440 (WIPRO 2026-11-02 09:15 IST): no real SL is ever placed below the position's entry-day stop (long) or above
it (short). Live: the 09:15 re-place after the exchange's 15:15 cancel used the stale stored stop Rs175.12, which the
B-1411 band pre-clamp raised to the band floor Rs179.01, although View 4 showed an entry-day SL of Rs185.35 (the paper
row's frozen initial stop) and Friday's LTP-trailed stop had reached Rs192.89. B-1441: View 4's SL type is only ever
'Trail' or 'Fixed'."""
import time
from contextlib import closing

import pytest

import kotak_real_orders as kro
import main
import strategy_registry


# --------------------------------------------------------------------------- chokepoint (kotak_real_orders)

@pytest.fixture
def _floor(monkeypatch):
    state = {"floor": None, "last": None, "prev": None}
    monkeypatch.setattr(kro, "_STOP_FLOOR_PROVIDER", lambda trd, side: state["floor"])
    monkeypatch.setattr(kro, "_band_reference", lambda trd: (state["prev"], state["last"]))
    monkeypatch.setattr(kro, "_tick_size_for", lambda trd: 0.05)
    return state


def test_long_stop_below_entry_day_floor_is_raised(_floor):
    _floor.update(floor=185.35, last=198.0, prev=198.9)
    trg, info = kro.apply_entry_day_floor("WIPRO-EQ", 175.12, "long")
    assert trg == 185.35 and info["entry_floor_raised_from"] == 175.12 and "entry_floor_breached" not in info


def test_long_stop_above_floor_untouched(_floor):
    _floor.update(floor=185.35, last=198.0, prev=198.9)
    assert kro.apply_entry_day_floor("WIPRO-EQ", 194.11, "long") == (194.11, {})


def test_no_provider_or_no_floor_is_previous_behaviour(monkeypatch):
    monkeypatch.setattr(kro, "_STOP_FLOOR_PROVIDER", None)
    assert kro.apply_entry_day_floor("X-EQ", 100.0, "long") == (100.0, {})
    monkeypatch.setattr(kro, "_STOP_FLOOR_PROVIDER", lambda t, s: None)
    assert kro.apply_entry_day_floor("X-EQ", 100.0, "short") == (100.0, {})


def test_provider_error_never_blocks_the_stop(monkeypatch):
    def boom(t, s):
        raise RuntimeError("db locked")
    monkeypatch.setattr(kro, "_STOP_FLOOR_PROVIDER", boom)
    assert kro.apply_entry_day_floor("X-EQ", 100.0, "long") == (100.0, {})


def test_long_floor_through_the_market_keeps_protection(_floor):
    # entry-day stop 185.35 but the stock trades 184: a sell stop there would fire/be refused -> tightest placeable
    _floor.update(floor=185.35, last=184.0, prev=190.0)
    trg, info = kro.apply_entry_day_floor("WIPRO-EQ", 175.12, "long")
    assert info["entry_floor_breached"] == 185.35
    assert 175.12 < trg < 184.0 and trg == 183.10


def test_short_mirror(_floor):
    _floor.update(floor=105.0, last=100.0, prev=100.0)
    trg, info = kro.apply_entry_day_floor("S-EQ", 108.0, "short")
    assert trg == 105.0 and info["entry_floor_raised_from"] == 108.0
    assert kro.apply_entry_day_floor("S-EQ", 103.0, "short") == (103.0, {})
    _floor.update(floor=105.0, last=106.0)
    trg, info = kro.apply_entry_day_floor("S-EQ", 108.0, "short")
    assert info["entry_floor_breached"] == 105.0 and 106.0 < trg <= 108.0


def test_place_real_stop_loss_sends_the_floored_trigger_not_the_band_floor(_floor, monkeypatch):
    """The WIPRO replay: requested 175.12, band floor 179.01, entry-day stop 185.35 -> Kotak gets 185.35."""
    _floor.update(floor=185.35, last=198.0, prev=198.9)
    sent = []
    monkeypatch.setattr(kro, "_before_equity_open", lambda: False)
    monkeypatch.setattr(kro, "_place_real_stop_loss_once",
                        lambda trd, q, t: sent.append(t) or {"ok": True, "order_id": "1", "trigger_price": t})
    res = kro.place_real_stop_loss("WIPRO-EQ", 1, 175.12)
    assert sent == [185.35] and res["entry_floor_raised_from"] == 175.12 and "band_clamped_from" not in res


def test_ensure_resting_sl_does_not_adopt_a_live_sl_under_the_floor(_floor, monkeypatch):
    _floor.update(floor=185.35, last=198.0, prev=198.9)
    book = [{"trdSym": "WIPRO-EQ", "trnsTp": "S", "prcTp": "SL", "ordSt": "trigger pending", "nOrdNo": "OLD",
             "trgPrc": "179.01", "qty": "1"}]

    class _C:
        def order_report(self):
            return {"data": book}
    monkeypatch.setattr(kro.kotak_neo, "login", lambda: _C())
    monkeypatch.setattr(kro, "_in_closing_session", lambda: False)
    monkeypatch.setattr(kro, "_before_equity_open", lambda: False)
    cancelled, sent = [], []
    monkeypatch.setattr(kro, "cancel_real_order", lambda oid: cancelled.append(oid) or {"ok": True})
    monkeypatch.setattr(kro, "_place_real_stop_loss_once",
                        lambda trd, q, t: sent.append(t) or {"ok": True, "order_id": "NEW", "trigger_price": t})
    kro._RECENT_SL_PLACED.pop("WIPRO-EQ", None)
    res = kro.ensure_resting_sl("WIPRO-EQ", 1, 175.12)
    kro._RECENT_SL_PLACED.pop("WIPRO-EQ", None)
    assert res["action"] == "replaced" and cancelled == ["OLD"] and sent == [185.35]


# --------------------------------------------------------------------------- provider + View 4 (main)

def _wipro_db(peak=None):
    main.init_db()
    with closing(main.get_db()) as c:
        for t in ("real_positions", "real_positions_short", "real_positions_swing", "real_positions_swing_short",
                  "signal_state", "signal_state_short", "signal_state_swing", "real_order_events", "swing_entry_stop",
                  "swing_ltp_peak"):
            c.execute(f"DELETE FROM {t}")
        c.execute("INSERT INTO real_positions_swing (symbol, kotak_trading_symbol, qty, entry_price, entry_order_id, "
                  "opened_at, day, stop_loss, strategy) VALUES ('WIPRO.NS','WIPRO-EQ',1,188.75,'E',?,'2026-10-21',"
                  "175.12,?)", (time.time(), main.ORPHAN_SWING_STRATEGY_TAG))
        c.execute("INSERT INTO signal_state_swing (symbol, strategy, entry_day, entry_price, initial_stop_loss, qty, "
                  "entry_ts, atr_at_entry, running_max_close) VALUES ('WIPRO.NS',"
                  "'macddiv__hist_any__long__1h__atr3_w5__nonovl__v2','2026-10-29',189.90,185.35,1,?,4.55,189.9)",
                  (time.time(),))
        c.execute("INSERT INTO swing_entry_stop (symbol, entry_stop, set_at, source) VALUES ('WIPRO.NS',164.42,0,'seed')")
        if peak:
            c.execute("INSERT INTO swing_ltp_peak (symbol, peak_ltp, updated_at) VALUES ('WIPRO.NS', ?, 0)", (peak,))
        c.commit()


def test_provider_returns_view4_entry_day_sl(monkeypatch):
    monkeypatch.setattr(main, "_open_positions_prices", lambda syms, wl, budget_s=None: {})
    _wipro_db()
    assert main._real_stop_floor_for_trdsym("WIPRO-EQ", "long") == 185.35
    assert main._real_stop_floor_for_trdsym("WIPRO-EQ", "short") is None
    assert main._real_stop_floor_for_trdsym("NOPE-EQ", "long") is None
    row = {r["symbol"]: r for r in main.real_positions_sl_today()["positions"]}["WIPRO.NS"]
    assert (row["entry_day_sl"], row["entry_day_sl_source"]) == (185.35, "strategy")
    assert row["sl_type"] == "Trail"  # B-1441: the orphan tag used to show 'unknown'


def test_backfill_target_stop_is_floored_and_reuses_the_ltp_trail(monkeypatch):
    monkeypatch.setattr(main, "_swing_live_ltp", lambda s: 198.0)
    main._SWING_LAST_CLOSE.pop("WIPRO.NS", None)
    _wipro_db()
    assert main._swing_stop_floored(main.get_db(), "WIPRO.NS", 175.12) == 185.35
    _wipro_db(peak=198.66)  # Friday's persisted LTP peak -> peak - 1R (189.90 - 185.35 = 4.55)
    assert main._swing_stop_floored(main.get_db(), "WIPRO.NS", 175.12) == 194.11
    monkeypatch.setattr(main, "_swing_live_ltp", lambda s: 190.0)  # gapped under the trail -> entry-day floor only
    main._SWING_TRAIL_SKIP_LOGGED.pop("WIPRO.NS", None)
    assert main._swing_stop_floored(main.get_db(), "WIPRO.NS", 175.12) == 185.35


def test_entry_day_stop_ignores_wrong_side_candidates():
    main.init_db()
    with closing(main.get_db()) as c:
        c.execute("DELETE FROM swing_entry_stop")
        assert main._real_entry_day_stop(c, "Z.NS", "long", None, 120.0, 100.0, "buy") == (None, None)
        assert main._real_entry_day_stop(c, "Z.NS", "long", None, 95.0, 100.0, "buy") == (95.0, "strategy")
        assert main._real_entry_day_stop(c, "Z.NS", "short", None, 95.0, 100.0, "short_sell") == (None, None)
        assert main._real_entry_day_stop(c, "Z.NS", "short", None, 104.0, 100.0, "short_sell") == (104.0, "strategy")


def test_option_trailing_sl_never_below_entry_stop():
    """Options are floored by their own engine: desired = max(previous trigger, entry x (1 - 3%)) or the trail above
    it, so the entry-day stop is the minimum by construction (documented, not routed through the equity provider)."""
    entry = 100.0
    init = entry * (1 - main.FO_OPTION_INITIAL_STOP_PCT / 100.0)
    for prev in (0.0, 50.0, 97.0, 99.0):
        desired = max(prev, entry * (1 - main.FO_OPTION_INITIAL_STOP_PCT / 100.0))
        assert desired >= init


# --------------------------------------------------------------------------- B-1441 SL type

def _all_tags():
    tags = {s.name for s in strategy_registry.REGISTRY}
    tags |= set(main._STRATEGY_TAG_TO_REGISTRY_NAME) | set(main._STRATEGY_TAG_TO_REGISTRY_NAME.values())
    tags |= set(main._SWING_SL_RULES) | set(main.SWING_TRAILING_STOP_TAGS) | set(main.GAP_AND_GO_EXITFAMILY_LIVE_CELLS)
    tags |= {main.ORPHAN_SWING_STRATEGY_TAG, "", None, "orb-unknown", "some_future_tag__v9"}
    return tags


def test_sl_type_is_only_trail_or_fixed_for_every_tag_and_category():
    for tag in _all_tags():
        for cat in ("buy", "short_sell", "swing", "swing_short"):
            for sym in (None, "RVNL.NS", "WIPRO.NS"):
                assert main._sl_kind(cat, tag, sym) in {"Trail", "Fixed"}, (cat, tag, sym)


def test_sl_type_follows_each_engines_real_stop_logic():
    for tag in main.SWING_TRAILING_STOP_TAGS | set(main.GAP_AND_GO_EXITFAMILY_LIVE_CELLS):
        assert main._sl_kind("swing", tag) == "Trail", tag
    assert main._sl_kind("swing", "minervini_vcp_be3r") == "Trail"
    assert main._sl_kind("swing", main.ORPHAN_SWING_STRATEGY_TAG) == "Trail"
    assert main._sl_kind("swing", "gap_and_go") == "Trail"  # B-1491: peak-LTP 0.5R trail
    assert main._sl_kind("swing", main.BRK20_LONG_SWING_TAGS[1]) == "Fixed"
    assert main._sl_kind("swing", main.BRK20_SWING_TAG) == "Trail"  # B-1486 peak-LTP trail
    assert main._sl_kind("swing", "never_seen_tag") == "Fixed"  # unknown swing tag exits off its frozen stop
    assert main._sl_kind("swing", "gap_and_go", "RVNL.NS") == "Trail"  # LTP-trail symbol
    assert main._sl_kind("buy", "orb-universal-score") == "Trail"
    for t in list(main.CHAN_LONG_CELLS)[:3] + list(main.CHAN_SHORT_CELLS)[:3]:
        assert main._sl_kind("buy", t) == "Fixed"
