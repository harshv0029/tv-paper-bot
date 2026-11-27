"""B-1746: index ATM single-leg option PAPER engine (ORB call / EMA-cross put, novol and futvol twins).
PAPER ONLY: the shared fixture fails the test on any Kotak order call or NSE network call."""
import datetime as dt
import json
import os
import sys

import numpy as np
import pandas as pd
import pytest

import main
from tests.test_fno_momo_paper_b1676 import T0, db  # noqa: F401 (db autouse)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import index_option_trigger_research as R  # noqa: E402

ORB_NV, ORB_FV, EMA_NV, EMA_FV = main.IDXOPT_TAGS


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch):
    monkeypatch.setattr(main, "_IDXOPT_STATE", {"last_error": None, "last_pass_ts": None, "futures": {},
                                                 "last_signal": {}})
DAY = dt.date(2026, 11, 23)  # Monday, NSE trading day
HOURS = ("09:15", "10:15", "11:15", "12:15", "13:15", "14:15", "15:15")


def _bars(today_break=True):
    """5 flat earlier sessions + today's 4 completed bars (09:15-12:15); 12:15 closes above the opening range."""
    start, high, close, day = [], [], [], []
    d = DAY - dt.timedelta(days=7)
    while len({x for x in day}) < 5:
        if d.weekday() < 5:
            for h in HOURS:
                start.append(dt.datetime.combine(d, dt.time(int(h[:2]), int(h[3:]))))
                high.append(100.5)
                close.append(100.0)
                day.append(d.isoformat())
        d += dt.timedelta(days=1)
    for h, hi, cl in (("09:15", 100.4, 100.1), ("10:15", 100.6, 100.3), ("11:15", 100.8, 100.5),
                      ("12:15", 101.5, 101.2 if today_break else 100.6)):
        start.append(dt.datetime.combine(DAY, dt.time(int(h[:2]), int(h[3:]))))
        high.append(hi)
        close.append(cl)
        day.append(DAY.isoformat())
    return {"^NSEI": {"start": start, "high": np.array(high), "close": np.array(close), "day": day}}


def _chain(u, right):
    return {"contract": f"{u} 25900 {right} 25-Nov-2026", "lastPrice": 100.0, "strikePrice": 25900,
            "underlyingValue": 25890.0, "pChange": 1.0}, None


def _at(hh, mm):
    return dt.datetime.combine(DAY, dt.time(hh, mm))


def _ts(now):
    return T0 + (now - _at(9, 15)).total_seconds()


def _step(db, now, bars=None, quote=lambda c, u: None):
    return main._idxopt_step(db, now=now, now_ts=_ts(now), bars_by_sym=bars if bars is not None else _bars(),
                             quote=quote, chain=_chain)


def _open(db, tag):
    return db.execute("SELECT * FROM fno_momo_paper_trades WHERE tag = ? ORDER BY id DESC LIMIT 1", (tag,)).fetchone()


def _seed_futvol(db, today_last_hour_vol, hist_vol=1000.0, days=2):
    """Earlier full sessions with `hist_vol` per hour, then today's boundaries up to 13:15."""
    rows, d, n = [], DAY - dt.timedelta(days=1), 0
    while n < days:
        if d.weekday() < 5:
            for k, b in enumerate(main.IDXOPT_BOUNDARIES):
                rows.append(("NIFTY", d.isoformat(), b, 0.0, hist_vol * (k + 1)))
            n += 1
        d -= dt.timedelta(days=1)
    for k, b in enumerate(("10:15", "11:15", "12:15")):
        rows.append(("NIFTY", DAY.isoformat(), b, 0.0, hist_vol * (k + 1)))
    rows.append(("NIFTY", DAY.isoformat(), "13:15", 0.0, hist_vol * 3 + today_last_hour_vol))
    db.executemany("INSERT INTO idxopt_futvol (underlying, day, boundary, ts, cum_volume) VALUES (?, ?, ?, ?, ?)", rows)
    db.commit()


def test_triggers_match_the_replay_functions():
    rng = np.random.default_rng(7)
    rows, px = [], 25000.0
    d = dt.date(2026, 9, 1)
    while len(rows) < 7 * 60:
        if d.weekday() < 5:
            for h in HOURS:
                o = px
                px *= float(np.exp(rng.normal(0, 0.004)))
                rows.append((f"{d} {h}:00+05:30", o, max(o, px) * 1.001, min(o, px) * 0.999, px, 0.0))
        d += dt.timedelta(days=1)
    df = pd.DataFrame(rows, columns=["Date", "Open", "High", "Low", "Close", "Volume"])
    days = df["Date"].str[:10].tolist()
    assert main._idxopt_orb3(days, df["High"].tolist(), df["Close"].tolist()) == R.trig_orb(df, 3).tolist()
    assert main._idxopt_ema_cross_down(df["Close"].tolist()) == R.trig_ema_cross(R.flip(df)).tolist()
    assert any(R.trig_orb(df, 3)) and any(R.trig_ema_cross(R.flip(df)))


def test_hourly_frame_drops_the_open_bar_and_rejects_off_grid_times():
    idx = pd.DatetimeIndex([f"2026-11-23 {h}:00" for h in HOURS[:5]]).tz_localize("Asia/Kolkata")
    df = pd.DataFrame({"High": [1.0] * 5, "Close": [1.0] * 5}, index=idx)
    b = main._idxopt_hourly(df, _at(13, 20))  # the 13:15 bar is still forming
    assert [s.strftime("%H:%M") for s in b["start"]] == ["09:15", "10:15", "11:15", "12:15"]
    utc_naive = pd.DataFrame({"High": [1.0] * 3, "Close": [1.0] * 3},
                             index=pd.DatetimeIndex(["2026-11-23 03:45", "2026-11-23 04:45", "2026-11-23 05:45"]))
    assert main._idxopt_hourly(utc_naive, _at(13, 20)) is None  # never guess a timezone


def test_novol_orb_enters_atm_call_with_stop_then_trails_and_stops_out(db):
    acts = _step(db, _at(13, 16))
    row = _open(db, ORB_NV)
    assert row["status"] == "open" and row["option_type"] == "CE" and row["underlying"] == "NIFTY"
    assert row["entry_price"] == 100.0 and row["stop_price"] == 90.0  # every paper trade carries its stop
    assert json.loads(row["entry_meta"])["signal_bar"] == "13:15"
    assert any(a["tag"] == ORB_NV for a in acts if a["action"] == "entry")
    _step(db, _at(13, 30), quote=lambda c, u: 106.0)  # +6% arms the 5% trail
    assert _open(db, ORB_NV)["stop_price"] == round(106.0 * 0.95, 4)
    _step(db, _at(13, 40), quote=lambda c, u: 100.0)
    row = _open(db, ORB_NV)
    assert row["status"] == "closed" and row["close_reason"] == "trailing_sl" and row["close_price"] == 100.7
    _step(db, _at(13, 45))  # the same 13:15 signal bar is never re-entered
    assert db.execute("SELECT COUNT(*) FROM fno_momo_paper_trades WHERE tag = ?", (ORB_NV,)).fetchone()[0] == 1


def test_orb_time_exit_after_one_hour(db):
    _step(db, _at(13, 16))
    _step(db, _at(14, 17), quote=lambda c, u: 103.0)
    row = _open(db, ORB_NV)
    assert row["status"] == "closed" and row["close_reason"] == "time_exit_60min"


def test_futvol_twin_fails_closed_in_warmup_and_logs_the_skip(db):
    _step(db, _at(13, 16))
    assert _open(db, ORB_FV) is None
    log = db.execute("SELECT * FROM fno_momo_scan_log WHERE tag = ?", (ORB_FV,)).fetchall()
    assert len(log) == 1 and log[0]["skip"] == "skipped_futvol_missing_sample"


def test_futvol_twin_enters_only_when_the_hour_beats_its_average(db):
    _seed_futvol(db, today_last_hour_vol=1500.0)
    _step(db, _at(13, 16))
    row = _open(db, ORB_FV)
    assert row is not None and json.loads(row["entry_meta"])["futvol"]["bar_volume"] == 1500.0


def test_futvol_twin_below_average_is_skipped(db):
    _seed_futvol(db, today_last_hour_vol=500.0)
    _step(db, _at(13, 16))
    assert _open(db, ORB_FV) is None
    skip = db.execute("SELECT skip FROM fno_momo_scan_log WHERE tag = ?", (ORB_FV,)).fetchone()[0]
    assert skip == "skipped_futvol_below_avg"


def test_futvol_warmup_needs_six_hours():
    ok, why, det = None, None, None
    import sqlite3
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE idxopt_futvol (underlying TEXT, day TEXT, boundary TEXT, ts REAL, cum_volume REAL)")
    for k, b in enumerate(("10:15", "11:15", "12:15", "13:15")):
        c.execute("INSERT INTO idxopt_futvol VALUES ('NIFTY', '2026-11-23', ?, 0, ?)", (b, 1000.0 * (k + 1) + k))
    ok, why, det = main._idxopt_futvol_gate(c, "NIFTY", "2026-11-23", "13:15")
    assert ok is False and why == "skipped_futvol_warmup" and det["hist_bars"] == 3


def test_no_signal_no_entry_and_nothing_before_first_entry_time(db):
    assert _step(db, _at(13, 16), bars=_bars(today_break=False)) == [] or _open(db, ORB_NV) is None
    assert _open(db, ORB_NV) is None
    assert _step(db, _at(10, 0)) == []


def test_put_row_is_forced_out_at_1513_and_eod_sweep_keeps_engine_rows(db):
    db.execute("INSERT INTO fno_momo_paper_trades (tag, day, status, contract, underlying, option_type, opened_ts, "
               "entry_price, peak_price, stop_price, last_price, last_ts) VALUES (?, ?, 'open', 'NIFTY 25900 PE "
               "25-Nov-2026', 'NIFTY', 'PE', ?, 100, 100, 85, 100, ?)", (EMA_NV, DAY.isoformat(), T0, T0))
    db.commit()
    assert main._fno_momo_eod_sweep(db, now=_at(14, 0), now_ts=T0 + 100) == []  # not closed as a retired variant
    _step(db, _at(15, 13), quote=lambda c, u: 97.0)
    row = _open(db, EMA_NV)
    assert row["status"] == "closed" and row["close_reason"] == "forced_exit_1513" and row["close_price"] == 97.0


def test_futvol_samples_mirror_to_git_not_upstash():
    assert "idxopt_futvol" in main._GENERIC_MIRROR_GIT_TIER
    assert "idxopt_futvol" not in main._GENERIC_MIRROR_UPSTASH_TABLES
    wf = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           ".github/workflows/table-git-sync.yml")).read()
    assert "idxopt_futvol" in wf


def test_sampler_stores_one_cumulative_volume_per_boundary(db, monkeypatch):
    monkeypatch.setattr(main, "_idxopt_future",
                        lambda u, d: {"instrument_token": 1, "exchange_segment": "nse_fo"} if u == "NIFTY" else None)
    q = lambda toks, seg: {"1": {"last_volume": 4200}}  # noqa: E731
    assert main._idxopt_sample_futvol(db, _at(11, 16), quote_rows=q) == 1
    assert main._idxopt_sample_futvol(db, _at(11, 17), quote_rows=q) == 0  # once per boundary
    assert main._idxopt_sample_futvol(db, _at(11, 25), quote_rows=q) == 0  # outside the 5-min window
    assert db.execute("SELECT boundary, cum_volume FROM idxopt_futvol").fetchall()[0][:] == ("11:15", 4200.0)
