"""Strategy registry scaffold (design-only, 2026-09-28).

Purpose: a single place to register every strategy this codebase has
researched or built - intraday, swing, futures, options - and track
each one's validation status, so that as a strategy clears the full
CLAUDE.md validation gate (unit tests -> full pytest -> 52-symbol/60-day
validation replay -> explicit user go-ahead) it has one obvious place
to be marked as such, instead of that status living only in a chat
transcript or a transfer pack (see CLAUDE.md's own 2026-09-14 incident
writeup on exactly that failure mode).

NOTHING in this module is imported or called by main.py today, and
nothing here changes live behavior. `scan_universe` is a walk-the-
watchlist skeleton for a LATER, separately-approved change that would
let the live scheduler check every LIVE-status strategy's entry
condition per symbol before moving to the next symbol; wiring it in is
its own implement/test/validate/approve cycle, not this commit.
Registering a strategy here, or even marking it LIVE, does not by
itself make it trade real money - only main.py's actual live order
path does that.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional


class AssetClass(str, Enum):
    EQUITY_INTRADAY = "equity_intraday"
    EQUITY_SWING = "equity_swing"
    FUTURES = "futures"
    OPTIONS = "options"


class StrategyStatus(str, Enum):
    RESEARCH = "research"      # single-pass or early backtest result only
    VALIDATED = "validated"    # full pytest + validation replay passed; not yet wired live
    LIVE = "live"               # wired into main.py's live order path and trading real money


@dataclass(frozen=True)
class StrategyDef:
    name: str
    asset_class: AssetClass
    timeframe: str
    status: StrategyStatus
    entry_fn: Optional[Callable] = None
    risk_profile: dict = field(default_factory=dict)
    source: str = ""     # research workflow or doc this strategy came from
    evidence: str = ""   # pointer to the actual replay/run that justifies `status` - never trust a status without one
    notes: str = ""


REGISTRY: list[StrategyDef] = [
    StrategyDef(
        name="universal_score",
        asset_class=AssetClass.EQUITY_INTRADAY,
        timeframe="5m",
        status=StrategyStatus.LIVE,
        entry_fn=None,  # lives in main.py._compute_universal_entry_score - not duplicated here
        risk_profile={"sizing_source": "NSE_STOCK_PARAM_OVERRIDES / NSE_STOCK_DEFAULT_PARAMS"},
        source="main.py (live)",
        evidence="live trading history; ongoing tuning research in universal-score-*-research.yml",
        notes="Live intraday (5m) engine, watchlist WATCHLIST.",
    ),
    StrategyDef(
        name="gap_and_go_swing",
        asset_class=AssetClass.EQUITY_SWING,
        timeframe="1d",
        status=StrategyStatus.LIVE,
        entry_fn=None,  # lives in main.py.gap_and_go_entry_signal/_run_swing_scan - not duplicated here
        risk_profile={"sizing_source": "get_scheduler_capital_inr(); watchlist SWING_WATCHLIST"},
        source="main.py (live) - validated in swing-gap-and-go-5y-research.yml",
        evidence=(
            "swing-gap-and-go-5y-research.yml: PFnet 1.65, n=142, on the original "
            "_SWING_VALIDATED_52 universe. 2026-09-22: widened live (paper AND real "
            "together) to the full NIFTY-200/NSE_FULL_UNIVERSE-derived SWING_WATCHLIST "
            "without a prior backtest on the extra ~150 symbols, per explicit user "
            "instruction after the tradeoff was flagged - main.py's own SWING_WATCHLIST "
            "comment documents this as a known, deliberate gap, not an oversight."
        ),
        notes=(
            "Found live in main.py while researching for this registry (2026-09-28) - "
            "was NOT in this registry's first version, which incorrectly listed "
            "universal_score as the only live strategy. Real, unhedged, currently-"
            "live real-money strategy; mirrors as a real order via "
            "is_real_swing_trading_enabled()."
        ),
    ),
    StrategyDef(
        name="universal_score_entry_floor_85",
        asset_class=AssetClass.EQUITY_INTRADAY,
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        risk_profile={"UNIVERSAL_ENTRY_SCORE_MIN": 85.0},
        source=".github/workflows/universal-score-entry-floor-research.yml",
        evidence=(
            "run 36444172866 (2026-09-28): TREND-only PFnet 0.09->0.13, PFgross 1.11->1.64, "
            "win% 11.6->17.1; ALL-population PFnet unchanged at 0.06 since TREND is only "
            "~17% of trade volume and RANGE (untouched) dominates."
        ),
        notes="One replay result. Needs full pytest + validation replay + explicit user go-ahead before any live wiring.",
    ),
    StrategyDef(
        name="minervini_trend_template_vcp",
        asset_class=AssetClass.EQUITY_SWING,
        timeframe="1d",
        status=StrategyStatus.RESEARCH,
        source=".github/workflows/swing-minervini-trend-template-vcp-research.yml",
        evidence="dispatched 2026-09-28; result pending",
        notes=(
            "Long-only, sourced from Trade Like a Stock Market Wizard (Minervini). "
            "A short mirror is out of scope until the long side itself clears validation, "
            "per the standing long/short thumb rule."
        ),
    ),
]


def strategies_by_status(status: StrategyStatus) -> list[StrategyDef]:
    return [s for s in REGISTRY if s.status == status]


def strategies_by_asset_class(asset_class: AssetClass) -> list[StrategyDef]:
    return [s for s in REGISTRY if s.asset_class == asset_class]


def scan_universe(symbols, as_of_data_fn, statuses=(StrategyStatus.LIVE,)):
    """Walk `symbols` one at a time; for each symbol, check every
    registered strategy whose status is in `statuses`, in registry
    order, before moving to the next symbol.

    `as_of_data_fn(symbol)` must return whatever each strategy's
    `entry_fn` needs - left abstract here since this scaffold does not
    fetch data itself. A strategy with `entry_fn=None` (the normal case
    for anything not yet wired into this module) is skipped rather than
    raising, so registering or promoting a strategy's status never by
    itself risks a crash in a future caller.

    Design-only skeleton: not called from main.py's live scheduler.
    """
    signals = []
    candidates = [s for s in REGISTRY if s.status in statuses]
    for symbol in symbols:
        data = as_of_data_fn(symbol)
        for strat in candidates:
            if strat.entry_fn is None:
                continue
            result = strat.entry_fn(data)
            if result:
                signals.append({"symbol": symbol, "strategy": strat.name, "signal": result})
    return signals
