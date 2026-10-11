import main


def _set(monkeypatch, tmp_path, value):
    import sqlite3
    from contextlib import closing
    db = tmp_path / "t.db"
    c = sqlite3.connect(db); c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE IF NOT EXISTS runtime_settings (key TEXT PRIMARY KEY, value REAL)")
    c.execute("DELETE FROM runtime_settings")
    if value is not None:
        c.execute("INSERT INTO runtime_settings VALUES ('real_enabled_swing', ?)", (value,))
    c.commit(); c.close()
    def _get():
        x = sqlite3.connect(db); x.row_factory = sqlite3.Row; return x
    monkeypatch.setattr(main, "get_db", _get)


def test_unset_follows_env(monkeypatch, tmp_path):
    _set(monkeypatch, tmp_path, None)
    monkeypatch.setenv("REAL_SWING_TRADING_ENABLED", "YES")
    assert main.is_real_swing_trading_enabled() is True
    monkeypatch.delenv("REAL_SWING_TRADING_ENABLED")
    assert main.is_real_swing_trading_enabled() is False


def test_panel_overrides_env(monkeypatch, tmp_path):
    monkeypatch.delenv("REAL_SWING_TRADING_ENABLED", raising=False)
    _set(monkeypatch, tmp_path, 1)
    assert main.is_real_swing_trading_enabled() is True
    monkeypatch.setenv("REAL_SWING_TRADING_ENABLED", "YES")
    _set(monkeypatch, tmp_path, 0)
    assert main.is_real_swing_trading_enabled() is False


def test_meta_requires_token():
    for k in ("real_enabled_equity", "real_enabled_swing", "real_enabled_fo"):
        assert main.RUNTIME_SETTINGS_META[k][3] is True


def test_master_switch_and_gate_wiring_present():
    import inspect
    # each category gate reads its own runtime key via the shared helper
    assert "real_enabled_equity" in inspect.getsource(main.is_real_trading_enabled)
    assert "real_enabled_swing" in inspect.getsource(main.is_real_swing_trading_enabled)
    assert "real_enabled_fo" in inspect.getsource(main.is_real_fo_trading_enabled)


def test_negative_value_means_follow_env(monkeypatch, tmp_path):
    _set(monkeypatch, tmp_path, -1)
    monkeypatch.setenv("REAL_SWING_TRADING_ENABLED", "YES")
    assert main.is_real_swing_trading_enabled() is True
