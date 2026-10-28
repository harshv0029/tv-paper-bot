"""B-1401 (user 2026-10-28): orb-range-short / orb-universal-score fall below the viability criteria, so they are not scanned."""
import main


def test_nonviable_engines_not_scanned():
    assert main._intraday_engine_scan_enabled("orb-universal-score") is False
    assert main._intraday_engine_scan_enabled("orb-range-short") is False


def test_scan_follows_viability_verdict(monkeypatch):
    monkeypatch.setattr(main, "_viability_verdict", lambda t, check_switch=True: (t == "orb-range-short", "x"))
    assert main._intraday_engine_scan_enabled("orb-range-short") is True
    assert main._intraday_engine_scan_enabled("orb-universal-score") is False


def test_counters_skip_nonviable(monkeypatch):
    seen = []
    monkeypatch.setattr(main, "_record_strategy_scan", seen.append)
    monkeypatch.setattr(main, "_viability_verdict", lambda t, check_switch=True: (t == "orb-trend-short", "x"))
    main._record_intraday_strategy_scan({"strategy": "universal_score"})
    main._record_short_strategy_scans()
    assert seen == ["trend_down_momentum_short"]


def test_verdict_error_fails_closed(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError
    monkeypatch.setattr(main, "_viability_verdict", boom)
    assert main._intraday_engine_scan_enabled("orb-universal-score") is False
