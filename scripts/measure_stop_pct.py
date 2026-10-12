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
INTERVALS = {"5m": ("5m", "60d"), "15m": ("15m", "60d"), "1h": ("1h", "730d"), "1d": ("1d", "5y"), "1w": ("1wk", "10y")}

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
        mult, tf = parse_atr_mult(t), tag_tf(t)
        a = atr_table.get(tf, {}).get("median_atr_pct") if tf else None
        if mult is not None and a is not None:
            out[t] = round(mult * a, 4)
    return out


def fetch_table(max_symbols=None):
    import yfinance as yf
    import main
    syms = list(main._load_nse_universe_from_file())  # full unrestricted universe (CLAUDE.md)
    if max_symbols:
        syms = syms[:max_symbols]
    table = {}
    for tf, (iv, per) in INTERVALS.items():
        per_sym = []
        for s in syms:
            try:
                df = yf.download(s, interval=iv, period=per, progress=False, auto_adjust=False)
                if df is None or df.empty:
                    continue
                if hasattr(df.columns, "levels"):
                    df.columns = df.columns.get_level_values(0)
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
    a = ap.parse_args()
    DATA.mkdir(parents=True, exist_ok=True)
    if a.fetch:
        ATR_TABLE.write_text(json.dumps(fetch_table(a.max_symbols), indent=1, sort_keys=True))
    table = json.loads(ATR_TABLE.read_text())
    res = derive([s.name for s in sr.REGISTRY], table)
    SIDECAR.write_text(json.dumps(res, indent=1, sort_keys=True))
    BASIS.write_text(json.dumps({"basis": "atr_mult_x_universe_median_atr_pct",
                                 "note": "planned stop distance, not per-trade measured; atrnone tags excluded"}, indent=1))
    print(f"tags with measured planned stop-%: {len(res)}")


if __name__ == "__main__":
    main_cli()
