import main


def test_cross_rows_carry_doc_and_backtest_pfnet():
    r = main._strategy_symbol_cross(limit=5)
    assert r["rows"], "cross returned no rows"
    for row in r["rows"]:
        assert "pfnet_doc" in row and "pfnet_backtest" in row


def test_backtest_pfnet_only_when_main_replayed():
    doc, bt = main._pfnet_doc_and_backtest("starc__fade_full__short__1d__atr2d5_h20__v2")
    assert doc == 0.597 and bt == 0.597  # run_ref names the main.py-function replay
    doc, bt = main._pfnet_doc_and_backtest("starc__fade_full__short__1d__atr2d5_h20__v1")
    assert doc == 0.7 and bt is None  # pattern-lab research implementation only
    assert main._pfnet_doc_and_backtest("nope") == (None, None)
