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
