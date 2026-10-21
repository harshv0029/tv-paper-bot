import main


def _run(monkeypatch, rows):
    import kotak_neo
    monkeypatch.setattr(kotak_neo, "positions", lambda: {"data": rows})
    main._refresh_real_trades_cache()
    return main._real_trades_cache["value"]


def _row(seg, b, s, ba, sa):
    return {"exSeg": seg, "trdSym": "X", "flBuyQty": b, "flSellQty": s, "buyAmt": ba,
            "sellAmt": sa, "hsUpTm": main.ist_now().strftime("%Y/%m/%d %H:%M:%S")}


def test_fo_and_partial_counted(monkeypatch):
    t = _run(monkeypatch, [_row("nse_fo", 100, 100, 254, 251),
                           _row("nse_cm", 10, 4, 100, 48),
                           _row("nse_cm", 5, 0, 50, 0)])
    assert [x["pnl_inr"] for x in t] == [-3.0, 8.0]


def test_charges_estimated_and_netted_from_loss_figure(monkeypatch):
    """B-1315 remainder: option sell of Rs5969 premium pays 0.1% STT etc; the loss budget reads P&L net of it."""
    rows = [_row("nse_fo", 2350, 2350, 5969.0, 5898.5)]
    rows[0]["trdSym"] = "JIOFIN25OCT300CE"
    t = _run(monkeypatch, rows)
    assert t[0]["pnl_inr"] == -70.5
    c = t[0]["charges_est_inr"]
    # STT 5.90 + exchange 4.16 + SEBI 0.01 + stamp 0.18 + GST 0.75 = about 11.0
    assert 10.5 < c < 11.5
    main._real_trades_cache["fetched_at"] = __import__("time").time()
    assert round(main.get_real_pnl_today_inr(), 2) == round(-70.5 - c, 2)


def test_equity_intraday_charges_small_and_delivery_larger():
    intra = main._estimate_statutory_charges_inr("nse_cm", "ITC-EQ", "MIS", 10000.0, 10000.0)
    deliv = main._estimate_statutory_charges_inr("nse_cm", "ITC-EQ", "CNC", 10000.0, 10000.0)
    assert 3.0 < intra < 4.5  # STT 2.5 + exch 0.59 + stamp 0.3 + GST/SEBI
    assert 22.0 < deliv < 24.5  # STT 20 + stamp 1.5 + exch 0.59 + GST/SEBI
