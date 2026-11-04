"""B-1460: View 4 ROC block states when it was computed and when Kotak fills were last fetched (IST)."""
import pathlib
import main


def test_payload_has_ist_timestamps(monkeypatch):
    monkeypatch.setitem(main._real_trades_cache, "fetched_at", 1_700_000_000.0)
    out = main._roc_kpis_payload()
    assert len(out["as_of_ist"]) == 19
    assert out["kotak_fills_fetched_ist"] == "2023-11-15 03:43:20"  # 22:13:20 UTC + 5:30


def test_payload_fills_none_when_never_fetched(monkeypatch):
    monkeypatch.setitem(main._real_trades_cache, "fetched_at", 0.0)
    assert main._roc_kpis_payload()["kotak_fills_fetched_ist"] is None


def test_view4_shows_updated_and_axes():
    t = pathlib.Path(__file__).resolve().parent.parent.joinpath("static", "trade-view4.html").read_text()
    assert "kotak_fills_fetched_ist" in t and "as_of_ist" in t
    assert "x: day, y: ROC %" in t and "exited only" in t


def test_since_start_has_gross_and_charges():
    import datetime as dt
    import roc_kpis
    closed = [{"entry_day": "2026-11-02", "exit_day": "2026-11-03", "entry_value_inr": 1000.0,
               "gross_pnl_inr": 10.0, "charges_inr": 2.5, "net_pnl_inr": 7.5}]
    out = roc_kpis.since_start_kpis(closed, [], dt.date(2026, 11, 2), dt.date(2026, 11, 4))
    assert (out["gross_pnl_inr"], out["charges_inr"], out["net_pnl_inr"]) == (10.0, 2.5, 7.5)
    t = __import__("pathlib").Path(__file__).resolve().parent.parent.joinpath("static", "trade-view4.html").read_text()
    assert "S.gross_pnl_inr" in t and "S.charges_inr" in t
