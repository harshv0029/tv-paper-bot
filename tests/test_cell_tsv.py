import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import cell_tsv as ct  # noqa: E402
import oneil_research as orx  # noqa: E402


def _cells():
    cells = {}
    orx.acc_add(cells, "chan_kalman__band__long__1h__atr2d5_hold40__v1", [(0.01, 0.018, 3, "stop"), (-0.02, -0.012, 5, "max_hold")])
    orx.acc_add(cells, "oneil_pivot__breakout__short__1w__atr3_h26__v1", [(0.05, 0.058, 9, "stop")])
    return cells


def test_tsv_keeps_cells_below_min_n_and_all_columns(tmp_path):
    cells = _cells()
    assert orx.finalize(cells) == {}  # default min_n=30 drops both: the B-783 gap
    res = orx.finalize(cells, min_n=1)
    path = str(tmp_path / "c.tsv")
    assert ct.write_cells_tsv(res, path) == 2
    lines = open(path).read().splitlines()
    assert lines[0].split("\t") == ct.COLS
    assert len(lines) == 3
    row = dict(zip(ct.COLS, lines[1].split("\t")))
    assert row["family"] == "chan_kalman" and row["dir"] == "long" and row["tf"] == "1h"
    assert row["avg_hold_unit"] == "1h bars" and row["n"] == "2"


def test_hold_unit_labels():
    assert ct.hold_unit("1w") == "weeks" and ct.hold_unit("1d") == "trading days" and ct.hold_unit("4h") == "4h bars"


def test_resample_4h_session_windows_no_lookahead():
    idx = pd.date_range("2026-01-05 09:15", periods=7, freq="1h", tz="Asia/Kolkata")  # 09:15..15:15
    df = pd.DataFrame({"Open": np.arange(7.0), "High": np.arange(7.0) + 2, "Low": np.arange(7.0) - 1,
                       "Close": np.arange(7.0) + 0.5, "Volume": 10.0}, index=idx)
    out = ct.resample_4h(df)
    assert len(out) == 2
    a, b = out.iloc[0], out.iloc[1]
    assert a["Open"] == 0 and a["Close"] == 3.5 and a["High"] == 5 and a["Low"] == -1 and a["Volume"] == 40  # 09:15-12:15
    assert b["Open"] == 4 and b["Close"] == 6.5 and b["Volume"] == 30  # 13:15, 14:15, 15:15 (13:15 starts window 2)
    assert out.index[0] == idx[0]
