"""B-1269: MCX contract ROLL. Expiring contract skipped within MCX_ROLL_DAYS; open positions untouched."""
import datetime as dt
import time
import pytest
import kotak_live_feed as lf
import nse_fo_chain as nf

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
DAY = 86400


def _exp_ts(days):
    d = (dt.datetime.now(IST) + dt.timedelta(days=days)).date()
    return dt.datetime(d.year, d.month, d.day, 23, 30, tzinfo=IST).timestamp()


class _C:
    def __init__(self, rows): self.rows = rows
    def search_scrip(self, **k): return self.rows


def _rows(*days):
    return [{"pSymbolName": "CRUDEOIL", "pInstType": "FUTCOM", "pSymbol": str(100 + d), "lExpiryDate": _exp_ts(d)} for d in days]


def _tok(days_list):
    return lf._resolve_mcx_tokens(_C(_rows(*days_list)), ["CL=F"])["CL=F"][1]


def test_normal_case_unchanged():
    assert _tok([10, 40]) == "110"


def test_roll_three_days_out_not_rolled():
    assert _tok([3, 33]) == "103"


def test_roll_two_days_before():
    assert _tok([2, 32]) == "132"


def test_roll_on_expiry_day():
    assert _tok([0, 30]) == "130"


def test_only_expiring_contract_falls_back():
    assert _tok([0]) == "100"


def _fut_rows(days, inst="FUTCOM"):
    t = dt.date.today()
    return [{"pInstType": inst, "pExpiryDate": (t + dt.timedelta(days=d)).strftime("%d%b%Y"), "pSymbol": str(d),
             "pTrdSymbol": f"X{d}", "lLotSize": 10} for d in days]


@pytest.mark.parametrize("days,want", [([0, 30], 30), ([2, 30], 30), ([5, 30], 5)])
def test_select_future_rolls_mcx(monkeypatch, days, want):
    monkeypatch.setattr(nf, "_fo_rows", lambda u, option_type=None: (_fut_rows(days), None))
    fut, _ = nf.select_nse_future("CRUDEOILM")
    assert fut["dte"] == want


def test_nse_future_not_rolled(monkeypatch):
    monkeypatch.setattr(nf, "_fo_rows", lambda u, option_type=None: (_fut_rows([0, 30], "FUTIDX"), None))
    fut, _ = nf.select_nse_future("NIFTY")
    assert fut["dte"] == 0


def test_open_position_exit_does_not_reresolve():
    """Exit/SL paths use the stored trading symbol; select_nse_future is only an entry/scan resolver."""
    import inspect, main
    for fn in ("_maybe_place_real_fo_option_exit",):
        f = getattr(main, fn, None)
        if f:
            assert "select_nse_future" not in inspect.getsource(f)
