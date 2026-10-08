import main


def test_non_etf_passes():
    assert main._etf_entry_range_ok("RELIANCE.NS")[0] is True


def test_etf_range_gate(monkeypatch):
    import pandas as pd
    sym = sorted(main.ETF_SYMBOLS)[0]

    def mk(rng):
        n = 40
        return pd.DataFrame({"High": [100 + rng] * n, "Low": [100.0] * n, "Close": [100.0] * n})

    for rng, want in ((1.0, True), (0.1, False), (6.0, False)):
        main._etf_range_cache.clear()
        monkeypatch.setattr(main.yf, "download", lambda *a, _r=rng, **k: mk(_r))
        assert main._etf_entry_range_ok(sym)[0] is want


def test_etf_fail_closed(monkeypatch):
    sym = sorted(main.ETF_SYMBOLS)[0]
    main._etf_range_cache.clear()
    def boom(*a, **k): raise RuntimeError("x")
    monkeypatch.setattr(main.yf, "download", boom)
    assert main._etf_entry_range_ok(sym)[0] is False


def test_all_etfs_in_universe():
    assert len(main.ETF_SYMBOLS) >= 150
    assert set(main.ETF_SYMBOLS) <= set(main.NSE_FULL_UNIVERSE)
