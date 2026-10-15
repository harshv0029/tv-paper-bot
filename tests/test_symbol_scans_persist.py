"""B-1278: per-symbol strategy-tested set survives a restart (Upstash mirror, simulated wipe)."""
import json
from unittest.mock import patch

import main


def _reset():
    main._symbol_strategy_scans.clear()
    main._symbol_strategy_scans_day = ""
    main._symbol_scans_hydrated = False
    main._symbol_scans_last_sync = 0.0


def test_push_then_wipe_then_hydrate_restores():
    _reset()
    store = {}
    today = main.ist_now().strftime("%Y-%m-%d")
    main._symbol_strategy_scans_day = today
    main._symbol_strategy_scans["AUBANK.NS"] = {"a", "b"}
    with patch.object(main, "UPSTASH_REDIS_REST_URL", "https://x"), \
         patch.object(main, "UPSTASH_REDIS_REST_TOKEN", "t"), \
         patch.object(main, "_upstash_set", side_effect=lambda k, v: store.__setitem__(k, v)), \
         patch.object(main, "_upstash_get", side_effect=lambda k: store.get(k)):
        main._symbol_scans_push_now()
        _reset()  # simulated restart wipe
        assert main._symbol_scans_hydrate_now() is True
        assert main._symbol_strategy_scans["AUBANK.NS"] == {"a", "b"}
        assert main._symbol_strategies_tested_today("AUBANK.NS") == 2
    _reset()


def test_stale_day_snapshot_not_restored():
    _reset()
    store = {main._SYMBOL_SCANS_REDIS_KEY: json.dumps({"day": "2020-01-01", "scans": {"X.NS": ["t"]}})}
    with patch.object(main, "UPSTASH_REDIS_REST_URL", "https://x"), \
         patch.object(main, "UPSTASH_REDIS_REST_TOKEN", "t"), \
         patch.object(main, "_upstash_get", side_effect=lambda k: store.get(k)):
        assert main._symbol_scans_hydrate_now() is True
        assert "X.NS" not in main._symbol_strategy_scans
    _reset()


def test_no_upstash_is_noop():
    _reset()
    with patch.object(main, "UPSTASH_REDIS_REST_URL", None):
        assert main._symbol_scans_hydrate_now() is False
        main._symbol_scans_kick_sync()  # must not raise
    _reset()
