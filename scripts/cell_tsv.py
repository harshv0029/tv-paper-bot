"""Shared keep-all-data helpers for the O'Neil / Chan research merges (backlog B-783, B-785).

* write_cells_tsv(): one row per cell, EVERY field, no top-N and no n-threshold trimming (callers pass the result
  of finalize(cells, min_n=1)). Tag grammar fields are split into columns; avg hold carries an explicit UNIT.
* print_tsv(): dumps the whole file between markers so the log carries it even when the artifact download 403s.
* resample_4h(): 1h OHLCV -> 4h bars per NSE session (windows 09:15-13:15 and 13:15-15:30 local clock), no
  look-ahead (a bar only contains 1h bars inside its window and is stamped by its first 1h bar).
"""
import json
import os

import pandas as pd

HOLD_UNIT = {"1d": "trading days", "1w": "weeks", "1h": "1h bars", "4h": "4h bars", "15m": "15m bars",
             "5m": "5m bars", "1m": "1m bars"}
COLS = ["tag", "family", "variant", "dir", "tf", "params", "version", "n", "win_pct", "pfnet", "pfgross",
        "avg_hold", "avg_hold_unit", "avg_net_pct", "max_trade_net_pct", "exit_reasons_json"]


def hold_unit(tf):
    return HOLD_UNIT.get(tf, "bars")


def parse_tag(tag):
    base = tag.split("__x__")[0]
    p = (base.split("__") + [""] * 6)[:6]
    return dict(family=p[0], variant=p[1], dir=p[2], tf=p[3], params=p[4], version=p[5])


def cells_to_rows(res):
    rows = []
    for tag in sorted(res):
        m = res[tag]
        f = parse_tag(tag)
        rows.append(dict(
            tag=tag, **f, n=m.get("n"), win_pct=m.get("win_pct"), pfnet=m.get("pfnet"), pfgross=m.get("pfgross"),
            avg_hold=m.get("avg_held_bars"), avg_hold_unit=hold_unit(f["tf"]), avg_net_pct=m.get("avg_net_pct"),
            max_trade_net_pct=m.get("max_trade_net_pct"),
            exit_reasons_json=json.dumps(m.get("exit_reasons", {}), default=str, sort_keys=True,
                                         separators=(",", ":"))))
    return rows


def _fmt(v):
    return "" if v is None else str(v)


def write_cells_tsv(res, path):
    rows = cells_to_rows(res)
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w") as fh:
        fh.write("\t".join(COLS) + "\n")
        for r in rows:
            fh.write("\t".join(_fmt(r[c]) for c in COLS) + "\n")
    return len(rows)


def print_tsv(path, label):
    print(f"=== BEGIN FULL CELL TSV {label} ({path}) ===")
    with open(path) as fh:
        print(fh.read(), end="")
    print(f"=== END FULL CELL TSV {label} ===")


def emit_full(res_all, path, label):
    """Write + print every cell of res_all (finalize(..., min_n=1) output)."""
    n = write_cells_tsv(res_all, path)
    print(f"FULL cell table: {n} cells -> {path}")
    print_tsv(path, label)
    return n


def resample_4h(df):
    """1h OHLCV with a DatetimeIndex -> 4h session bars (09:15-13:15, 13:15-close)."""
    if df.empty:
        return df
    idx = df.index
    mins = idx.hour * 60 + idx.minute
    key = [(d, int(m >= 13 * 60 + 15)) for d, m in zip(idx.normalize(), mins)]
    g = df.groupby(pd.Index(key, tupleize_cols=False), sort=False)
    out = pd.DataFrame({
        "Open": g["Open"].first(), "High": g["High"].max(), "Low": g["Low"].min(),
        "Close": g["Close"].last(), "Volume": g["Volume"].sum()})
    firsts = [grp.index[0] for _, grp in g]
    out.index = pd.DatetimeIndex(firsts)
    return out.sort_index()
