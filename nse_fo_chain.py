"""
Real F&O contract resolution via Kotak's own live scrip master - NSE
index options AND MCX commodity options.

Explicit user instruction (2026-09-07): "build it right now" (real F&O
order placement) + "also mcx" - this module is the contract-resolution
half of that. No synthesis, no yfinance: NSE index/MCX commodity options
aren't on yfinance's free chain at all (options_pricing.py's
select_option_contract only ever worked for US underliers, which
WATCHLIST stopped trading 2026-09-03 - see its own comment there). Every
strike/expiry/lot-size/instrument-token this module returns comes
straight from Kotak's live search_scrip(...) response, confirmed
field-by-field against real dumps taken 2026-09-07 (NIFTY futures+options,
GOLD/GOLDM/SILVERM/CRUDEOILM) before this was written.

CRITICAL, confirmed live 2026-09-07: kotak_neo.search_scrip's `symbol`
filter is a SUBSTRING match against Kotak's OWN live scrip master, not an
exact one - searching "nifty" real-matched "NIFTYFPI" rows (a wildly
different, low-liquidity contract, lot size 1100) instead of/alongside
genuine NIFTY rows; same failure mode kotak_neo.py's own module docstring
already flagged for MCX ("gold" matching GOLD/GOLDM/GOLDGUINEA/GOLDTEN).
Every function here re-filters the response for an EXACT pSymbolName
match (case-insensitive) before using anything from it - never trust the
substring match alone.

MCX real-money finding (2026-09-07, live dumps): the FULL-size commodity
contract (pSymbolName "GOLD"/"SILVER"/"CRUDEOIL" - same names
kotak_live_feed.py's own already-verified _MCX_SYMBOL_MAP uses for price-
proxy futures) lists FUTURES ONLY in a live dump - no options chain. Only
the MINI contract (pSymbolName "GOLDM"/"SILVERM"/"CRUDEOILM") actually
lists options (real CE/PE rows confirmed live for all three). _UNDERLYING_TO_SEGMENT
below covers both names per commodity - futures resolution against the
full-size name, options resolution against the mini name - a caller
never guesses which to use, select_nse_future/select_nse_option_contract
each take whatever underlying string is actually relevant to what
they're resolving.

quotes()'s response shape IS confirmed (2026-09-07, live GET
/kotak-neo/quotes against the real NIFTY future): a LIST of dicts, e.g.
[{"exchange_token": "68407", "display_symbol": "NIFTY26SEPFUT",
"exchange": "nse_fo", "ltp": "23866.1000"}] - see _extract_ltp's own
comment. search_scrip's real shape (also confirmed the same day, after
an actual live bug - see _fo_rows) is a plain LIST too, not the
{"total_matched","showing"} shape that only exists in main.py's own
/kotak-neo/search-scrip diagnostic wrapper.
"""
import datetime as dt

import kotak_neo

# Exact Kotak pSymbolName -> its exchange_segment - confirmed live
# 2026-09-07 for every entry here (see this module's docstring). Index
# options (NIFTY/BANKNIFTY) share one name for futures+options; MCX
# commodities use TWO different names (full-size for futures, mini for
# options - see docstring) so both appear here as separate keys.
#
# SENSEX added 2026-09-16 (explicit user request), confirmed live the
# same day via GET /kotak-neo/search-scrip against exchange_segment=
# bse_fo: real IF (future, lot_size=20) and IO (option, real CE/PE rows,
# lot_size=20, 100-point strike spacing, e.g. 67000/67100/67200...)
# contracts exist under the EXACT pSymbolName "SENSEX". A separate,
# genuinely distinct BSE index "SENSEX50" (lot_size=75, ~23000-strike
# range) is ALSO real and ALSO live on bse_fo and substring-matches
# "sensex" - NOT added here, out of scope of what was asked; _fo_rows's
# existing exact-pSymbolName filter already excludes it correctly, same
# discipline as the NIFTY/NIFTYFPI and MCX GOLD/GOLDM cases above.
_UNDERLYING_TO_SEGMENT = {
    "NIFTY": "nse_fo", "BANKNIFTY": "nse_fo",
    "SENSEX": "bse_fo",
    "GOLD": "mcx_fo", "GOLDM": "mcx_fo",
    "SILVER": "mcx_fo", "SILVERM": "mcx_fo",
    "CRUDEOIL": "mcx_fo", "CRUDEOILM": "mcx_fo",
}

# Single-stock F&O (2026-09-16, explicit user request: "Update this to
# all tickers Not just equity" -> "Expand F&O trading to single-stock
# options too"). Confirmed live the same day via GET /kotak-neo/
# search-scrip against exchange_segment=nse_fo, option_type=FUT, no
# symbol filter (downloads the whole nse_fo futures universe in one
# call - same "one unfiltered call costs the same as a filtered one"
# reasoning kotak_live_feed.py's _resolve_mcx_tokens already documents):
# every pInstType=="FUTSTK" row's pSymbolName is EXACTLY the bare NSE
# equity ticker (e.g. "RELIANCE"), same convention kotak_live_feed.py's
# own _bare_nse_symbol already assumes for the cash-market side. 210
# distinct FUTSTK names found live that day - this is that exact
# confirmed list, not a guessed/scraped "F&O eligible stocks" list from
# anywhere else, since NSE's F&O-eligible set changes periodically and
# only Kotak's own live scrip master is this module's source of truth.
#
# CRITICAL, distinct from every other underlying in this module:
# confirmed live the same day that single-stock F&O in India is
# PHYSICALLY settled (pSettlementType="Physical" on a real RELIANCE
# contract), not cash-settled like every index/commodity underlying
# above. kotak_real_fo_orders.py's own docstring ("premium paid is the
# entire risk, capped and known upfront") is true for index options and
# FALSE for single-stock ones left open past expiry - a bought call/put
# on any of these 210 names that isn't closed before expiry can result
# in a REAL obligation to buy/sell the underlying shares (500+ per lot,
# lot-size dependent), not a cash settlement. Any code that places real
# orders against this list MUST force-close the position before expiry;
# this module only resolves contracts, it never places or manages a
# position, so that safety rule belongs wherever real orders eventually
# get wired up, not here - flagging it at the point of definition so it
# can't be missed later.
STOCK_FO_UNDERLYINGS = (
    "360ONE", "ABB", "ABCAPITAL", "ADANIENSOL", "ADANIENT", "ADANIGREEN", "ADANIPORTS",
    "ADANIPOWER", "ALKEM", "AMBER", "AMBUJACEM", "ANGELONE", "APLAPOLLO", "APOLLOHOSP",
    "ASHOKLEY", "ASIANPAINT", "ASTRAL", "ATHERENERG", "AUBANK", "AUROPHARMA", "AXISBANK",
    "BAJAJ-AUTO", "BAJAJFINSV", "BAJAJHLDNG", "BAJFINANCE", "BANDHANBNK", "BANKBARODA",
    "BANKINDIA", "BDL", "BEL", "BHARATFORG", "BHARTIARTL", "BHEL", "BIOCON", "BLUESTARCO",
    "BOSCHLTD", "BPCL", "BRITANNIA", "BSE", "CAMS", "CANBK", "CDSL", "CGPOWER", "CHOLAFIN",
    "CIPLA", "COALINDIA", "COCHINSHIP", "COFORGE", "COLPAL", "CONCOR", "CROMPTON",
    "CUMMINSIND", "DABUR", "DELHIVERY", "DIVISLAB", "DIXON", "DLF", "DMART", "DRREDDY",
    "EICHERMOT", "ETERNAL", "FEDERALBNK", "FORCEMOT", "FORTIS", "GAIL", "GLENMARK",
    "GMRAIRPORT", "GODFRYPHLP", "GODREJCP", "GODREJPROP", "GRASIM", "GVT&D", "HAL", "HAVELLS",
    "HCLTECH", "HDFCAMC", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO", "HINDALCO", "HINDPETRO",
    "HINDUNILVR", "HINDZINC", "HYUNDAI", "ICICIBANK", "ICICIGI", "ICICIPRULI", "IDEA",
    "IDFCFIRSTB", "IEX", "INDHOTEL", "INDIANB", "INDIGO", "INDUSINDBK", "INDUSTOWER", "INFY",
    "INOXWIND", "IOC", "IREDA", "IRFC", "ITC", "JINDALSTEL", "JIOFIN", "JSWENERGY", "JSWSTEEL",
    "JUBLFOOD", "KALYANKJIL", "KAYNES", "KEI", "KFINTECH", "KOTAKBANK", "KPITTECH",
    "LAURUSLABS", "LICHSGFIN", "LICI", "LODHA", "LT", "LTF", "LTM", "LUPIN", "M&M", "MAHABANK",
    "MANAPPURAM", "MANKIND", "MARICO", "MARUTI", "MAXHEALTH", "MAZDOCK", "MCX", "MFSL",
    "MOTHERSON", "MOTILALOFS", "MPHASIS", "MUTHOOTFIN", "NAM-INDIA", "NATIONALUM", "NAUKRI",
    "NBCC", "NESTLEIND", "NHPC", "NMDC", "NTPC", "NYKAA", "OBEROIRLTY", "OFSS", "OIL", "ONGC",
    "PAGEIND", "PATANJALI", "PAYTM", "PERSISTENT", "PETRONET", "PFC", "PGEL", "PHOENIXLTD",
    "PIDILITIND", "PIIND", "PNB", "PNBHOUSING", "POLICYBZR", "POLYCAB", "POWERGRID",
    "POWERINDIA", "PREMIERENE", "PRESTIGE", "RADICO", "RBLBANK", "RECLTD", "RELIANCE", "RVNL",
    "SAGILITY", "SAIL", "SBICARD", "SBILIFE", "SBIN", "SHREECEM", "SHRIRAMFIN", "SIEMENS",
    "SOLARINDS", "SONACOMS", "SRF", "SUNPHARMA", "SUPREMEIND", "SUZLON", "SWIGGY",
    "TATACONSUM", "TATAELXSI", "TATAPOWER", "TATASTEEL", "TCS", "TECHM", "TIINDIA", "TITAN",
    "TMPV", "TORNTPHARM", "TRENT", "TVSMOTOR", "ULTRACEMCO", "UNIONBANK", "UNITDSPR",
    "UNOMINDA", "UPL", "VBL", "VEDL", "VMM", "VOLTAS", "WAAREEENER", "WIPRO", "YESBANK",
    "ZYDUSLIFE",
)
_UNDERLYING_TO_SEGMENT.update({name: "nse_fo" for name in STOCK_FO_UNDERLYINGS})

OPTIONS_MIN_DTE = 1
OPTIONS_MAX_DTE = 10  # same near-week window options_pricing.py already uses for US chains


def _parse_expiry(p_expiry_date: str) -> dt.date:
    # "27Oct2026" - confirmed real format from the live 2026-09-07 dumps.
    return dt.datetime.strptime(p_expiry_date, "%d%b%Y").date()


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fo_rows(underlying: str, option_type: str | None = None):
    fo_symbol = underlying.upper()
    segment = _UNDERLYING_TO_SEGMENT.get(fo_symbol)
    if segment is None:
        return [], f"no_segment_mapping_for:{underlying}"
    try:
        resp = kotak_neo.search_scrip(
            exchange_segment=segment, symbol=fo_symbol.lower(), option_type=option_type,
        )
    except Exception as e:
        return [], f"search_scrip_error:{e}"
    # REAL, CONFIRMED response shape (2026-09-07, found live - a genuine bug
    # in an earlier version of this function, not a Kotak API limitation):
    # kotak_neo.search_scrip returns the SDK's raw result UNMODIFIED - a
    # plain LIST of scrip dicts on success (confirmed from main.py's own
    # /kotak-neo/search-scrip endpoint: `if isinstance(result, list): ...` -
    # the "total_matched"/"showing" shape only exists in THAT diagnostic
    # endpoint's own wrapper, built by slicing the real list to `limit`;
    # it is NOT what search_scrip itself returns). A dict response means
    # an error (e.g. {"error": [...]} for bad TOTP, or the SDK's own
    # {"Error": e, "message": "Exchange Segment is not available"}) - see
    # kotak_neo.py's search_scrip docstring. The earlier version of this
    # function looked for a "showing" key that never existed on the real
    # list response, so _fo_rows always silently returned zero rows -
    # caught live 2026-09-07 by comparing this function's own failure
    # against a direct GET /kotak-neo/search-scrip call that DID find the
    # real NIFTY future rows.
    if isinstance(resp, list):
        rows = resp
    elif isinstance(resp, dict):
        err = resp.get("error") or resp.get("Error") or resp.get("message")
        return [], f"search_scrip_error_response:{err}"
    else:
        return [], f"unexpected_search_scrip_response_type:{type(resp).__name__}"
    exact = [r for r in rows if str(r.get("pSymbolName", "")).strip().upper() == fo_symbol]
    if not exact:
        return [], f"no_exact_pSymbolName_match_for:{fo_symbol}"
    return exact, None


def select_nse_future(underlying: str):
    """Nearest-expiry future contract for `underlying`. Returns
    (contract_dict, None) or (None, reason_str) - never invents a
    contract. contract_dict: {underlying, kotak_trading_symbol,
    instrument_token, exchange_segment, lot_size, expiry (YYYY-MM-DD), dte}.

    Not wired to any automatic real entry in main.py - see
    kotak_real_fo_orders.py's module docstring for why (no backtested
    outright-futures signal exists, and a 1-lot NIFTY future's own margin
    made it impractical at every capital level checked live 2026-09-07).
    Exposed for manual/diagnostic use and so futures need no new
    resolution code later, only a wiring decision.

    Real reliability finding (2026-09-07): search_scrip's `symbol` filter
    is a broad substring match, and Kotak's OWN API only ever returns a
    small top-N "showing" slice out of the real total_matched count (a
    live "nifty" search returned total_matched=11840 but only ~20 rows) -
    without a type filter, that slice can easily be dominated by
    NIFTYFPI/FINNIFTY/MIDCPNIFTY/NIFTYNXT50/every NIFTY option strike
    and miss the actual NIFTY future entirely (confirmed live: a bare
    search_scrip("nse_fo","nifty") call found it, but this function's
    OWN first version - which passed no option_type - did not, on the
    live deployed endpoint). option_type="FUT" is the SDK's own real,
    documented value for narrowing server-side to futures rows only
    (confirmed from the SDK's own search_scrip docstring) - passing it
    here makes the "showing" slice almost entirely futures contracts for
    this symbol, not diluted by every option strike across every
    similarly-named product."""
    rows, err = _fo_rows(underlying, option_type="FUT")
    if err:
        return None, err
    # FUTIDX (NSE index futures) or FUTCOM (MCX commodity futures) -
    # both confirmed real pInstType values from the live 2026-09-07 dumps.
    futs = [r for r in rows if r.get("pInstType") in ("FUTIDX", "FUTCOM")]
    if not futs:
        return None, "no_future_rows"
    with_dte = []
    for r in futs:
        try:
            exp = _parse_expiry(r["pExpiryDate"])
        except Exception:
            continue
        dte = (exp - dt.date.today()).days
        if dte >= 0:
            with_dte.append((dte, exp, r))
    if not with_dte:
        return None, "no_upcoming_future"
    dte, exp, row = min(with_dte, key=lambda t: t[0])
    return {
        "underlying": underlying, "kotak_trading_symbol": row["pTrdSymbol"],
        "instrument_token": str(row["pSymbol"]), "exchange_segment": _UNDERLYING_TO_SEGMENT[underlying.upper()],
        "lot_size": int(row["lLotSize"]), "expiry": exp.strftime("%Y-%m-%d"), "dte": dte,
    }, None


def select_nse_option_contract(underlying: str, spot: float, right: str):
    """Nearest-ATM strike, nearest valid-DTE-window expiry, for
    `underlying`'s `right` ('call'/'put'). Returns (contract_dict, None)
    or (None, reason_str). Mirrors options_pricing.py's
    select_option_contract's field names where the two overlap
    (underlying/right/expiry/dte/strike/premium) but carries no greeks -
    Kotak's scrip master doesn't carry IV/delta the way a yfinance chain
    does, so ATM selection substitutes for delta-targeting here. premium
    is a live LTP from kotak_neo.quotes(), never synthetic.

    KNOWN RELIABILITY GAP (2026-09-07, see select_nse_future's own
    docstring for the fuller finding): Kotak's search_scrip only ever
    returns a small top-N slice of a broad substring match, and for
    "nifty" specifically that match competes against NIFTYFPI/FINNIFTY/
    MIDCPNIFTY/NIFTYNXT50's own option strikes too - option_type
    narrows to CE/PE only (already applied here) but can't fully
    eliminate that competition the way option_type="FUT" does for
    futures. This function still fails safe either way (a missed
    contract returns "no_option_rows"/no_exact_pSymbolName_match, never
    a wrong one - see _fo_rows's own exact-match filter) - it just may
    more often report no contract for NIFTY specifically than for a less
    crowded underlying (BANKNIFTY, GOLDM, SILVERM, CRUDEOILM)."""
    opt_type = "ce" if right == "call" else "pe"
    rows, err = _fo_rows(underlying, option_type=opt_type)
    if err:
        return None, err
    opt_rows = [r for r in rows if str(r.get("pOptionType", "")).strip().lower() == opt_type]
    if not opt_rows:
        return None, "no_option_rows"

    by_expiry: dict = {}
    for r in opt_rows:
        try:
            exp = _parse_expiry(r["pExpiryDate"])
        except Exception:
            continue
        by_expiry.setdefault(exp, []).append(r)

    today = dt.date.today()
    candidates = [(exp, (exp - today).days) for exp in by_expiry if (exp - today).days >= 0]
    in_window = [(exp, dte) for exp, dte in candidates if OPTIONS_MIN_DTE <= dte <= OPTIONS_MAX_DTE]
    pool = in_window or candidates
    if not pool:
        return None, "no_upcoming_expiry"
    expiry, dte = min(pool, key=lambda t: t[1])

    chain = by_expiry[expiry]
    # dStrikePrice; is the real strike * 100 - confirmed from the live
    # 2026-09-07 dump (e.g. pTrdSymbol "...840CE" carried
    # dStrikePrice;: 84000.0). The trailing semicolon is part of the real
    # field name, not a typo.
    scored = []
    for r in chain:
        strike = _to_float(r.get("dStrikePrice;"))
        if strike is None:
            continue
        scored.append((abs(strike / 100.0 - spot), strike / 100.0, r))
    if not scored:
        return None, "no_strike_data"
    _, atm_strike, atm_row = min(scored, key=lambda t: t[0])

    segment = _UNDERLYING_TO_SEGMENT[underlying.upper()]
    try:
        q = kotak_neo.quotes(
            [{"instrument_token": str(atm_row["pSymbol"]), "exchange_segment": segment}], quote_type="ltp",
        )
    except Exception as e:
        return None, f"quotes_error:{e}"
    premium = _extract_ltp(q)
    if premium is None or premium <= 0:
        return None, "no_live_premium"

    return {
        "underlying": underlying, "right": right, "expiry": expiry.strftime("%Y-%m-%d"), "dte": dte,
        "strike": atm_strike, "premium": round(premium, 2),
        "kotak_trading_symbol": atm_row["pTrdSymbol"], "instrument_token": str(atm_row["pSymbol"]),
        "exchange_segment": segment, "lot_size": int(atm_row["lLotSize"]),
    }, None


def classify_expiries_weekly_monthly(expiries: list) -> dict:
    """Pure function (no network call) - buckets a list of `datetime.date`
    expiries into {"weekly": date|None, "monthly": date|None}. Added
    2026-09-16 for F&O chain monitoring (weekly/monthly tracked
    separately, per explicit user instruction).

    Rule (a heuristic, not an NSE-published rule - NSE doesn't expose a
    "this expiry is the monthly one" flag anywhere this codebase already
    reads): "monthly" = the LATEST available expiry that falls within the
    SOONEST expiry's own calendar month, since NSE's monthly index-options
    contract for a given month simply IS that month's last weekly expiry
    (same contract, not a separate listing). "weekly" = the SOONEST
    available expiry overall (today's/next Thursday) - usually differs
    from "monthly" except during the final week of a month, when they can
    legitimately be the same date - both keys may then hold equal dates,
    which is correct, not a bug.

    `expiries` must be non-empty `datetime.date` objects, already filtered
    to today-or-later by the caller (this function does no date-math
    beyond grouping/comparison)."""
    if not expiries:
        return {"weekly": None, "monthly": None}
    weekly = min(expiries)
    this_month = [e for e in expiries if (e.year, e.month) == (weekly.year, weekly.month)]
    monthly = max(this_month) if this_month else weekly
    return {"weekly": weekly, "monthly": monthly}


def select_nse_option_contract_by_expiry_class(underlying: str, spot: float, right: str, expiry_class: str):
    """Same ATM-strike/live-premium resolution as select_nse_option_contract,
    but lets the caller choose "weekly" or "monthly" instead of always the
    single nearest-DTE-window expiry - added 2026-09-16 for F&O chain
    monitoring, so weekly and monthly contracts can be tracked as two
    genuinely separate rows rather than only ever seeing whichever one
    select_nse_option_contract's OPTIONS_MIN_DTE/MAX_DTE window happened to
    pick. Returns (contract_dict, None) or (None, reason_str) - same
    fields as select_nse_option_contract, plus "expiry_class"."""
    if expiry_class not in ("weekly", "monthly"):
        return None, f"invalid_expiry_class:{expiry_class}"
    opt_type = "ce" if right == "call" else "pe"
    rows, err = _fo_rows(underlying, option_type=opt_type)
    if err:
        return None, err
    opt_rows = [r for r in rows if str(r.get("pOptionType", "")).strip().lower() == opt_type]
    if not opt_rows:
        return None, "no_option_rows"

    by_expiry: dict = {}
    for r in opt_rows:
        try:
            exp = _parse_expiry(r["pExpiryDate"])
        except Exception:
            continue
        by_expiry.setdefault(exp, []).append(r)

    today = dt.date.today()
    upcoming = [e for e in by_expiry if (e - today).days >= 0]
    if not upcoming:
        return None, "no_upcoming_expiry"
    chosen = classify_expiries_weekly_monthly(upcoming)[expiry_class]
    if chosen is None:
        return None, "no_matching_expiry_class"

    chain = by_expiry[chosen]
    scored = []
    for r in chain:
        strike = _to_float(r.get("dStrikePrice;"))
        if strike is None:
            continue
        scored.append((abs(strike / 100.0 - spot), strike / 100.0, r))
    if not scored:
        return None, "no_strike_data"
    _, atm_strike, atm_row = min(scored, key=lambda t: t[0])

    segment = _UNDERLYING_TO_SEGMENT[underlying.upper()]
    try:
        q = kotak_neo.quotes(
            [{"instrument_token": str(atm_row["pSymbol"]), "exchange_segment": segment}], quote_type="ltp",
        )
    except Exception as e:
        return None, f"quotes_error:{e}"
    premium = _extract_ltp(q)
    if premium is None or premium <= 0:
        return None, "no_live_premium"

    dte = (chosen - today).days
    return {
        "underlying": underlying, "right": right, "expiry": chosen.strftime("%Y-%m-%d"), "dte": dte,
        "expiry_class": expiry_class, "strike": atm_strike, "premium": round(premium, 2),
        "kotak_trading_symbol": atm_row["pTrdSymbol"], "instrument_token": str(atm_row["pSymbol"]),
        "exchange_segment": segment, "lot_size": int(atm_row["lLotSize"]),
    }, None


def list_nse_option_strike_chain(underlying: str, right: str, expiry_class: str):
    """Every live strike (not just the single ATM contract
    select_nse_option_contract_by_expiry_class picks) for `underlying`'s
    `right` at the given `expiry_class` ('weekly'/'monthly') - added
    2026-09-16, explicit user request to monitor "every strike" (e.g.
    24500, 24550, 24600...) rather than only the nearest-to-spot one.
    Returns (chain, None) or (None, reason_str). chain: list of dicts
    sorted by strike ascending, same field shape as
    select_nse_option_contract_by_expiry_class's single-contract dict
    MINUS 'premium' - this is contract-resolution only (strike/expiry/
    instrument-token/lot-size straight from Kotak's live scrip master, no
    network call beyond that one search_scrip). Fetching a live LTP for
    every strike in the chain (potentially dozens per underlying/expiry)
    is a separate, not-yet-built concern: kotak_neo.quotes()'s
    instrument_tokens param accepts a list, but this module has only ever
    confirmed it live with a single-instrument list (see every other
    quotes() call site here) - never assume multi-instrument batching
    works without confirming it live first, same discipline as
    everything else in this module."""
    if expiry_class not in ("weekly", "monthly"):
        return None, f"invalid_expiry_class:{expiry_class}"
    opt_type = "ce" if right == "call" else "pe"
    rows, err = _fo_rows(underlying, option_type=opt_type)
    if err:
        return None, err
    opt_rows = [r for r in rows if str(r.get("pOptionType", "")).strip().lower() == opt_type]
    if not opt_rows:
        return None, "no_option_rows"

    by_expiry: dict = {}
    for r in opt_rows:
        try:
            exp = _parse_expiry(r["pExpiryDate"])
        except Exception:
            continue
        by_expiry.setdefault(exp, []).append(r)

    today = dt.date.today()
    upcoming = [e for e in by_expiry if (e - today).days >= 0]
    if not upcoming:
        return None, "no_upcoming_expiry"
    chosen = classify_expiries_weekly_monthly(upcoming)[expiry_class]
    if chosen is None:
        return None, "no_matching_expiry_class"

    segment = _UNDERLYING_TO_SEGMENT[underlying.upper()]
    dte = (chosen - today).days
    chain = []
    for r in by_expiry[chosen]:
        # dStrikePrice; is the real strike * 100 - see
        # select_nse_option_contract's own comment on this field.
        strike = _to_float(r.get("dStrikePrice;"))
        if strike is None:
            continue
        chain.append({
            "underlying": underlying, "right": right, "expiry": chosen.strftime("%Y-%m-%d"),
            "dte": dte, "expiry_class": expiry_class, "strike": strike / 100.0,
            "kotak_trading_symbol": r["pTrdSymbol"], "instrument_token": str(r["pSymbol"]),
            "exchange_segment": segment, "lot_size": int(r["lLotSize"]),
        })
    if not chain:
        return None, "no_strike_data"
    chain.sort(key=lambda c: c["strike"])
    return chain, None


# Explicit user instruction 2026-09-16: subscribe/trade a bounded ATM +/-
# N strike band, not every listed strike - live-confirmed capacity math
# against Kotak's WebSocket max_subscriptions=3000 cap (see
# kotak_live_feed.py for where this actually gets subscribed): N=15 means
# 15 strikes above + 15 below + ATM itself = 31 strikes x 2 rights (CE/PE)
# x 3 underlyings (NIFTY/BANKNIFTY/SENSEX) x 2 expiry classes (weekly/
# monthly) = 372 option contracts, plus ~6 futures - comfortably under
# the cap alongside the existing 206-symbol equity/index watchlist
# already on the same feed (206 + 372 + 6 ~= 584 of 3000).
DEFAULT_ATM_STRIKE_BAND = 15


def select_atm_banded_option_strikes(underlying: str, spot: float, right: str, expiry_class: str,
                                      band: int = DEFAULT_ATM_STRIKE_BAND):
    """The `band` strikes immediately above AND below the at-the-money
    strike (up to 2*band + 1 strikes total - fewer at either end of a
    short real chain) for `underlying`'s `right` at `expiry_class` -
    added 2026-09-16, explicit user instruction to subscribe/trade a
    bounded band around ATM rather than every listed strike (deep ITM/
    OTM strikes rarely have real liquidity, and Kotak's WebSocket feed
    has a hard subscription cap - see DEFAULT_ATM_STRIKE_BAND's own
    comment for the capacity math this band size was chosen against).
    Returns (chain, None) or (None, reason_str); chain is a sub-list of
    list_nse_option_strike_chain's own return value, unchanged field
    shape, still sorted by strike ascending."""
    if band <= 0:
        return None, f"invalid_band:{band}"
    chain, err = list_nse_option_strike_chain(underlying, right, expiry_class)
    if err:
        return None, err
    atm_idx = min(range(len(chain)), key=lambda i: abs(chain[i]["strike"] - spot))
    lo = max(0, atm_idx - band)
    hi = min(len(chain), atm_idx + band + 1)
    return chain[lo:hi], None


def _extract_ltp(quotes_response) -> float | None:
    """REAL, CONFIRMED response shape (2026-09-07, live GET
    /kotak-neo/quotes?exchange_segment=nse_fo&instrument_token=68407 against
    the real NIFTY future): a LIST of dicts, e.g.
    [{"exchange_token": "68407", "display_symbol": "NIFTY26SEPFUT",
    "exchange": "nse_fo", "ltp": "23866.1000"}] - same "assumed dict,
    got a list" mistake this module's search_scrip parsing had (see
    _fo_rows's own comment on that real bug) - fixed the same way here:
    treat a list as the real success shape directly, a dict as an error
    response (kotak_neo.quotes's own {"error": [...]} validation-failure
    shape), and never guess past that."""
    if isinstance(quotes_response, list):
        data = quotes_response[0] if quotes_response else None
    elif isinstance(quotes_response, dict):
        return None  # error response (e.g. {"error": [...]}) - never guess a price from it
    else:
        return None
    if not isinstance(data, dict):
        return None
    for key in ("ltp", "last_price", "lastPrice", "LTP"):
        if key in data:
            val = _to_float(data[key])
            if val is not None:
                return val
    return None
