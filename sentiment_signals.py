"""
Sector/asset sentiment as an entry-signal input - sourced from this repo's
own docs/sentiment_log/YYYY-MM-DD.md files.

Explicit user instruction (2026-09-07): asked why the news/sentiment scan
cadence (30min market hours / 3h otherwise) isn't adjustable from this
session - that automation turned out to be an external Claude routine
outside this repo's own GitHub Actions/scheduler, not something this code
controls. Follow-up instruction, once that was explained: "i want this
info to be used for sector specific knowledge to pick assets for trading
... in almost real time for picking trade." This module is the answer -
it can't change how OFTEN the external routine scans, but it CAN make
this app actually read and act on what that routine already writes,
rather than the data sitting in docs/ unused by the trading logic.

WHAT'S ACTUALLY PARSEABLE: each day's log is prose written by that
routine for a human reader, not a stable machine schema - most scan
entries are freeform updates ("no material change", "holding Neutral").
The one genuinely structured piece is the FIRST scan of the day, which
writes a markdown table (| Symbol | Sentiment | Rationale |). This module
parses the LAST such table found in a day's file (in case a day ever has
more than one) and treats that as the latest known structured sentiment -
it does NOT attempt to parse the freeform prose updates. `as_of_date` is
always returned so a caller/endpoint can see exactly how stale this is,
rather than silently trusting a morning read all day.

FETCHED LIVE FROM GITHUB (raw.githubusercontent.com), not from the local
checkout - main.py's own module docstring precedent for this: Render's
deployed process only has whatever was in the repo AT DEPLOY TIME baked
in; the sentiment routine commits new files/entries throughout the day
completely independent of this app's own deploys. Fetching the raw file
live is what makes "almost real time" (bounded by the external routine's
own cadence + this module's cache TTL) actually true, instead of only-
as-fresh-as-the-last-redeploy.

Only ever a SOFT, fail-open filter on NEW entries (see allows_entry) -
never touches exit/management logic (an existing open position's stop/
target/trailing-stop keeps working exactly as it does today regardless
of sentiment), and never blocks an entry when this data is unavailable,
stale-format, or the network call itself fails - a missing/broken
external feed must never silently halt trading, only forgo one advisory
input to it.
"""
import re
import time

import requests

_RAW_BASE = "https://raw.githubusercontent.com/harshv0029/tv-paper-bot/main/docs/sentiment_log"
_CACHE_TTL_SECONDS = 600  # 10 min - well inside the routine's own fastest (30min) cadence
_cache: dict = {"fetched_at": 0.0, "date": None, "data": None}

# Direct Yahoo-ticker matches (symbols the sentiment log names exactly as
# WATCHLIST already spells them) plus the two NSE indices under their
# common names, not Yahoo's ^-prefixed ones - confirmed real column names
# by reading docs/sentiment_log/*.md directly (see this module's own
# fetch, not guessed). NSE cash equities (*.NS) have no per-stock row in
# the log yet - PROXY_FOR falls back to "NIFTY" as the broad-market read
# for those (see sentiment_proxy_for). MCX proxies (GC=F/SI=F/CL=F) have
# no commodity-sentiment coverage in the log at all - left unmapped
# (allows_entry fails open for any symbol with no mapping).
_DIRECT_PROXY_FOR = {
    "^NSEI": "NIFTY", "^NSEBANK": "BANKNIFTY", "^BSESN": "SENSEX",
    "BTC-USD": "BTC-USD", "ETH-USD": "ETH-USD", "SPY": "SPY", "QQQ": "QQQ", "AAPL": "AAPL",
}

_TABLE_ROW_RE = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(.*?)\s*\|\s*$")


def _normalize_sentiment(raw: str) -> str:
    """'Bearish (mild)' -> 'Bearish', 'Bullish (strong)' -> 'Bullish',
    anything else (including genuinely 'Neutral') -> 'Neutral' - the gate
    only ever needs to distinguish "avoid new longs here" from "no
    objection", so collapsing qualifiers is deliberate, not a data loss
    that matters for this use."""
    raw_lower = raw.strip().lower()
    if raw_lower.startswith("bearish"):
        return "Bearish"
    if raw_lower.startswith("bullish"):
        return "Bullish"
    return "Neutral"


def _parse_last_sentiment_table(markdown_text: str) -> dict:
    """Returns {symbol: normalized_sentiment} from the LAST
    '| Symbol | Sentiment | Rationale |' table in the given markdown -
    see this module's docstring for why only the last table, not every
    prose update, is parsed."""
    lines = markdown_text.splitlines()
    tables_found = []
    current = {}
    in_table = False
    for line in lines:
        stripped = line.strip()
        if stripped.lower().startswith("| symbol") and "sentiment" in stripped.lower():
            if current:
                tables_found.append(current)
            current = {}
            in_table = True
            continue
        if in_table:
            if stripped.startswith("|---") or set(stripped) <= {"|", "-", " ", ":"}:
                continue  # header separator row
            m = _TABLE_ROW_RE.match(stripped)
            if not m:
                in_table = False  # table ended (blank line / prose resumed)
                continue
            symbol, sentiment_raw, _rationale = m.groups()
            current[symbol.strip()] = _normalize_sentiment(sentiment_raw)
    if current:
        tables_found.append(current)
    return tables_found[-1] if tables_found else {}


def _fetch_file(date_str: str) -> str | None:
    url = f"{_RAW_BASE}/{date_str}.md"
    try:
        resp = requests.get(url, timeout=10)
    except Exception:
        return None
    if resp.status_code != 200:
        return None
    return resp.text


def get_latest_sentiment(today_ist_date_str: str) -> dict:
    """{"as_of_date": ..., "signals": {symbol: "Bullish"|"Bearish"|"Neutral"}}
    for the most recent day (today, falling back to yesterday if today's
    file doesn't exist yet - e.g. before the first scan of the day has
    run) that has a parseable table. TTL-cached in-process; never raises -
    a fetch/parse failure returns {"as_of_date": None, "signals": {}} so
    callers (allows_entry) fail open by construction."""
    now = time.time()
    if _cache["data"] is not None and _cache["date"] == today_ist_date_str and (now - _cache["fetched_at"]) < _CACHE_TTL_SECONDS:
        return _cache["data"]

    import datetime as _dt
    try:
        d = _dt.datetime.strptime(today_ist_date_str, "%Y-%m-%d").date()
    except ValueError:
        d = None

    result = {"as_of_date": None, "signals": {}, "source": None}
    for offset in (0, 1):  # today, then yesterday as a fallback
        date_str = (d - _dt.timedelta(days=offset)).strftime("%Y-%m-%d") if d else today_ist_date_str
        text = _fetch_file(date_str)
        if text is None:
            continue
        signals = _parse_last_sentiment_table(text)
        if signals:
            result = {"as_of_date": date_str, "signals": signals, "source": f"docs/sentiment_log/{date_str}.md"}
            break

    _cache["data"] = result
    _cache["date"] = today_ist_date_str
    _cache["fetched_at"] = now
    return result


def sentiment_proxy_for(symbol: str) -> str | None:
    """Which sentiment-log symbol (if any) speaks to this WATCHLIST
    symbol. None means no mapping exists yet - allows_entry treats that
    as fail-open, not as bearish."""
    if symbol in _DIRECT_PROXY_FOR:
        return _DIRECT_PROXY_FOR[symbol]
    if symbol.endswith(".NS"):
        return "NIFTY"  # broad-market proxy - no per-stock sentiment tracked yet
    return None


def allows_entry(symbol: str, today_ist_date_str: str) -> tuple[bool, str]:
    """(allowed, reason) - the ONLY gate this module exposes. Blocks a
    NEW entry only when the latest known sentiment for this symbol's
    proxy is Bearish; fails open (allowed=True) for every other case -
    no mapping, no data fetched yet, a stale/fallback-to-yesterday read,
    or Neutral/Bullish sentiment. See this module's docstring for why
    fail-open is the deliberate default."""
    try:
        data = get_latest_sentiment(today_ist_date_str)
    except Exception as e:
        return True, f"sentiment_fetch_error:{e}"
    proxy = sentiment_proxy_for(symbol)
    if proxy is None:
        return True, "no_sentiment_mapping"
    sentiment = data["signals"].get(proxy)
    if sentiment is None:
        return True, "proxy_not_in_latest_scan"
    if sentiment == "Bearish":
        return False, f"sentiment_bearish:{proxy}:as_of_{data['as_of_date']}"
    return True, f"sentiment_{sentiment.lower()}:{proxy}:as_of_{data['as_of_date']}"
