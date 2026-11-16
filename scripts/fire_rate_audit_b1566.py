"""B-1566 fire-rate audit: how often SHOULD each live cell fire? Replays the LIVE main.py entry functions bar by bar over
the last N completed NSE sessions (default 5) on the live scan universes, with the same frames the bot builds:
  - chan_kalman band long/short 5m + 15m (buy / short engines): fetch_ohlc(sym, "5d"-style window, iv) -> the 5 sessions
    ending at the bar, _chan_short_frame, _chan_live_masks, chan_kalman_series, entries only 09:15 <= bar < 15:00 IST.
  - 1h swing long cells (macddiv, brk20 1h, chan_kalman 1h): _hourly_with_str_date(fetch_ohlc(sym, "60d", "1h")) prefixes.
  - power_play (daily swing): fetch_ohlc(sym, "2y", "1d") prefixes.
A signal is counted on every bar whose prefix returns a signal (gates/viability NOT applied: this measures raw fires, the
number the live scans_today / fired counters should be near). Output docs/fire_rate_audit_b1566.json: per cell bar fires,
distinct (symbol, session) fires, fires per session, symbols. Compare with the live /strategy counters: a cell expected
to fire that shows 0 live is a wiring bug. Env: SESSIONS (default 5; via sector-rotation-backtest.yml pass it in the
`ks` input, which that workflow exports as KS), UNI_LIMIT (0 = all), BOT_URL (default: the live bot when run on Actions).
Live comparison: GET BOT_URL/entry-funnel (balance-free) per tag {scans, fired, blocked_triggers, attempts}; with
SESSIONS=1 run after the close on the same IST day, a cell expected >= 1 fire whose live fired + blocked is 0 is marked
SUSPECT_WIRING. Runs on GitHub Actions via sector-rotation-backtest.yml (script input); Yahoo and Render are not reachable
from the dev container."""
import json
import os
import sys
import time
from collections import defaultdict

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main  # noqa: E402

_KS = os.environ.get("KS", "")
SESSIONS = int(os.environ.get("SESSIONS") or (_KS if _KS.isdigit() else "5"))
BOT_URL = os.environ.get("BOT_URL") or ("https://tv-paper-bot-gdan.onrender.com" if os.environ.get("GITHUB_ACTIONS") else "")
_LIVE_KEYS = ("scans", "fired", "blocked_triggers", "attempts", "blocked_by_position")  # B-1566: + held elsewhere
UNI_LIMIT = int(os.environ.get("UNI_LIMIT", "0"))
OUT = "docs/fire_rate_audit_b1566.json"
IST = "Asia/Kolkata"


def _utc(d):
    t = pd.to_datetime(d["Date"])
    return t.dt.tz_convert("UTC") if t.dt.tz is not None else t.dt.tz_localize("UTC")


def _chan_cells(iv):
    out = [("long", t, c) for t, c in main.CHAN_LONG_CELLS.items() if main.CHAN_LONG_CELL_INTERVAL[t] == iv]
    out += [("short", t, c) for t, c in main.CHAN_SHORT_CELLS.items() if main.CHAN_SHORT_CELL_INTERVAL[t] == iv]
    return out


def chan_fires(sym, iv, acc):
    d = main.fetch_ohlc(sym, "15d" if iv == "5m" else "30d", iv)
    if d is None or len(d) < 40:
        return
    ts = _utc(d)
    dfa = main._chan_short_frame(d.reset_index(drop=True), ts)
    loc = dfa.index.tz_convert(IST)
    days = sorted(set(loc.date))
    cells = _chan_cells(iv)
    for day in days[-SESSIONS:]:
        k = days.index(day)
        win = [x for x in days[max(0, k - 4): k + 1]]  # live frame = fetch_ohlc(sym, "5d", iv): 5 sessions ending today
        sel = pd.Series(loc.date).isin(win).to_numpy()
        w = dfa[sel]
        wl = loc[sel]
        ks = {}
        for i in range(len(w)):
            if wl[i].date() != day:
                continue
            mins = wl[i].hour * 60 + wl[i].minute
            if not (9 * 60 + 15 <= mins < main.CHAN_LONG_ENTRY_CUTOFF_MIN):
                continue
            pre = w.iloc[: i + 1]
            masks = main._chan_live_masks(pre.index, iv)
            for side, tag, (a, ve, z) in cells:
                if ve not in ks:
                    ks[ve] = main.chan_kalman_series(w["Close"].to_numpy(float), ve)  # causal: prefix of the window run
                fn = main.chan_kalman_band_long_entry_signal if side == "long" else main.chan_kalman_band_short_entry_signal
                try:
                    sig = fn(pre, iv, z=z, ve=ve, atr_mult=a, ks=ks[ve][: i + 1], masks=masks)
                except Exception:
                    sig = None
                if sig:
                    acc[tag].append((sym, str(day), str(wl[i])))


def h1_fires(sym, acc):
    df = main._hourly_with_str_date(main.fetch_ohlc(sym, "60d", "1h"))
    if df is None or len(df) < 60:
        return
    days = sorted(set(df["Date"].astype(str).str[:10]))[-SESSIONS:]
    fns = [(t, (lambda p, t=t: main.macddiv_long_cell_signal(p, t))) for t in main.MACDDIV_LONG_LIVE_CELLS]
    fns += [(t, (lambda p, t=t: main.brk20_1h_long_entry_signal(p, t))) for t in main.BRK20_1H_LONG_CELLS]
    fns += [(t, (lambda p, t=t: main.chan_kalman_1h_long_entry_signal(p, t))) for t in main.CHAN_KALMAN_1H_CELLS]
    for i in range(len(df)):
        dstr = str(df["Date"].iloc[i])
        if dstr[:10] not in days:
            continue
        pre = df.iloc[: i + 1]
        for tag, fn in fns:
            try:
                sig = fn(pre)
            except Exception:
                sig = None
            if sig:
                acc[tag].append((sym, dstr[:10], dstr))


def d1_fires(sym, acc):
    df = main.fetch_ohlc(sym, "2y", "1d")
    if df is None or len(df) < 120:
        return
    for i in range(len(df) - SESSIONS, len(df)):
        try:
            sig = main.power_play_entry_signal(df.iloc[: i + 1])
        except Exception:
            sig = None
        if sig:
            acc["power_play"].append((sym, str(df["Date"].iloc[i])[:10], str(df["Date"].iloc[i])))


def live_counts(url=None):
    """{day, tags: {tag: {scans, fired, blocked_triggers, attempts}}} from the bot's /entry-funnel (max over categories,
    since one tag can sit in several). None when no URL; {"_error": ...} when the bot does not answer."""
    url = BOT_URL if url is None else url
    if not url:
        return None
    import urllib.request
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/entry-funnel", timeout=180) as r:
            d = json.load(r)
    except Exception as e:
        return {"_error": str(e)[:200]}
    tags = {}
    for o in (d.get("categories") or {}).values():
        for r in (o.get("strategies") or []) + (o.get("no_signal_strategies") or []):
            x = tags.setdefault(str(r.get("strategy")), dict.fromkeys(_LIVE_KEYS, 0))
            for k in _LIVE_KEYS:
                x[k] = max(x[k], int(r.get(k) or 0))
    return {"day": d.get("day"), "tags": tags}


def verdict(row, live, last_day):
    """SUSPECT_WIRING / ok / n/a for one row (see the module docstring)."""
    if not live or "tags" not in live or SESSIONS != 1 or live.get("day") != last_day:
        return "n/a"
    lv = live["tags"].get(row["tag"])
    if row["symbol_session_fires"] < 1:
        return "ok"
    if lv is None or (lv["fired"] + lv["blocked_triggers"] + lv["attempts"] + lv.get("blocked_by_position", 0)) == 0:
        return "SUSPECT_WIRING"
    return "ok"


def main_run():
    t0 = time.time()
    acc = defaultdict(list)
    intraday = list(main.NSE_FULL_UNIVERSE)
    swing = list(main.SWING_WATCHLIST)
    if UNI_LIMIT:
        intraday, swing = intraday[:UNI_LIMIT], swing[:UNI_LIMIT]
    errs = 0
    for n, sym in enumerate(intraday):
        for iv in ("5m", "15m"):
            try:
                chan_fires(sym, iv, acc)
            except Exception as e:
                errs += 1
                print(f"[chan {iv}] {sym}: {e}")
        if n % 20 == 0:
            print(f"intraday {n}/{len(intraday)} {time.time() - t0:.0f}s", flush=True)
    for n, sym in enumerate(swing):
        for f in (h1_fires, d1_fires):
            try:
                f(sym, acc)
            except Exception as e:
                errs += 1
                print(f"[{f.__name__}] {sym}: {e}")
        if n % 20 == 0:
            print(f"swing {n}/{len(swing)} {time.time() - t0:.0f}s", flush=True)
    tags = ([t for _s, t, _c in _chan_cells("5m") + _chan_cells("15m")] + list(main.MACDDIV_LONG_LIVE_CELLS)
            + list(main.BRK20_1H_LONG_CELLS) + list(main.CHAN_KALMAN_1H_CELLS) + ["power_play"])
    rows, live = [], live_counts()
    last_day = max((d for ev in acc.values() for _s, d, _b in ev), default=None)
    for t in tags:
        ev = acc.get(t, [])
        sd = {(s, d) for s, d, _b in ev}
        rows.append({"tag": t, "bar_fires": len(ev), "symbol_session_fires": len(sd),
                     "per_session": round(len(sd) / SESSIONS, 2), "symbols": sorted({s for s, _d in sd})[:50],
                     "first": ev[:5]})
        rows[-1]["live"] = (live or {}).get("tags", {}).get(t) if live else None
        rows[-1]["verdict"] = verdict(rows[-1], live, last_day)
    out = {"run": os.environ.get("GITHUB_RUN_ID", "local"), "sessions": SESSIONS,
           "universe_intraday": len(intraday), "universe_swing": len(swing), "errors": errs,
           "secs": round(time.time() - t0), "live_day": (live or {}).get("day"), "live_error": (live or {}).get("_error"),
           "last_session": last_day, "rows": rows}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w"), indent=1)
    for r in rows:
        print(f"{r['tag']:<90} bar {r['bar_fires']:>5} sym-sess {r['symbol_session_fires']:>4} /sess {r['per_session']}"
              f" live {r['live']} {r['verdict']}")


if __name__ == "__main__":
    main_run()
