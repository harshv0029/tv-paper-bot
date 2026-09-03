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

# No single new trade may claim more than capital/CAPITAL_TRANCHES of the
# shared pool, even when more sits free - reserves room for other real
# opportunities to be taken in parallel rather than one position locking
# out the rest of the day. 2 = the account's current split (a trade can use
# at most half the pool at once); raise for finer-grained parallelism.
CAPITAL_TRANCHES = 2

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
                fx_to_inr REAL NOT NULL DEFAULT 1.0,  -- price*fx_to_inr = INR value/unit
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
                entry_price REAL,       -- native currency (e.g. USD for SPY)
                stop_loss REAL,         -- native currency
                target REAL,            -- native currency
                qty REAL,
                entry_ts REAL,
                orb_high REAL,
                orb_low REAL,
                fx_to_inr REAL NOT NULL DEFAULT 1.0,  -- captured at entry; entry_price*fx_to_inr = INR/unit
                interval TEXT NOT NULL DEFAULT '5m'   -- candle size this trade was taken on
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS option_state (
                opt_symbol TEXT PRIMARY KEY,  -- "{underlying}:OPT-CALL" / "{underlying}:OPT-PUT"
                underlying TEXT NOT NULL,
                day TEXT NOT NULL,
                right TEXT NOT NULL,          -- call | put
                expiry TEXT NOT NULL,         -- YYYY-MM-DD
                strike REAL NOT NULL,
                contracts REAL NOT NULL,      -- 1 contract = 100 shares, the real multiplier
                entry_premium REAL NOT NULL,  -- native currency, per share
                stop_premium REAL NOT NULL,
                target_premium REAL NOT NULL,
                entry_iv REAL,
                entry_delta REAL,
                entry_ts REAL NOT NULL,
                fx_to_inr REAL NOT NULL DEFAULT 1.0
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


def get_fx_to_inr(currency: str) -> float:
    """1 unit of `currency` -> this many INR. Live rate (cached like any
    other fetch_ohlc call), not a hardcoded guess - USD/INR moves enough
    that a stale constant would itself become a sizing error."""
    if currency == "INR":
        return 1.0
    if currency == "USD":
        df = fetch_ohlc("INR=X", "5d", "1d")
        return float(df["Close"].iloc[-1])
    raise HTTPException(status_code=400, detail=f"No FX rate wired up for currency={currency!r}")


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

    elif strategy == "bullish_engulfing":
        # Price-action candlestick strategy. Sources (2026-09-03 research):
        # standalone bullish engulfing ~53-55% win rate; rises to ~55-65% when
        # combined with a trend/support-context filter and volume confirmation
        # (liberatedstocktrader.com, tradingrush.net backtest write-ups).
        # Enter long on a bullish engulfing candle (optionally only in an
        # uptrend per trend_sma), exit on the next bearish engulfing candle -
        # same enter/exit-loop shape as rsi_reversal above.
        trend_sma = int(params.get("trend_sma", 0))  # 0 = no trend filter
        volume_confirm = bool(params.get("volume_confirm", False))

        prev_open = df["Open"].shift(1)
        prev_close = df["Close"].shift(1)
        prev_bearish = prev_close < prev_open
        prev_bullish = prev_close > prev_open
        cur_bullish = df["Close"] > df["Open"]
        cur_bearish = df["Close"] < df["Open"]

        engulf_long = (
            cur_bullish & prev_bearish
            & (df["Open"] <= prev_close) & (df["Close"] >= prev_open)
        )
        engulf_exit = (
            cur_bearish & prev_bullish
            & (df["Open"] >= prev_close) & (df["Close"] <= prev_open)
        )

        if trend_sma > 0:
            sma = df["Close"].rolling(trend_sma).mean()
            engulf_long = engulf_long & (df["Close"] > sma)

        if volume_confirm:
            vol_avg = df["Volume"].rolling(20).mean()
            engulf_long = engulf_long & (df["Volume"] > vol_avg)

        holding, flags = False, []
        for is_entry, is_exit in zip(engulf_long, engulf_exit):
            if not holding and is_entry:
                holding = True
            elif holding and is_exit:
                holding = False
            flags.append(holding)
        df["long"] = flags

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
                   f"orb_breakout, orb_volume, vwap_reclaim, bullish_engulfing, macd_cross",
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
    trend_sma: int = 0,
    volume_confirm: bool = False,
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
    strategy=bullish_engulfing    -> params: trend_sma (0=off), volume_confirm
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
    elif strategy == "bullish_engulfing":
        params = {"trend_sma": trend_sma, "volume_confirm": volume_confirm}
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
    # bullish_engulfing params - comma-separated lists
    trend_sma: str = "0,20,50",
    volume_confirm: str = "false,true",
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
    elif strategy == "bullish_engulfing":
        ts_list = _parse_num_list(trend_sma, int)
        vc_list = [v.strip().lower() == "true" for v in volume_confirm.split(",") if v.strip() != ""]
        combos = [
            {"trend_sma": ts, "volume_confirm": vc}
            for ts, vc in product(ts_list, vc_list)
        ]
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown strategy {strategy!r}. Supported: sma_crossover, rsi_reversal, "
                   f"orb_breakout, orb_volume, bullish_engulfing",
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
        "SELECT symbol, action, qty, price, fx_to_inr, ts FROM trades WHERE strategy LIKE ? ORDER BY id",
        (ORB_STRATEGY_PREFIX + "%",),
    ).fetchall()
    book: dict[str, dict] = {}
    realized = 0.0
    for t in all_trades:
        # Normalize to INR/unit at the row's own fx rate so symbols in
        # different currencies (NSE in INR, US/crypto in USD) can be summed
        # together correctly - mixing raw $ and Rs numbers would silently
        # misstate P&L by the exchange rate (~83-88x for USD).
        price_inr = t["price"] * t["fx_to_inr"]
        b = book.setdefault(t["symbol"], {"qty": 0.0, "avg": 0.0})
        if t["action"] == "buy":
            new_qty = b["qty"] + t["qty"]
            b["avg"] = ((b["qty"] * b["avg"]) + (t["qty"] * price_inr)) / new_qty if new_qty else 0.0
            b["qty"] = new_qty
        else:
            pnl = (price_inr - b["avg"]) * min(t["qty"], b["qty"])
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
    account. entry_price is native currency; fx_to_inr (captured at entry)
    converts it to INR so USD positions (SPY etc.) don't get sized as if
    $1 == Rs 1."""
    rows = conn.execute(
        "SELECT qty, entry_price, fx_to_inr FROM signal_state WHERE status = 'long'"
    ).fetchall()
    equity_notional = sum(r["qty"] * r["entry_price"] * r["fx_to_inr"] for r in rows)
    opt_rows = conn.execute(
        "SELECT contracts, entry_premium, fx_to_inr FROM option_state"
    ).fetchall()
    # Same shared pool as equities (docs/TRADING_CONSTRAINTS.md) - an open
    # option position's cost basis (premium paid, its real max loss on a
    # total wipeout) counts against the same capital cap so options and
    # equities can't jointly overspend the account.
    option_notional = sum(r["contracts"] * 100 * r["entry_premium"] * r["fx_to_inr"] for r in opt_rows)
    return equity_notional + option_notional


# ---------------------------------------------------------------------------
# Options overlay: buy real, currently-quoted calls/puts on symbols with a
# live yfinance options chain (SPY/QQQ/AAPL - see OPTIONS_ELIGIBLE_SYMBOLS).
# NSE/BSE index and stock options are explicitly NOT covered here - there is
# no real chain/IV data for them without a broker connection (Kotak Neo,
# not yet wired up - docs/TRADING_CONSTRAINTS.md); synthesizing one would be
# exactly the kind of fabricated-data shortcut this project has repeatedly
# ruled out. The equity engine above (_auto_signal_core) stays long-only and
# untouched by any of this - direction detection here is a read-only mirror
# of its own bullish logic (plus the bearish case it deliberately doesn't
# trade), used only to decide "buy a call" vs "buy a put".
# 2026-09-03: expanded from just SPY/QQQ/AAPL per explicit user instruction
# ("don't skip stocks with options available") - every name here is a
# heavily-optioned, deeply liquid US mega-cap/ETF, so chain availability
# isn't in question. Each must also be a WATCHLIST entry (session hours/
# currency/risk_pct come from there) - see the WATCHLIST comment above this
# set for why it's a curated list, not literally every optionable US stock.
OPTIONS_ELIGIBLE_SYMBOLS = [
    "SPY", "QQQ", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
    "NFLX", "AMD", "JPM", "V", "DIA", "IWM",
]
OPTIONS_TARGET_DELTA = 0.35     # moderately OTM: real leverage (bigger % payoff on a win) without
                                 # betting on a near-impossible move - deep ITM has little leverage,
                                 # far OTM is a lottery ticket the IV check below would flag anyway.
OPTIONS_MIN_DTE = 2             # skip 0-1 DTE - gamma/pin risk dominates, not the underlying's trend.
OPTIONS_MAX_DTE = 10            # weekly-ish - long-dated options carry theta we don't need for an
                                 # intraday-signal-driven entry.
OPTIONS_MAX_IV_VS_ATM = 1.6     # IV oversight: reject a strike priced >60% rich vs the chain's own
                                 # ATM IV - a skew/event spike means this specific line is expensive
                                 # relative to the rest of the curve and prone to giving the gain
                                 # straight back to IV crush even if the direction call is right.
OPTIONS_MAX_SPREAD_PCT = 15.0   # liquidity guard: (ask-bid)/ask must be tighter than this, or the
                                 # quote is too thin to trust as a real fill.
OPTIONS_STOP_PCT = 45.0         # premium-based stop - options swing harder than the underlying, so
                                 # this plays the same role stop_pct plays for equities.
OPTIONS_STRATEGY_TAG = f"{ORB_STRATEGY_PREFIX}option"


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _bs_delta(spot: float, strike: float, iv: float, dte_years: float, right: str, r: float = 0.05):
    """Black-Scholes delta from the chain's own quoted IV - yfinance doesn't
    return delta directly, and this is the standard way to derive it (no
    scipy dependency needed; math.erf gives the normal CDF)."""
    if spot <= 0 or strike <= 0 or iv <= 0 or dte_years <= 0:
        return None
    d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * dte_years) / (iv * math.sqrt(dte_years))
    nd1 = _norm_cdf(d1)
    return nd1 if right == "call" else nd1 - 1.0


def select_option_contract(underlying: str, spot: float, right: str):
    """Picks one real, currently-quoted contract from yfinance's live chain.
    See the module docstring above for the strike/expiry/IV rules. Returns
    (contract_dict, None) on success or (None, reason_str) - never invents a
    contract; a chain fetch failure or no qualifying line is reported, not
    silently defaulted."""
    try:
        t = yf.Ticker(underlying)
        expiries = t.options
    except Exception as e:
        return None, f"options_chain_error: {e}"
    if not expiries:
        return None, "no_expiries_listed"

    now = dt.datetime.utcnow()
    in_range = []
    all_dtes = []
    for exp in expiries:
        dte = (dt.datetime.strptime(exp, "%Y-%m-%d") - now).days
        all_dtes.append((exp, dte))
        if OPTIONS_MIN_DTE <= dte <= OPTIONS_MAX_DTE:
            in_range.append((exp, dte))
    if in_range:
        expiry, dte = min(in_range, key=lambda c: c[1])
    else:
        # No expiry in the preferred window - fall back to the nearest one
        # that's still past OPTIONS_MIN_DTE (never 0-1 DTE) rather than
        # refusing to trade a symbol just because this week's calendar is odd.
        beyond = [c for c in all_dtes if c[1] >= OPTIONS_MIN_DTE]
        if not beyond:
            return None, "no_expiry_beyond_min_dte"
        expiry, dte = min(beyond, key=lambda c: c[1])
    dte_years = max(dte, 1) / 365.0

    try:
        chain = t.option_chain(expiry)
    except Exception as e:
        return None, f"chain_fetch_error: {e}"
    book = chain.calls if right == "call" else chain.puts
    if book is None or book.empty:
        return None, "empty_chain"

    book = book.copy()
    book["dist_to_atm"] = (book["strike"] - spot).abs()
    atm_row = book.loc[book["dist_to_atm"].idxmin()]
    atm_iv = float(atm_row["impliedVolatility"]) if atm_row["impliedVolatility"] and atm_row["impliedVolatility"] > 0 else None

    best = None  # (delta_dist, row, iv, delta)
    for _, row in book.iterrows():
        iv = float(row["impliedVolatility"]) if row["impliedVolatility"] else 0.0
        bid = float(row["bid"]) if row["bid"] else 0.0
        ask = float(row["ask"]) if row["ask"] else 0.0
        if iv <= 0 or bid <= 0 or ask <= 0:
            continue
        if (ask - bid) / ask * 100 > OPTIONS_MAX_SPREAD_PCT:
            continue
        delta = _bs_delta(spot, float(row["strike"]), iv, dte_years, right)
        if delta is None:
            continue
        delta_dist = abs(abs(delta) - OPTIONS_TARGET_DELTA)
        if best is None or delta_dist < best[0]:
            best = (delta_dist, row, iv, delta)

    if best is None:
        return None, "no_liquid_contract_near_target_delta"

    _, row, iv, delta = best
    if atm_iv and iv > atm_iv * OPTIONS_MAX_IV_VS_ATM:
        return None, f"iv_too_rich_vs_atm ({iv:.2f} vs atm {atm_iv:.2f})"

    mid = (float(row["bid"]) + float(row["ask"])) / 2.0
    return {
        "underlying": underlying, "right": right, "expiry": expiry, "dte": dte,
        "strike": float(row["strike"]), "premium": round(mid, 4),
        "bid": float(row["bid"]), "ask": float(row["ask"]),
        "iv": round(iv, 4), "atm_iv": round(atm_iv, 4) if atm_iv else None,
        "delta": round(delta, 3), "open_interest": int(row.get("openInterest") or 0),
        "volume": int(row.get("volume") or 0),
    }, None


def _requote_contract(underlying: str, expiry: str, strike: float, right: str):
    """Re-fetches the live bid/ask for one already-open contract, to mark an
    open option position to a real quote (not the entry price) when checking
    stop/target. Returns mid price or None if the chain can't be fetched or
    the strike is no longer listed (e.g. past expiry)."""
    try:
        t = yf.Ticker(underlying)
        chain = t.option_chain(expiry)
    except Exception:
        return None
    book = chain.calls if right == "call" else chain.puts
    if book is None or book.empty:
        return None
    match = book[(book["strike"] - strike).abs() < 0.01]
    if match.empty:
        return None
    row = match.iloc[0]
    bid, ask = float(row["bid"] or 0), float(row["ask"] or 0)
    if bid <= 0 or ask <= 0:
        return None
    return round((bid + ask) / 2.0, 4)


def _compute_trend(symbol: str, sma_fast: int, sma_slow: int, tz_offset_min: int, interval: str = "5m"):
    """Same sma_fast/sma_slow trend read _auto_signal_core computes at
    every check (not just at entry) - factored out so the options overlay's
    open-position management can check it too. Reuses fetch_ohlc's own
    180s cache, so calling this for a symbol already checked elsewhere this
    tick is normally a cache hit, not a fresh network call. Returns
    'up'/'down'/None (None = not enough candles yet)."""
    try:
        df = fetch_ohlc(symbol, "5d", interval)
        ts = pd.to_datetime(df["Date"])
        ts_utc = ts.dt.tz_convert("UTC") if ts.dt.tz is not None else ts.dt.tz_localize("UTC")
        ts_local = ts_utc + pd.Timedelta(minutes=tz_offset_min)
        df = df.assign(ts_local=ts_local)
        today_str = (dt.datetime.utcnow() + dt.timedelta(minutes=tz_offset_min)).strftime("%Y-%m-%d")
        today_df = df[df["ts_local"].dt.strftime("%Y-%m-%d") == today_str]
        closes = today_df["Close"].to_numpy(dtype=float)
    except Exception:
        return None
    if len(closes) < max(sma_fast, sma_slow):
        return None
    sma_f = float(np.mean(closes[-sma_fast:]))
    sma_s = float(np.mean(closes[-sma_slow:]))
    return "up" if sma_f > sma_s else "down"


def _detect_direction_signal(symbol: str, orb_minutes: int, sma_fast: int, sma_slow: int,
                              trend_sma: int, tz_offset_min: int, open_min: int, interval: str = "5m"):
    """Direction-only signal (bullish/bearish/None) for the options overlay.
    Mirrors _auto_signal_core's own orb_breakout-with-trend and
    bullish_engulfing entry logic, PLUS their bearish mirrors (orb breakdown,
    bearish engulfing) that the equity engine deliberately never trades (it
    stays long-only). This function trades nothing itself and never opens an
    equity position - it only tells the options layer below which direction,
    if any, the same evidence-backed patterns are currently pointing."""
    now_local = dt.datetime.utcnow() + dt.timedelta(minutes=tz_offset_min)
    today_str = now_local.strftime("%Y-%m-%d")
    try:
        df = fetch_ohlc(symbol, "5d", interval)
        ts = pd.to_datetime(df["Date"])
        ts_utc = ts.dt.tz_convert("UTC") if ts.dt.tz is not None else ts.dt.tz_localize("UTC")
        ts_local = ts_utc + pd.Timedelta(minutes=tz_offset_min)
        df = df.assign(ts_local=ts_local)
        df["date_local"] = df["ts_local"].dt.strftime("%Y-%m-%d")
        today_df = df[df["date_local"] == today_str].reset_index(drop=True)
    except Exception as e:
        return None, f"data_error: {e}", None
    if today_df.empty or len(df) < 2:
        return None, "no_data_yet", None
    today_df = today_df.copy()
    today_df["mins"] = today_df["ts_local"].dt.hour * 60 + today_df["ts_local"].dt.minute

    last_close = float(today_df.iloc[-1]["Close"])
    closes = today_df["Close"].to_numpy(dtype=float)
    sma_f = float(np.mean(closes[-sma_fast:])) if len(closes) >= sma_fast else None
    sma_s = float(np.mean(closes[-sma_slow:])) if len(closes) >= sma_slow else None
    trend = ("up" if sma_f > sma_s else "down") if (sma_f is not None and sma_s is not None) else None

    orb_cutoff = open_min + orb_minutes
    orb_df = today_df[today_df["mins"] < orb_cutoff]
    if not orb_df.empty and today_df["mins"].max() >= orb_cutoff:
        orb_high, orb_low = float(orb_df["High"].max()), float(orb_df["Low"].min())
        if last_close > orb_high and trend == "up":
            return "bullish", "orb_breakout_with_trend", last_close
        if last_close < orb_low and trend == "down":
            return "bearish", "orb_breakdown_with_trend", last_close

    cur_bar, prev_bar = df.iloc[-1], df.iloc[-2]
    cur_bullish, cur_bearish = cur_bar["Close"] > cur_bar["Open"], cur_bar["Close"] < cur_bar["Open"]
    prev_bearish, prev_bullish = prev_bar["Close"] < prev_bar["Open"], prev_bar["Close"] > prev_bar["Open"]
    trend_ok_up = trend_ok_down = True
    if trend_sma > 0:
        full_closes = df["Close"].to_numpy(dtype=float)
        if len(full_closes) < trend_sma:
            trend_ok_up = trend_ok_down = False
        else:
            sma_ref = float(np.mean(full_closes[-trend_sma:]))
            trend_ok_up, trend_ok_down = last_close > sma_ref, last_close < sma_ref

    if (cur_bullish and prev_bearish and cur_bar["Open"] <= prev_bar["Close"]
            and cur_bar["Close"] >= prev_bar["Open"] and trend_ok_up):
        return "bullish", "bullish_engulfing", last_close
    if (cur_bearish and prev_bullish and cur_bar["Open"] >= prev_bar["Close"]
            and cur_bar["Close"] <= prev_bar["Open"] and trend_ok_down):
        return "bearish", "bearish_engulfing", last_close

    return None, "no_signal", last_close


def _options_signal_core(
    underlying: str, capital: float = 400000, daily_risk_pct: float = 2.0,
    risk_per_trade_pct: float = 2.0, rr: float = 3.0, option_stop_pct: float = OPTIONS_STOP_PCT,
    orb_minutes: int = 15, sma_fast: int = 9, sma_slow: int = 21, trend_sma: int = 20,
    interval: str = "5m", tz_offset_min: int = IST_OFFSET_MIN, open_min: int = 9 * 60 + 15,
    close_min: int = 15 * 60 + 30, squareoff_min: int = 15 * 60 + 20, trade_weekends: bool = False,
    currency: str = "USD",
):
    """Options equivalent of _auto_signal_core: same shared capital pool,
    daily-loss cap, RR-minimum and EOD-squareoff discipline
    (docs/TRADING_CONSTRAINTS.md), applied to a real call/put contract
    instead of the underlying. `underlying` must be in OPTIONS_ELIGIBLE_SYMBOLS.
    Position is tracked in option_state, keyed by "{underlying}:OPT-{RIGHT}"
    so it can never collide with that same symbol's own equity position in
    signal_state, and its buy/sell legs are logged into the SAME `trades`
    table (qty = contracts*100, price = premium/share) so today's realized
    P&L and the daily loss cap automatically include it alongside equities -
    one account, one shared risk budget, regardless of instrument."""
    if underlying not in OPTIONS_ELIGIBLE_SYMBOLS:
        return {"underlying": underlying, "status": "not_options_eligible"}

    now_ist = ist_now()
    now_local = dt.datetime.utcnow() + dt.timedelta(minutes=tz_offset_min)
    today_str = now_local.strftime("%Y-%m-%d")
    mins_now = now_local.hour * 60 + now_local.minute

    if not trade_weekends and now_local.weekday() >= 5:
        return {"underlying": underlying, "status": "closed_weekend", "time_local": str(now_local)}
    if mins_now < open_min:
        return {"underlying": underlying, "status": "pre_open", "time_local": str(now_local)}
    is_squareoff_time = mins_now >= squareoff_min
    if mins_now > close_min:
        return {"underlying": underlying, "status": "closed", "time_local": str(now_local)}

    with closing(get_db()) as conn:
        since_ts = ist_midnight_epoch(now_ist)
        realized_today = today_realized_pnl(conn, since_ts)
        daily_loss_cap = capital * daily_risk_pct / 100
        remaining_budget = max(0.0, daily_loss_cap - max(0.0, -realized_today))
        halted = remaining_budget <= 0

        try:
            fx_to_inr = get_fx_to_inr(currency)
        except HTTPException as e:
            return {"underlying": underlying, "status": "fx_error", "detail": e.detail}

        result = {
            "underlying": underlying, "status": "checked", "time_local": str(now_local),
            "realized_today": round(realized_today, 2), "budget_remaining": round(remaining_budget, 2),
            "halted_for_day": halted, "action_taken": "none",
        }

        # ---- manage any open option position on this underlying (either right) ----
        for right in ("call", "put"):
            opt_symbol = f"{underlying}:OPT-{right.upper()}"
            row = conn.execute("SELECT * FROM option_state WHERE opt_symbol = ?", (opt_symbol,)).fetchone()
            if not row:
                continue

            premium = _requote_contract(underlying, row["expiry"], row["strike"], right)
            exit_reason = None
            dte_left = (dt.datetime.strptime(row["expiry"], "%Y-%m-%d") - dt.datetime.utcnow()).days
            if halted:
                exit_reason = "daily_loss_cap_hit"
            elif dte_left <= 0:
                exit_reason = "expiry_reached"
            elif is_squareoff_time:
                exit_reason = "eod_squareoff"
            elif premium is not None and premium >= row["target_premium"]:
                exit_reason = "target_hit"
            elif premium is not None and premium <= row["stop_premium"]:
                exit_reason = "stop_hit"
            else:
                # Same "is the trend that justified this trade still
                # intact?" check the equity engine runs on every open
                # position (docs/TRADING_CONSTRAINTS.md) - a call is a
                # bullish bet (exit if the underlying's trend flips down),
                # a put is a bearish bet (exit if it flips up). Standing
                # policy per explicit user instruction 2026-09-03.
                trend_now = _compute_trend(underlying, sma_fast, sma_slow, tz_offset_min, interval)
                if right == "call" and trend_now == "down":
                    exit_reason = "trend_weakened"
                elif right == "put" and trend_now == "up":
                    exit_reason = "trend_weakened"

            if exit_reason:
                # A stale/failed requote must never block a forced exit
                # (daily halt, EOD, expiry) - fall back to entry premium
                # (0 P&L) rather than leaving a position open past the risk
                # framework's own hard deadlines.
                exit_premium = premium if premium is not None else row["entry_premium"]
                contracts = row["contracts"]
                qty = contracts * 100
                entry_fx = row["fx_to_inr"]
                pnl_native = (exit_premium - row["entry_premium"]) * qty
                pnl_inr = pnl_native * entry_fx
                risk_per_contract = row["entry_premium"] - row["stop_premium"]
                rr_achieved = round((exit_premium - row["entry_premium"]) / risk_per_contract, 2) if risk_per_contract else None
                payload = {
                    "symbol": opt_symbol, "underlying": underlying, "right": right, "action": "sell",
                    "qty": qty, "contracts": contracts, "price": exit_premium, "currency": currency,
                    "fx_to_inr": entry_fx, "strategy": OPTIONS_STRATEGY_TAG, "exit_reason": exit_reason,
                    "entry_price": row["entry_premium"], "stop_loss": row["stop_premium"],
                    "target": row["target_premium"], "rr_target": rr, "rr_achieved": rr_achieved,
                    "strike": row["strike"], "expiry": row["expiry"],
                    "pnl_native": round(pnl_native, 2), "pnl_inr": round(pnl_inr, 2),
                    "pnl_pct_of_capital": round(100 * pnl_inr / capital, 3),
                }
                apply_paper_trade(conn, opt_symbol, "sell", qty, exit_premium)
                conn.execute(
                    "INSERT INTO trades (ts, symbol, action, qty, price, fx_to_inr, strategy, raw_payload) "
                    "VALUES (?, ?, 'sell', ?, ?, ?, ?, ?)",
                    (time.time(), opt_symbol, qty, exit_premium, entry_fx, OPTIONS_STRATEGY_TAG, json.dumps(payload)),
                )
                conn.execute("DELETE FROM option_state WHERE opt_symbol = ?", (opt_symbol,))
                conn.commit()
                result.update(action_taken=f"exited_{right}_{exit_reason}", exit_pnl_inr=payload["pnl_inr"], rr_achieved=rr_achieved)
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

        direction, reason, spot = _detect_direction_signal(
            underlying, orb_minutes, sma_fast, sma_slow, trend_sma, tz_offset_min, open_min, interval,
        )
        result["direction_signal"] = direction
        result["direction_reason"] = reason
        result["spot"] = spot
        if not direction or spot is None:
            result["action_taken"] = "no_signal"
            return result

        right = "call" if direction == "bullish" else "put"
        contract, err = select_option_contract(underlying, spot, right)
        if contract is None:
            result["action_taken"] = "no_qualifying_contract"
            result["reason"] = err
            return result

        entry_premium = contract["premium"]
        stop_premium = round(entry_premium * (1 - option_stop_pct / 100), 4)
        target_premium = round(entry_premium * (1 + rr * option_stop_pct / 100), 4)
        risk_per_contract_native = entry_premium - stop_premium
        risk_per_contract_inr = risk_per_contract_native * 100 * fx_to_inr
        if risk_per_contract_inr <= 0:
            result["action_taken"] = "invalid_stop_skipped"
            return result

        available_capital_inr = max(0.0, capital - deployed_notional(conn))
        max_single_trade_inr = capital / CAPITAL_TRANCHES
        usable_capital_inr = min(available_capital_inr, max_single_trade_inr)

        # Per-trade risk is risk_per_trade_pct% of the capital actually
        # INVESTED IN THIS TRADE (usable_capital_inr), not of the whole
        # account - same explicit standing policy as the equity engine
        # (see _auto_signal_core). remaining_budget is the separate,
        # independently-enforced daily cap measured against TOTAL capital -
        # both apply, whichever binds first.
        risk_amount_inr = min(usable_capital_inr * risk_per_trade_pct / 100, remaining_budget)
        contracts = math.floor(risk_amount_inr / risk_per_contract_inr)
        # 1 contract (100 shares) is the smallest tradeable unit - real
        # option premiums often make even 1 contract's risk-at-stop exceed
        # this one trade's risk_per_trade_pct target (unlike equities, which
        # can size down to a fraction of a share). Rather than silently
        # zeroing out a real, qualified signal the same way the pre-fix
        # integer-floored equity qty did, take the smallest unit whenever
        # its own risk still fits the FULL remaining daily-loss budget - the
        # same "one trade can use the whole day's budget" ceiling
        # docs/TRADING_CONSTRAINTS.md already applies to equities when
        # risk_per_trade_pct == daily_risk_pct, just made explicit here for
        # the contract-quantization case.
        if contracts < 1 and risk_per_contract_inr <= remaining_budget:
            contracts = 1

        notional_per_contract_inr = entry_premium * 100 * fx_to_inr
        if notional_per_contract_inr > 0:
            contracts = min(contracts, math.floor(usable_capital_inr / notional_per_contract_inr))

        if contracts < 1:
            result["action_taken"] = (
                "insufficient_capital" if available_capital_inr < notional_per_contract_inr
                else "budget_too_small_for_1_contract"
            )
            result["available_capital_inr"] = round(available_capital_inr, 2)
            result["contract_considered"] = contract
            return result

        opt_symbol = f"{underlying}:OPT-{right.upper()}"
        qty = contracts * 100
        notional_inr = round(qty * entry_premium * fx_to_inr, 2)
        payload = {
            "symbol": opt_symbol, "underlying": underlying, "right": right, "action": "buy",
            "qty": qty, "contracts": contracts, "price": entry_premium, "currency": currency,
            "fx_to_inr": fx_to_inr, "strategy": OPTIONS_STRATEGY_TAG, "entry_reason": reason,
            "strike": contract["strike"], "expiry": contract["expiry"], "dte": contract["dte"],
            "iv": contract["iv"], "atm_iv": contract["atm_iv"], "delta": contract["delta"],
            "stop_loss": stop_premium, "target": target_premium, "rr_target": rr,
            "risk_amount_inr": round(risk_amount_inr, 2), "notional_inr": notional_inr,
        }
        apply_paper_trade(conn, opt_symbol, "buy", qty, entry_premium)
        conn.execute(
            "INSERT INTO trades (ts, symbol, action, qty, price, fx_to_inr, strategy, raw_payload) "
            "VALUES (?, ?, 'buy', ?, ?, ?, ?, ?)",
            (time.time(), opt_symbol, qty, entry_premium, fx_to_inr, OPTIONS_STRATEGY_TAG, json.dumps(payload)),
        )
        conn.execute(
            "INSERT INTO option_state "
            "(opt_symbol, underlying, day, right, expiry, strike, contracts, entry_premium, "
            "stop_premium, target_premium, entry_iv, entry_delta, entry_ts, fx_to_inr) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(opt_symbol) DO UPDATE SET day=excluded.day, expiry=excluded.expiry, "
            "strike=excluded.strike, contracts=excluded.contracts, entry_premium=excluded.entry_premium, "
            "stop_premium=excluded.stop_premium, target_premium=excluded.target_premium, "
            "entry_iv=excluded.entry_iv, entry_delta=excluded.entry_delta, entry_ts=excluded.entry_ts, "
            "fx_to_inr=excluded.fx_to_inr",
            (opt_symbol, underlying, today_str, right, contract["expiry"], contract["strike"], contracts,
             entry_premium, stop_premium, target_premium, contract["iv"], contract["delta"], time.time(), fx_to_inr),
        )
        conn.commit()
        result.update(action_taken=f"entered_{right}", entry=payload)
        return result


@app.get("/options-signal")
def options_signal(
    underlying: str, capital: float = 400000, daily_risk_pct: float = 2.0,
    risk_per_trade_pct: float = 2.0, rr: float = 3.0, option_stop_pct: float = OPTIONS_STOP_PCT,
    orb_minutes: int = 15, sma_fast: int = 9, sma_slow: int = 21, trend_sma: int = 20,
    interval: str = "5m", tz_offset_min: int = -240, open_min: int = 570,
    close_min: int = 960, squareoff_min: int = 950, trade_weekends: bool = False, currency: str = "USD",
):
    """HTTP wrapper around _options_signal_core - see that function's and the
    options-overlay module docstring above for the actual rules. Defaults
    match the US-market session (SPY/QQQ/AAPL, the only options-eligible
    symbols today - OPTIONS_ELIGIBLE_SYMBOLS)."""
    return _options_signal_core(
        underlying=underlying, capital=capital, daily_risk_pct=daily_risk_pct,
        risk_per_trade_pct=risk_per_trade_pct, rr=rr, option_stop_pct=option_stop_pct,
        orb_minutes=orb_minutes, sma_fast=sma_fast, sma_slow=sma_slow, trend_sma=trend_sma,
        interval=interval, tz_offset_min=tz_offset_min, open_min=open_min, close_min=close_min,
        squareoff_min=squareoff_min, trade_weekends=trade_weekends, currency=currency,
    )


def _auto_signal_core(
    symbol: str,
    capital: float = 400000,
    daily_risk_pct: float = 2.0,
    risk_per_trade_pct: float = 2.0,
    stop_pct: float = 2.0,
    rr: float = 3.0,
    orb_minutes: int = 15,
    sma_fast: int = 9,
    sma_slow: int = 21,
    interval: str = "5m",
    tz_offset_min: int = IST_OFFSET_MIN,
    open_min: int = 9 * 60 + 15,
    close_min: int = 15 * 60 + 30,
    squareoff_min: int = 15 * 60 + 20,
    trade_weekends: bool = False,
    currency: str = "INR",
    strategy: str = "orb_breakout",
    trend_sma: int = 0,
    volume_confirm: bool = False,
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

    `currency` is the symbol's OWN quote currency ("INR" for NSE/BSE, "USD"
    for US stocks/ETFs and crypto). All price levels fetched from yfinance
    (close, orb_high/low, stop, target) stay in that native currency - they
    have to, since that's what the live quote is in. Only capital sizing,
    the daily-loss/capital caps, and reported P&L are converted to INR
    (via a live USD/INR rate, fetched the same cached way as price data),
    because capital and the caps are one shared Rs 2L pool across every
    market. Getting this wrong (treating $1 == Rs 1) would size USD
    positions ~83-88x too large in real terms.

    `strategy` selects the ENTRY trigger only ("orb_breakout" - the above -
    or "bullish_engulfing", a candlestick-pattern entry backtested
    2026-09-03, docs/strategy_log.xlsx). Stop-loss/target/EOD-squareoff/
    daily-loss-cap risk management is identical either way - deliberately
    NOT the open-ended "hold until opposite signal" exit the backtest used,
    so every live strategy stays on the same bounded-risk framework
    (docs/TRADING_CONSTRAINTS.md), not whatever exit its own backtest
    happened to use.
    """
    if strategy == "orb_breakout":
        strategy_tag = f"{ORB_STRATEGY_PREFIX}{orb_minutes}m-sma{sma_fast}-{sma_slow}"
    elif strategy == "bullish_engulfing":
        strategy_tag = f"{ORB_STRATEGY_PREFIX}bullish-engulfing-trend{trend_sma}"
    else:
        raise HTTPException(status_code=400, detail=f"Unknown live strategy {strategy!r}")
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
            fx_to_inr = get_fx_to_inr(currency)
        except HTTPException as e:
            return {"symbol": symbol, "status": "fx_error", "detail": e.detail}

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

        if strategy == "orb_breakout":
            orb_cutoff = open_min + orb_minutes
            orb_df = today_df[today_df["mins"] < orb_cutoff]
            if orb_df.empty or today_df["mins"].max() < orb_cutoff:
                return {
                    "symbol": symbol, "status": "waiting_for_opening_range",
                    "bars_so_far": len(today_df), "time_local": str(now_local),
                }
            orb_high = float(orb_df["High"].max())
            orb_low = float(orb_df["Low"].min())
        else:
            # bullish_engulfing needs no opening range - just enough candles
            # (across days, same as its backtest) to compare two consecutive
            # bars. orb_high/orb_low stay unset here; filled from the
            # pattern candle itself below if/when it fires, purely so
            # signal_state's existing columns have a meaningful "structural
            # reference level" regardless of which strategy is live.
            if len(df) < 2:
                return {
                    "symbol": symbol, "status": "waiting_for_pattern_data",
                    "bars_so_far": len(today_df), "time_local": str(now_local),
                }
            orb_high = orb_low = None

        last = today_df.iloc[-1]
        last_close = float(last["Close"])

        closes = today_df["Close"].to_numpy(dtype=float)
        sma_f = float(np.mean(closes[-sma_fast:])) if len(closes) >= sma_fast else None
        sma_s = float(np.mean(closes[-sma_slow:])) if len(closes) >= sma_slow else None
        trend = ("up" if sma_f > sma_s else "down") if (sma_f is not None and sma_s is not None) else None

        result = {
            "symbol": symbol, "status": "checked", "time_local": str(now_local),
            "currency": currency, "fx_to_inr": round(fx_to_inr, 4),
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
            elif trend == "down":
                # The position is long because trend was "up" at entry
                # (orb_breakout requires it directly; bullish_engulfing's
                # own trend_sma filter serves the same purpose) - if the
                # short-term trend (same sma_fast/sma_slow this function
                # already recomputes every check) has since flipped
                # against the trade, that's real evidence the setup that
                # justified holding is gone, not just the market's normal
                # noise around a fixed stop/target. Exit now instead of
                # riding it all the way down to stop_loss on a trade whose
                # own premise has already broken - standing policy per
                # explicit user instruction 2026-09-03 (docs/TRADING_CONSTRAINTS.md).
                exit_reason = "trend_weakened"
            elif is_squareoff_time:
                exit_reason = "eod_squareoff"

            if exit_reason:
                qty = row["qty"]
                entry_fx = row["fx_to_inr"]  # same rate used at entry, for a consistent round-trip
                pnl_native = (last_close - row["entry_price"]) * qty
                pnl_inr = pnl_native * entry_fx
                stop_dist = row["entry_price"] - row["stop_loss"]
                rr_achieved = round((last_close - row["entry_price"]) / stop_dist, 2) if stop_dist else None
                payload = {
                    "symbol": symbol, "action": "sell", "qty": qty, "price": last_close,
                    "currency": currency, "fx_to_inr": entry_fx,
                    "strategy": strategy_tag, "exit_reason": exit_reason,
                    "entry_price": row["entry_price"], "stop_loss": row["stop_loss"],
                    "target": row["target"], "rr_target": rr, "rr_achieved": rr_achieved,
                    "pnl_native": round(pnl_native, 2), "pnl_inr": round(pnl_inr, 2),
                    "pnl_pct_of_capital": round(100 * pnl_inr / capital, 3),
                }
                apply_paper_trade(conn, symbol, "sell", qty, last_close)
                conn.execute(
                    "INSERT INTO trades (ts, symbol, action, qty, price, fx_to_inr, strategy, raw_payload) "
                    "VALUES (?, ?, 'sell', ?, ?, ?, ?, ?)",
                    (time.time(), symbol, qty, last_close, entry_fx, strategy_tag, json.dumps(payload)),
                )
                conn.execute("DELETE FROM signal_state WHERE symbol = ?", (symbol,))
                conn.commit()
                result.update(
                    action_taken=f"exited_{exit_reason}", exit_pnl_inr=payload["pnl_inr"],
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

        if strategy == "orb_breakout":
            entry_signal = last_close > orb_high and trend == "up"
            structural_low = orb_low
            entry_reason = "orb_breakout_with_trend"
        else:  # bullish_engulfing - see add_strategy_signal() for the backtested version
            cur_bar, prev_bar = df.iloc[-1], df.iloc[-2]
            cur_bullish = cur_bar["Close"] > cur_bar["Open"]
            prev_bearish = prev_bar["Close"] < prev_bar["Open"]
            entry_signal = bool(
                cur_bullish and prev_bearish
                and cur_bar["Open"] <= prev_bar["Close"] and cur_bar["Close"] >= prev_bar["Open"]
            )
            if entry_signal and trend_sma > 0:
                full_closes = df["Close"].to_numpy(dtype=float)
                if len(full_closes) < trend_sma:
                    entry_signal = False
                else:
                    entry_signal = last_close > float(np.mean(full_closes[-trend_sma:]))
            if entry_signal and volume_confirm:
                vol_hist = df["Volume"].to_numpy(dtype=float)
                vol_avg = float(np.mean(vol_hist[-21:-1])) if len(vol_hist) >= 21 else None
                entry_signal = bool(vol_avg) and float(cur_bar["Volume"]) > vol_avg
            structural_low = float(cur_bar["Low"])
            orb_high, orb_low = float(cur_bar["High"]), structural_low  # for result/signal_state display only
            entry_reason = f"bullish_engulfing_trend{trend_sma}"

        if entry_signal:
            # Stop is the strategy's own technical level (opening-range low
            # for orb_breakout, the entry candle's own low for
            # bullish_engulfing), capped at stop_pct% max risk - whichever
            # is tighter (closer to entry) wins, so the trade never risks
            # more than the cap even if the structural level is wider.
            stop_loss_cap = last_close * (1 - stop_pct / 100)
            stop_loss = max(structural_low, stop_loss_cap)
            stop_dist = last_close - stop_loss
            if stop_dist <= 0:
                result["action_taken"] = "invalid_stop_skipped"
                return result
            target = last_close + rr * stop_dist

            # risk_amount is Rs (part of the shared capital pool); stop_dist
            # is native currency (e.g. USD for SPY) - must convert one to
            # the other's currency before dividing, or a USD stop distance
            # gets divided into a Rs budget as if $1 == Rs 1.
            stop_dist_inr = stop_dist * fx_to_inr

            # Capital is shared and finite - cap qty so this trade's notional
            # doesn't push total deployed capital across all open symbols
            # past `capital`. Also: no single new trade may claim more than
            # one tranche (capital / CAPITAL_TRANCHES) of the pool, even if
            # more is sitting free - reserves room for other opportunities
            # to be taken in parallel instead of one big position locking
            # out everything else for the rest of the day (this happened
            # for real 2026-09-03: one BTC-USD entry used the entire pool).
            # Whichever symbol is evaluated first in a poll cycle still gets
            # first claim within its tranche limit; a true cross-symbol
            # "best signal wins" ranking is a fast-follow.
            available_capital_inr = max(0.0, capital - deployed_notional(conn))
            max_single_trade_inr = capital / CAPITAL_TRANCHES
            usable_capital_inr = min(available_capital_inr, max_single_trade_inr)

            # Per-trade risk is risk_per_trade_pct% of the capital actually
            # INVESTED IN THIS TRADE (usable_capital_inr - the tranche/
            # available-capital-capped amount this trade can deploy), not
            # risk_per_trade_pct% of the whole account - explicit standing
            # policy (2026-09-03). The daily loss cap (remaining_budget) is
            # a separate, independently-enforced limit measured against
            # TOTAL capital at the start of the day (see daily_loss_cap
            # above) - both caps apply, whichever binds first forces the
            # exit/entry-block. min() with remaining_budget still means one
            # stopped-out trade can burn the rest of today's whole budget if
            # that's smaller than this trade's own 2%.
            risk_amount_inr = min(usable_capital_inr * risk_per_trade_pct / 100, remaining_budget)
            # Fractional qty, not integer-floored: a high-priced unit (gold
            # ~Rs 4.2L/oz, BTC ~Rs 73L/coin) costs more than this account's
            # entire Rs 2L capital, so int() silently zeroed every such
            # trade to "insufficient_capital" regardless of the strategy's
            # real edge - confirmed this had been blocking every BTC-USD/
            # ETH-USD entry all session. Real brokers (crypto exchanges,
            # fractional-share equity brokers, gold ETF/mini-lot products)
            # support this; treat it the same way here rather than
            # silently discarding a good signal to a rounding artifact.
            qty = risk_amount_inr / stop_dist_inr if stop_dist_inr > 0 else 0.0

            notional_per_unit_inr = last_close * fx_to_inr
            if notional_per_unit_inr > 0:
                qty = min(qty, usable_capital_inr / notional_per_unit_inr)
            qty = round(qty, 6)

            # A trade sized to a few rupees isn't a real position - guard
            # against dust-sized fills from float rounding rather than
            # requiring a whole unit.
            MIN_TRADE_NOTIONAL_INR = 100.0
            if qty <= 0 or qty * notional_per_unit_inr < MIN_TRADE_NOTIONAL_INR:
                result["action_taken"] = (
                    "insufficient_capital" if available_capital_inr < notional_per_unit_inr
                    else "budget_too_small_for_1_unit"
                )
                result["available_capital_inr"] = round(available_capital_inr, 2)
                return result

            notional_inr = qty * last_close * fx_to_inr
            payload = {
                "symbol": symbol, "action": "buy", "qty": qty, "price": last_close,
                "currency": currency, "fx_to_inr": fx_to_inr,
                "strategy": strategy_tag, "entry_reason": entry_reason,
                "stop_loss": stop_loss, "target": target, "rr_target": rr,
                "risk_amount_inr": round(risk_amount_inr, 2),
                "risk_pct_of_capital": round(100 * risk_amount_inr / capital, 3),
                "notional_native": round(qty * last_close, 2), "notional_inr": round(notional_inr, 2),
            }
            apply_paper_trade(conn, symbol, "buy", qty, last_close)
            conn.execute(
                "INSERT INTO trades (ts, symbol, action, qty, price, fx_to_inr, strategy, raw_payload) "
                "VALUES (?, ?, 'buy', ?, ?, ?, ?, ?)",
                (time.time(), symbol, qty, last_close, fx_to_inr, strategy_tag, json.dumps(payload)),
            )
            conn.execute(
                "INSERT INTO signal_state "
                "(symbol, day, status, entry_price, stop_loss, target, qty, entry_ts, orb_high, orb_low, fx_to_inr, interval) "
                "VALUES (?, ?, 'long', ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(symbol) DO UPDATE SET day=excluded.day, status=excluded.status, "
                "entry_price=excluded.entry_price, stop_loss=excluded.stop_loss, "
                "target=excluded.target, qty=excluded.qty, entry_ts=excluded.entry_ts, "
                "orb_high=excluded.orb_high, orb_low=excluded.orb_low, fx_to_inr=excluded.fx_to_inr, "
                "interval=excluded.interval",
                (symbol, today_str, last_close, stop_loss, target, qty, time.time(), orb_high, orb_low, fx_to_inr, interval),
            )
            conn.commit()
            result.update(action_taken="entered_long", entry=payload)
            return result

        result["action_taken"] = "no_signal"
        return result


@app.get("/auto-signal")
def auto_signal(
    symbol: str,
    capital: float = 400000,
    daily_risk_pct: float = 2.0,
    risk_per_trade_pct: float = 2.0,
    stop_pct: float = 2.0,
    rr: float = 3.0,
    orb_minutes: int = 15,
    sma_fast: int = 9,
    sma_slow: int = 21,
    interval: str = "5m",
    tz_offset_min: int = IST_OFFSET_MIN,
    open_min: int = 9 * 60 + 15,
    close_min: int = 15 * 60 + 30,
    squareoff_min: int = 15 * 60 + 20,
    trade_weekends: bool = False,
    currency: str = "INR",
    strategy: str = "orb_breakout",
    trend_sma: int = 0,
    volume_confirm: bool = False,
):
    """HTTP wrapper around _auto_signal_core - see that function's docstring
    for the actual rules. Kept as a thin pass-through so manual/GH-Actions
    calls and the in-process scheduler share one implementation."""
    return _auto_signal_core(
        symbol=symbol, capital=capital, daily_risk_pct=daily_risk_pct,
        risk_per_trade_pct=risk_per_trade_pct, stop_pct=stop_pct, rr=rr,
        orb_minutes=orb_minutes, sma_fast=sma_fast, sma_slow=sma_slow, interval=interval,
        tz_offset_min=tz_offset_min, open_min=open_min, close_min=close_min,
        squareoff_min=squareoff_min, trade_weekends=trade_weekends, currency=currency,
        strategy=strategy, trend_sma=trend_sma, volume_confirm=volume_confirm,
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
    # risk_pct/stop_pct: 2% is the account-wide MAXIMUM (docs/TRADING_CONSTRAINTS.md),
    # not a fixed rate - set lower per symbol where evidence supports it.
    # NIFTY/BANKNIFTY/SENSEX ran the full evidence-backed ceiling (2%) since
    # they have real 60-day backtest evidence behind this exact strategy
    # (docs/daily_logs/2026-09-02-entry-trigger-research.md). SPY/QQQ/AAPL/
    # BTC-USD/ETH-USD have NEVER been backtested with orb_breakout - no
    # evidence yet, so they run at half the ceiling (1%) until they build a
    # track record worth trusting with the full 2%.
    {"symbol": "^NSEI", "orb_minutes": 30, "sma_fast": 5, "sma_slow": 50,
     "tz_offset_min": IST_OFFSET_MIN, "open_min": 555, "close_min": 930, "squareoff_min": 920,
     "trade_weekends": False, "currency": "INR", "risk_pct": 2.0, "stop_pct": 2.0},
    {"symbol": "^NSEBANK", "orb_minutes": 5, "sma_fast": 9, "sma_slow": 50,
     "tz_offset_min": IST_OFFSET_MIN, "open_min": 555, "close_min": 930, "squareoff_min": 920,
     "trade_weekends": False, "currency": "INR", "risk_pct": 2.0, "stop_pct": 2.0},
    {"symbol": "^BSESN", "orb_minutes": 30, "sma_fast": 20, "sma_slow": 50,
     "tz_offset_min": IST_OFFSET_MIN, "open_min": 555, "close_min": 930, "squareoff_min": 920,
     "trade_weekends": False, "currency": "INR", "risk_pct": 2.0, "stop_pct": 2.0},
    # Crypto - UTC, 24/7, trades weekends too. Quoted in USD. No backtest evidence yet.
    {"symbol": "BTC-USD", "orb_minutes": 15, "sma_fast": 9, "sma_slow": 21,
     "tz_offset_min": 0, "open_min": 0, "close_min": 1439, "squareoff_min": 1439,
     "trade_weekends": True, "currency": "USD", "risk_pct": 1.0, "stop_pct": 1.0},
    {"symbol": "ETH-USD", "orb_minutes": 15, "sma_fast": 9, "sma_slow": 21,
     "tz_offset_min": 0, "open_min": 0, "close_min": 1439, "squareoff_min": 1439,
     "trade_weekends": True, "currency": "USD", "risk_pct": 1.0, "stop_pct": 1.0},
    # US markets - ET, quoted in USD. No backtest evidence yet. tz_offset_min=-240
    # is EDT (UTC-4), correct through early Nov 2026; needs -300 (EST) after
    # the US DST changeover.
    {"symbol": "SPY", "orb_minutes": 15, "sma_fast": 9, "sma_slow": 21,
     "tz_offset_min": -240, "open_min": 570, "close_min": 960, "squareoff_min": 950,
     "trade_weekends": False, "currency": "USD", "risk_pct": 1.0, "stop_pct": 1.0},
    {"symbol": "QQQ", "orb_minutes": 15, "sma_fast": 9, "sma_slow": 21,
     "tz_offset_min": -240, "open_min": 570, "close_min": 960, "squareoff_min": 950,
     "trade_weekends": False, "currency": "USD", "risk_pct": 1.0, "stop_pct": 1.0},
    # AAPL: switched 2026-09-03 from unvalidated orb_breakout defaults to
    # bullish_engulfing (trend_sma=20, no volume filter) - the swept params
    # that were actually evidenced for this symbol (100% of 6 swept combos
    # profitable, docs/strategy_log.xlsx). Promoted to the full 2% risk
    # ceiling now that real evidence exists, same bar NIFTY/BANKNIFTY/SENSEX
    # met. orb_minutes/sma_fast/sma_slow are unused by bullish_engulfing but
    # kept here so this dict shape stays uniform across WATCHLIST.
    {"symbol": "AAPL", "orb_minutes": 15, "sma_fast": 9, "sma_slow": 21,
     "tz_offset_min": -240, "open_min": 570, "close_min": 960, "squareoff_min": 950,
     "trade_weekends": False, "currency": "USD", "risk_pct": 2.0, "stop_pct": 2.0,
     "strategy": "bullish_engulfing", "trend_sma": 20, "volume_confirm": False},
    # Added 2026-09-03 per explicit user instruction: don't skip stocks with
    # a real options/futures market - watch them too, not just SPY/QQQ/AAPL.
    # These are the most heavily-optioned, most liquid US mega-caps/ETFs -
    # every one of them has deep, liquid listed options (no chain-
    # availability doubt the way a random small-cap would carry). This is a
    # curated set, not literally every optionable US equity (~4,000+ names
    # via the OCC) - scanning that whole universe every 30s against Yahoo's
    # free/unofficial API would trip rate limits and blow well past the
    # scheduler's own cycle time for no real benefit, since an un-backtested
    # symbol trades at the same conservative 1% ceiling regardless. Same
    # equity engine (orb_breakout, unproven -> half ceiling) as SPY/QQQ;
    # also added to OPTIONS_ELIGIBLE_SYMBOLS below so the options overlay
    # (real strike/IV selection - docs/TRADING_CONSTRAINTS.md) covers them
    # too. Tell me specific tickers to add beyond this set any time.
    {"symbol": "MSFT", "orb_minutes": 15, "sma_fast": 9, "sma_slow": 21,
     "tz_offset_min": -240, "open_min": 570, "close_min": 960, "squareoff_min": 950,
     "trade_weekends": False, "currency": "USD", "risk_pct": 1.0, "stop_pct": 1.0},
    {"symbol": "GOOGL", "orb_minutes": 15, "sma_fast": 9, "sma_slow": 21,
     "tz_offset_min": -240, "open_min": 570, "close_min": 960, "squareoff_min": 950,
     "trade_weekends": False, "currency": "USD", "risk_pct": 1.0, "stop_pct": 1.0},
    {"symbol": "AMZN", "orb_minutes": 15, "sma_fast": 9, "sma_slow": 21,
     "tz_offset_min": -240, "open_min": 570, "close_min": 960, "squareoff_min": 950,
     "trade_weekends": False, "currency": "USD", "risk_pct": 1.0, "stop_pct": 1.0},
    {"symbol": "META", "orb_minutes": 15, "sma_fast": 9, "sma_slow": 21,
     "tz_offset_min": -240, "open_min": 570, "close_min": 960, "squareoff_min": 950,
     "trade_weekends": False, "currency": "USD", "risk_pct": 1.0, "stop_pct": 1.0},
    {"symbol": "NVDA", "orb_minutes": 15, "sma_fast": 9, "sma_slow": 21,
     "tz_offset_min": -240, "open_min": 570, "close_min": 960, "squareoff_min": 950,
     "trade_weekends": False, "currency": "USD", "risk_pct": 1.0, "stop_pct": 1.0},
    {"symbol": "TSLA", "orb_minutes": 15, "sma_fast": 9, "sma_slow": 21,
     "tz_offset_min": -240, "open_min": 570, "close_min": 960, "squareoff_min": 950,
     "trade_weekends": False, "currency": "USD", "risk_pct": 1.0, "stop_pct": 1.0},
    {"symbol": "NFLX", "orb_minutes": 15, "sma_fast": 9, "sma_slow": 21,
     "tz_offset_min": -240, "open_min": 570, "close_min": 960, "squareoff_min": 950,
     "trade_weekends": False, "currency": "USD", "risk_pct": 1.0, "stop_pct": 1.0},
    {"symbol": "AMD", "orb_minutes": 15, "sma_fast": 9, "sma_slow": 21,
     "tz_offset_min": -240, "open_min": 570, "close_min": 960, "squareoff_min": 950,
     "trade_weekends": False, "currency": "USD", "risk_pct": 1.0, "stop_pct": 1.0},
    {"symbol": "JPM", "orb_minutes": 15, "sma_fast": 9, "sma_slow": 21,
     "tz_offset_min": -240, "open_min": 570, "close_min": 960, "squareoff_min": 950,
     "trade_weekends": False, "currency": "USD", "risk_pct": 1.0, "stop_pct": 1.0},
    {"symbol": "V", "orb_minutes": 15, "sma_fast": 9, "sma_slow": 21,
     "tz_offset_min": -240, "open_min": 570, "close_min": 960, "squareoff_min": 950,
     "trade_weekends": False, "currency": "USD", "risk_pct": 1.0, "stop_pct": 1.0},
    {"symbol": "DIA", "orb_minutes": 15, "sma_fast": 9, "sma_slow": 21,
     "tz_offset_min": -240, "open_min": 570, "close_min": 960, "squareoff_min": 950,
     "trade_weekends": False, "currency": "USD", "risk_pct": 1.0, "stop_pct": 1.0},
    {"symbol": "IWM", "orb_minutes": 15, "sma_fast": 9, "sma_slow": 21,
     "tz_offset_min": -240, "open_min": 570, "close_min": 960, "squareoff_min": 950,
     "trade_weekends": False, "currency": "USD", "risk_pct": 1.0, "stop_pct": 1.0},
    # Gold futures - near-24h (COMEX has a brief daily settlement pause,
    # simplified here to the same always-open shape as crypto below).
    # Added 2026-09-03: orb_breakout evidenced strongly on real data - 100%
    # of 24 swept combos profitable, best combo 65% win rate/+676.50 over
    # 60d (docs/strategy_log.xlsx) - a stronger result than most NSE
    # symbols got. Full 2% ceiling, same bar as everything else here.
    {"symbol": "GC=F", "orb_minutes": 15, "sma_fast": 20, "sma_slow": 21,
     "tz_offset_min": 0, "open_min": 0, "close_min": 1439, "squareoff_min": 1439,
     "trade_weekends": False, "currency": "USD", "risk_pct": 2.0, "stop_pct": 2.0},
]

# ---------------------------------------------------------------------------
# Startup reconciliation: Render's free tier has no persistent disk, so every
# redeploy wipes the SQLite DB clean - including any open position, which
# would otherwise just vanish from tracking (never checked against its
# stop/target again, no exit ever recorded). state/open_positions.json is a
# plain git-tracked file, not part of the DB, so it survives every redeploy
# (it's baked into each fresh checkout). The GH Actions workflows
# (live-signals*.yml) write it after every poll, so it's never more than one
# poll interval (<=5 min) stale - not perfectly real-time, but a position is
# never silently forgotten.
STATE_JOURNAL_PATH = os.path.join(os.path.dirname(__file__), "state", "open_positions.json")


def reconcile_open_positions_from_journal():
    """Restore any position the journal remembers but a freshly-wiped DB
    doesn't - as a real 'buy' in trades (so today_realized_pnl's cost-basis
    book is correct once it's eventually closed) and as an open row in
    signal_state (so the normal stop/target/eod-squareoff check on the very
    next scheduler tick picks it up and closes it exactly as if the redeploy
    never happened)."""
    if not os.path.exists(STATE_JOURNAL_PATH):
        return
    try:
        with open(STATE_JOURNAL_PATH) as f:
            journal = json.load(f)
    except Exception as e:
        print(f"[reconcile] could not read {STATE_JOURNAL_PATH}: {e}")
        return

    tz_by_symbol = {cfg["symbol"]: cfg["tz_offset_min"] for cfg in WATCHLIST}
    recovered = []
    with closing(get_db()) as conn:
        for pos in journal.get("open_positions", []):
            symbol = pos["symbol"]

            if pos.get("instrument") == "option":
                # A different table (option_state, not signal_state) and a
                # different row shape (strike/expiry/right, no orb_high/low)
                # - see _options_signal_core. Restored the same way in
                # spirit: a real 'buy' leg in trades for correct cost basis,
                # plus the open row so the very next scheduler tick manages
                # it (requote/stop/target/eod-squareoff) exactly as if the
                # redeploy never happened.
                already_open_opt = conn.execute(
                    "SELECT 1 FROM option_state WHERE opt_symbol = ?", (symbol,)
                ).fetchone()
                if already_open_opt:
                    continue
                entry_ts = pos["entry_ts"]
                day_str = (
                    dt.datetime.utcfromtimestamp(entry_ts) + dt.timedelta(minutes=IST_OFFSET_MIN)
                ).strftime("%Y-%m-%d")
                conn.execute(
                    "INSERT INTO trades (ts, symbol, action, qty, price, fx_to_inr, strategy, raw_payload) "
                    "VALUES (?, ?, 'buy', ?, ?, ?, ?, ?)",
                    (entry_ts, symbol, pos["qty"], pos["entry_price_native"], pos["fx_to_inr"],
                     OPTIONS_STRATEGY_TAG, json.dumps({"recovered_from_journal": True, **pos})),
                )
                apply_paper_trade(conn, symbol, "buy", pos["qty"], pos["entry_price_native"])
                conn.execute(
                    "INSERT INTO option_state "
                    "(opt_symbol, underlying, day, right, expiry, strike, contracts, entry_premium, "
                    "stop_premium, target_premium, entry_iv, entry_delta, entry_ts, fx_to_inr) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(opt_symbol) DO UPDATE SET day=excluded.day, expiry=excluded.expiry, "
                    "strike=excluded.strike, contracts=excluded.contracts, entry_premium=excluded.entry_premium, "
                    "stop_premium=excluded.stop_premium, target_premium=excluded.target_premium, "
                    "entry_iv=excluded.entry_iv, entry_delta=excluded.entry_delta, entry_ts=excluded.entry_ts, "
                    "fx_to_inr=excluded.fx_to_inr",
                    (symbol, pos["underlying"], day_str, pos["right"], pos["expiry"], pos["strike"],
                     pos["contracts"], pos["entry_price_native"], pos["stop_loss_native"],
                     pos["target_native"], pos.get("entry_iv"), pos.get("entry_delta"), entry_ts, pos["fx_to_inr"]),
                )
                recovered.append(symbol)
                continue

            already_open = conn.execute(
                "SELECT 1 FROM signal_state WHERE symbol = ? AND status = 'long'", (symbol,)
            ).fetchone()
            if already_open:
                continue

            entry_ts = pos["entry_ts"]
            tz_offset_min = tz_by_symbol.get(symbol, IST_OFFSET_MIN)
            # Same day derivation _auto_signal_core uses (utcnow + tz offset),
            # applied at entry_ts instead of "now" - if this doesn't match,
            # the very next poll treats the position as stale-from-a-prior-day
            # and silently deletes it (see the row["day"] != today_str check).
            day_str = (
                dt.datetime.utcfromtimestamp(entry_ts) + dt.timedelta(minutes=tz_offset_min)
            ).strftime("%Y-%m-%d")

            strategy_tag = f"{ORB_STRATEGY_PREFIX}recovered"
            conn.execute(
                "INSERT INTO trades (ts, symbol, action, qty, price, fx_to_inr, strategy, raw_payload) "
                "VALUES (?, ?, 'buy', ?, ?, ?, ?, ?)",
                (entry_ts, symbol, pos["qty"], pos["entry_price_native"], pos["fx_to_inr"],
                 strategy_tag, json.dumps({"recovered_from_journal": True, **pos})),
            )
            apply_paper_trade(conn, symbol, "buy", pos["qty"], pos["entry_price_native"])
            conn.execute(
                "INSERT INTO signal_state "
                "(symbol, day, status, entry_price, stop_loss, target, qty, entry_ts, orb_high, orb_low, fx_to_inr, interval) "
                "VALUES (?, ?, 'long', ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(symbol) DO UPDATE SET day=excluded.day, status=excluded.status, "
                "entry_price=excluded.entry_price, stop_loss=excluded.stop_loss, "
                "target=excluded.target, qty=excluded.qty, entry_ts=excluded.entry_ts, "
                "orb_high=excluded.orb_high, orb_low=excluded.orb_low, fx_to_inr=excluded.fx_to_inr, "
                "interval=excluded.interval",
                (symbol, day_str, pos["entry_price_native"], pos["stop_loss_native"],
                 pos["target_native"], pos["qty"], entry_ts, pos["orb_high_native"],
                 pos["orb_low_native"], pos["fx_to_inr"], pos.get("interval", "5m")),
            )
            recovered.append(symbol)
        conn.commit()

    if recovered:
        print(f"[reconcile] restored {len(recovered)} open position(s) from journal: {recovered}")


SCHEDULER_INTERVAL_SECONDS = 30
SCHEDULER_CAPITAL = 400000  # 2026-09-03: raised from Rs 2L to Rs 4L per user instruction ("for today")
SCHEDULER_DAILY_RISK_PCT = 2.0  # account-wide daily loss cap - always the full 2%, not per-symbol
SCHEDULER_RR = 3.0  # 2026-09-03: raised from 1:2 to a 1:3 minimum per standing user instruction

_scheduler_last_tick_ts = 0.0
_scheduler_last_error = None
# Latest _auto_signal_core result per symbol, from the real scheduler tick
# (not a synthetic re-check) - exposed via /scheduler-attempts so there's
# real visibility into what the engine actually decided and why, not just
# closed trades. journal-sync.yml snapshots this into a durable, growing
# attempt log each sync.
_scheduler_last_results: dict = {}

# Round-robin cursor into WATCHLIST for entry-scanning "flat" symbols (no
# open position) - persists across ticks. 2026-09-03: the watchlist grew
# from 9 to 21 symbols (+ 15 options underlyings) in one session; scanning
# every single one, every 30s tick, on Yahoo Finance's free/unofficial
# endpoint risks tripping rate limits and can make one tick's real wall-
# clock time exceed SCHEDULER_INTERVAL_SECONDS, silently degrading the
# actual check cadence for everyone as the roster grows. Round-robin fixes
# this without losing coverage: an open position is ALWAYS checked every
# tick (time-critical - stop/target/eod), and flat symbols rotate through
# a bounded batch per tick instead of all being scanned every time.
_scheduler_rr_cursor = 0
SCHEDULER_ENTRY_SCAN_BATCH_SIZE = 7  # flat symbols freshly entry-scanned per tick, round-robin -
# chosen so a full rotation (21 equity symbols / 7 ~= 3 ticks ~= 90s) lands
# comfortably inside fetch_ohlc's own 180s cache TTL: a flat symbol's
# candle data can't have changed meaningfully faster than that anyway, so
# nothing is being missed by not re-scanning it every single 30s tick -
# the "wasted" cycles just go to other symbols instead.

# Live pipeline visibility for /scheduler-pipeline (trade-view's scanner
# panel) - what's actively in flight right now, not just the last completed
# result. _scheduler_currently_checking is set right before the blocking
# call and cleared right after, so a poll mid-tick shows the real in-flight
# symbol; None means the loop is between ticks (sleeping).
_scheduler_currently_checking: dict | None = None

# How many times each symbol/underlying has actually been checked TODAY
# (IST calendar day, same "day" boundary as the rest of the account -
# ist_midnight_epoch) - for /trade-view's per-asset check-count table.
# Purely in-memory, like _scheduler_last_results itself - resets on a
# Render redeploy the same way the rest of this visibility state does;
# it's a display counter, not a financial record (docs/attempt_log.json is
# the durable, journal-synced trail of what was checked).
_scheduler_check_counts: dict = {}
_scheduler_check_counts_day: str = ""


def _record_scheduler_check(key: str):
    """Bumps key's today-count, resetting everyone's count first if the
    IST calendar day has rolled over since the last check."""
    global _scheduler_check_counts_day
    today_str = ist_now().strftime("%Y-%m-%d")
    if today_str != _scheduler_check_counts_day:
        _scheduler_check_counts.clear()
        _scheduler_check_counts_day = today_str
    _scheduler_check_counts[key] = _scheduler_check_counts.get(key, 0) + 1


def _scheduler_peek_next_batch(n: int = 5) -> list:
    """What the round-robin will scan on its NEXT turn through the flat
    (no open position) symbols, without mutating the real cursor - a pure
    peek, safe to call from an HTTP handler at any time. Mirrors the same
    selection _scheduler_loop itself uses, off the CURRENT (already-
    advanced-past-this-tick) cursor position."""
    with closing(get_db()) as conn:
        open_equity_symbols = {
            r["symbol"] for r in conn.execute(
                "SELECT symbol FROM signal_state WHERE status = 'long'"
            ).fetchall()
        }
    flat_symbols = [cfg["symbol"] for cfg in WATCHLIST if cfg["symbol"] not in open_equity_symbols]
    if not flat_symbols:
        return []
    m = len(flat_symbols)
    count = min(n, m)
    return [flat_symbols[(_scheduler_rr_cursor + i) % m] for i in range(count)]


async def _scheduler_loop():
    global _scheduler_last_tick_ts, _scheduler_last_error, _scheduler_rr_cursor, _scheduler_currently_checking
    while True:
        watchlist_by_symbol = {cfg["symbol"]: cfg for cfg in WATCHLIST}

        with closing(get_db()) as conn:
            open_equity_symbols = {
                r["symbol"] for r in conn.execute(
                    "SELECT symbol FROM signal_state WHERE status = 'long'"
                ).fetchall()
            }
            open_option_underlyings = {
                r["underlying"] for r in conn.execute(
                    "SELECT underlying FROM option_state"
                ).fetchall()
            }

        all_symbols = [cfg["symbol"] for cfg in WATCHLIST]
        flat_symbols = [s for s in all_symbols if s not in open_equity_symbols]
        if flat_symbols:
            n = len(flat_symbols)
            batch_size = min(SCHEDULER_ENTRY_SCAN_BATCH_SIZE, n)
            rr_batch = [flat_symbols[(_scheduler_rr_cursor + i) % n] for i in range(batch_size)]
            _scheduler_rr_cursor = (_scheduler_rr_cursor + batch_size) % n
        else:
            rr_batch = []

        # Always: every symbol with an open equity position (time-critical
        # stop/target/eod check) + every underlying with an open option
        # position (same reason, for the overlay below) + this tick's
        # round-robin entry-scan batch of otherwise-flat symbols.
        symbols_this_tick = open_equity_symbols | open_option_underlyings | set(rr_batch)

        for symbol in symbols_this_tick:
            cfg = watchlist_by_symbol.get(symbol)
            if not cfg:
                continue
            _scheduler_currently_checking = {
                "symbol": symbol, "kind": "equity", "started_at_utc": time.time(),
            }
            _record_scheduler_check(symbol)
            try:
                result = await asyncio.to_thread(
                    _auto_signal_core,
                    symbol=cfg["symbol"], capital=SCHEDULER_CAPITAL,
                    daily_risk_pct=SCHEDULER_DAILY_RISK_PCT,
                    risk_per_trade_pct=cfg["risk_pct"],
                    stop_pct=cfg["stop_pct"], rr=SCHEDULER_RR,
                    orb_minutes=cfg["orb_minutes"], sma_fast=cfg["sma_fast"], sma_slow=cfg["sma_slow"],
                    interval="5m", tz_offset_min=cfg["tz_offset_min"], open_min=cfg["open_min"],
                    close_min=cfg["close_min"], squareoff_min=cfg["squareoff_min"],
                    trade_weekends=cfg["trade_weekends"], currency=cfg["currency"],
                    strategy=cfg.get("strategy", "orb_breakout"),
                    trend_sma=cfg.get("trend_sma", 0), volume_confirm=cfg.get("volume_confirm", False),
                )
                _scheduler_last_results[cfg["symbol"]] = {"checked_at_utc": time.time(), **result}
            except Exception as e:
                _scheduler_last_error = f"{cfg['symbol']}: {e}"
                _scheduler_last_results[cfg["symbol"]] = {
                    "checked_at_utc": time.time(), "symbol": cfg["symbol"],
                    "status": "error", "detail": str(e),
                }
            finally:
                _scheduler_currently_checking = None

        # Options overlay - real calls/puts on the symbols with a live
        # yfinance chain (OPTIONS_ELIGIBLE_SYMBOLS), using that same
        # symbol's own WATCHLIST session config (hours/tz/currency) so it
        # follows the same market clock as the equity engine on that ticker.
        # Covers the SAME symbols_this_tick set as the equity loop above
        # (open positions + this tick's round-robin batch) - not a
        # separate schedule - so a symbol's OHLC fetch (fetch_ohlc, cached
        # 180s) is shared between the two checks instead of doubling the
        # network calls for symbols that are both an equity WATCHLIST entry
        # and options-eligible.
        for underlying in OPTIONS_ELIGIBLE_SYMBOLS:
            if underlying not in symbols_this_tick:
                continue
            cfg = watchlist_by_symbol.get(underlying)
            if not cfg:
                continue
            key = f"{underlying}:OPT"
            _scheduler_currently_checking = {
                "symbol": key, "kind": "options", "started_at_utc": time.time(),
            }
            _record_scheduler_check(key)
            try:
                result = await asyncio.to_thread(
                    _options_signal_core,
                    underlying=underlying, capital=SCHEDULER_CAPITAL,
                    daily_risk_pct=SCHEDULER_DAILY_RISK_PCT,
                    risk_per_trade_pct=cfg["risk_pct"], rr=SCHEDULER_RR,
                    trend_sma=cfg.get("trend_sma", 20),
                    tz_offset_min=cfg["tz_offset_min"], open_min=cfg["open_min"],
                    close_min=cfg["close_min"], squareoff_min=cfg["squareoff_min"],
                    trade_weekends=cfg["trade_weekends"], currency=cfg["currency"],
                )
                _scheduler_last_results[key] = {"checked_at_utc": time.time(), **result}
            except Exception as e:
                _scheduler_last_results[key] = {
                    "checked_at_utc": time.time(), "underlying": underlying,
                    "status": "error", "detail": str(e),
                }
            finally:
                _scheduler_currently_checking = None

        _scheduler_last_tick_ts = time.time()
        await asyncio.sleep(SCHEDULER_INTERVAL_SECONDS)


@app.on_event("startup")
async def _start_scheduler():
    reconcile_open_positions_from_journal()
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


@app.get("/scheduler-attempts")
def scheduler_attempts():
    """The real-time scheduler's latest entry-condition check per symbol -
    what it actually saw and decided (checked/no_signal/entered_long/
    exited_.../pre_open/etc.), not a synthetic re-check. journal-sync.yml
    snapshots this into docs/attempt_log.json each sync so there's a
    persistent trail of what was attempted and why, not just closed
    trades."""
    return _scheduler_last_results


@app.get("/scheduler-pipeline")
def scheduler_pipeline(recent: int = 10, next_n: int = 5):
    """Live scanner view for /trade-view: what was just checked, what's
    being checked RIGHT NOW, and what's queued up next in the round-robin
    (see _scheduler_loop/SCHEDULER_ENTRY_SCAN_BATCH_SIZE). `recent` is the
    max number of most-recently-checked entries to return; `next_n` is how
    far to peek ahead into the round-robin queue."""
    last_checked = sorted(
        ({"symbol": k, **v} for k, v in _scheduler_last_results.items()),
        key=lambda r: r.get("checked_at_utc", 0),
        reverse=True,
    )[:recent]

    # Every symbol ever checked today (equity WATCHLIST entries and
    # "{underlying}:OPT" options rows alike), with its running today-count
    # and its latest known status - the full per-asset table for
    # /trade-view, not just the most-recent few. Includes a symbol that's
    # been checked 0 times today (pre-open all day, say) so the table
    # reflects the whole watchlist, not only what's fired so far.
    all_keys = set(_scheduler_check_counts) | set(_scheduler_last_results) | {
        cfg["symbol"] for cfg in WATCHLIST
    } | {f"{u}:OPT" for u in OPTIONS_ELIGIBLE_SYMBOLS}
    check_counts_today = sorted(
        (
            {
                "symbol": k,
                "checks_today": _scheduler_check_counts.get(k, 0),
                "last_action": (
                    _scheduler_last_results.get(k, {}).get("action_taken")
                    or _scheduler_last_results.get(k, {}).get("status")
                ),
                "last_checked_at_utc": _scheduler_last_results.get(k, {}).get("checked_at_utc"),
            }
            for k in all_keys
        ),
        key=lambda r: (-r["checks_today"], r["symbol"]),
    )

    return {
        "last_checked": last_checked,
        "currently_checking": _scheduler_currently_checking,
        "next_up": _scheduler_peek_next_batch(next_n),
        "check_counts_today": check_counts_today,
        "check_counts_day": _scheduler_check_counts_day,
        "scheduler_interval_seconds": SCHEDULER_INTERVAL_SECONDS,
        "entry_scan_batch_size": SCHEDULER_ENTRY_SCAN_BATCH_SIZE,
        "last_tick_ts": _scheduler_last_tick_ts,
        "server_time_utc": time.time(),
    }


@app.get("/daily-summary")
def daily_summary(capital: float = 400000, daily_risk_pct: float = 2.0):
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
            "SELECT id, ts, symbol, action, qty, price, fx_to_inr, strategy, raw_payload FROM trades "
            "WHERE strategy LIKE ? ORDER BY id",
            (ORB_STRATEGY_PREFIX + "%",),
        ).fetchall()
        # No day filter - a genuinely open position should show regardless of
        # which local trading day it was opened on (relevant once a market
        # other than NSE, with its own local "day", is in the mix).
        open_state = conn.execute("SELECT * FROM signal_state WHERE status = 'long'").fetchall()
        open_option_state = conn.execute("SELECT * FROM option_state").fetchall()

    book: dict[str, dict] = {}
    realized = 0.0
    closed_trades = []
    for t in all_trades:
        sym = t["symbol"]
        price_inr = t["price"] * t["fx_to_inr"]
        b = book.setdefault(sym, {"qty": 0.0, "avg": 0.0})
        if t["action"] == "buy":
            new_qty = b["qty"] + t["qty"]
            b["avg"] = ((b["qty"] * b["avg"]) + (t["qty"] * price_inr)) / new_qty if new_qty else 0.0
            b["qty"] = new_qty
        else:
            pnl = (price_inr - b["avg"]) * min(t["qty"], b["qty"])
            b["qty"] -= t["qty"]
            if t["ts"] < since_ts:
                continue
            realized += pnl
            try:
                extra = json.loads(t["raw_payload"])
            except Exception:
                extra = {}
            closed_trades.append({
                "symbol": sym, "exit_time_utc": t["ts"],
                "entry_price_native": extra.get("entry_price"), "exit_price_native": t["price"],
                "currency": extra.get("currency", "INR"), "qty": t["qty"],
                "pnl_inr": round(pnl, 2), "pnl_pct_of_capital": round(100 * pnl / capital, 3),
                "exit_reason": extra.get("exit_reason"), "rr_target": extra.get("rr_target"),
                "rr_achieved": extra.get("rr_achieved"),
            })

    open_positions = []
    capital_deployed_inr = 0.0
    for r in open_state:
        notional_inr = r["qty"] * r["entry_price"] * r["fx_to_inr"]
        capital_deployed_inr += notional_inr
        open_positions.append({
            "symbol": r["symbol"], "qty": r["qty"],
            "entry_price_native": r["entry_price"], "stop_loss_native": r["stop_loss"],
            "target_native": r["target"], "fx_to_inr": r["fx_to_inr"],
            "notional_inr": round(notional_inr, 2),
            "orb_high_native": r["orb_high"], "orb_low_native": r["orb_low"],
            "entry_ts": r["entry_ts"], "interval": r["interval"],
        })
    for r in open_option_state:
        qty = r["contracts"] * 100
        notional_inr = qty * r["entry_premium"] * r["fx_to_inr"]
        capital_deployed_inr += notional_inr
        opt_symbol = r["opt_symbol"]
        open_positions.append({
            # symbol stays the unique bookkeeping key ("SPY:OPT-CALL") so it
            # never collides with that same underlying's own equity card;
            # "underlying" is the real fetchable ticker for anything (e.g.
            # trade-view's chart) that wants the underlying's own price
            # action instead - the option's own premium isn't a candle
            # series yfinance exposes historically.
            "symbol": opt_symbol, "underlying": r["underlying"], "instrument": "option",
            "right": r["right"], "strike": r["strike"], "expiry": r["expiry"],
            "contracts": r["contracts"], "qty": qty,
            "entry_price_native": r["entry_premium"], "stop_loss_native": r["stop_premium"],
            "target_native": r["target_premium"], "fx_to_inr": r["fx_to_inr"],
            "notional_inr": round(notional_inr, 2),
            "entry_iv": r["entry_iv"], "entry_delta": r["entry_delta"],
            "entry_ts": r["entry_ts"], "interval": "5m",
        })

    daily_loss_cap = capital * daily_risk_pct / 100
    loss_so_far = max(0.0, -realized)
    budget_remaining = max(0.0, daily_loss_cap - loss_so_far)
    wins = [c for c in closed_trades if c["pnl_inr"] > 0]

    return {
        "date_ist": today_str,
        "capital": capital,
        "capital_deployed_inr": round(capital_deployed_inr, 2),
        "capital_available_inr": round(capital - capital_deployed_inr, 2),
        "daily_loss_cap": daily_loss_cap,
        "daily_loss_cap_pct": daily_risk_pct,
        "realized_pnl": round(realized, 2),
        "realized_pnl_pct": round(100 * realized / capital, 3),
        "budget_remaining": round(budget_remaining, 2),
        "halted_for_day": budget_remaining <= 0,
        "closed_trades_count": len(closed_trades),
        "win_rate_pct": round(100 * len(wins) / len(closed_trades), 1) if closed_trades else None,
        "open_positions": open_positions,
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
    capital: float = 400000,
    daily_risk_pct: float = 2.0,
    risk_per_trade_pct: float = 2.0,
    stop_pct: float = 2.0,
    rr: float = 3.0,
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


@app.get("/trade-view")
def trade_view():
    """Self-refreshing candlestick chart for whatever position(s) are
    currently open, with entry/stop/target/opening-range lines overlaid -
    pulls live from /daily-summary + /history client-side, same pattern
    as /live."""
    return FileResponse("static/trade-view.html")
