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

quotes()'s exact response shape for nse_fo/mcx_fo has NOT been
independently confirmed the way search_scrip/margin_required have -
_extract_ltp is deliberately defensive (tries the field names
kotak_neo.quotes's own docstring implies, gives up cleanly rather than
guessing) so a shape surprise fails safe (refuses the contract) instead
of ever returning a wrong premium. Verify with one live
GET /kotak-neo/nse-fo-chain call before enabling real straddle/option
trading on a new underlying.
"""
import datetime as dt

import kotak_neo

# Exact Kotak pSymbolName -> its exchange_segment - confirmed live
# 2026-09-07 for every entry here (see this module's docstring). Index
# options (NIFTY/BANKNIFTY) share one name for futures+options; MCX
# commodities use TWO different names (full-size for futures, mini for
# options - see docstring) so both appear here as separate keys.
_UNDERLYING_TO_SEGMENT = {
    "NIFTY": "nse_fo", "BANKNIFTY": "nse_fo",
    "GOLD": "mcx_fo", "GOLDM": "mcx_fo",
    "SILVER": "mcx_fo", "SILVERM": "mcx_fo",
    "CRUDEOIL": "mcx_fo", "CRUDEOILM": "mcx_fo",
}

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
    rows = resp.get("showing", []) if isinstance(resp, dict) else []
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


def _extract_ltp(quotes_response) -> float | None:
    """See this module's docstring: quotes()'s real nse_fo response shape
    is unconfirmed - tries the field names kotak_neo.quotes's own
    docstring implies, returns None (never a guessed number) on anything
    unexpected."""
    if not isinstance(quotes_response, dict):
        return None
    data = quotes_response.get("data") or quotes_response.get("Success") or quotes_response
    if isinstance(data, list) and data:
        data = data[0]
    if not isinstance(data, dict):
        return None
    for key in ("ltp", "last_price", "lastPrice", "LTP"):
        if key in data:
            val = _to_float(data[key])
            if val is not None:
                return val
    return None
