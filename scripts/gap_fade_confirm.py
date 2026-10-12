#!/usr/bin/env python3
"""B-778 gap-fade confirmation harness (research only, no main.py edit).

Re-runs the Elder exhaustion-gap fade (gaps__exhaust_fade, nb 3/4/5, both directions) and the common-gap fade
(control) on the FULL NSE universe (main._load_nse_universe_from_file()) with the SAME simulator as
elder_macd_dirgap_research (stop on every trade, 0.8% cost, one position per symbol), but:
  * emits gross AND net PFnet, win %, avg hold bars, exit reasons for every cell (the run 38145684388 table omitted gross);
  * tags are v2 (`...__v2`), so the registered v1 numbers stay untouched (new run = new tag);
  * takes --interval so the candle-size sweep (1d, 1h, 15m, 5m) is one dispatch input; bar-count constants (nb, 30-bar
    max hold) change meaning with the interval.
  * strict non-overlap FIFO per symbol (fifo_filter: a trade is kept only if its entry bar is after the last kept exit);
  * chronological IS/OOS split at IS_FRAC (0.6) of each symbol's bars, by SIGNAL bar: every cell is emitted pooled
    (`...atr3_nb5__v2`) AND as `...atr3_nb5_segis__v2` / `...atr3_nb5_segoos__v2` so the 1.246 claim can be checked out of sample.
Owed after the run: compare v2 vs v1 (n=4404, PFnet 1.246 for atr3_nb5 long 1d); decide short-hold wiring, which needs a
live entry path with an always-attached stop and a main.py-calling replay (main has gap_up_fade_entry_signal_short, a
different rule, so it is NOT a substitute).
Usage: python3 scripts/gap_fade_confirm.py --shard 0 --nshards 4 --interval 1d --period 5y --out out/
       python3 scripts/gap_fade_confirm.py --merge out/ --json results.json
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import elder_indicators_research as er  # noqa: E402
import elder_macd_dirgap_research as g  # noqa: E402

VARIANTS = ("exhaust_fade", "common_fade")
NBS = (3, 4, 5)
IS_FRAC = 0.6


def fifo_filter(trades):
    """Strict FIFO: entry bar = s+1, exit bar = s+hold; keep a trade only if it enters after the last kept exit."""
    kept, last_exit = [], -1
    for t in sorted(trades, key=lambda x: x["s"]):
        e = t["s"] + 1
        if e <= last_exit:
            continue
        kept.append(t)
        last_exit = e + t["hold"] - 1
    return kept


def has_overlap(trades):
    return len(fifo_filter(trades)) != len(trades)


def specs():
    return [(v, p, fn, m) for v, p, fn, m in g.variant_specs("gaps") if v in VARIANTS and p.get("nb") in NBS]


def run_symbol(df, tf, aggs):
    for variant, params, fn, mgmt in specs():
        try:
            sig = fn(df)
        except Exception as ex:  # noqa: BLE001
            print("VARIANT ERROR", variant, ex, file=sys.stderr)
            continue
        for direction in ("long", "short"):
            if not sig[direction].any():
                continue
            for am in er.ATR_MULTS:
                trades = fifo_filter(er.simulate(df, sig, direction, am, mgmt))
                cut = int(len(df) * IS_FRAC)
                for seg, sel in (("", trades), ("is", [x for x in trades if x["s"] < cut]),
                                 ("oos", [x for x in trades if x["s"] >= cut])):
                    p = {**params, "atr": am, **({"seg": seg} if seg else {})}
                    tag = er.make_tag("gaps", variant, direction, tf, p, version=2)
                    er.add_trades(aggs.setdefault(tag, er.new_agg()), sel)


def _shard(a):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import main as m
    syms = sorted(set(m._load_nse_universe_from_file()))
    syms = [s for k, s in enumerate(syms) if k % a.nshards == a.shard]
    aggs, fetched = {}, 0
    for s in syms:
        try:
            raw = m.fetch_ohlc(s, a.period, a.interval)
            if raw is None or len(raw) < 120:
                continue
            run_symbol(er.prep(raw), a.interval, aggs)
            fetched += 1
        except Exception as ex:  # noqa: BLE001
            print("ERROR", s, ex, file=sys.stderr)
    os.makedirs(a.out, exist_ok=True)
    json.dump({"fetched": fetched, "universe": len(syms), "interval": a.interval, "aggs": aggs},
              open(os.path.join(a.out, f"gapfade_{a.shard}.json"), "w"))
    print(f"shard {a.shard}: fetched {fetched}/{len(syms)}, cells {len(aggs)}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--nshards", type=int, default=4)
    ap.add_argument("--interval", default="1d")
    ap.add_argument("--period", default="5y")
    ap.add_argument("--out", default="out")
    ap.add_argument("--merge")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    if a.merge:
        import elder_lab_driver as drv
        return drv.run(["--merge", a.merge] + (["--json", a.json] if a.json else []), (), None)
    _shard(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
