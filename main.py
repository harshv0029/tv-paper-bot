"""
TradingView Paper Trading Webhook Receiver
-------------------------------------------
Receives TradingView alert webhooks and logs SIMULATED (paper) trades.
No real orders are ever sent to any broker from this app.

Endpoints:
  POST /webhook      -> TradingView posts alerts here
  GET  /positions     -> current simulated open positions
  GET  /trades        -> full trade log
  GET  /pnl           -> realized + unrealized P&L summary
  GET  /health        -> uptime check
  GET  /history       -> historical OHLC data for strategy research/backtesting
                         (this server has real internet access; Claude's own
                         workspace does not, so this is the automatic data path)
"""

import asyncio
import datetime as dt
import json
import math
import os
import sqlite3
import time
from contextlib import closing
from itertools import product

import numpy as np
import pandas as pd
import yfinance as yf

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

DB_PATH = os.environ.get("DB_PATH", "paper_trades.db")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "change-me")
STARTING_CASH = float(os.environ.get("STARTING_CASH", "100000"))  # paper capital

app = FastAPI(title="TradingView Paper Trading Bot")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Allows the dashboard (a page hosted on a different domain) to call /history,
# /backtest, /sweep directly from the browser. Fine for these read-only,
# unauthenticated GET endpoints - /webhook is POST-only and still requires the
# secret, so this does not weaken that.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with closing(get_db()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                symbol TEXT NOT NULL,
                action TEXT NOT NULL,      -- buy | sell
                qty REAL NOT NULL,
                price REAL NOT NULL,
                strategy TEXT,
                raw_payload TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS positions (
                symbol TEXT PRIMARY KEY,
                qty REAL NOT NULL,
                avg_price REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS signal_state (
                symbol TEXT PRIMARY KEY,
                day TEXT NOT NULL,
                status TEXT NOT NULL,   -- 'long'
                entry_price REAL,
                stop_loss REAL,
                target REAL,
                qty REAL,
                entry_ts REAL,
                orb_high REAL,
                orb_low REAL
            )
            """
        )
        conn.commit()


init_db()


class AlertPayload(BaseModel):
    secret: str
    symbol: str
    action: str  # "buy" or "sell"
    qty: float
    price: float
    strategy: str | None = None


def apply_paper_trade(conn, symbol: str, action: str, qty: float, price: float):
    """Update the simulated position book. Simple average-price accounting,
    long-only close-out on sell (extend this if you need shorting)."""
    row = conn.execute(
        "SELECT * FROM positions WHERE symbol = ?", (symbol,)
    ).fetchone()
    cur_qty = row["qty"] if row else 0.0
    cur_avg = row["avg_price"] if row else 0.0

    if action == "buy":
        new_qty = cur_qty + qty
        new_avg = ((cur_qty * cur_avg) + (qty * price)) / new_qty if new_qty else 0.0
    elif action == "sell":
        new_qty = cur_qty - qty
        new_avg = cur_avg if new_qty > 0 else 0.0
    else:
        raise HTTPException(status_code=400, detail="action must be 'buy' or 'sell'")

    conn.execute(
        """
        INSERT INTO positions (symbol, qty, avg_price) VALUES (?, ?, ?)
        ON CONFLICT(symbol) DO UPDATE SET qty = excluded.qty, avg_price = excluded.avg_price
        """,
        (symbol, new_qty, new_avg),
    )


@app.post("/webhook")
async def webhook(request: Request):
    body = await request.body()
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Payload must be JSON")

    payload = AlertPayload(**data)

    if payload.secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Bad secret")

    action = payload.action.lower().strip()
    with closing(get_db()) as conn:
        conn.execute(
            "INSERT INTO trades (ts, symbol, action, qty, price, strategy, raw_payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                time.time(),
                payload.symbol,
                action,
                payload.qty,
                payload.price,
                payload.strategy,
                body.decode("utf-8"),
            ),
        )
        apply_paper_trade(conn, payload.symbol, action, payload.qty, payload.price)
        conn.commit()

    return {"status": "ok", "logged": payload.dict(exclude={"secret"})}


@app.get("/positions")
def positions():
    with closing(get_db()) as conn:
        rows = conn.execute(
            "SELECT symbol, qty, avg_price FROM positions WHERE qty != 0"
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/trades")
def trades(limit: int = 100):
    with closing(get_db()) as conn:
        rows = conn.execute(
            "SELECT id, ts, symbol, action, qty, price, strategy FROM trades "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/pnl")
def pnl():
    """Realized P&L from closed portions of trades, using FIFO-ish average-cost logic
    already applied in positions. This is a simple summary, not tax/accounting grade."""
    with closing(get_db()) as conn:
        trades_rows = conn.execute(
            "SELECT symbol, action, qty, price FROM trades ORDER BY id"
        ).fetchall()

    book: dict[str, dict] = {}
    realized = 0.0
    for t in trades_rows:
        sym = t["symbol"]
        b = book.setdefault(sym, {"qty": 0.0, "avg": 0.0})
        if t["action"] == "buy":
            new_qty = b["qty"] + t["qty"]
            b["avg"] = ((b["qty"] * b["avg"]) + (t["qty"] * t["price"])) / new_qty if new_qty else 0.0
            b["qty"] = new_qty
        elif t["action"] == "sell":
            realized += (t["price"] - b["avg"]) * min(t["qty"], b["qty"])
            b["qty"] -= t["qty"]

    return {
        "starting_cash": STARTING_CASH,
        "realized_pnl": round(realized, 2),
        "open_positions": {k: v for k, v in book.items() if abs(v["qty"]) > 1e-9},
        "note": "Unrealized P&L needs a live price feed — pull latest price per symbol "
                "and compare to avg_price from /positions to compute it.",
    }


@app.get("/history")
def history(symbol: str, period: str = "6mo", interval: str = "1d"):
    """
    Historical OHLC data for strategy research/backtesting.

    symbol   - Yahoo Finance style ticker. Examples:
                 "^NSEI"        -> NIFTY 50 index
                 "^NSEBANK"     -> BANK NIFTY index
                 "RELIANCE.NS"  -> Reliance Industries (NSE)
                 "TCS.NS"       -> TCS (NSE)
    period   - "1mo","3mo","6mo","1y","2y","5y","max"
    interval - "1d","1h","30m","15m","5m" (intraday intervals only return
                recent history - Yahoo limits how far back intraday data goes)
    """
    df = yf.download(symbol, period=period, interval=interval, progress=False)

    if df.empty:
        raise HTTPException(
            status_code=404,
            detail=f"No data for symbol={symbol!r} period={period!r} interval={interval!r}. "
                   f"Check the symbol is a valid Yahoo Finance ticker.",
        )

    # yfinance sometimes returns MultiIndex columns like ('Close', '^NSEI')
    # even for a single symbol - flatten them.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.reset_index()
    date_col = "Date" if "Date" in df.columns else "Datetime"

    records = [
        {
            "date": row[date_col].isoformat(),
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
            "volume": float(row["Volume"]),
        }
        for _, row in df.iterrows()
    ]

    return {
        "symbol": symbol,
        "period": period,
        "interval": interval,
        "count": len(records),
        "data": records,
    }


_DATA_CACHE: dict[tuple, tuple[float, pd.DataFrame]] = {}
_CACHE_TTL_SECONDS = 180  # re-fetch at most every 3 minutes per (symbol, period, interval)


def fetch_ohlc(symbol: str, period: str, interval: str) -> pd.DataFrame:
    """Fetches OHLC data, cached briefly in memory so a sweep of many strategy
    params against the same symbol/period/interval only hits Yahoo Finance once,
    not once per combination."""
    key = (symbol, period, interval)
    now = time.time()

    cached = _DATA_CACHE.get(key)
    if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1].copy()

    df = yf.download(symbol, period=period, interval=interval, progress=False)
    if df.empty:
        raise HTTPException(
            status_code=404,
            detail=f"No data for symbol={symbol!r} period={period!r} interval={interval!r}.",
        )
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index()
    date_col = "Date" if "Date" in df.columns else "Datetime"
    df = df.rename(columns={date_col: "Date"}).dropna(subset=["Open", "High", "Low", "Close"])
    df = df.reset_index(drop=True)

    _DATA_CACHE[key] = (now, df)
    return df.copy()


def add_strategy_signal(df: pd.DataFrame, strategy: str, params: dict) -> pd.DataFrame:
    """Adds a boolean 'long' column: True = want to be long, False = want to be flat.
    Long-only, single-position. Extend here to add more strategies."""
    df = df.copy()

    if strategy == "sma_crossover":
        fast, slow = params["fast"], params["slow"]
        df["fast_ma"] = df["Close"].rolling(fast).mean()
        df["slow_ma"] = df["Close"].rolling(slow).mean()
        df["long"] = df["fast_ma"] > df["slow_ma"]

    elif strategy == "rsi_reversal":
        period = params["rsi_period"]
        oversold, overbought = params["oversold"], params["overbought"]
        delta = df["Close"].diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        rs = gain / loss.replace(0, float("nan"))
        df["rsi"] = 100 - (100 / (1 + rs))

        holding, flags = False, []
        for r in df["rsi"]:
            if pd.notna(r):
                if not holding and r < oversold:
                    holding = True
                elif holding and r > overbought:
                    holding = False
            flags.append(holding)
        df["long"] = flags

    elif strategy in ("orb_breakout", "orb_volume"):
        orb_minutes = int(params.get("orb_minutes", 15))
        sma_fast = int(params.get("sma_fast", 9))
        sma_slow = int(params.get("sma_slow", 21))
        open_min = int(params.get("open_min", 9 * 60 + 15))
        volume_mult = float(params.get("volume_mult", 1.5))

        ts = pd.to_datetime(df["Date"])
        ts_ist = ts.dt.tz_convert("Asia/Kolkata") if ts.dt.tz is not None else ts.dt.tz_localize(
            "UTC"
        ).dt.tz_convert("Asia/Kolkata")
        day = ts_ist.dt.strftime("%Y-%m-%d")
        mins = ts_ist.dt.hour * 60 + ts_ist.dt.minute

        df["fast_ma"] = df["Close"].rolling(sma_fast).mean()
        df["slow_ma"] = df["Close"].rolling(sma_slow).mean()
        trend_up = df["fast_ma"] > df["slow_ma"]

        in_orb_window = (mins >= open_min) & (mins < open_min + orb_minutes)
        orb_high = df["High"].where(in_orb_window).groupby(day).transform("max")
        orb_high = orb_high.groupby(day).ffill()  # holds the ORB high for the rest of that day

        after_orb = mins >= open_min + orb_minutes
        raw = (df["Close"] > orb_high) & after_orb & trend_up.fillna(False)

        if strategy == "orb_volume":
            vol_avg = df["Volume"].rolling(20).mean()
            raw = raw & (df["Volume"] > vol_avg * volume_mult)

        # Once triggered, stay long for the rest of that trading day (flat overnight).
        df["long"] = raw.groupby(day).cummax()

    elif strategy == "vwap_reclaim":
        ts = pd.to_datetime(df["Date"])
        ts_ist = ts.dt.tz_convert("Asia/Kolkata") if ts.dt.tz is not None else ts.dt.tz_localize(
            "UTC"
        ).dt.tz_convert("Asia/Kolkata")
        day = ts_ist.dt.strftime("%Y-%m-%d")

        typical = (df["High"] + df["Low"] + df["Close"]) / 3
        pv = typical * df["Volume"]
        cum_pv = pv.groupby(day).cumsum()
        cum_vol = df["Volume"].groupby(day).cumsum().replace(0, float("nan"))
        vwap = cum_pv / cum_vol

        raw = df["Close"] > vwap
        df["long"] = raw.groupby(day).cummax()
        df["vwap"] = vwap

    elif strategy == "macd_cross":
        fast_span = int(params.get("macd_fast", 12))
        slow_span = int(params.get("macd_slow", 26))
        signal_span = int(params.get("macd_signal", 9))
        ema_fast = df["Close"].ewm(span=fast_span, adjust=False).mean()
        ema_slow = df["Close"].ewm(span=slow_span, adjust=False).mean()
        macd = ema_fast - ema_slow
        signal_line = macd.ewm(span=signal_span, adjust=False).mean()
        df["long"] = macd > signal_line

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown strategy {strategy!r}. Supported: sma_crossover, rsi_reversal, "
                   f"orb_breakout, orb_volume, vwap_reclaim, macd_cross",
        )

    return df.dropna(subset=["long"]).reset_index(drop=True)


def extract_trades_fast(
    long_arr: np.ndarray, close_arr: np.ndarray, dates: np.ndarray, qty: float
) -> tuple[list[dict], dict | None]:
    """Vectorized (numpy, no Python row loop) version of trade extraction -
    entries/exits found via array shifts instead of iterating. This is the
    version used by the sweep endpoint, since it runs once per parameter
    combination and needs to stay fast even for thousands of combinations."""
    shifted = np.roll(long_arr, 1)
    shifted[0] = False
    entries = np.where(long_arr & ~shifted)[0]
    exits = np.where(~long_arr & shifted)[0]

    n_closed = min(len(entries), len(exits))
    closed_entries = entries[:n_closed]
    closed_exits = exits[:n_closed]

    entry_prices = close_arr[closed_entries]
    exit_prices = close_arr[closed_exits]
    pnls = (exit_prices - entry_prices) * qty

    trades = [
        {
            "entry_date": str(dates[e]),
            "entry_price": round(float(entry_prices[i]), 4),
            "exit_date": str(dates[x]),
            "exit_price": round(float(exit_prices[i]), 4),
            "pnl": round(float(pnls[i]), 2),
        }
        for i, (e, x) in enumerate(zip(closed_entries, closed_exits))
    ]

    open_position = None
    if len(entries) > n_closed:
        last_entry_idx = entries[n_closed]
        last_price = float(close_arr[-1])
        entry_price = float(close_arr[last_entry_idx])
        open_position = {
            "entry_date": str(dates[last_entry_idx]),
            "entry_price": entry_price,
            "current_price": last_price,
            "unrealized_pnl": round((last_price - entry_price) * qty, 2),
        }

    return trades, open_position


def extract_trades(df: pd.DataFrame, qty: float) -> tuple[list[dict], dict | None]:
    """Convenience wrapper for a single ad-hoc backtest (/backtest)."""
    long_arr = df["long"].to_numpy()
    close_arr = df["Close"].to_numpy(dtype=float)
    dates = df["Date"].apply(lambda d: d.isoformat()).to_numpy()
    return extract_trades_fast(long_arr, close_arr, dates, qty)


@app.get("/backtest")
def backtest(
    symbol: str,
    period: str = "7d",
    interval: str = "1m",
    strategy: str = "sma_crossover",
    fast: int = 5,
    slow: int = 20,
    rsi_period: int = 14,
    oversold: float = 30,
    overbought: float = 70,
    orb_minutes: int = 15,
    sma_fast: int = 9,
    sma_slow: int = 21,
    open_min: int = 9 * 60 + 15,
    volume_mult: float = 1.5,
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal: int = 9,
    qty: float = 1,
):
    """
    Runs a long-only backtest server-side (real internet + pandas live here)
    and returns just the results - keeps responses small regardless of how
    many bars were analyzed.

    strategy=sma_crossover        -> params: fast, slow
    strategy=rsi_reversal         -> params: rsi_period, oversold, overbought
    strategy=orb_breakout/orb_volume -> params: orb_minutes, sma_fast, sma_slow,
                                        open_min (orb_volume also: volume_mult)
    strategy=vwap_reclaim         -> no extra params
    strategy=macd_cross           -> params: macd_fast, macd_slow, macd_signal
    """
    df = fetch_ohlc(symbol, period, interval)

    if strategy == "sma_crossover":
        params = {"fast": fast, "slow": slow}
    elif strategy == "rsi_reversal":
        params = {"rsi_period": rsi_period, "oversold": oversold, "overbought": overbought}
    elif strategy in ("orb_breakout", "orb_volume"):
        params = {
            "orb_minutes": orb_minutes, "sma_fast": sma_fast, "sma_slow": sma_slow,
            "open_min": open_min, "volume_mult": volume_mult,
        }
    elif strategy == "vwap_reclaim":
        params = {}
    elif strategy == "macd_cross":
        params = {"macd_fast": macd_fast, "macd_slow": macd_slow, "macd_signal": macd_signal}
    else:
        params = {}

    df = add_strategy_signal(df, strategy, params)
    trades, open_position = extract_trades(df, qty)

    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    total_pnl = round(sum(t["pnl"] for t in trades), 2)

    return {
        "symbol": symbol,
        "period": period,
        "interval": interval,
        "strategy": strategy,
        "params": params,
        "bars_used": len(df),
        "num_trades": len(trades),
        "win_rate_pct": round(100 * len(wins) / len(trades), 1) if trades else None,
        "total_pnl": total_pnl,
        "avg_win": round(sum(t["pnl"] for t in wins) / len(wins), 2) if wins else None,
        "avg_loss": round(sum(t["pnl"] for t in losses) / len(losses), 2) if losses else None,
        "open_position": open_position,
        "last_10_trades": trades[-10:],
    }


MAX_SWEEP_COMBINATIONS = 3000


def _parse_num_list(raw: str, cast) -> list:
    try:
        return [cast(x.strip()) for x in raw.split(",") if x.strip() != ""]
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Could not parse number list: {raw!r}")


@app.get("/sweep")
def sweep(
    symbol: str,
    period: str = "7d",
    interval: str = "1m",
    strategy: str = "sma_crossover",
    qty: float = 1,
    rank_by: str = "total_pnl",  # total_pnl | win_rate_pct | num_trades
    top_n: int = 15,
    # sma_crossover params - comma-separated lists, e.g. fast=3,5,8,10
    fast: str = "5,10,15,20",
    slow: str = "20,50,100,150",
    # rsi_reversal params - comma-separated lists
    rsi_period: str = "7,14,21",
    oversold: str = "20,25,30",
    overbought: str = "70,75,80",
    # orb_breakout / orb_volume params - comma-separated lists
    orb_minutes: str = "5,15,30",
    sma_fast: str = "5,9,20",
    sma_slow: str = "20,21,50",
    volume_mult: str = "1.2,1.5,2.0",
):
    """
    Tests every combination of the given parameter lists against ONE fetch of
    the data (cached), and returns only the ranked summary - not every trade
    from every combination - so this stays fast and the response stays small
    even for thousands of combinations.

    Example (sma_crossover): fetch OHLC once, then test every (fast, slow)
    pair where fast in {5,10,15,20} and slow in {20,50,100,150} = 16 runs.
    """
    df = fetch_ohlc(symbol, period, interval)
    close_arr = df["Close"].to_numpy(dtype=float)
    dates = df["Date"].apply(lambda d: d.isoformat()).to_numpy()

    if strategy == "sma_crossover":
        fast_list = _parse_num_list(fast, int)
        slow_list = _parse_num_list(slow, int)
        combos = [
            {"fast": f, "slow": s} for f, s in product(fast_list, slow_list) if f < s
        ]
    elif strategy == "rsi_reversal":
        rp_list = _parse_num_list(rsi_period, int)
        os_list = _parse_num_list(oversold, float)
        ob_list = _parse_num_list(overbought, float)
        combos = [
            {"rsi_period": rp, "oversold": o, "overbought": b}
            for rp, o, b in product(rp_list, os_list, ob_list)
            if o < b
        ]
    elif strategy in ("orb_breakout", "orb_volume"):
        om_list = _parse_num_list(orb_minutes, int)
        sf_list = _parse_num_list(sma_fast, int)
        ss_list = _parse_num_list(sma_slow, int)
        if strategy == "orb_volume":
            vm_list = _parse_num_list(volume_mult, float)
            combos = [
                {"orb_minutes": om, "sma_fast": sf, "sma_slow": ss, "volume_mult": vm}
                for om, sf, ss, vm in product(om_list, sf_list, ss_list, vm_list)
                if sf < ss
            ]
        else:
            combos = [
                {"orb_minutes": om, "sma_fast": sf, "sma_slow": ss}
                for om, sf, ss in product(om_list, sf_list, ss_list)
                if sf < ss
            ]
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown strategy {strategy!r}. Supported: sma_crossover, rsi_reversal, "
                   f"orb_breakout, orb_volume",
        )

    if not combos:
        raise HTTPException(status_code=400, detail="No valid parameter combinations (check your ranges).")
    if len(combos) > MAX_SWEEP_COMBINATIONS:
        raise HTTPException(
            status_code=400,
            detail=f"{len(combos)} combinations requested, max is {MAX_SWEEP_COMBINATIONS}. "
                    f"Narrow your ranges or split into multiple sweep calls.",
        )

    results = []
    for params in combos:
        sig_df = add_strategy_signal(df, strategy, params)
        long_arr = sig_df["long"].to_numpy()
        aligned_close = sig_df["Close"].to_numpy(dtype=float)
        aligned_dates = sig_df["Date"].apply(lambda d: d.isoformat()).to_numpy()

        trades, _ = extract_trades_fast(long_arr, aligned_close, aligned_dates, qty)
        if not trades:
            continue

        wins = [t for t in trades if t["pnl"] > 0]
        total_pnl = round(sum(t["pnl"] for t in trades), 2)
        results.append({
            "params": params,
            "num_trades": len(trades),
            "win_rate_pct": round(100 * len(wins) / len(trades), 1),
            "total_pnl": total_pnl,
        })

    if rank_by not in ("total_pnl", "win_rate_pct", "num_trades"):
        raise HTTPException(status_code=400, detail="rank_by must be total_pnl, win_rate_pct, or num_trades")

    results.sort(key=lambda r: r[rank_by], reverse=True)

    all_pnls = [r["total_pnl"] for r in results]
    summary = {
        "combinations_tested": len(combos),
        "combinations_with_trades": len(results),
        "median_total_pnl": round(float(np.median(all_pnls)), 2) if all_pnls else None,
        "pct_profitable_combos": round(100 * sum(1 for p in all_pnls if p > 0) / len(all_pnls), 1) if all_pnls else None,
    }

    return {
        "symbol": symbol,
        "period": period,
        "interval": interval,
        "strategy": strategy,
        "bars_used": len(df),
        "rank_by": rank_by,
        "summary": summary,
        "top_results": results[:top_n],
        "note": (
            "Testing many parameter combinations on ONE historical window risks "
            "overfitting - the single best combo here may just be curve-fit noise. "
            "Look at 'median_total_pnl' and 'pct_profitable_combos' too: a strategy "
            "where most nearby parameter combos are also profitable is more trustworthy "
            "than one lone spike at the top. Validate top candidates on a different "
            "date range before trusting them."
        ),
    }


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_price(S: float, K: float, T: float, r: float, sigma: float, option_type: str) -> float:
    """Black-Scholes European option price. Falls back to intrinsic value at/after
    expiry or for degenerate (zero) vol."""
    if T <= 0 or sigma <= 0:
        return max(S - K, 0.0) if option_type == "C" else max(K - S, 0.0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if option_type == "C":
        return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def parse_legs(legs_str: str) -> list[dict]:
    """Parses 'TYPE:ACTION:OFFSET,...' e.g. 'C:buy:0.0,C:sell:0.03'.
    TYPE: C=call, P=put, U=underlying (long only). OFFSET: strike = spot*(1+OFFSET)."""
    legs = []
    for part in legs_str.split(","):
        typ, action, offset = part.split(":")
        legs.append({"type": typ.strip().upper(), "action": action.strip().lower(), "offset": float(offset)})
    return legs


def run_options_backtest(
    df: pd.DataFrame, legs: list[dict], expiry_days: int, iv_mode: str, r: float, step_days: int
) -> dict:
    """Rolling-window backtest: every `step_days` trading days, opens the given
    multi-leg structure priced via Black-Scholes at that day's spot/vol, holds to
    `expiry_days` later, settles at intrinsic value against the actual historical
    close. This is a MODEL ESTIMATE (no historical options-chain data source is
    wired in) - useful for comparing strategy structures against real underlying
    price history, not a substitute for real fill/IV data."""
    closes = df["Close"].to_numpy(dtype=float)
    dates = df["Date"].apply(lambda d: d.isoformat()).to_numpy()
    n = len(closes)
    log_ret = np.diff(np.log(closes))
    T = expiry_days / 365.0

    def leg_strike(spot: float, leg: dict) -> float:
        return spot * (1 + leg["offset"])

    def classify_risk() -> str:
        has_underlying = any(l["type"] == "U" for l in legs)
        call_sells = [l for l in legs if l["type"] == "C" and l["action"] == "sell"]
        call_buys = [l for l in legs if l["type"] == "C" and l["action"] == "buy"]
        put_sells = [l for l in legs if l["type"] == "P" and l["action"] == "sell"]
        put_buys = [l for l in legs if l["type"] == "P" and l["action"] == "buy"]
        naked_calls = call_sells and not call_buys and not has_underlying
        naked_puts = put_sells and not put_buys
        covered_calls = call_sells and not call_buys and has_underlying and not put_buys
        if naked_calls or naked_puts:
            return "large/undefined (naked short exposure)"
        if covered_calls:
            return "large (covered by underlying - same downside as holding it outright)"
        return "defined/capped"

    def structure_pnl(spot_entry: float, spot_exit: float, sigma: float, entry_cf: float) -> float:
        expiry_cf, underlying_pnl = 0.0, 0.0
        for leg in legs:
            if leg["type"] == "U":
                underlying_pnl += spot_exit - spot_entry
                continue
            K = leg_strike(spot_entry, leg)
            payoff = max(spot_exit - K, 0.0) if leg["type"] == "C" else max(K - spot_exit, 0.0)
            expiry_cf += -payoff if leg["action"] == "sell" else payoff
        return entry_cf + expiry_cf + underlying_pnl

    trades = []
    i = 60
    while i + expiry_days < n:
        S0 = float(closes[i])
        if iv_mode == "realized":
            window = log_ret[max(0, i - 20): i]
            sigma = float(np.std(window) * math.sqrt(252)) if len(window) > 5 else 0.14
            sigma = max(sigma, 0.05)
        else:
            sigma = 0.14

        entry_cf = 0.0
        for leg in legs:
            if leg["type"] == "U":
                continue
            K = leg_strike(S0, leg)
            premium = bs_price(S0, K, T, r, sigma, leg["type"])
            entry_cf += premium if leg["action"] == "sell" else -premium

        ST = float(closes[i + expiry_days])
        pnl = structure_pnl(S0, ST, sigma, entry_cf)
        trades.append({
            "entry_date": str(dates[i]),
            "entry_spot": round(S0, 2),
            "expiry_date": str(dates[i + expiry_days]),
            "expiry_spot": round(ST, 2),
            "iv_used_pct": round(sigma * 100, 2),
            "pnl_points": round(pnl, 2),
        })
        i += step_days

    if not trades:
        return {"trades": [], "summary": None}

    pnls = np.array([t["pnl_points"] for t in trades])
    equity = np.cumsum(pnls)
    max_dd = float((equity - np.maximum.accumulate(equity)).min())

    # Crude worst-case risk proxy: reprice the same structure at the last entry
    # spot/flat-IV and evaluate payoff at extreme moves (halved / doubled spot).
    S0_ref = float(closes[max(i - step_days, 0)])
    entry_cf_ref = 0.0
    for leg in legs:
        if leg["type"] == "U":
            continue
        K = leg_strike(S0_ref, leg)
        entry_cf_ref += bs_price(S0_ref, K, T, r, 0.14, leg["type"]) * (1 if leg["action"] == "sell" else -1)
    worst = min(
        structure_pnl(S0_ref, S0_ref * 0.5, 0.14, entry_cf_ref),
        structure_pnl(S0_ref, S0_ref * 2.0, 0.14, entry_cf_ref),
    )

    summary = {
        "trades_count": len(trades),
        "win_rate_pct": round(100 * float((pnls > 0).mean()), 1),
        "avg_pnl_points": round(float(pnls.mean()), 2),
        "total_pnl_points": round(float(pnls.sum()), 2),
        "max_drawdown_points": round(max_dd, 2),
        "best_trade_points": round(float(pnls.max()), 2),
        "worst_trade_points": round(float(pnls.min()), 2),
        "max_loss_proxy_points": round(float(worst), 2),
        "risk": classify_risk(),
    }
    return {"trades": trades[-3:], "summary": summary}


@app.get("/options-backtest")
def options_backtest_endpoint(
    symbol: str,
    legs: str,
    expiry_days: int = 15,
    iv_mode: str = "realized",
    lookback: str = "2y",
    step_days: int = 5,
    r: float = 0.0525,
):
    """
    Rolling-window historical backtest for a multi-leg options strategy, priced
    with Black-Scholes. No historical options-chain data source is wired in -
    this simulates fair-value premiums against the underlying's REAL price
    history (yfinance), it does not replay actual historical option prices.

    legs     - comma-separated TYPE:ACTION:OFFSET, e.g. "C:buy:0.0,C:sell:0.03"
               TYPE: C=call, P=put, U=underlying (long only)
               ACTION: buy | sell
               OFFSET: strike = spot_at_entry * (1 + OFFSET)
    iv_mode  - "realized" (trailing 20-day realized vol, annualized) or "flat14"
    """
    df = fetch_ohlc(symbol, lookback, "1d")
    parsed_legs = parse_legs(legs)
    result = run_options_backtest(df, parsed_legs, expiry_days, iv_mode, r, step_days)

    closes = df["Close"].to_numpy(dtype=float)
    log_ret = np.diff(np.log(closes))
    spot = float(closes[-1])
    sma20 = float(np.mean(closes[-20:]))
    sma50 = float(np.mean(closes[-50:])) if len(closes) >= 50 else None
    realized_vol_20d = float(np.std(log_ret[-20:]) * math.sqrt(252)) if len(log_ret) >= 20 else None
    trend_60d_pct = float((closes[-1] / closes[-60] - 1) * 100) if len(closes) >= 60 else None

    return {
        "symbol": symbol,
        "legs": parsed_legs,
        "params": {"expiry_days": expiry_days, "iv_mode": iv_mode, "lookback": lookback, "step_days": step_days},
        "current": {
            "spot": round(spot, 2),
            "sma20": round(sma20, 2),
            "sma50": round(sma50, 2) if sma50 else None,
            "realized_vol_20d_pct": round(realized_vol_20d * 100, 2) if realized_vol_20d else None,
            "trend_60d_pct": round(trend_60d_pct, 2) if trend_60d_pct else None,
        },
        "backtest": result["summary"],
        "sample_trades": result["trades"],
    }


IST_OFFSET_MIN = 330  # UTC+5:30, no holiday calendar
ORB_STRATEGY_PREFIX = "orb-"


def ist_now() -> dt.datetime:
    return dt.datetime.utcnow() + dt.timedelta(minutes=IST_OFFSET_MIN)


def ist_midnight_epoch(now_ist: dt.datetime) -> float:
    midnight_ist = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
    midnight_utc = midnight_ist - dt.timedelta(minutes=IST_OFFSET_MIN)
    return midnight_utc.replace(tzinfo=dt.timezone.utc).timestamp()


def today_realized_pnl(conn, since_ts: float) -> float:
    """Realized P&L today across all auto-signal ('orb-*') trades, all symbols -
    this is the shared capital/risk pool the daily loss cap applies to.

    Builds the cost-basis book from the FULL trade history (not just today's
    rows) so a position opened before today's cutoff still has a correct avg
    price - needed for any market whose session can span the IST midnight
    boundary (e.g. US markets, ~19:00-01:30 IST), where the entry and exit
    would otherwise land in different day-buckets and this would wrongly
    treat the exit as a sell with no matching buy. Only sells at/after
    `since_ts` count toward the returned figure."""
    all_trades = conn.execute(
        "SELECT symbol, action, qty, price, ts FROM trades WHERE strategy LIKE ? ORDER BY id",
        (ORB_STRATEGY_PREFIX + "%",),
    ).fetchall()
    book: dict[str, dict] = {}
    realized = 0.0
    for t in all_trades:
        b = book.setdefault(t["symbol"], {"qty": 0.0, "avg": 0.0})
        if t["action"] == "buy":
            new_qty = b["qty"] + t["qty"]
            b["avg"] = ((b["qty"] * b["avg"]) + (t["qty"] * t["price"])) / new_qty if new_qty else 0.0
            b["qty"] = new_qty
        else:
            pnl = (t["price"] - b["avg"]) * min(t["qty"], b["qty"])
            if t["ts"] >= since_ts:
                realized += pnl
            b["qty"] -= t["qty"]
    return realized


def deployed_notional(conn) -> float:
    """Capital currently tied up in open auto-signal positions, across all
    symbols - capital is shared and finite (only Rs 2L total), so this caps
    how much a new entry can size into regardless of that trade's own risk
    budget. Without this, two symbols breaking out in the same poll cycle
    could each size a full position independently and jointly overspend the
    account."""
    rows = conn.execute(
        "SELECT qty, entry_price FROM signal_state WHERE status = 'long'"
    ).fetchall()
    return sum(r["qty"] * r["entry_price"] for r in rows)


def _auto_signal_core(
    symbol: str,
    capital: float = 200000,
    daily_risk_pct: float = 2.0,
    risk_per_trade_pct: float = 2.0,
    stop_pct: float = 2.0,
    rr: float = 2.0,
    orb_minutes: int = 15,
    sma_fast: int = 9,
    sma_slow: int = 21,
    interval: str = "5m",
    tz_offset_min: int = IST_OFFSET_MIN,
    open_min: int = 9 * 60 + 15,
    close_min: int = 15 * 60 + 30,
    squareoff_min: int = 15 * 60 + 20,
    trade_weekends: bool = False,
):
    """
    Plain function version of the /auto-signal logic - callable directly
    (no HTTP round-trip) by both the /auto-signal endpoint below and the
    in-process background scheduler (see WATCHLIST/_scheduler_loop), so
    there is exactly one implementation of the actual trading rules.

    Intraday opening-range-breakout (ORB) signal engine, long-only, paper trades
    only. Designed to be called repeatedly (e.g. every 5 min during market
    hours via a GitHub Actions cron) - all state (open position, today's
    realized P&L) is persisted in SQLite so it survives Render restarts/sleeps
    between calls. `interval` sets the candle size this all runs on (1m, 2m,
    5m, 15m, 30m, 60m/1h - anything yfinance supports intraday); orb_minutes,
    sma_fast/slow are all in that candle's own units (minutes / bar-count).
    Note: polling faster than `interval` gains nothing - a new candle only
    closes every `interval`. This is same-day only (ORB needs an intraday
    opening range); a multi-day/swing engine on daily+ candles is a separate,
    not-yet-built strategy shape.

    Market session is fully configurable, so this same engine covers any
    market/asset class, not just NSE - tz_offset_min/open_min/close_min/
    squareoff_min are all minutes-since-local-midnight in that market's own
    timezone (defaults = NSE/BSE, IST 9:15-15:30). For a 24/7 market (e.g.
    crypto), pass open_min=0, close_min=1439, squareoff_min=1439,
    trade_weekends=true. NOTE: the shared Rs-capital daily-loss cap and
    capital-deployed cap (see deployed_notional/today_realized_pnl) always
    reset at IST midnight regardless of this market's own session, since
    that's the single account's "day" - a position whose session spans IST
    midnight (e.g. US markets, ~19:00-01:30 IST) is handled correctly for
    P&L (see today_realized_pnl's docstring) but still counts against
    *today's* (IST) budget at exit even if it opened "yesterday" IST.

    Rules (all tweakable via query params):
      - Opening range = high/low of the first `orb_minutes` after the market
        opens (open_min, in its own local time).
      - Entry: candle closes above the opening range high AND SMA(fast) >
        SMA(slow) (trend filter). Long only - no shorting in this book.
      - Stop-loss: the strategy's own technical level (opening-range low),
        capped at stop_pct% max below entry - whichever is tighter, so max
        loss per trade is bounded at stop_pct% of that trade's value even if
        the ORB range is wider. Target: entry + rr * (entry - stop).
      - Position size: risk_amount / (entry - stop), where risk_amount =
        min(risk_per_trade_pct% of capital, remaining daily loss budget) -
        i.e. how much capital gets deployed into the trade is set so a
        stop_pct% move costs at most risk_per_trade_pct% of capital.
      - Daily loss cap: daily_risk_pct% of capital. Once today's realized loss
        (across all symbols AND all markets - the capital is one shared pool)
        hits this, no new entries and any open position is squared off
        immediately. With risk_per_trade_pct == daily_risk_pct (both 2% by
        default), one stopped-out trade can use the whole day's budget - by
        design, per the user's stated risk rule.
      - End-of-day square-off at squareoff_min regardless of stop/target.
    """
    strategy_tag = f"{ORB_STRATEGY_PREFIX}{orb_minutes}m-sma{sma_fast}-{sma_slow}"
    now_ist = ist_now()
    now_local = dt.datetime.utcnow() + dt.timedelta(minutes=tz_offset_min)
    today_str = now_local.strftime("%Y-%m-%d")
    mins_now = now_local.hour * 60 + now_local.minute

    if not trade_weekends and now_local.weekday() >= 5:
        return {"symbol": symbol, "status": "closed_weekend", "time_local": str(now_local)}
    if mins_now < open_min:
        return {"symbol": symbol, "status": "pre_open", "time_local": str(now_local)}

    is_squareoff_time = mins_now >= squareoff_min
    is_market_open = mins_now <= close_min
    if not is_market_open:
        return {"symbol": symbol, "status": "closed", "time_local": str(now_local)}

    with closing(get_db()) as conn:
        row = conn.execute("SELECT * FROM signal_state WHERE symbol = ?", (symbol,)).fetchone()
        if row and row["day"] != today_str:
            conn.execute("DELETE FROM signal_state WHERE symbol = ?", (symbol,))
            conn.commit()
            row = None

        # Shared account budget always resets on the IST calendar day,
        # regardless of which market/timezone this call is for.
        since_ts = ist_midnight_epoch(now_ist)
        realized_today = today_realized_pnl(conn, since_ts)
        daily_loss_cap = capital * daily_risk_pct / 100
        loss_so_far = max(0.0, -realized_today)
        remaining_budget = max(0.0, daily_loss_cap - loss_so_far)
        halted = remaining_budget <= 0

        try:
            df = fetch_ohlc(symbol, "5d", interval)
            ts = pd.to_datetime(df["Date"])
            ts_utc = ts.dt.tz_convert("UTC") if ts.dt.tz is not None else ts.dt.tz_localize("UTC")
            ts_local = ts_utc + pd.Timedelta(minutes=tz_offset_min)
            df = df.assign(ts_local=ts_local)
            df["date_local"] = df["ts_local"].dt.strftime("%Y-%m-%d")
            today_df = df[df["date_local"] == today_str].reset_index(drop=True)
        except Exception as e:
            return {"symbol": symbol, "status": "data_error", "detail": str(e)}

        if today_df.empty:
            return {"symbol": symbol, "status": "no_intraday_data_yet", "time_local": str(now_local)}

        today_df["mins"] = today_df["ts_local"].dt.hour * 60 + today_df["ts_local"].dt.minute
        orb_cutoff = open_min + orb_minutes
        orb_df = today_df[today_df["mins"] < orb_cutoff]
        if orb_df.empty or today_df["mins"].max() < orb_cutoff:
            return {
                "symbol": symbol, "status": "waiting_for_opening_range",
                "bars_so_far": len(today_df), "time_local": str(now_local),
            }

        orb_high = float(orb_df["High"].max())
        orb_low = float(orb_df["Low"].min())
        last = today_df.iloc[-1]
        last_close = float(last["Close"])

        closes = today_df["Close"].to_numpy(dtype=float)
        sma_f = float(np.mean(closes[-sma_fast:])) if len(closes) >= sma_fast else None
        sma_s = float(np.mean(closes[-sma_slow:])) if len(closes) >= sma_slow else None
        trend = ("up" if sma_f > sma_s else "down") if (sma_f is not None and sma_s is not None) else None

        result = {
            "symbol": symbol, "status": "checked", "time_local": str(now_local),
            "last_close": last_close, "orb_high": orb_high, "orb_low": orb_low,
            "sma_fast": sma_f, "sma_slow": sma_s, "trend": trend,
            "capital": capital, "daily_loss_cap": daily_loss_cap,
            "realized_today": round(realized_today, 2),
            "realized_today_pct": round(100 * realized_today / capital, 3),
            "budget_remaining": round(remaining_budget, 2),
            "halted_for_day": halted, "action_taken": "none",
        }

        # ---- manage an existing open position ----
        if row and row["status"] == "long":
            exit_reason = None
            if halted:
                exit_reason = "daily_loss_cap_hit"
            elif last_close >= row["target"]:
                exit_reason = "target_hit"
            elif last_close <= row["stop_loss"]:
                exit_reason = "stop_hit"
            elif is_squareoff_time:
                exit_reason = "eod_squareoff"

            if exit_reason:
                qty = row["qty"]
                pnl = (last_close - row["entry_price"]) * qty
                stop_dist = row["entry_price"] - row["stop_loss"]
                rr_achieved = round((last_close - row["entry_price"]) / stop_dist, 2) if stop_dist else None
                payload = {
                    "symbol": symbol, "action": "sell", "qty": qty, "price": last_close,
                    "strategy": strategy_tag, "exit_reason": exit_reason,
                    "entry_price": row["entry_price"], "stop_loss": row["stop_loss"],
                    "target": row["target"], "rr_target": rr, "rr_achieved": rr_achieved,
                    "pnl": round(pnl, 2), "pnl_pct_of_capital": round(100 * pnl / capital, 3),
                }
                apply_paper_trade(conn, symbol, "sell", qty, last_close)
                conn.execute(
                    "INSERT INTO trades (ts, symbol, action, qty, price, strategy, raw_payload) "
                    "VALUES (?, ?, 'sell', ?, ?, ?, ?)",
                    (time.time(), symbol, qty, last_close, strategy_tag, json.dumps(payload)),
                )
                conn.execute("DELETE FROM signal_state WHERE symbol = ?", (symbol,))
                conn.commit()
                result.update(
                    action_taken=f"exited_{exit_reason}", exit_pnl=payload["pnl"],
                    exit_pnl_pct=payload["pnl_pct_of_capital"], rr_achieved=rr_achieved,
                )
                return result

            result["open_position"] = dict(row)
            return result

        # ---- look for a new entry ----
        if halted:
            result["action_taken"] = "blocked_daily_loss_cap"
            return result
        if is_squareoff_time:
            result["action_taken"] = "no_new_entries_market_closing"
            return result

        if last_close > orb_high and trend == "up":
            # Stop is the strategy's own technical level (opening-range low),
            # capped at stop_pct% max risk - whichever is tighter (closer to
            # entry) wins, so the trade never risks more than the cap even if
            # the ORB range itself is wider than that.
            stop_loss_cap = last_close * (1 - stop_pct / 100)
            stop_loss = max(orb_low, stop_loss_cap)
            stop_dist = last_close - stop_loss
            if stop_dist <= 0:
                result["action_taken"] = "invalid_stop_skipped"
                return result
            target = last_close + rr * stop_dist
            risk_amount = min(capital * risk_per_trade_pct / 100, remaining_budget)
            qty = int(risk_amount // stop_dist)

            # Capital is shared and finite - cap qty so this trade's notional
            # doesn't push total deployed capital across all open symbols
            # past `capital`. Whichever symbol's entry is evaluated first in
            # a given poll cycle gets first claim on the remaining capital
            # (see /daily-summary and the workflow's call order); a true
            # cross-symbol "best signal wins" ranking is a fast-follow.
            available_capital = max(0.0, capital - deployed_notional(conn))
            qty = min(qty, int(available_capital // last_close))

            if qty < 1:
                result["action_taken"] = (
                    "insufficient_capital" if available_capital < last_close
                    else "budget_too_small_for_1_unit"
                )
                result["available_capital"] = round(available_capital, 2)
                return result

            payload = {
                "symbol": symbol, "action": "buy", "qty": qty, "price": last_close,
                "strategy": strategy_tag, "entry_reason": "orb_breakout_with_trend",
                "stop_loss": stop_loss, "target": target, "rr_target": rr,
                "risk_amount": round(risk_amount, 2),
                "risk_pct_of_capital": round(100 * risk_amount / capital, 3),
                "notional": round(qty * last_close, 2),
            }
            apply_paper_trade(conn, symbol, "buy", qty, last_close)
            conn.execute(
                "INSERT INTO trades (ts, symbol, action, qty, price, strategy, raw_payload) "
                "VALUES (?, ?, 'buy', ?, ?, ?, ?)",
                (time.time(), symbol, qty, last_close, strategy_tag, json.dumps(payload)),
            )
            conn.execute(
                "INSERT INTO signal_state "
                "(symbol, day, status, entry_price, stop_loss, target, qty, entry_ts, orb_high, orb_low) "
                "VALUES (?, ?, 'long', ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(symbol) DO UPDATE SET day=excluded.day, status=excluded.status, "
                "entry_price=excluded.entry_price, stop_loss=excluded.stop_loss, "
                "target=excluded.target, qty=excluded.qty, entry_ts=excluded.entry_ts, "
                "orb_high=excluded.orb_high, orb_low=excluded.orb_low",
                (symbol, today_str, last_close, stop_loss, target, qty, time.time(), orb_high, orb_low),
            )
            conn.commit()
            result.update(action_taken="entered_long", entry=payload)
            return result

        result["action_taken"] = "no_signal"
        return result


@app.get("/auto-signal")
def auto_signal(
    symbol: str,
    capital: float = 200000,
    daily_risk_pct: float = 2.0,
    risk_per_trade_pct: float = 2.0,
    stop_pct: float = 2.0,
    rr: float = 2.0,
    orb_minutes: int = 15,
    sma_fast: int = 9,
    sma_slow: int = 21,
    interval: str = "5m",
    tz_offset_min: int = IST_OFFSET_MIN,
    open_min: int = 9 * 60 + 15,
    close_min: int = 15 * 60 + 30,
    squareoff_min: int = 15 * 60 + 20,
    trade_weekends: bool = False,
):
    """HTTP wrapper around _auto_signal_core - see that function's docstring
    for the actual rules. Kept as a thin pass-through so manual/GH-Actions
    calls and the in-process scheduler share one implementation."""
    return _auto_signal_core(
        symbol=symbol, capital=capital, daily_risk_pct=daily_risk_pct,
        risk_per_trade_pct=risk_per_trade_pct, stop_pct=stop_pct, rr=rr,
        orb_minutes=orb_minutes, sma_fast=sma_fast, sma_slow=sma_slow, interval=interval,
        tz_offset_min=tz_offset_min, open_min=open_min, close_min=close_min,
        squareoff_min=squareoff_min, trade_weekends=trade_weekends,
    )


# ---------------------------------------------------------------------------
# In-process scheduler: replaces reliance on GitHub Actions' `schedule:` cron
# for the actual timing of entries/exits. GH Actions scheduled runs proved
# unreliable in practice (2026-09-02: ~1 of ~75 expected 5-min NSE polls
# actually fired; similar drop rate on crypto/US - see docs/KNOWN_ISSUES.md).
# This loop runs inside the same always-imported process Render keeps alive,
# checking every SCHEDULER_INTERVAL_SECONDS with no dependency on any
# external trigger. It does NOT fix Render free-tier sleep (the process
# stops running entirely when asleep, scheduler included) - only an
# always-on paid plan does that. The external GH Actions workflows are kept
# as a redundant backstop (harmless: _auto_signal_core is idempotent, checked
# against DB state on every call) and, more importantly, as one of the ways
# the server gets woken back up.
# ---------------------------------------------------------------------------

WATCHLIST = [
    # NSE/BSE - IST 9:15-15:30, weekdays. Params from 2026-09-02 research
    # (docs/daily_logs/2026-09-02-entry-trigger-research.md).
    {"symbol": "^NSEI", "orb_minutes": 30, "sma_fast": 5, "sma_slow": 50,
     "tz_offset_min": IST_OFFSET_MIN, "open_min": 555, "close_min": 930, "squareoff_min": 920,
     "trade_weekends": False},
    {"symbol": "^NSEBANK", "orb_minutes": 5, "sma_fast": 9, "sma_slow": 50,
     "tz_offset_min": IST_OFFSET_MIN, "open_min": 555, "close_min": 930, "squareoff_min": 920,
     "trade_weekends": False},
    {"symbol": "^BSESN", "orb_minutes": 30, "sma_fast": 20, "sma_slow": 50,
     "tz_offset_min": IST_OFFSET_MIN, "open_min": 555, "close_min": 930, "squareoff_min": 920,
     "trade_weekends": False},
    # Crypto - UTC, 24/7, trades weekends too.
    {"symbol": "BTC-USD", "orb_minutes": 15, "sma_fast": 9, "sma_slow": 21,
     "tz_offset_min": 0, "open_min": 0, "close_min": 1439, "squareoff_min": 1439,
     "trade_weekends": True},
    {"symbol": "ETH-USD", "orb_minutes": 15, "sma_fast": 9, "sma_slow": 21,
     "tz_offset_min": 0, "open_min": 0, "close_min": 1439, "squareoff_min": 1439,
     "trade_weekends": True},
    # US markets - ET. tz_offset_min=-240 is EDT (UTC-4), correct through
    # early Nov 2026; needs -300 (EST) after the US DST changeover.
    {"symbol": "SPY", "orb_minutes": 15, "sma_fast": 9, "sma_slow": 21,
     "tz_offset_min": -240, "open_min": 570, "close_min": 960, "squareoff_min": 950,
     "trade_weekends": False},
    {"symbol": "QQQ", "orb_minutes": 15, "sma_fast": 9, "sma_slow": 21,
     "tz_offset_min": -240, "open_min": 570, "close_min": 960, "squareoff_min": 950,
     "trade_weekends": False},
    {"symbol": "AAPL", "orb_minutes": 15, "sma_fast": 9, "sma_slow": 21,
     "tz_offset_min": -240, "open_min": 570, "close_min": 960, "squareoff_min": 950,
     "trade_weekends": False},
]

SCHEDULER_INTERVAL_SECONDS = 30
SCHEDULER_CAPITAL = 200000
SCHEDULER_DAILY_RISK_PCT = 2.0
SCHEDULER_RISK_PER_TRADE_PCT = 2.0
SCHEDULER_STOP_PCT = 2.0
SCHEDULER_RR = 2.0

_scheduler_last_tick_ts = 0.0
_scheduler_last_error = None


async def _scheduler_loop():
    global _scheduler_last_tick_ts, _scheduler_last_error
    while True:
        for cfg in WATCHLIST:
            try:
                await asyncio.to_thread(
                    _auto_signal_core,
                    symbol=cfg["symbol"], capital=SCHEDULER_CAPITAL,
                    daily_risk_pct=SCHEDULER_DAILY_RISK_PCT,
                    risk_per_trade_pct=SCHEDULER_RISK_PER_TRADE_PCT,
                    stop_pct=SCHEDULER_STOP_PCT, rr=SCHEDULER_RR,
                    orb_minutes=cfg["orb_minutes"], sma_fast=cfg["sma_fast"], sma_slow=cfg["sma_slow"],
                    interval="5m", tz_offset_min=cfg["tz_offset_min"], open_min=cfg["open_min"],
                    close_min=cfg["close_min"], squareoff_min=cfg["squareoff_min"],
                    trade_weekends=cfg["trade_weekends"],
                )
            except Exception as e:
                _scheduler_last_error = f"{cfg['symbol']}: {e}"
        _scheduler_last_tick_ts = time.time()
        await asyncio.sleep(SCHEDULER_INTERVAL_SECONDS)


@app.on_event("startup")
async def _start_scheduler():
    asyncio.create_task(_scheduler_loop())


@app.get("/scheduler-status")
def scheduler_status():
    return {
        "watchlist_size": len(WATCHLIST),
        "interval_seconds": SCHEDULER_INTERVAL_SECONDS,
        "last_tick_ts": _scheduler_last_tick_ts,
        "last_tick_ago_seconds": round(time.time() - _scheduler_last_tick_ts, 1) if _scheduler_last_tick_ts else None,
        "last_error": _scheduler_last_error,
    }


@app.get("/daily-summary")
def daily_summary(capital: float = 200000, daily_risk_pct: float = 2.0):
    """Aggregated view of today's auto-signal paper trading across all symbols:
    realized P&L (Rs and % of capital), win rate, risk-reward achieved per
    trade, remaining daily-loss budget, and any still-open positions."""
    now_ist = ist_now()
    today_str = now_ist.strftime("%Y-%m-%d")
    since_ts = ist_midnight_epoch(now_ist)

    with closing(get_db()) as conn:
        # Full history for correct cost-basis (see today_realized_pnl) - only
        # sells at/after since_ts are reported as "today's" closed trades.
        all_trades = conn.execute(
            "SELECT id, ts, symbol, action, qty, price, strategy, raw_payload FROM trades "
            "WHERE strategy LIKE ? ORDER BY id",
            (ORB_STRATEGY_PREFIX + "%",),
        ).fetchall()
        # No day filter - a genuinely open position should show regardless of
        # which local trading day it was opened on (relevant once a market
        # other than NSE, with its own local "day", is in the mix).
        open_state = conn.execute("SELECT * FROM signal_state WHERE status = 'long'").fetchall()

    book: dict[str, dict] = {}
    realized = 0.0
    closed_trades = []
    for t in all_trades:
        sym = t["symbol"]
        b = book.setdefault(sym, {"qty": 0.0, "avg": 0.0})
        if t["action"] == "buy":
            new_qty = b["qty"] + t["qty"]
            b["avg"] = ((b["qty"] * b["avg"]) + (t["qty"] * t["price"])) / new_qty if new_qty else 0.0
            b["qty"] = new_qty
        else:
            pnl = (t["price"] - b["avg"]) * min(t["qty"], b["qty"])
            b["qty"] -= t["qty"]
            if t["ts"] < since_ts:
                continue
            realized += pnl
            try:
                extra = json.loads(t["raw_payload"])
            except Exception:
                extra = {}
            closed_trades.append({
                "symbol": sym, "exit_time_utc": t["ts"], "entry_price": extra.get("entry_price"),
                "exit_price": t["price"], "qty": t["qty"], "pnl": round(pnl, 2),
                "pnl_pct_of_capital": round(100 * pnl / capital, 3),
                "exit_reason": extra.get("exit_reason"), "rr_target": extra.get("rr_target"),
                "rr_achieved": extra.get("rr_achieved"),
            })

    daily_loss_cap = capital * daily_risk_pct / 100
    loss_so_far = max(0.0, -realized)
    budget_remaining = max(0.0, daily_loss_cap - loss_so_far)
    wins = [c for c in closed_trades if c["pnl"] > 0]

    return {
        "date_ist": today_str,
        "capital": capital,
        "daily_loss_cap": daily_loss_cap,
        "daily_loss_cap_pct": daily_risk_pct,
        "realized_pnl": round(realized, 2),
        "realized_pnl_pct": round(100 * realized / capital, 3),
        "budget_remaining": round(budget_remaining, 2),
        "halted_for_day": budget_remaining <= 0,
        "closed_trades_count": len(closed_trades),
        "win_rate_pct": round(100 * len(wins) / len(closed_trades), 1) if closed_trades else None,
        "open_positions": [dict(r) for r in open_state],
        "closed_trades": closed_trades,
    }


DRY_RUN_DEFAULT_SYMBOLS = [
    {"symbol": "^NSEI", "orb_minutes": 30, "sma_fast": 5, "sma_slow": 50},
    {"symbol": "^NSEBANK", "orb_minutes": 5, "sma_fast": 9, "sma_slow": 50},
    {"symbol": "^BSESN", "orb_minutes": 30, "sma_fast": 20, "sma_slow": 50},
]


@app.get("/dry-run-day")
def dry_run_day(
    date: str,
    capital: float = 200000,
    daily_risk_pct: float = 2.0,
    risk_per_trade_pct: float = 2.0,
    stop_pct: float = 2.0,
    rr: float = 2.0,
    orb_minutes_override: int = 0,  # 0 = use each symbol's validated default
):
    """
    Sandboxed same-day replay: re-runs the exact ORB+trend rules the live
    /auto-signal uses, tick by tick across NIFTY/BANKNIFTY/SENSEX together
    (sharing one capital pool, exactly like the real workflows), against
    REAL historical 5-min data for `date` - but writes NOTHING to the real
    paper_trades.db. Pure simulation, safe to run anytime, for any past
    trading day still in yfinance's 5m window (~60 days).

    Uses each symbol's evidence-backed params from the 2026-09-02 research
    (see docs/daily_logs/2026-09-02-entry-trigger-research.md) unless
    orb_minutes_override is set (applies the same orb_minutes to all 3,
    sma_fast/slow unchanged).
    """
    symbols = DRY_RUN_DEFAULT_SYMBOLS
    open_min = 9 * 60 + 15
    squareoff_min = 15 * 60 + 20

    per_symbol_df = {}
    for cfg in symbols:
        sym = cfg["symbol"]
        try:
            raw = fetch_ohlc(sym, "5d", "5m")
        except HTTPException as e:
            return {"error": f"data fetch failed for {sym}: {e.detail}"}
        ts = pd.to_datetime(raw["Date"])
        ts_ist = ts.dt.tz_convert("Asia/Kolkata") if ts.dt.tz is not None else ts.dt.tz_localize(
            "UTC"
        ).dt.tz_convert("Asia/Kolkata")
        raw = raw.assign(ts_ist=ts_ist, date_ist=ts_ist.dt.strftime("%Y-%m-%d"))
        day_df = raw[raw["date_ist"] == date].reset_index(drop=True)
        if day_df.empty:
            return {"error": f"no 5m data for {sym} on {date} (outside yfinance's ~60d intraday window?)"}
        day_df["mins"] = day_df["ts_ist"].dt.hour * 60 + day_df["ts_ist"].dt.minute
        per_symbol_df[sym] = day_df

    # Precompute each symbol's ORB high/orb window/trend using the same
    # vectorized logic as add_strategy_signal's orb_breakout branch.
    precomputed = {}
    for cfg in symbols:
        sym = cfg["symbol"]
        om = orb_minutes_override or cfg["orb_minutes"]
        sf, ss = cfg["sma_fast"], cfg["sma_slow"]
        df = per_symbol_df[sym].copy()
        df["fast_ma"] = df["Close"].rolling(sf).mean()
        df["slow_ma"] = df["Close"].rolling(ss).mean()
        df["trend_up"] = df["fast_ma"] > df["slow_ma"]
        in_window = df["mins"] < open_min + om
        df["orb_high_running"] = df["High"].where(in_window).cummax().ffill()
        df["orb_low_running"] = df["Low"].where(in_window).cummin().ffill()
        precomputed[sym] = {"df": df, "orb_minutes": om, "cutoff": open_min + om}

    all_times = sorted(set(t for cfg in symbols for t in per_symbol_df[cfg["symbol"]]["mins"]))

    daily_loss_cap = capital * daily_risk_pct / 100
    state = {cfg["symbol"]: None for cfg in symbols}  # None or dict(entry,stop,target,qty)
    realized = 0.0
    events = []
    checkpoints = []
    orb_summary = {}

    def remaining_budget():
        loss_so_far = max(0.0, -realized)
        return max(0.0, daily_loss_cap - loss_so_far)

    def deployed_notional():
        return sum(s["qty"] * s["entry"] for s in state.values() if s)

    for t_idx, m in enumerate(all_times):
        for cfg in symbols:
            sym = cfg["symbol"]
            pc = precomputed[sym]
            df = pc["df"]
            rows = df[df["mins"] == m]
            if rows.empty:
                continue
            row = rows.iloc[-1]
            close = float(row["Close"])
            time_str = str(row["ts_ist"])[11:16]
            pos = state[sym]
            halted = remaining_budget() <= 0

            # record ORB formation once
            if sym not in orb_summary and m >= pc["cutoff"] - 1 and pd.notna(row["orb_high_running"]):
                orb_summary[sym] = {
                    "orb_high": round(float(row["orb_high_running"]), 2),
                    "orb_low": round(float(row["orb_low_running"]), 2),
                    "formed_by": time_str,
                }

            if pos:
                reason = None
                if halted:
                    reason = "daily_loss_cap_hit"
                elif close >= pos["target"]:
                    reason = "target_hit"
                elif close <= pos["stop"]:
                    reason = "stop_hit"
                elif m >= squareoff_min:
                    reason = "eod_squareoff"
                if reason:
                    pnl = (close - pos["entry"]) * pos["qty"]
                    realized += pnl
                    rr_ach = round((close - pos["entry"]) / (pos["entry"] - pos["stop"]), 2)
                    events.append({
                        "time": time_str, "symbol": sym, "event": f"exited_{reason}",
                        "price": round(close, 2), "pnl": round(pnl, 2),
                        "pnl_pct_of_capital": round(100 * pnl / capital, 3), "rr_achieved": rr_ach,
                    })
                    state[sym] = None
                continue

            if halted or m >= squareoff_min or m < pc["cutoff"]:
                continue

            orb_high = row["orb_high_running"]
            trend_up = bool(row["trend_up"]) if pd.notna(row["trend_up"]) else False
            if pd.notna(orb_high) and close > float(orb_high) and trend_up:
                orb_low = float(row["orb_low_running"])
                stop = max(orb_low, close * (1 - stop_pct / 100))
                stop_dist = close - stop
                if stop_dist <= 0:
                    continue
                target = close + rr * stop_dist
                risk_amount = min(capital * risk_per_trade_pct / 100, remaining_budget())
                avail_capital = max(0.0, capital - deployed_notional())
                qty = min(int(risk_amount // stop_dist), int(avail_capital // close))
                if qty < 1:
                    continue
                state[sym] = {"entry": close, "stop": stop, "target": target, "qty": qty}
                events.append({
                    "time": time_str, "symbol": sym, "event": "entered_long",
                    "price": round(close, 2), "stop": round(stop, 2), "target": round(target, 2),
                    "qty": qty, "notional": round(qty * close, 2),
                })

        if m % 30 == 0:
            snap = {"time_mins": m}
            for cfg in symbols:
                sym = cfg["symbol"]
                rows = precomputed[sym]["df"]
                rr_ = rows[rows["mins"] == m]
                if rr_.empty:
                    continue
                r = rr_.iloc[-1]
                snap[sym] = {
                    "close": round(float(r["Close"]), 2),
                    "position": "long" if state[sym] else "flat",
                }
            checkpoints.append(snap)

    wins = [e for e in events if e["event"].startswith("exited_") and e.get("pnl", 0) > 0]
    exits = [e for e in events if e["event"].startswith("exited_")]

    return {
        "date": date,
        "capital": capital,
        "daily_loss_cap": daily_loss_cap,
        "orb_formation": orb_summary,
        "events": events,
        "checkpoints_every_30min": checkpoints,
        "summary": {
            "realized_pnl": round(realized, 2),
            "realized_pnl_pct": round(100 * realized / capital, 3),
            "trades_closed": len(exits),
            "win_rate_pct": round(100 * len(wins) / len(exits), 1) if exits else None,
            "still_open_at_session_end": {k: v for k, v in state.items() if v},
            "budget_remaining": round(remaining_budget(), 2),
        },
    }


@app.get("/health")
def health():
    return {"status": "alive", "time": time.time()}


@app.get("/live")
def live():
    """Self-refreshing NIFTY/BANKNIFTY/SENSEX/India VIX dashboard."""
    return FileResponse("static/live.html")
