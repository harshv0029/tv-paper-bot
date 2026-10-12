import importlib.util
import pathlib

_p = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "monthly_loss_cap_backtest.py"
_s = importlib.util.spec_from_file_location("mlc", _p)
mlc = importlib.util.module_from_spec(_s)
_s.loader.exec_module(mlc)


def T(en, ex, r, strat="a"):
    return {"strategy": strat, "entry": en, "exit": ex, "net_r": r, "risk_frac": None}


def test_no_cap_takes_all():
    ts = [T("2026-01-02", "2026-01-03", -1), T("2026-01-05", "2026-01-06", 2)]
    r = mlc.simulate(ts, 0, 1.0)
    assert r["n_taken"] == 2 and r["n_skipped"] == 0
    assert abs(r["total_return_pct"] - (0.99 * 1.02 - 1) * 100) < 1e-6


def test_cap_halts_rest_of_month_only():
    # 1% risk, -1R losses: cap 4% trips after the 4th loss; later Jan entries skipped.
    ts = [T(f"2026-01-{d:02d}", f"2026-01-{d:02d}", -1) for d in range(2, 8)]
    ts.append(T("2026-01-20", "2026-01-21", 5))   # same month: skipped
    ts.append(T("2026-02-02", "2026-02-03", 5))   # new month: taken
    r = mlc.simulate(ts, 4, 1.0)
    # 0.99^4 = -3.94% (not yet), 5th loss = -4.9% trips the halt -> 6th loss + Jan 20 skipped
    assert r["n_skipped"] == 2 and r["n_taken"] == 6
    assert r["profit_forgone"] > 0.04 and r["loss_avoided"] > 0
    nocap = mlc.simulate(ts, 0, 1.0)
    assert nocap["n_skipped"] == 0 and nocap["total_return_pct"] > r["total_return_pct"]


def test_open_positions_survive_halt():
    ts = [T("2026-03-02", "2026-03-10", 3), T("2026-03-03", "2026-03-03", -10),
          T("2026-03-04", "2026-03-05", 1)]
    r = mlc.simulate(ts, 6, 1.0)  # -10R at 1% = -10% -> halt; runner (open) still closes
    assert r["n_taken"] == 2 and r["n_skipped"] == 1


def test_load_trades_return_pct(tmp_path):
    f = tmp_path / "t.csv"
    f.write_text("strategy,entry_date,exit_date,net_return_pct,risk_frac\nx,2026-01-02,2026-01-05,-4,0.04\n")
    t = mlc.load_trades(str(f))
    assert abs(t[0]["net_r"] + 1.0) < 1e-9


def test_side_filter_long_short(tmp_path):
    import json
    rows = [{"strategy": "s", "entry_date": "2026-01-01", "exit_date": "2026-01-02", "net_r": 1, "side": "short"},
            {"strategy": "s", "entry_date": "2026-01-01", "exit_date": "2026-01-02", "net_r": -1}]
    f = tmp_path / "t.json"
    f.write_text(json.dumps(rows))
    tr = mlc.load_trades(str(f))
    assert [t["side"] for t in tr] == ["short", "long"]
    assert len(mlc.filter_side(tr, "short")) == 1 and len(mlc.filter_side(tr, "all")) == 2
