"""B-1713: View 6 rolling 5-min and 1-hour % change beside the 15-min one."""
import pytest

import main

T0 = 1_800_000_000.0


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(main, "_FNO_PX_HIST", {})
    monkeypatch.setattr(main, "_FNO_PX_HIST_1H", {})
    monkeypatch.setattr(main, "_FNO_PX_HIST_SYNC", {"restored": True, "last_save_ts": 0.0, "error": None})
    monkeypatch.setattr(main, "_fno_hist_save", lambda now_ts: False)


def _feed(minutes, price_of):
    for i in range(minutes + 1):
        main._fno_hist_record({"NIFTY": [{"contract": "C", "lastPrice": price_of(i)}]}, T0 + 60 * i)


def test_5m_and_1h_warm_up_then_report():
    _feed(4, lambda i: 100.0 + i)
    d = main._fno_chg_multi_detail("C", 110.0, T0 + 4 * 60)
    assert d["chg5_pct"] is None and d["chg60_pct"] is None and d["chg15_pct"] is None
    _feed(65, lambda i: 100.0 + i)
    d = main._fno_chg_multi_detail("C", 165.0, T0 + 65 * 60)
    assert d["chg5_pct"] == pytest.approx((165 / 160 - 1) * 100, abs=0.01)
    assert d["chg15_pct"] == pytest.approx((165 / 150 - 1) * 100, abs=0.01)
    # 1h samples every 2 min (0, 2, 4, ...); at minute 65 the one 60-62 min old is minute 4 (price 104)
    assert d["chg60_pct"] == pytest.approx((165 / 104 - 1) * 100, abs=0.01)
    assert d["chg60_from_ist"].endswith("IST")


def test_1h_samples_thinned_and_pruned():
    _feed(80, lambda i: 100.0)
    h1 = main._FNO_PX_HIST_1H["C"]
    assert all(b[0] - a[0] >= main.FNO_HIST_1H_STEP_S for a, b in zip(h1, h1[1:]))
    assert T0 + 80 * 60 - h1[0][0] <= main.FNO_HIST_1H_KEEP_S
    assert len(h1) <= 40
    assert T0 + 80 * 60 - main._FNO_PX_HIST["C"][0][0] <= main.FNO_HIST_KEEP_S  # 15m store unchanged


def test_gap_gives_none_not_stale_base():
    main._FNO_PX_HIST_1H["C"] = [(T0, 100.0)]
    assert main._fno_chg_window(main._FNO_PX_HIST_1H, "C", 120.0, T0 + 70 * 60, 3600, 3720) == (None, None)
    assert main._fno_chg_window(main._FNO_PX_HIST_1H, "C", 120.0, T0 + 61 * 60, 3600, 3720)[0] == 20.0


def test_view6_page_has_5m_and_1h_columns():
    html = open("static/trade-view6.html").read()
    assert "<th class=\"num\">5m %</th><th class=\"num\">15m %</th><th class=\"num\">1h %</th>" in html
    assert "chg5_pct" in html and "chg60_pct" in html
