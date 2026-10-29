"""B-1269 finding (1): ONE shared MCX expiry-roll picker (nse_fo_chain.pick_mcx_future)
used by both the live scan feed and the real/paper entry resolver; open positions
keep their own stored contract."""
import datetime as dt
import inspect

import kotak_live_feed as lf
import nse_fo_chain as nf

T = dt.date(2026, 10, 13)  # CRUDEOIL Oct contract expires 15 Oct 2026
NEAR, NEXT = dt.date(2026, 10, 15), dt.date(2026, 11, 17)


def _pick(*expiries, today=T):
    return nf.pick_mcx_future([(e, {"id": e.isoformat()}) for e in expiries], today=today)


def test_far_expiry_keeps_near_month():
    assert _pick(NEAR, NEXT, today=dt.date(2026, 10, 1))["id"] == NEAR.isoformat()


def test_within_roll_window_rolls():
    assert nf.MCX_ROLL_DAYS >= 1
    today = NEAR - dt.timedelta(days=nf.MCX_ROLL_DAYS)
    assert _pick(NEAR, NEXT, today=today)["id"] == NEXT.isoformat()


def test_one_day_outside_window_keeps_near():
    today = NEAR - dt.timedelta(days=nf.MCX_ROLL_DAYS + 1)
    assert _pick(NEAR, NEXT, today=today)["id"] == NEAR.isoformat()


def test_expiry_day_rolls():
    assert _pick(NEAR, NEXT, today=NEAR)["id"] == NEXT.isoformat()


def test_no_later_contract_keeps_near_month():
    assert _pick(NEAR, today=NEAR)["id"] == NEAR.isoformat()


def test_expired_contract_never_picked():
    assert _pick(NEAR, today=NEAR + dt.timedelta(days=1)) is None


def test_scan_and_order_paths_agree(monkeypatch):
    """Same contracts, same IST day -> the feed token and the order resolver pick the same contract."""
    today = nf.ist_today()
    exps = [today + dt.timedelta(days=1), today + dt.timedelta(days=34)]
    ist = dt.timezone(dt.timedelta(hours=5, minutes=30))
    rows = [{"pSymbolName": "CRUDEOIL", "pInstType": "FUTCOM", "pSymbol": str(i), "pTrdSymbol": f"CRUDEOIL{i}",
             "lLotSize": 100, "pExpiryDate": e.strftime("%d%b%Y"),
             "lExpiryDate": dt.datetime(e.year, e.month, e.day, 23, 30, tzinfo=ist).timestamp()}
            for i, e in enumerate(exps)]

    class _C:
        def search_scrip(self, **k):
            return rows

    feed_tok = lf._resolve_mcx_tokens(_C(), ["CL=F"])["CL=F"][1]
    monkeypatch.setattr(nf, "_fo_rows", lambda u, option_type=None: (rows, None))
    fut, err = nf.select_nse_future("CRUDEOIL")
    assert err is None and fut["instrument_token"] == feed_tok == "1"
    assert fut["dte"] == 34


def test_both_paths_route_through_shared_helper():
    assert "pick_mcx_future" in inspect.getsource(lf._resolve_mcx_tokens)
    assert "pick_mcx_future" in inspect.getsource(nf.select_nse_future)


def test_open_position_keeps_its_contract():
    """Exit and SL-sync act on the row's stored kotak_trading_symbol, never a re-resolved month."""
    import main
    for fn in ("_close_real_fo_option_leg", "_sync_real_fo_option_sl", "_maybe_place_real_fo_option_exit"):
        src = inspect.getsource(getattr(main, fn))
        assert "select_nse_future" not in src and "pick_mcx_future" not in src
    assert 'row["kotak_trading_symbol"]' in inspect.getsource(main._close_real_fo_option_leg)
    assert 'row["kotak_trading_symbol"]' in inspect.getsource(main._sync_real_fo_option_sl)
