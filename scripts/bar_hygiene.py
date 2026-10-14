"""Shared vendor-glitch bar cleaning for research replays (B-1110).

Same rule as scripts/pattern_lab.py / minervini_lab.py / oneil_research.py clean_bars: drop bars whose open/close fall
outside the bar's range, absurd ranges (high/low >= 1.6) or >35% close-to-close jumps. A bad open print once produced
+900% 'trades' and PFnet 6.2 (2026-10-10 IST). The pl1d and sector_rotation replays read raw yfinance frames and had no
such guard. Cleaning is counted, never silent: callers write bars_dropped into their output JSON so the effect is visible.
"""
import pandas as pd


def clean_bars(df, max_move=0.35):
    o, h, l, c = df["Open"], df["High"], df["Low"], df["Close"]
    ok = (o <= h * 1.001) & (o >= l * 0.999) & (c <= h * 1.001) & (c >= l * 0.999) & (l > 0) & ((h / l) < 1.6)
    jump = (c / c.shift(1) - 1).abs() > max_move
    return df[ok & ~jump.fillna(False)]


def clean_frames(frames, max_move=0.35):
    """{sym: df} -> ({sym: cleaned df with fresh RangeIndex}, total bars dropped). Symbols left too short are kept as-is
    (the caller's own minimum-length check decides)."""
    out, dropped = {}, 0
    for s, f in frames.items():
        g = clean_bars(f, max_move)
        dropped += len(f) - len(g)
        out[s] = g.reset_index(drop=True)
    return out, dropped
