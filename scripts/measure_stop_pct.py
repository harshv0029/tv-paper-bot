"""B-775: measure planned stop-% per ATR-stop strategy tag, written to the read-time sidecar
docs/backtest_data/stop_pct.json consumed by scripts/count_sl_cap.py.

stop_pct(tag) = ATR multiple (parsed from the tag's `atr<N>` param) x median over the FULL NSE
universe of per-symbol median(ATR14/close) at the tag's own candle size. This is a universe-
median PLANNED stop distance, not a per-trade measurement: it is stored with basis
"atr_mult_x_universe_median_atr_pct" in stop_pct_basis.json so it is never mistaken for a
per-trade figure. `atrnone` tags (no stop in the backtest) and non-ATR stops get no entry
(UNKNOWN, never guessed). Raw per-tf ATR% tables are kept in docs/backtest_data/atr_pct_by_tf.json.

Usage: python3 scripts/measure_stop_pct.py --fetch [--max-symbols N]   (needs network: Actions)
       python3 scripts/measure_stop_pct.py                              (re-derive from stored ATR table)"""
import argparse
import json
import pathlib
import re
import statistics
import sys

sys.path.insert(0, ".")
DATA = pathlib.Path("docs/backtest_data")
ATR_TABLE = DATA / "atr_pct_by_tf.json"
SIDECAR = DATA / "stop_pct.json"
BASIS = DATA / "stop_pct_basis.json"
# 4h has no yfinance interval: fetched as 1h and resampled to 4h bars (B-875).
INTERVALS = {"4h": ("1h", "730d"), "5m": ("5m", "60d"), "15m": ("15m", "60d"), "1h": ("1h", "730d"), "1d": ("1d", "5y"), "1w": ("1wk", "10y")}

_ATR_RE = re.compile(r"(?:^|_)atr(\d+(?:d\d+)?|none)(?:_|$)")


def parse_atr_mult(tag):
    """ATR multiple from a grammar tag's params field, or None (no atr param / atrnone)."""
    parts = tag.split("__")
    if len(parts) < 5:
        return None
    m = _ATR_RE.search(parts[4])
    if not m or m.group(1) == "none":
        return None
    return float(m.group(1).replace("d", "."))


_PCT_RE = re.compile(r"(?:^|_)pct(\d+(?:d\d+)?)(?:_|$)")
_TGT_RE = re.compile(r"(?:^|_)tgt\d+(?:d\d+)?(?:_|$)")
FIXED_TGT_STOP_PCT = 8.0  # main.oneil_stop_price mode "tgt": fixed 8% initial stop


def parse_fixed_pct(tag):
    """(stop_pct, kind) for tags whose stop is an explicit percent (oneil `pct<N>`; main.oneil_stop_price
    pct mode = N percent) or the fixed-8% `tgt` mode; else None. ATR tags are handled by parse_atr_mult."""
    parts = tag.split("__")
    if len(parts) < 5:
        return None
    m = _PCT_RE.search(parts[4])
    if m:
        return float(m.group(1).replace("d", ".")), "pct"
    if _TGT_RE.search(parts[4]) and parse_atr_mult(tag) is None:
        return FIXED_TGT_STOP_PCT, "tgt_fixed_8pct"
    return None


def tag_tf(tag):
    parts = tag.split("__")
    return parts[3] if len(parts) > 3 else None


def atr_pct_series(highs, lows, closes, n=14):
    """Median of ATR_n/close (percent) over a bar series (simple-mean TR); None if too short."""
    if len(closes) < n + 2:
        return None
    vals = []
    trs = []
    for i in range(1, len(closes)):
        trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
        if len(trs) >= n and closes[i] > 0:
            vals.append(100.0 * (sum(trs[-n:]) / n) / closes[i])
    return statistics.median(vals) if vals else None


def derive(tags, atr_table):
    """{tag: stop_pct} for tags with an ATR multiple and a measured ATR% at their tf."""
    out = {}
    for t in tags:
        fixed = parse_fixed_pct(t)
        if fixed is not None and parse_atr_mult(t) is None:
            out[t] = round(fixed[0], 4)
            continue
        mult, tf = parse_atr_mult(t), tag_tf(t)
        a = atr_table.get(tf, {}).get("median_atr_pct") if tf else None
        if mult is not None and a is not None:
            out[t] = round(mult * a, 4)
    return out


def _resample_4h(df):
    """1h OHLC -> 4h bars (right-closed groups anchored at session open via 4-hour bins)."""
    return df.resample("4h", origin="start_day", offset="3h15min").agg(
        {"High": "max", "Low": "min", "Close": "last"}).dropna()


def fetch_table(max_symbols=None, tfs=None):
    import yfinance as yf
    import main
    syms = list(main._load_nse_universe_from_file())  # full unrestricted universe (CLAUDE.md)
    if max_symbols:
        syms = syms[:max_symbols]
    table = {}
    for tf, (iv, per) in INTERVALS.items():
        if tfs and tf not in tfs:
            continue
        per_sym = []
        for s in syms:
            try:
                df = yf.download(s, interval=iv, period=per, progress=False, auto_adjust=False)
                if df is None or df.empty:
                    continue
                if hasattr(df.columns, "levels"):
                    df.columns = df.columns.get_level_values(0)
                if tf == "4h":
                    df = _resample_4h(df)
                v = atr_pct_series(df["High"].tolist(), df["Low"].tolist(), df["Close"].tolist())
                if v is not None:
                    per_sym.append(v)
            except Exception:
                continue
        table[tf] = {"median_atr_pct": statistics.median(per_sym) if per_sym else None,
                     "n_symbols": len(per_sym), "symbols_requested": len(syms)}
    return table


def main_cli():
    import strategy_registry as sr
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--max-symbols", type=int)
    ap.add_argument("--tfs", default="", help="comma list (e.g. 4h): fetch only these tfs, merged into the stored ATR table")
    ap.add_argument("--out-dir", default=str(DATA), help="write outputs here (dry runs)")
    a = ap.parse_args()
    out = pathlib.Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    table = json.loads(ATR_TABLE.read_text()) if ATR_TABLE.exists() else {}
    if a.fetch:
        want = {t.strip() for t in a.tfs.split(",") if t.strip()} or None
        table.update(fetch_table(a.max_symbols, want))
        (out / ATR_TABLE.name).write_text(json.dumps(table, indent=1, sort_keys=True))
    res = derive([s.name for s in sr.REGISTRY], table)
    # never drop a previously stored measurement (raw data kept intact, CLAUDE.md 2026-10-11)
    if SIDECAR.exists():
        prev = json.loads(SIDECAR.read_text())
        res = {**prev, **res}
    side, basis = out / "stop_pct.json", out / "stop_pct_basis.json"
    side.write_text(json.dumps(res, indent=1, sort_keys=True))
    basis.write_text(json.dumps({"basis": "atr_mult_x_universe_median_atr_pct",
                                 "also": {"pct": "explicit N percent stop parsed from tag (exact)",
                                          "tgt_fixed_8pct": "main.oneil_stop_price tgt mode fixed 8%"},
                                 "note": "planned stop distance, not per-trade measured; atrnone tags excluded"}, indent=1))
    import count_sl_cap
    r = count_sl_cap.count(sidecar=str(side))
    print(f"viable hold<=5d unknown_stop after run: {len(r['unknown_stop'])}")
    print(f"tags with measured planned stop-%: {len(res)}")


if __name__ == "__main__":
    main_cli()
