"""Strategy registry + leaderboard (2026-09-28, extended 2026-09-29).

Purpose: a single place to register every strategy this codebase has
researched or built - intraday, swing, futures, options, long and short -
carrying its VALIDATED performance metrics (win rate, PFnet, PFgross,
sample size, cost drag) and its status, so "keep testing, add everything
to the pool, always prefer whichever is actually best" (explicit user
instruction, 2026-09-29) has one durable, queryable place to live instead
of scattered chat transcripts and transfer packs (see CLAUDE.md's own
2026-09-14 incident writeup on exactly that failure mode - a status
claimed in prose that was never actually true).

NOTHING in this module is imported or called by main.py today, and
nothing here changes live behavior or places any order. Registering a
strategy here, or even marking it LIVE, does not by itself make it trade
real money - only main.py's actual live order path does that. This is a
RESEARCH/TRACKING registry, not a live-trading gate.

Explicit, load-bearing distinction (2026-09-29, after the user asked to
"merge all of these into production into pool of strategies for
monitoring... trade entry"): ranking a strategy #1 in its category means
"best of what's been tried", NOT "profitable" or "safe for real money".
`is_viable()` is the actual bar - PFnet >= PFNET_LIVE_FLOOR (1.0, real
breakeven after costs) - and every leaderboard() row carries it
explicitly so a "top 5" listing can never be mistaken for "5 good
options" when none of them clear breakeven. As of 2026-09-29, EVERY
short-sell candidate and the only live buy strategy are below that floor
- see each entry's own `metrics`.

Pool vs. monitoring, explicit user instruction, 2026-09-29 ("keep pool of
strategies tested till date but while using to monitor the stocks, u apply
or check entry condition for top 5 only, so ur pool gets bigger n bigger
always"): REGISTRY itself never shrinks and never gets pruned - every
strategy ever tried stays on the record, good or bad. But `scan_universe()`
(and anything else that walks strategies to check entry conditions) only
ever evaluates `top_strategies_for_monitoring()` - the CURRENT top
TOP_N_PER_CATEGORY per category, re-ranked fresh on every call. Growing
the registry never grows what gets checked per symbol per cycle; it only
changes which (up to MAX_STRATEGY_CHECKS_PER_SYMBOL_PER_CYCLE) strategies
currently hold those slots.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional


class AssetClass(str, Enum):
    EQUITY_INTRADAY = "equity_intraday"
    EQUITY_SWING = "equity_swing"
    FUTURES = "futures"
    OPTIONS = "options"


class TradeCategory(str, Enum):
    """The pools the user asked to track a top-5 leaderboard for
    (2026-09-29, BIDIRECTIONAL added 2026-10-05). Distinct from
    AssetClass: a category is "what kind of trade is this" (direction/
    timeframe), not "what instrument". A strategy is never confined to
    exactly one of these - see StrategyDef.categories and CLAUDE.md's
    2026-09-29 "a strategy is not confined to one TradeCategory" thumb
    rule.

    BIDIRECTIONAL (2026-10-05, explicit user instruction): for a strategy
    whose entry/exit mechanic is NATIVELY two-sided - one combined signal
    that trades both long and short depending on where price sits (e.g.
    Box Theory's top-zone-sell/bottom-zone-buy state machine, Parabolic
    SAR's always-in-market long/short reversal system) - registered and
    validated as ONE strategy, ONE set of pooled metrics covering both
    directions together, not decomposed into two separate BUY/SHORT_SELL
    registry entries the way e.g. gap_and_go_swing (SWING only - never BUY;
    its PFnet was measured on 1d multi-day holds) and
    gap_and_go_short_fade (SHORT_SELL) are two separate strategies. Holds
    both viable and non-viable bidirectional strategies, same "pool never
    shrinks, every strategy tried stays on the record" discipline as
    every other category."""
    SHORT_SELL = "short_sell"
    BUY = "buy"
    SWING = "swing"
    FUTURES = "futures"
    OPTIONS = "options"
    BIDIRECTIONAL = "bidirectional"


# CLAUDE.md, 2026-09-29 thumb rule (category count updated 2026-10-05 with
# BIDIRECTIONAL's addition - the formula itself is unchanged, it just
# scales automatically with len(TradeCategory)): categories x this many
# leaderboard slots each bounds live per-stock monitoring cost at a fixed
# number of strategy-checks per round-robin cycle, regardless of how large
# the overall registry grows.
TOP_N_PER_CATEGORY = 5
MAX_STRATEGY_CHECKS_PER_SYMBOL_PER_CYCLE = len(TradeCategory) * TOP_N_PER_CATEGORY


class StrategyStatus(str, Enum):
    RESEARCH = "research"      # single-pass or early backtest result only
    VALIDATED = "validated"    # full pytest + validation replay passed; not yet wired live
    LIVE = "live"               # wired into main.py's live order path and trading real money
    BLOCKED_NO_EXECUTION = "blocked_no_execution"  # no order-placement path exists for this asset class at all


# Real breakeven after transaction costs. A strategy below this loses
# money on average, however it ranks against its peers - see this
# module's own docstring for why that distinction is load-bearing.
PFNET_LIVE_FLOOR = 1.0


# NSE cash session 09:15-15:30 IST = 6.25 market hours per trading day. Used only to
# express daily-bar backtests' "avg held N trading days" in the one common unit
# (market hours) the dashboard shows for every category.
TRADING_HOURS_PER_DAY = 6.25


@dataclass(frozen=True)
class Metrics:
    """Pointer to one specific validation run's pooled numbers - never a
    hand-typed guess. `n_trades` and `universe` exist so a thin, easily-
    noisy sample (e.g. n=2) is never confused with a full-universe result
    (see this repo's own Minervini VCP 52-symbol-vs-full-universe finding,
    which moved PFnet by 0.35 - CLAUDE.md's full-universe standing rule)."""
    pfnet: float
    pfgross: float
    win_rate_pct: float
    n_trades: int
    avg_net_inr: Optional[float] = None
    cost_drag_pct: Optional[float] = None
    avg_held_hrs: Optional[float] = None  # mean holding period in MARKET (trading-session) HOURS of the SAME run as pfnet/win_rate_pct - how long, on average, a trade took to realize those numbers; one unit for every category (explicit user instruction 2026-10-05). Daily-bar runs record avg held trading DAYS, converted as days * TRADING_HOURS_PER_DAY; intraday runs record minutes, / 60. None = not recorded for that run yet (never guessed).
    universe: str = ""          # "full_2680", "52_symbol_sample", etc. - never omit
    run_ref: str = ""           # workflow file + run id, or commit, that produced this


@dataclass(frozen=True)
class StrategyDef:
    name: str
    asset_class: AssetClass
    categories: tuple  # tuple[TradeCategory, ...] - never a single TradeCategory, see its own docstring
    timeframe: str
    status: StrategyStatus
    entry_fn: Optional[Callable] = None
    metrics: Optional[Metrics] = None
    risk_profile: dict = field(default_factory=dict)
    source: str = ""     # research workflow or doc this strategy came from
    evidence: str = ""   # pointer to the actual replay/run that justifies `status` - never trust a status without one
    notes: str = ""

    def is_viable(self, floor: float = PFNET_LIVE_FLOOR) -> Optional[bool]:
        """None if no metrics exist yet (can't judge), else whether this
        strategy's own validated PFnet clears real breakeven."""
        if self.metrics is None:
            return None
        return self.metrics.pfnet >= floor


REGISTRY: list[StrategyDef] = [
    # ---- BUY (long) ---------------------------------------------------
    StrategyDef(
        name="universal_score",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.BUY,),
        timeframe="5m",
        status=StrategyStatus.LIVE,
        entry_fn=None,  # lives in main.py._compute_universal_entry_score - not duplicated here
        metrics=Metrics(
            pfnet=0.05, pfgross=1.20, win_rate_pct=10.6, n_trades=1233,
            avg_net_inr=-1369.10, cost_drag_pct=170.4,
            universe="52_symbol_sample", run_ref="universal-score-validation-replay.yml run 35729566196 (2026-09-22)",
        ),
        risk_profile={"sizing_source": "NSE_STOCK_PARAM_OVERRIDES / NSE_STOCK_DEFAULT_PARAMS"},
        source="main.py (live)",
        evidence="universal-score-validation-replay.yml run 35729566196 (2026-09-22) - last full validation of the exact live logic",
        notes=(
            "Live, trading real money, two-regime router (TREND 8-factor score / RANGE VWAP "
            "mean-reversion) - see main.py._classify_market_regime. Its own last validated "
            "PFnet (0.05) is BELOW PFNET_LIVE_FLOOR - see is_viable(). By regime: TREND-only "
            "PFnet 0.08 (n=231), RANGE-only PFnet 0.05 (n=1002) on the same run."
        ),
    ),
    StrategyDef(
        name="universal_score_entry_floor_85",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.BUY,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        metrics=Metrics(
            pfnet=0.14, pfgross=1.31, win_rate_pct=17.1, n_trades=160937,
            avg_net_inr=-1222.44, cost_drag_pct=123.0,
            universe="full_2680 (2639/2680 fetched)",
            run_ref="universal-score-entry-floor-validation-replay.yml run 36577670843 (2026-09-29, calls the real main.py functions)",
        ),
        risk_profile={"UNIVERSAL_ENTRY_SCORE_MIN": 85.0},
        source="main.py (_compute_universal_entry_score, UNIVERSAL_ENTRY_SCORE_MIN overridden to 85.0)",
        evidence=(
            "Real-function full-universe validation (2026-09-29, run 36577670843): ALL PFnet "
            "0.14 (n=160,937), TREND-only PFnet 0.14 (n=5,139), RANGE-only PFnet 0.14 "
            "(n=155,798) - the earlier 52-symbol-sample finding's optimistic TREND-only lift "
            "(PFnet 0.09->0.13 as floor rose 70->85) does NOT hold at full-universe scale: "
            "current_70's own TREND-only PFnet was already 0.15 here, and floor_85 does not "
            "improve on it. Also tested floor_90 in the same run: ALL PFnet 0.14 (n=160,790), "
            "TREND-only PFnet 0.14 (n=4,980) - same flat result. Raising the entry-score floor "
            "does not move PFnet at full-universe scale, in either direction."
        ),
        notes="Confined to research status - well below PFNET_LIVE_FLOOR, no meaningful improvement over the live 70-floor baseline. Not worth pursuing further as a standalone lever.",
    ),

    # ---- SWING ----------------------------------------------------------
    StrategyDef(
        name="gap_and_go_swing",
        asset_class=AssetClass.EQUITY_SWING,
        categories=(TradeCategory.SWING,),
        timeframe="1d",
        status=StrategyStatus.LIVE,
        entry_fn=None,  # lives in main.py.gap_and_go_entry_signal/_run_swing_scan - not duplicated here
        metrics=Metrics(
            pfnet=1.65, pfgross=None, win_rate_pct=None, n_trades=142,
            universe="_SWING_VALIDATED_52 (original validated set)",
            run_ref="swing-gap-and-go-5y-research.yml",
        ),
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
            "The ONLY strategy in this entire registry with a validated PFnet above "
            "PFNET_LIVE_FLOOR - see is_viable(). Real, unhedged, currently-live real-money "
            "strategy; mirrors as a real order via is_real_swing_trading_enabled(). "
            "Candle-size sweep (2026-09-29, "
            "minervini-vcp-gap-and-go-candle-size-sweep-research.yml run 36613040107, "
            "52-symbol sample, real gap_and_go_entry_signal/exit_reason): 1d (PFnet "
            "1.62, n=141) is comparable to the original validated 1.65/n=142, "
            "confirming 1d is correctly chosen - 1h is close behind (PFnet 1.55, n=63) "
            "and worth a full-universe check of its own, but 15m/5m/1m are too thin "
            "(n<=6) to read anything from."
        ),
    ),
    StrategyDef(
        name="minervini_trend_template_generic_breakout",
        asset_class=AssetClass.EQUITY_SWING,
        categories=(TradeCategory.SWING,),
        timeframe="1d",
        status=StrategyStatus.RESEARCH,
        metrics=Metrics(
            pfnet=0.90, pfgross=None, win_rate_pct=None, n_trades=1367,
            universe="full_2680 (2362/2680 fetched)",
            run_ref="swing-minervini-trend-template-vcp-research.yml (2026-09-28/29 full-universe run)",
        ),
        source=".github/workflows/swing-minervini-trend-template-vcp-research.yml",
        evidence=(
            "Full-universe run: PFnet 0.90, n=1367, on 2362/2680 fetched symbols. Best "
            "single-strategy PFnet found anywhere this session (long or short), and the "
            "highest-n result with it. Never wired into main.py or unit-tested - a single "
            "replay result, not a full CLAUDE.md validation cycle."
        ),
        notes=(
            "Trend Template (8-criteria) breakout variant, long-only, sourced from "
            "Minervini's Trade Like a Stock Market Wizard. Top-of-by-symbol-list caveat: "
            "microcap/illiquid symbols dominated the top of the per-symbol breakdown in "
            "this run - worth re-checking with a liquidity floor before trusting the "
            "pooled number at face value. Highest-priority unbuilt candidate in this "
            "registry per explicit user direction (2026-09-29)."
        ),
    ),
    StrategyDef(
        name="minervini_trend_template_vcp",
        asset_class=AssetClass.EQUITY_SWING,
        categories=(TradeCategory.SWING,),
        timeframe="1d",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,  # minervini_vcp_entry_signal/minervini_vcp_exit_reason exist in main.py but are not wired into _run_swing_scan
        metrics=Metrics(
            pfnet=0.908, pfgross=1.147, win_rate_pct=34.56, n_trades=327,
            avg_net_inr=-73.83,
            universe="full_2680 (2362/2680 fetched)",
            run_ref="minervini-vcp-validation-replay.yml run 36566995254 (2026-09-29, calls the real main.py functions)",
        ),
        source="main.py (minervini_vcp_entry_signal/minervini_vcp_exit_reason)",
        evidence=(
            "Real-function full-universe validation (2026-09-29, run 36566995254): PFnet "
            "0.908, n=327, win_rate 34.56%, avg_net -Rs73.83/trade. Confirms the "
            "implementation faithfully reproduces the original research script's number "
            "(PFnet 0.90, n=325, swing-minervini-trend-template-vcp-research.yml, 2026-09-28/29 "
            "- kept for the record, see docs/MINERVINI_VCP_RESEARCH_LOG.md) - no replay-"
            "driver-drift bug found this time, unlike the RSI-band-reflection bug caught in "
            "the TREND-down short mirror. Still below PFNET_LIVE_FLOOR."
        ),
        notes=(
            "Long-only. A short mirror is explicitly out of scope until the long side "
            "itself clears full validation, per the standing long/short thumb rule. "
            "trail_stop_hit is 89% of trades (n=292) and is itself a net loser (PFnet "
            "0.757) - the dominant exit path is the weak point, not the entry trigger. "
            "data_end_forced_close's high PFnet (3.455, n=30) is a backtest-window "
            "artifact, not a real signal - see docs/MINERVINI_VCP_RESEARCH_LOG.md. Only "
            "ever tested at the 1d candle size per the 2026-09-29 candle-size thumb rule."
        ),
    ),

    StrategyDef(
        name="minervini_vcp_breakeven_2r",
        asset_class=AssetClass.EQUITY_SWING,
        categories=(TradeCategory.SWING,),
        timeframe="1d",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,  # minervini_vcp_exit_reason_breakeven exists in main.py but is not wired into any scan
        metrics=Metrics(
            pfnet=1.145, pfgross=1.336, win_rate_pct=42.65, n_trades=279, avg_held_hrs=34.0 * TRADING_HOURS_PER_DAY,
            avg_net_inr=162.06,
            universe="full_2680 (2362/2680 fetched)",
            run_ref="minervini-vcp-breakeven-2r-validation-replay.yml run 36670096485 "
                     "(2026-09-30, calls the real main.py minervini_vcp_exit_reason_breakeven)",
        ),
        source="main.py (minervini_vcp_entry_signal_livermore_confirmed's own base entry + minervini_vcp_exit_reason_breakeven, breakeven_r_multiple=MINERVINI_BREAKEVEN_R_2)",
        evidence=(
            "Real-function full-universe validation (2026-09-30, run 36670096485): PFnet "
            "1.145, n=279, win_rate 42.65%, avg_net +Rs162.06/trade - CLEARS "
            "PFNET_LIVE_FLOOR, unlike the same entries' original chandelier-trail exit "
            "(minervini_trend_template_vcp, PFnet 0.908 on the closely comparable n=327 "
            "run). Book-literal chapter-13 2R breakeven-stop (docs/minervini_book_notes.txt) "
            "beats the chandelier trail head-to-head on the same entry signal."
        ),
        notes=(
            "A straight ALTERNATIVE exit, not a hybrid - stop is flat at initial_stop until "
            "the 2R threshold, then floors at entry_price (breakeven), never trails further. "
            "3R (minervini_vcp_breakeven_3r) edges this out slightly (PFnet 1.153 vs 1.145) "
            "on a near-identical n - see that entry's own notes. Only tested at 1d (the "
            "strategy's own natural timeframe); not yet wired into any scan."
        ),
    ),
    StrategyDef(
        name="minervini_vcp_breakeven_3r",
        asset_class=AssetClass.EQUITY_SWING,
        categories=(TradeCategory.SWING,),
        timeframe="1d",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,  # minervini_vcp_exit_reason_breakeven exists in main.py but is not wired into any scan
        metrics=Metrics(
            pfnet=1.153, pfgross=1.342, win_rate_pct=44.29, n_trades=280, avg_held_hrs=34.6 * TRADING_HOURS_PER_DAY,
            avg_net_inr=170.75,
            universe="full_2680 (2362/2680 fetched)",
            run_ref="minervini-vcp-breakeven-3r-validation-replay.yml run 36670098717 "
                     "(2026-09-30, calls the real main.py minervini_vcp_exit_reason_breakeven)",
        ),
        source="main.py (minervini_vcp_entry_signal_livermore_confirmed's own base entry + minervini_vcp_exit_reason_breakeven, breakeven_r_multiple=MINERVINI_BREAKEVEN_R_3)",
        evidence=(
            "Real-function full-universe validation (2026-09-30, run 36670098717): PFnet "
            "1.153, n=280, win_rate 44.29%, avg_net +Rs170.75/trade - the best of the two "
            "breakeven variants tested, and both clear PFNET_LIVE_FLOOR where the original "
            "chandelier trail (PFnet 0.908) did not."
        ),
        notes=(
            "Book-literal chapter-13 3R breakeven-stop (docs/minervini_book_notes.txt). "
            "Marginally beats the 2R variant (1.153 vs 1.145 PFnet) on a near-identical "
            "n (280 vs 279) - the later breakeven threshold gives a few more trades room "
            "to run before locking in, at negligible cost in trades that get stopped out "
            "before reaching it. Only tested at 1d; not yet wired into any scan."
        ),
    ),
    StrategyDef(
        name="minervini_vcp_scale_in_sizing",
        asset_class=AssetClass.EQUITY_SWING,
        categories=(TradeCategory.SWING,),
        timeframe="1d",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,  # _scale_in_tranches exists in main.py but is not wired into any scan
        metrics=Metrics(
            pfnet=0.863, pfgross=1.106, win_rate_pct=27.36, n_trades=329,
            avg_net_inr=-85.20,
            universe="full_2680 (2362/2680 fetched)",
            run_ref="minervini-vcp-scale-in-sizing-validation-replay.yml run 36670100345 "
                     "(2026-09-30, calls the real main.py _scale_in_tranches)",
        ),
        source="main.py (minervini_vcp entries/exits + _scale_in_tranches, MINERVINI_SCALE_IN_TRANCHE_PCTS=(0.4, 0.4, 0.2))",
        evidence=(
            "Real-function full-universe validation (2026-09-30, run 36670100345): PFnet "
            "0.863, n=329, win_rate 27.36%, avg_net -Rs85.20/trade - WORSE than the "
            "single-shot-sizing baseline (minervini_trend_template_vcp, PFnet 0.908) on "
            "the same entries/exits/universe/period, sizing being the only variable "
            "changed. A negative result, reported as-is per standing discipline (never "
            "omit a strategy for looking bad)."
        ),
        notes=(
            "Book chapter-13 scale-in tranche sizing (docs/minervini_book_notes.txt), added "
            "ONLY as price confirms with an open profit, never averaging down. trail_stop_hit "
            "dominates (n=294, PFnet 0.699) and drags the pooled number below the single-"
            "shot baseline - splitting entry into tranches added at a rising average cost "
            "left less room before the same chandelier trail stopped the position out, on "
            "net. Not worth pursuing further as a standalone lever on this entry signal; "
            "untested whether it would help the 2R/3R breakeven exits instead of the "
            "chandelier trail it was tested against here."
        ),
    ),
    StrategyDef(
        name="primary_base",
        asset_class=AssetClass.EQUITY_SWING,
        categories=(TradeCategory.SWING,),
        timeframe="1d",
        status=StrategyStatus.LIVE,  # 2026-10-01, "wire to live real money only to
        # viable ones" - wired into _run_swing_scan, checked right after power_play
        # (both PFnet-ranked ahead of minervini_vcp_livermore); real-order mirror
        # gated by _is_strategy_viable_for_real_money like every other real entry.
        entry_fn=None,  # main.py's own primary_base_entry_signal IS the live entry_fn - this
        # field only ever fed the design-only scan_universe() scaffold, never main.py's real scheduler
        metrics=Metrics(
            pfnet=2.069, pfgross=2.551, win_rate_pct=44.31, n_trades=2591, avg_held_hrs=17.0 * TRADING_HOURS_PER_DAY,
            avg_net_inr=404.74,
            universe="full_2680 (2401/2680 fetched)",
            run_ref="primary-base-validation-replay.yml run 36820565494 "
                     "(2026-10-01, calls the real main.py primary_base_entry_signal + minervini_vcp_exit_reason)",
        ),
        source="main.py (primary_base_entry_signal + minervini_vcp_exit_reason, the original chandelier trail)",
        evidence=(
            "Full-universe run 36820565494: PFnet 2.069, PFgross 2.551, n=2,591, win_rate "
            "44.31%, avg_net +Rs404.74/trade, avg held 17.0 days - clears PFNET_LIVE_FLOOR "
            "comfortably and is close to minervini_vcp_livermore_confirmed's own 2.043 PFnet, "
            "on a far larger sample (2,591 vs 121 trades) and a SHORTER average hold (17.0d "
            "vs Livermore-confirmed's own ~equivalent chandelier-trail hold). By exit reason: "
            "trail_stop_hit (n=2,499, 96.5% of trades) is itself already solidly profitable "
            "(PFnet 1.870) - unlike every short-sell strategy tested this session, this entry "
            "does NOT show the 'exit cuts winners short' pattern; max_hold_timeout (n=82) is "
            "extremely profitable (PFnet 86.2, 95.1% win rate) but a small minority of trades."
        ),
        notes=(
            "docs/minervini_book_notes.txt CHAPTER 11 ('PRIMARY BASE') - a recently-listed "
            "stock (proxy: short total available price history, see primary_base_entry_"
            "signal's own header comment for the full disclosed algorithm) breaking out to a "
            "NEW ALL-TIME HIGH from its first buyable base. Deliberately distinct from "
            "minervini_vcp_entry_signal (needs 150+/200+ days of history to even evaluate the "
            "Trend Template) - this targets a young stock's VERY FIRST base, not a stage-2 "
            "continuation base. Its own feasibility precondition (does 'short available "
            "history' on this data source track real IPO recency, or is it a Yahoo data-"
            "availability artifact?) was checked FIRST and cleared: minervini-primary-base-"
            "feasibility-check.yml run 36670094369 (2026-09-30) found known decades-old large "
            "caps (RELIANCE/TCS/INFY/HDFCBANK/ITC/LT/SBIN) show genuine 23-30+ years of "
            "history, while a meaningful minority of the full universe (17.4% under 1y) shows "
            "genuinely short histories including literal brand-new listings within days of "
            "that check. Reuses minervini_vcp_exit_reason UNCHANGED (the best-performing exit "
            "tried on this book's entries so far, strictly better than the 2R/3R breakeven "
            "variant per CLAUDE.md's own 2026-09-30 sweep-discipline note) - this is an "
            "entry-only, one-axis test, not a new exit variant. PERIOD='max' was required for "
            "the replay (not a shorter window) since the 'recently listed' proxy depends on "
            "each symbol's REAL total available history, not a truncated fetch window - see "
            "the validation-replay workflow's own header comment.\n"
            "2026-10-01: a candle-size sweep was considered (per CLAUDE.md's standing "
            "multi-timeframe thumb rule) and deliberately NOT built - checked infeasible for "
            "TWO independent reasons, not just the day-based-constants issue "
            "failed_breakout_short's own sweep flags. (1) Every lookback constant here "
            "(MAX_HISTORY_DAYS, MIN/MAX_BASE_DAYS, SHORT_BASE_MAX_DAYS) assumes 1 bar = 1 "
            "trading day, same re-derivation problem. (2) A harder, data-source-level blocker: "
            "the whole strategy depends on comparing REAL total available history across "
            "symbols (validated via minervini-primary-base-feasibility-check.yml's own "
            "PERIOD='max' daily fetch, which showed genuine 23-30+ year histories for old "
            "large caps) - but yfinance's intraday retention is far shorter at every other "
            "granularity (1h capped at ~2 years, 15m/5m at 60 days, 1m at 7 days), so at any "
            "of those a 30-year-old stock and a genuinely new listing would look equally "
            "'short-history' simply because the data source can't see back far enough - not a "
            "property of the market, a property of the fetch window. A sweep built on a "
            "resample or a shorter intraday period would measure yfinance's own retention "
            "limit, not the strategy, and would be exactly the 'faking it with a resample' "
            "CLAUDE.md's own sweep-discipline note warns against. Stays 1d-only by necessity, "
            "not oversight."
        ),
    ),
    StrategyDef(
        name="minervini_vcp_livermore_confirmed",
        asset_class=AssetClass.EQUITY_SWING,
        categories=(TradeCategory.SWING,),
        timeframe="1d",
        status=StrategyStatus.LIVE,  # 2026-09-30, "Wire the viable ones" - wired into
        # _run_swing_scan, checked before the plain minervini_vcp entry (see that
        # function's own comment); real-order mirror gated by _is_strategy_viable_for_
        # real_money like every other real entry.
        entry_fn=None,  # main.py's own minervini_vcp_entry_signal_livermore_confirmed IS the live entry_fn - this
        # field only ever fed the design-only scan_universe() scaffold, never main.py's real scheduler
        metrics=Metrics(
            pfnet=2.043, pfgross=2.658, win_rate_pct=33.88, n_trades=121, avg_held_hrs=14.8 * TRADING_HOURS_PER_DAY,
            avg_net_inr=713.52,
            universe="full_2680 (2362/2680 fetched)",
            run_ref="minervini-vcp-livermore-confirmed-validation-replay.yml run 36670102480 "
                     "(2026-09-30, calls the real main.py minervini_vcp_entry_signal_livermore_confirmed)",
        ),
        source="main.py (minervini_vcp_entry_signal_livermore_confirmed + minervini_vcp_exit_reason, the original chandelier trail)",
        evidence=(
            "Real-function full-universe validation (2026-09-30, run 36670102480): PFnet "
            "2.043, n=121, win_rate 33.88%, avg_net +Rs713.52/trade - by far the strongest "
            "result of the four book-refinement variants tested this session, more than "
            "double the base entry's own PFnet (0.908, minervini_trend_template_vcp) on "
            "the same chandelier-trail exit. Waiting for the SECOND rally high after two "
            "confirmed pullbacks (docs/minervini_book_notes.txt's Livermore system, "
            "ch.10) roughly a third of the base signal's own trade count (121 vs 327) but "
            "each surviving trade is markedly higher quality."
        ),
        notes=(
            "Entry-timing FILTER layered on the existing minervini_vcp_entry_signal pivot "
            "breakout, not a new entry signal of its own - see "
            "minervini_vcp_entry_signal_livermore_confirmed's own docstring for the "
            "disclosed fractal-swing/backward-reconstruction algorithm choices. The "
            "trade-off the book itself frames explicitly (worse average entry price, less "
            "whipsaw) reads as a clear net win here. Only tested at 1d; not yet wired into "
            "any scan or combined with the 2R/3R breakeven exits (untested combination)."
        ),
    ),
    StrategyDef(
        name="idea4_no_target",
        asset_class=AssetClass.EQUITY_SWING,
        categories=(TradeCategory.SWING,),
        timeframe="1d",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,  # main.py.idea4_entry_signal/idea4_exit_reason exist but are not wired into _run_swing_scan
        metrics=Metrics(
            pfnet=0.999, pfgross=1.236, win_rate_pct=37.48, n_trades=21138,
            avg_net_inr=-0.10,
            universe="full_2680 (2366/2680 fetched)",
            run_ref="idea4-validation-replay.yml run 36592165748 (2026-09-29, calls the real main.py functions)",
        ),
        source="main.py (idea4_entry_signal/idea4_exit_reason)",
        evidence=(
            "Real-function full-universe validation (2026-09-29, run 36592165748): PFnet "
            "printed as 1.000 (3dp) with avg_net -Rs0.10/trade - net negative, so the true "
            "PFnet is fractionally below 1.0; recorded here as 0.999 rather than the "
            "printed 1.000 so is_viable() doesn't misreport this as clearing the real "
            "PFNET_LIVE_FLOOR breakeven bar. n=21,138, win_rate 37.48%. The unvalidated "
            "research number this implementation was built to check (score-signal-4h-1d-"
            "retest-research.yml, 1d NO_TARGET variant, 52-symbol sample) was PFnet 1.04, "
            "n=927, avg_net +Rs79.92 - full-universe scale does NOT confirm a profitable "
            "edge. This also matches the same-day robustness check "
            "(daily-no-target-robustness-research.yml, run 35770868637, 2026-09-22) that "
            "had already flagged the edge as unstable: time-split PFnet decayed 1.39 "
            "(first half) -> 0.75 (second half), and excluding the top-15-by-PF symbols "
            "dropped PFnet from 1.04 to 0.82."
        ),
        notes=(
            "8-factor UNIVERSAL_SCORE_WEIGHTS entry (score>=70, EMA9>EMA21) at 1-day "
            "candles, above_vwap read via a rolling-VOLUME_CONFIRM_LOOKBACK-bar window "
            "substituting for session VWAP (see main.py's own idea4_entry_signal "
            "docstring). Fixed ATR(14)x1.5 stop set once at entry (never trailed), no "
            "fixed target - ride to that stop or 20 trading days. avg_net_inr is slightly "
            "negative despite pfnet rounding to 1.000 - essentially exact breakeven before "
            "counting the strategy's own opportunity cost, not a profitable edge. Named "
            "'Idea 4' per explicit user instruction (2026-09-29) after a critical review of "
            "every real trade taken to date. Candle-size sweep (CLAUDE.md 2026-09-29 thumb "
            "rule; idea4-power-play-candle-size-sweep-research.yml run 36603190009, 52-symbol "
            "sample, real idea4_entry_signal/idea4_exit_reason - not a reimplementation) "
            "confirms 1d as the correct timeframe: PFnet degrades monotonically at finer "
            "granularity (1m=0.01, 5m=0.05, 15m=0.15, 1h=0.49, 4h=0.60, 1d=0.87). Not enough "
            "to flip this strategy viable at any timeframe, but rules out 'try a faster candle' "
            "as a fix."
        ),
    ),
    StrategyDef(
        name="power_play_high_tight_flag",
        asset_class=AssetClass.EQUITY_SWING,
        categories=(TradeCategory.SWING, TradeCategory.BUY),
        timeframe="1d",
        status=StrategyStatus.LIVE,  # 2026-09-30, "Wire it now anyway" - see this
        # entry's own notes for the explicit override of its thin-sample caution.
        entry_fn=None,  # main.py's own power_play_entry_signal IS the live entry_fn - this field
        # only ever fed the design-only scan_universe() scaffold, never main.py's real scheduler
        metrics=Metrics(
            pfnet=5.023, pfgross=5.820, win_rate_pct=44.95, n_trades=109, avg_held_hrs=16.2 * TRADING_HOURS_PER_DAY,
            avg_net_inr=1953.04,
            universe="full_2680 (2366/2680 fetched)",
            run_ref="power-play-validation-replay.yml run 36599530532 (2026-09-29, calls the real main.py functions)",
        ),
        source="main.py (power_play_entry_signal/power_play_exit_reason)",
        evidence=(
            "Real-function full-universe validation (2026-09-29, run 36599530532): PFnet "
            "5.023, PFgross 5.820, n=109, win_rate 44.95%, avg_net +Rs1953.04/trade, avg "
            "held 16.2 days. By far the best full-universe PFnet found anywhere in this "
            "session - every strategy tried before this one (universal_score family, "
            "gap_and_go_swing's own 1.65 aside, tt_vcp, idea4, every short candidate) "
            "landed at or below breakeven. 100% of exits were trail_stop_hit (none hit "
            "POWER_PLAY_MAX_HOLD_DAYS=120) - the chandelier trail alone governs every exit "
            "here, never the timeout."
        ),
        notes=(
            "CAVEAT, do not skip: n=109 over 5 years across 2,366 symbols is a genuinely "
            "thin sample for a strategy this strong - matches the book's own description of "
            "Power Play as the RAREST setup it covers (explosive move + tight flag + "
            "breakout, all three required), so a low trade count is expected, not "
            "necessarily a red flag, but it does mean this result carries more variance/ "
            "luck risk than a strategy with a five- or six-figure trade count would. Worth "
            "a second look (longer period, symbol-holdout, time-split robustness checks, "
            "same discipline already applied to idea4_no_target) before this is trusted "
            "enough to consider live wiring - one strong replay is not itself a green light "
            "per CLAUDE.md's 'never trust one result' standing rule. POWER_PLAY_MAX_HOLD_DAYS "
            "(120) is an unswept starting estimate, not backtest-tuned - see main.py's own "
            "constant comment. Candle-size sweep attempted (CLAUDE.md 2026-09-29 thumb rule; "
            "idea4-power-play-candle-size-sweep-research.yml run 36603190009, real "
            "power_play_entry_signal/power_play_exit_reason, 52-symbol sample) but "
            "inconclusive: 0 trades fired at every timeframe (1m/5m/15m/1h/4h/1d) including "
            "1d itself. Not a bug - the full-universe 1d replay above found only 109 trades "
            "across 2,366 symbols over 5 years (~0.046 trades/symbol), so a 52-symbol sample "
            "would expect well under 3 trades even at the strategy's native timeframe; 0 is "
            "consistent with that base rate, not evidence the setup fails at other candle "
            "sizes. A real answer needs the full universe at each timeframe, not yet run. "
            "UPDATE 2026-09-30: wired into _run_swing_scan live per explicit user "
            "instruction ('Wire the viable ones' -> shown this exact CAVEAT and the "
            "robustness-check recommendation above via AskUserQuestion -> 'Wire it now "
            "anyway') - the thin-sample caution above is NOT retracted or superseded, it "
            "is kept verbatim as the honest record of the evidence this went live on, "
            "narrower than every other currently-live strategy's own evidence base."
        ),
    ),

    # ---- SHORT SELL -----------------------------------------------------
    # Every entry below is BELOW PFNET_LIVE_FLOOR - see each metrics.pfnet
    # and is_viable(). Ranked here per explicit user instruction ("keep
    # adding them into pool... prefer better version") but NONE should be
    # wired into live stock monitoring/entry - see this module's own
    # docstring on why "ranked" != "viable".
    StrategyDef(
        name="range_short_target_cluster",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.SHORT_SELL,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        metrics=Metrics(
            pfnet=0.26, pfgross=1.54, win_rate_pct=22.8, n_trades=96127,
            avg_net_inr=-1042.37, cost_drag_pct=98.9,
            universe="full_2680", run_ref="range-short-validation-replay.yml (target-cluster fix run, 2026-09-29)",
        ),
        source=".github/workflows/range-short-validation-replay.yml",
        evidence="Full-universe run: PFnet 0.26, n=96,127. Best short-sell PFnet found this session.",
        notes="RANGE VWAP-spike mean-reversion short, median-of-candidates target (mirrors long side's _compute_target_cluster). Implemented in main.py on claude/relaxed-sagan-fcrt6u (unmerged).",
    ),
    StrategyDef(
        name="range_short_bb3.0_filter",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.SHORT_SELL,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        metrics=Metrics(
            pfnet=0.23, pfgross=1.41, win_rate_pct=46.5, n_trades=51935,
            avg_net_inr=-714.85, cost_drag_pct=95.2,
            universe="full_2680 (2639/2680 fetched)",
            run_ref="range-short-validation-replay.yml run 36592169599 (2026-09-29, reconfirms the O(n^2)-bug-fixed, fully-wired real short-side functions)",
        ),
        source=".github/workflows/range-short-validation-replay.yml",
        evidence="Full-universe run 36592169599: PFnet 0.23, n=51,935 - reconfirms the earlier 51,583-trade result (PFnet 0.23, avg -Rs712.78) after the O(n^2) compute-bound fix and full reconciliation/real-order/scheduler wiring; numbers essentially unchanged. Highest win rate + lowest cost drag of any short variant.",
        notes="Same target-cluster + staged-ladder architecture as range_short_target_cluster, entry restricted to more extreme VWAP spikes (bb_std=3.0 vs live default 2.0).",
    ),
    StrategyDef(
        name="range_short_bb2.5_filter",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.SHORT_SELL,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        metrics=Metrics(
            pfnet=0.22, pfgross=1.41, win_rate_pct=45.3, n_trades=96785,
            avg_net_inr=-713.84, cost_drag_pct=99.0,
            universe="full_2680 (2639/2680 fetched)",
            run_ref="range-short-validation-replay.yml run 36592169599 (2026-09-29, reconfirms the O(n^2)-bug-fixed, fully-wired real short-side functions)",
        ),
        source=".github/workflows/range-short-validation-replay.yml",
        evidence="Full-universe run 36592169599: PFnet 0.22, n=96,785 - reconfirms the earlier 96,044-trade result (PFnet 0.22, avg -Rs712.47) after the O(n^2) compute-bound fix and full reconciliation/real-order/scheduler wiring; numbers essentially unchanged.",
        notes="Same architecture, bb_std=2.5.",
    ),
    StrategyDef(
        name="rsi_overbought_fade_65",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.SHORT_SELL,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        metrics=Metrics(
            pfnet=0.22, pfgross=1.38, win_rate_pct=44.0, n_trades=239530,
            avg_net_inr=-740.62, cost_drag_pct=100.5,
            universe="full_2680", run_ref="rsi-overbought-short-research.yml (rsi>=65, 2026-09-29)",
        ),
        source=".github/workflows/rsi-overbought-short-research.yml",
        evidence="Full-universe research replay: PFnet 0.22, n=239,530 - largest sample of any short candidate.",
        notes="Classic RSI-overbought mean-reversion fade, gated to RANGE regime. RESEARCH-STAGE ONLY - entry trigger never wired into main.py (no real function exists yet); everything else reuses validated real short-side functions.",
    ),
    StrategyDef(
        name="range_short_staged_ladder",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.SHORT_SELL,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        metrics=Metrics(
            pfnet=0.21, pfgross=1.43, win_rate_pct=44.9, n_trades=174702,
            avg_net_inr=-609.96, cost_drag_pct=103.6,
            universe="full_2680 (2639/2680 fetched)",
            run_ref="range-short-validation-replay.yml run 36592169599 (2026-09-29, reconfirms the O(n^2)-bug-fixed, fully-wired real short-side functions)",
        ),
        source=".github/workflows/range-short-validation-replay.yml",
        evidence="Full-universe run 36592169599: PFnet 0.21, n=174,702 - reconfirms the earlier 173,120-trade result (PFnet 0.21, avg -Rs609.61) after the O(n^2) compute-bound fix and full reconciliation/real-order/scheduler wiring; numbers essentially unchanged.",
        notes="Adds the long side's 25/25/25/trail staged exit ladder on top of the target-cluster fix - a faithful full architectural mirror, but PFnet did not improve over the target-cluster-only version (0.26->0.21).",
    ),
    StrategyDef(
        name="rsi_overbought_fade_70",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.SHORT_SELL,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        metrics=Metrics(
            pfnet=0.21, pfgross=1.30, win_rate_pct=44.0, n_trades=151543,
            avg_net_inr=-769.42, cost_drag_pct=99.5,
            universe="full_2680", run_ref="rsi-overbought-short-research.yml (rsi>=70, 2026-09-29)",
        ),
        source=".github/workflows/rsi-overbought-short-research.yml",
        evidence="Full-universe research replay: PFnet 0.21, n=151,543.",
        notes="Same as rsi_overbought_fade_65, threshold 70.",
    ),
    StrategyDef(
        name="rsi_overbought_fade_75",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.SHORT_SELL,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        metrics=Metrics(
            pfnet=0.21, pfgross=1.25, win_rate_pct=44.1, n_trades=92159,
            avg_net_inr=-794.31, cost_drag_pct=98.6,
            universe="full_2680", run_ref="rsi-overbought-short-research.yml (rsi>=75, 2026-09-29)",
        ),
        source=".github/workflows/rsi-overbought-short-research.yml",
        evidence="Full-universe research replay: PFnet 0.21, n=92,159.",
        notes="Same as rsi_overbought_fade_65, threshold 75.",
    ),
    StrategyDef(
        name="rsi_overbought_fade_80",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.SHORT_SELL,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        metrics=Metrics(
            pfnet=0.21, pfgross=1.21, win_rate_pct=44.3, n_trades=52442,
            avg_net_inr=-814.61, cost_drag_pct=97.7,
            universe="full_2680", run_ref="rsi-overbought-short-research.yml (rsi>=80, 2026-09-29)",
        ),
        source=".github/workflows/rsi-overbought-short-research.yml",
        evidence="Full-universe research replay: PFnet 0.21, n=52,442. Threshold does not move PFnet regardless of how extreme (65->80 all land at 0.21-0.22) - same pattern as the bb_std filter test on the VWAP family.",
        notes="Same as rsi_overbought_fade_65, threshold 80 (strictest tested).",
    ),
    StrategyDef(
        name="range_short_fixed_3r",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.SHORT_SELL,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        metrics=Metrics(
            pfnet=0.17, pfgross=1.36, win_rate_pct=15.3, n_trades=129898,
            avg_net_inr=-1222.62, cost_drag_pct=123.3,
            universe="full_2680", run_ref="range-short-validation-replay.yml (original fixed-3R run, 2026-09-29)",
        ),
        source=".github/workflows/range-short-validation-replay.yml",
        evidence="Full-universe run: PFnet 0.17, n=129,898. Original RANGE short-sell mirror before the target-cluster root-cause fix - superseded by range_short_target_cluster.",
        notes="Fixed last_close - rr*stop_dist target (needed >25% win rate to break even before costs, only hit 7.1%). Superseded, kept for the record.",
    ),
    StrategyDef(
        name="trend_down_momentum_short",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.SHORT_SELL,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        metrics=Metrics(
            pfnet=0.09, pfgross=1.08, win_rate_pct=31.4, n_trades=1531,
            avg_net_inr=-581.85, cost_drag_pct=145.3,
            universe="full_2680", run_ref="trend-short-validation-replay.yml (2026-09-29)",
        ),
        source=".github/workflows/trend-short-validation-replay.yml",
        evidence="Full-universe run: PFnet 0.09, n=1,531 - worst PFnet AND rarest signal (7.76M/8.78M bar-checks skipped as not-trend-regime) of every short candidate tried.",
        notes=(
            "8-factor TREND-down mirror of the long side's universal_score engine "
            "(momentum-continuation, not mean-reversion). Working theory for the "
            "underperformance: NSE names have grinding, persistent uptrends but sharp, "
            "short-lived downdrafts - momentum continuation is a structurally weaker bet "
            "shorting than buying on this universe."
        ),
    ),
    StrategyDef(
        name="minervini_vcp_short_breakdown",
        asset_class=AssetClass.EQUITY_SWING,
        categories=(TradeCategory.SHORT_SELL,),
        timeframe="1d",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,  # main.py.minervini_vcp_entry_signal_short/minervini_vcp_exit_reason_short exist but are not wired into any scan
        metrics=Metrics(
            pfnet=0.014, pfgross=0.015, win_rate_pct=42.08, n_trades=701,
            avg_net_inr=-49132.23,
            universe="full_2680 (2362/2680 fetched)",
            run_ref="minervini-vcp-short-validation-replay.yml run 36603511866 (2026-09-29, calls the real main.py functions)",
        ),
        source="main.py (minervini_vcp_entry_signal_short/minervini_vcp_exit_reason_short)",
        evidence=(
            "Full-universe run 36603511866: PFnet 0.014, PFgross 0.015, n=701, win_rate "
            "42.08%, avg_net -Rs49,132.23/trade, avg held 18.2 days. By far the worst "
            "PFnet AND worst avg_net_inr of any strategy tried this session, long or "
            "short - trail_stop_hit trades (n=516, 74% of all trades) alone carry PFnet "
            "0.008. Stage-4 VCP-down breakdown mirror does not work on this universe; "
            "the long side's own Minervini VCP result (tt_vcp, see idea4_no_target's "
            "sibling entries) was itself unremarkable, so a symmetric failure on the "
            "short side is at least consistent, not a surprising anomaly."
        ),
        notes=(
            "All Stage-4 trend-template SMA/lookback constants and the RS-percentile "
            "cross-sectional table (MINERVINI_RS_PERCENTILE_MAX_SHORT=30, bottom "
            "percentile) reused verbatim from the long side per CLAUDE.md's short-"
            "mirror discipline - only comparison directions inverted. Never checked "
            "across candle sizes (CLAUDE.md 2026-09-29 thumb rule) - 1d only so far; "
            "given how badly it fails here, a candle-size sweep is unlikely to be a "
            "priority ahead of higher-PFnet candidates."
        ),
    ),
    StrategyDef(
        name="power_play_short_fade",
        asset_class=AssetClass.EQUITY_SWING,
        categories=(TradeCategory.SHORT_SELL,),
        timeframe="1d",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,  # main.py.power_play_entry_signal_short/power_play_exit_reason_short exist but are not wired into any scan
        metrics=Metrics(
            pfnet=0.479, pfgross=0.580, win_rate_pct=36.00, n_trades=50,
            avg_net_inr=-401.18,
            universe="full_2680 (2366/2680 fetched)",
            run_ref="power-play-short-validation-replay.yml run 36605194832 (2026-09-29, calls the real main.py functions)",
        ),
        source="main.py (power_play_entry_signal_short/power_play_exit_reason_short)",
        evidence=(
            "Full-universe run 36605194832: PFnet 0.479, PFgross 0.580, n=50, win_rate "
            "36.00%, avg_net -Rs401.18/trade, avg held 24.0 days. Best PFnet of any "
            "short-sell candidate tried this session by a wide margin (next best is "
            "range_short_target_cluster at 0.26), but still well below "
            "PFNET_LIVE_FLOOR and a fraction of the long side's own 5.023 PFnet on the "
            "same setup. Confirms the crash-flag-breakdown structure does not mirror as "
            "cleanly into the fade direction as the RANGE VWAP mean-reversion short did "
            "relative to its own long side."
        ),
        notes=(
            "'Power fade' - crash (>=50% halving, log-symmetric mirror of the long "
            "side's +100% launch requirement per POWER_PLAY_CRASH_MIN_LOSS_PCT_SHORT) "
            "+ tight flag + breakdown, chandelier-trail exit. n=50 is thin even by "
            "Power Play's own rare-setup standard (long side n=109 on the identical "
            "universe) - the long side's own thumb rule (rarest setup in the book) "
            "applies doubly here. Never checked across candle sizes; 1d only so far."
        ),
    ),
    StrategyDef(
        name="idea4_short_ride_losers",
        asset_class=AssetClass.EQUITY_SWING,
        categories=(TradeCategory.SHORT_SELL,),
        timeframe="1d",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,  # main.py.idea4_entry_signal_short/idea4_exit_reason_short exist but are not wired into any scan
        metrics=Metrics(
            pfnet=0.119, pfgross=0.139, win_rate_pct=36.65, n_trades=12285,
            avg_net_inr=-6730.43,
            universe="full_2680 (2366/2680 fetched)",
            run_ref="idea4-short-validation-replay.yml run 36605198734 (2026-09-29, calls the real main.py functions)",
        ),
        source="main.py (idea4_entry_signal_short/idea4_exit_reason_short)",
        evidence=(
            "Full-universe run 36605198734: PFnet 0.119, PFgross 0.139, n=12,285, "
            "win_rate 36.65%, avg_net -Rs6,730.43/trade, avg held 13.9 days. By exit "
            "reason: stop_hit (n=6,013, 49% of trades) is a total loss - PFnet 0.000, "
            "0% win rate, every single one of these exits at a loss, same pattern as "
            "the long side's own idea4_no_target where the fixed, never-trailed stop "
            "is the weak point. max_hold_exit (n=5,945) and data_end_forced_close "
            "(n=327) both show strong PFnet (7.5 and 6.7) but these are the trades "
            "that were NOT stopped out - survivorship within the sample, not evidence "
            "the strategy works, since the stop_hit half wipes out the gains from the "
            "other half at the pooled level (net PFnet 0.119)."
        ),
        notes=(
            "'Ride losers down' - mirrors idea4_no_target's own fixed ATR(14)x1.5 "
            "stop set once at entry (never trailed), EMA9<EMA21 pre-filter, "
            "_compute_universal_entry_score_short (reused unmodified from the TREND-"
            "down short mirror) for the entry gate, ride to stop or "
            "IDEA4_MAX_HOLD_DAYS=20 trading days. Slowest replay of the whole session "
            "(~43 min vs VCP-short's 6 and Power Play-short's 15) - not a bug, this "
            "strategy's entry gate is far wider than either of those two rare-setup "
            "strategies (score>=70 + one EMA cross vs a multi-bar structural pattern), "
            "so it fires far more often (n=12,285 vs 701/50) and does more per-symbol "
            "work (merge_asof index-closes alignment every bar). Never checked across "
            "candle sizes; 1d only so far."
        ),
    ),
    StrategyDef(
        name="gap_and_go_short_fade",
        asset_class=AssetClass.EQUITY_SWING,
        categories=(TradeCategory.SHORT_SELL,),
        timeframe="1d",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,  # main.py.gap_and_go_entry_signal_short/gap_and_go_exit_reason_short exist but are not wired into any scan
        metrics=Metrics(
            pfnet=0.557, pfgross=0.670, win_rate_pct=25.98, n_trades=4576,
            avg_net_inr=-471.81,
            universe="full_2680 (2366/2680 fetched)",
            run_ref="gap-and-go-short-validation-replay.yml run 36613045246 (2026-09-29, calls the real main.py functions)",
        ),
        source="main.py (gap_and_go_entry_signal_short/gap_and_go_exit_reason_short)",
        evidence=(
            "Full-universe run 36613045246: PFnet 0.557, PFgross 0.670, n=4,576, win_rate "
            "25.98%, avg_net -Rs471.81/trade, avg held 27.0 days. Best short-sell PFnet "
            "of the entire session, edging out power_play_short_fade (0.479) despite a "
            "far larger, noisier sample. By exit reason: gap_filled (n=2,813, 61% of "
            "trades) is a total loss - PFnet 0.000, 0% win rate, the same 'the exit is "
            "the weak point, not the entry' pattern seen on idea4_no_target and its own "
            "short mirror. The trades that survive to max_hold_timeout (n=1,239, PFnet "
            "34.9, 88.6% win rate) or data_end_forced_close (n=107, PFnet 49.1) are "
            "hugely profitable - pooled PFnet is dragged down entirely by the majority "
            "gap_filled bucket exiting flat-to-negative before costs."
        ),
        notes=(
            "'Gap down and go' - mirrors gap_and_go_swing's own gap-threshold/volume-"
            "surge/ATR-stop/max-hold constants verbatim (SWING_GAP_PCT_THRESHOLD, "
            "SWING_VOL_MULT, SWING_ATR_STOP_MULT, SWING_MAX_HOLD_DAYS), only comparison "
            "directions inverted. Still well below PFNET_LIVE_FLOOR and not wired "
            "anywhere live, but worth a second look given the gap_filled-exit weak "
            "point looks fixable (a tighter/trailing exit there, mirroring what's "
            "already suspected on the long side and on idea4_no_target) rather than a "
            "structurally broken entry. The 2026-09-29 candle-size sweep (see "
            "gap_and_go_swing's own notes) only covered the long side - this short "
            "mirror has never been checked across candle sizes, 1d only so far."
        ),
    ),
    StrategyDef(
        name="failed_breakout_short",
        asset_class=AssetClass.EQUITY_SWING,
        categories=(TradeCategory.SHORT_SELL,),
        timeframe="1d",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,  # main.py.failed_breakout_entry_signal_short/failed_breakout_exit_reason_short exist but are not wired into any scan
        metrics=Metrics(
            pfnet=0.657, pfgross=0.827, win_rate_pct=34.88, n_trades=20879,
            avg_net_inr=-549.84,
            universe="full_2680 (2366/2680 fetched)",
            run_ref="failed-breakout-short-validation-replay.yml run 36712440006 (2026-09-30, calls the real main.py functions)",
        ),
        source="main.py (failed_breakout_entry_signal_short/failed_breakout_exit_reason_short)",
        evidence=(
            "Full-universe run 36712440006: PFnet 0.657, PFgross 0.827, n=20,879, win_rate "
            "34.88%, avg_net -Rs549.84/trade, avg held 16.4 days. SECOND-best short-sell "
            "PFnet of the entire session (after gap_and_go_short_fade's 0.557 - this "
            "actually beats it), on by far the largest short-sell sample tried (20,879 vs "
            "gap_and_go_short_fade's 4,576). By exit reason: trail_stop_hit (n=14,830, 71% "
            "of trades) is a clear net loser - PFnet 0.138, 12.99% win rate - the same "
            "'the exit is the weak point, not the entry' pattern already seen on "
            "idea4_no_target, gap_and_go_short_fade, and Minervini VCP. The trades that "
            "survive to max_hold_timeout (n=5,725, PFnet 47.3, 89.4% win rate) or "
            "data_end_forced_close (n=324, PFnet 9.96) are extremely profitable - pooled "
            "PFnet is dragged below breakeven entirely by the majority trail_stop_hit "
            "bucket exiting early."
        ),
        notes=(
            "Classic 'bull trap' - price breaks above an established resistance ceiling, "
            "the breakout fails to hold within a few sessions, price reverses back below "
            "it. Short entry fires on the failure/reversal confirmation, not the breakout "
            "itself (see _find_failed_breakout_setup's own docstring for the exact "
            "resistance-lookback/exclude-window/min-breakout-pct/max-days-since-breakout "
            "parameters). Still below PFNET_LIVE_FLOOR and not wired anywhere live, but "
            "the same recurring lead as gap_and_go_short_fade/idea4_no_target: the "
            "chandelier-trail exit (FAILED_BREAKOUT_ATR_STOP_MULT=2.0) may be cutting "
            "winners off before the move that actually pays out (max_hold_timeout trades "
            "are ~340x more profitable per the PFnet spread) - worth a wider-trail or "
            "later-activation exit variant in a future pass, never tuned blind off this "
            "one result alone. 2026-09-30, explicit user instruction ('Read about it and "
            "backtest'). Never checked across candle sizes - 1d only so far, its own "
            "natural timeframe for a multi-day breakout/failure pattern."
        ),
    ),

    StrategyDef(
        name="gap_up_fade_short",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.SHORT_SELL,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,  # main.py's own gap_up_fade_entry_signal_short/gap_up_fade_exit_reason_short exist but are not wired into any scan
        metrics=Metrics(
            pfnet=0.386, pfgross=1.250, win_rate_pct=24.68, n_trades=19941,
            avg_net_inr=-556.47,
            universe="full_2680 (2636/2680 fetched)",
            run_ref="gap-up-fade-short-validation-replay.yml run 36813637935 (2026-10-01, "
                     "sharded 40-way, calls the real main.py gap_up_fade_entry_signal_short/"
                     "gap_up_fade_exit_reason_short)",
        ),
        source="main.py (gap_up_fade_entry_signal_short/gap_up_fade_exit_reason_short)",
        evidence=(
            "Full-universe run 36813637935 (60d/5m, sharded after an earlier unsharded "
            "attempt - run 36712451311 - hit its own 340-minute timeout with zero result): "
            "PFnet 0.386, PFgross 1.250, n=19,941, win_rate 24.68%, avg_net -Rs556.47/trade, "
            "avg held 363.3 min. By exit reason: trail_stop_hit (n=12,950, 65% of trades) is "
            "a severe net loser - PFnet 0.075, 9.05% win rate - the SAME 'the exit is the "
            "weak point, not the entry' pattern already seen on failed_breakout_short, "
            "idea4_no_target, gap_and_go_short_fade, and Minervini VCP. Trades surviving to "
            "max_hold_timeout (n=6,931, PFnet 3.014, 53.83% win rate) are solidly profitable "
            "- pooled PFnet is dragged below breakeven by the majority trail_stop_hit bucket "
            "exiting early."
        ),
        notes=(
            "docs/minervini_book_notes.txt-adjacent, 2026-09-30 explicit user instruction "
            "('Read about it and backtest') - mirror-opposite of gap_and_go (needs the gap to "
            "HOLD) and distinct from gap_and_go_short_fade (a gap-DOWN continuation trade, not "
            "a fade): a stock gaps UP strongly at the open then fails to hold that gap during "
            "the session, reversing below its own opening print. Still below PFNET_LIVE_FLOOR "
            "and not wired anywhere live. Same recurring lead as failed_breakout_short: the "
            "chandelier-trail exit (GAP_UP_FADE_ATR_STOP_MULT=1.5) may be cutting winners off "
            "before the move that actually pays out (max_hold_timeout trades are ~40x more "
            "profitable per the PFnet spread) - a sweep of this multiplier is the same "
            "structured, hypothesis-driven candidate CLAUDE.md's own 2026-09-30 sweep-"
            "discipline thumb rule calls for, not yet executed. Never checked across candle "
            "sizes beyond its own native 5m."
        ),
    ),

    # ---- 2026-10-05 Indicator Combinatorics Step-1 (daily, LONG, full universe) ----
    # Registered per CLAUDE.md "register every variant tried with real metrics,
    # pass or fail" + "never merge differently-named variants". All are daily
    # bars with multi-week holds -> SWING category. None is wired to a live
    # path (no _STRATEGY_TAG_TO_REGISTRY_NAME entry), so _is_strategy_viable_
    # for_real_money fails closed for all of them regardless of PFnet.
    StrategyDef(
        name="order_block_delta_long",
        asset_class=AssetClass.EQUITY_SWING,
        categories=(TradeCategory.SWING,),
        timeframe="1d",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=1.062, pfgross=1.259, win_rate_pct=39.79, n_trades=33049, avg_held_hrs=21.7 * TRADING_HOURS_PER_DAY,
            avg_net_inr=69.72,
            universe="full_2680 (2409/2688 fetched)",
            run_ref="order-block-delta-research.yml run 37358050173 (2026-10-05, daily/5y, LONG)",
        ),
        source=".github/workflows/order-block-delta-research.yml (research-embedded order_block_entry_signal, not a main.py function)",
        evidence=(
            "Run 37358050173: PFnet 1.062, PFgross 1.259, n=33,049, win 39.79%, avg_net "
            "+Rs69.72, avg held 21.7d. trail_stop_hit n=18,060 PFnet 0.322; max_hold_timeout "
            "n=14,292 PFnet 7.255 (68% win); data_end_forced_close n=697 PFnet 0.595."
        ),
        notes=(
            "VIABLE by metrics but margin over the 1.0 floor is thin and rides entirely on "
            "30-day max-hold survivors (trail stops lose, PFnet ~0.3) - same recurring exit-"
            "is-the-weak-point pattern. Research-stage reimplementation, NOT a call into "
            "main.py. Backlog B-26: param/candle-size sweep + short mirror before any live "
            "wiring. Long only so far."
        ),
    ),

    StrategyDef(
        name="volume_profile_poc_bounce_long",
        asset_class=AssetClass.EQUITY_SWING,
        categories=(TradeCategory.SWING,),
        timeframe="1d",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=1.025, pfgross=1.396, win_rate_pct=24.98, n_trades=49927, avg_held_hrs=12.2 * TRADING_HOURS_PER_DAY,
            avg_net_inr=74.13,
            universe="full_2680 (2377/2688 fetched)",
            run_ref="volume-profile-poc-liquidity-research.yml run 37358062832 (2026-10-05, daily/5y, LONG)",
        ),
        source=".github/workflows/volume-profile-poc-liquidity-research.yml (research-embedded; approved volume-profile proxy for a liquidity heatmap, not a literal CoinGlass port)",
        evidence=(
            "Run 37358062832: PFnet 1.025, PFgross 1.396, n=49,927, win 24.98%, avg_net "
            "+Rs74.13, avg held 12.2d. trail_stop_hit n=40,052 PFnet 0.310 (9.9% win); "
            "max_hold_timeout n=9,524 PFnet 96.0 (87.8% win); window_end_forced_close n=351 PFnet 3.85."
        ),
        notes=(
            "VIABLE by metrics but only just (1.025); cost drag is large (gross 1.396 -> net "
            "1.025). Faster turnover than order_block_delta_long (12.2d vs 21.7d) per the "
            "capital-turnover thumb rule. Research-stage, not wired live; B-26 sweeps pending."
        ),
    ),
    StrategyDef(
        name="rsi_reversal__p14_os30_ob70",
        asset_class=AssetClass.EQUITY_SWING,
        categories=(TradeCategory.SWING,),
        timeframe="1d",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.838, pfgross=1.052, win_rate_pct=37.81, n_trades=28525, avg_held_hrs=15.1 * TRADING_HOURS_PER_DAY,
            avg_net_inr=-252.7,
            universe="full_2680",
            run_ref="rsi-reversal-variant-sweep-research.yml run 37358065924 (2026-10-05, daily/5y, LONG, calls the REAL main.add_strategy_signal 'rsi_reversal')",
        ),
        source=".github/workflows/rsi-reversal-variant-sweep-research.yml (real main.add_strategy_signal 'rsi_reversal')",
        evidence=(
            "Run 37358065924 variant p14_os30_ob70: PFnet 0.838, PFgross 1.052, n=28,525, win 37.81%, "
            "avg_net Rs-252.7, avg held 15.1d. NOT VIABLE (< PFNET_LIVE_FLOOR). "
            "trail_stop_hit bucket PFnet < 0.23 while rsi_overbought_exit PFnet >> 1."
        ),
        notes=(
            "Non-viable Step-1 variant, recorded per register-every-variant rule. Shared "
            "pattern across all 9 variants: the ATR trail stop is the drag, the RSI-overbought "
            "exit is the profit source - a stop-multiplier sweep is the hypothesis-driven next "
            "lever (not blind tuning). Long only; short mirror + other candle sizes not yet run."
        ),
    ),
    StrategyDef(
        name="rsi_reversal__p14_os25_ob75",
        asset_class=AssetClass.EQUITY_SWING,
        categories=(TradeCategory.SWING,),
        timeframe="1d",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.882, pfgross=1.102, win_rate_pct=36.21, n_trades=19797, avg_held_hrs=16.4 * TRADING_HOURS_PER_DAY,
            avg_net_inr=-185.85,
            universe="full_2680",
            run_ref="rsi-reversal-variant-sweep-research.yml run 37358065924 (2026-10-05, daily/5y, LONG, calls the REAL main.add_strategy_signal 'rsi_reversal')",
        ),
        source=".github/workflows/rsi-reversal-variant-sweep-research.yml (real main.add_strategy_signal 'rsi_reversal')",
        evidence=(
            "Run 37358065924 variant p14_os25_ob75: PFnet 0.882, PFgross 1.102, n=19,797, win 36.21%, "
            "avg_net Rs-185.85, avg held 16.4d. NOT VIABLE (< PFNET_LIVE_FLOOR). "
            "trail_stop_hit bucket PFnet < 0.23 while rsi_overbought_exit PFnet >> 1."
        ),
        notes=(
            "Non-viable Step-1 variant, recorded per register-every-variant rule. Shared "
            "pattern across all 9 variants: the ATR trail stop is the drag, the RSI-overbought "
            "exit is the profit source - a stop-multiplier sweep is the hypothesis-driven next "
            "lever (not blind tuning). Long only; short mirror + other candle sizes not yet run."
        ),
    ),
    StrategyDef(
        name="rsi_reversal__p14_os20_ob80",
        asset_class=AssetClass.EQUITY_SWING,
        categories=(TradeCategory.SWING,),
        timeframe="1d",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.933, pfgross=1.159, win_rate_pct=35.65, n_trades=12287, avg_held_hrs=17.3 * TRADING_HOURS_PER_DAY,
            avg_net_inr=-108.03,
            universe="full_2680",
            run_ref="rsi-reversal-variant-sweep-research.yml run 37358065924 (2026-10-05, daily/5y, LONG, calls the REAL main.add_strategy_signal 'rsi_reversal')",
        ),
        source=".github/workflows/rsi-reversal-variant-sweep-research.yml (real main.add_strategy_signal 'rsi_reversal')",
        evidence=(
            "Run 37358065924 variant p14_os20_ob80: PFnet 0.933, PFgross 1.159, n=12,287, win 35.65%, "
            "avg_net Rs-108.03, avg held 17.3d. NOT VIABLE (< PFNET_LIVE_FLOOR). "
            "trail_stop_hit bucket PFnet < 0.23 while rsi_overbought_exit PFnet >> 1."
        ),
        notes=(
            "Non-viable Step-1 variant, recorded per register-every-variant rule. Shared "
            "pattern across all 9 variants: the ATR trail stop is the drag, the RSI-overbought "
            "exit is the profit source - a stop-multiplier sweep is the hypothesis-driven next "
            "lever (not blind tuning). Long only; short mirror + other candle sizes not yet run."
        ),
    ),
    StrategyDef(
        name="rsi_reversal__p21_os30_ob70",
        asset_class=AssetClass.EQUITY_SWING,
        categories=(TradeCategory.SWING,),
        timeframe="1d",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.838, pfgross=1.048, win_rate_pct=33.85, n_trades=14708, avg_held_hrs=16.8 * TRADING_HOURS_PER_DAY,
            avg_net_inr=-265.46,
            universe="full_2680",
            run_ref="rsi-reversal-variant-sweep-research.yml run 37358065924 (2026-10-05, daily/5y, LONG, calls the REAL main.add_strategy_signal 'rsi_reversal')",
        ),
        source=".github/workflows/rsi-reversal-variant-sweep-research.yml (real main.add_strategy_signal 'rsi_reversal')",
        evidence=(
            "Run 37358065924 variant p21_os30_ob70: PFnet 0.838, PFgross 1.048, n=14,708, win 33.85%, "
            "avg_net Rs-265.46, avg held 16.8d. NOT VIABLE (< PFNET_LIVE_FLOOR). "
            "trail_stop_hit bucket PFnet < 0.23 while rsi_overbought_exit PFnet >> 1."
        ),
        notes=(
            "Non-viable Step-1 variant, recorded per register-every-variant rule. Shared "
            "pattern across all 9 variants: the ATR trail stop is the drag, the RSI-overbought "
            "exit is the profit source - a stop-multiplier sweep is the hypothesis-driven next "
            "lever (not blind tuning). Long only; short mirror + other candle sizes not yet run."
        ),
    ),
    StrategyDef(
        name="rsi_reversal__p21_os25_ob75",
        asset_class=AssetClass.EQUITY_SWING,
        categories=(TradeCategory.SWING,),
        timeframe="1d",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.869, pfgross=1.081, win_rate_pct=33.89, n_trades=8422, avg_held_hrs=17.1 * TRADING_HOURS_PER_DAY,
            avg_net_inr=-220.51,
            universe="full_2680",
            run_ref="rsi-reversal-variant-sweep-research.yml run 37358065924 (2026-10-05, daily/5y, LONG, calls the REAL main.add_strategy_signal 'rsi_reversal')",
        ),
        source=".github/workflows/rsi-reversal-variant-sweep-research.yml (real main.add_strategy_signal 'rsi_reversal')",
        evidence=(
            "Run 37358065924 variant p21_os25_ob75: PFnet 0.869, PFgross 1.081, n=8,422, win 33.89%, "
            "avg_net Rs-220.51, avg held 17.1d. NOT VIABLE (< PFNET_LIVE_FLOOR). "
            "trail_stop_hit bucket PFnet < 0.23 while rsi_overbought_exit PFnet >> 1."
        ),
        notes=(
            "Non-viable Step-1 variant, recorded per register-every-variant rule. Shared "
            "pattern across all 9 variants: the ATR trail stop is the drag, the RSI-overbought "
            "exit is the profit source - a stop-multiplier sweep is the hypothesis-driven next "
            "lever (not blind tuning). Long only; short mirror + other candle sizes not yet run."
        ),
    ),
    StrategyDef(
        name="rsi_reversal__p21_os20_ob80",
        asset_class=AssetClass.EQUITY_SWING,
        categories=(TradeCategory.SWING,),
        timeframe="1d",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.946, pfgross=1.174, win_rate_pct=34.72, n_trades=4314, avg_held_hrs=17.3 * TRADING_HOURS_PER_DAY,
            avg_net_inr=-92.08,
            universe="full_2680",
            run_ref="rsi-reversal-variant-sweep-research.yml run 37358065924 (2026-10-05, daily/5y, LONG, calls the REAL main.add_strategy_signal 'rsi_reversal')",
        ),
        source=".github/workflows/rsi-reversal-variant-sweep-research.yml (real main.add_strategy_signal 'rsi_reversal')",
        evidence=(
            "Run 37358065924 variant p21_os20_ob80: PFnet 0.946, PFgross 1.174, n=4,314, win 34.72%, "
            "avg_net Rs-92.08, avg held 17.3d. NOT VIABLE (< PFNET_LIVE_FLOOR). "
            "trail_stop_hit bucket PFnet < 0.23 while rsi_overbought_exit PFnet >> 1."
        ),
        notes=(
            "Non-viable Step-1 variant, recorded per register-every-variant rule. Shared "
            "pattern across all 9 variants: the ATR trail stop is the drag, the RSI-overbought "
            "exit is the profit source - a stop-multiplier sweep is the hypothesis-driven next "
            "lever (not blind tuning). Long only; short mirror + other candle sizes not yet run."
        ),
    ),
    StrategyDef(
        name="rsi_reversal__p9_os30_ob70",
        asset_class=AssetClass.EQUITY_SWING,
        categories=(TradeCategory.SWING,),
        timeframe="1d",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.905, pfgross=1.177, win_rate_pct=49.45, n_trades=54823, avg_held_hrs=11.6 * TRADING_HOURS_PER_DAY,
            avg_net_inr=-118.82,
            universe="full_2680",
            run_ref="rsi-reversal-variant-sweep-research.yml run 37358065924 (2026-10-05, daily/5y, LONG, calls the REAL main.add_strategy_signal 'rsi_reversal')",
        ),
        source=".github/workflows/rsi-reversal-variant-sweep-research.yml (real main.add_strategy_signal 'rsi_reversal')",
        evidence=(
            "Run 37358065924 variant p9_os30_ob70: PFnet 0.905, PFgross 1.177, n=54,823, win 49.45%, "
            "avg_net Rs-118.82, avg held 11.6d. NOT VIABLE (< PFNET_LIVE_FLOOR). "
            "trail_stop_hit bucket PFnet < 0.23 while rsi_overbought_exit PFnet >> 1."
        ),
        notes=(
            "Non-viable Step-1 variant, recorded per register-every-variant rule. Shared "
            "pattern across all 9 variants: the ATR trail stop is the drag, the RSI-overbought "
            "exit is the profit source - a stop-multiplier sweep is the hypothesis-driven next "
            "lever (not blind tuning). Long only; short mirror + other candle sizes not yet run."
        ),
    ),
    StrategyDef(
        name="rsi_reversal__p9_os25_ob75",
        asset_class=AssetClass.EQUITY_SWING,
        categories=(TradeCategory.SWING,),
        timeframe="1d",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.928, pfgross=1.182, win_rate_pct=45.47, n_trades=41920, avg_held_hrs=13.3 * TRADING_HOURS_PER_DAY,
            avg_net_inr=-96.4,
            universe="full_2680",
            run_ref="rsi-reversal-variant-sweep-research.yml run 37358065924 (2026-10-05, daily/5y, LONG, calls the REAL main.add_strategy_signal 'rsi_reversal')",
        ),
        source=".github/workflows/rsi-reversal-variant-sweep-research.yml (real main.add_strategy_signal 'rsi_reversal')",
        evidence=(
            "Run 37358065924 variant p9_os25_ob75: PFnet 0.928, PFgross 1.182, n=41,920, win 45.47%, "
            "avg_net Rs-96.4, avg held 13.3d. NOT VIABLE (< PFNET_LIVE_FLOOR). "
            "trail_stop_hit bucket PFnet < 0.23 while rsi_overbought_exit PFnet >> 1."
        ),
        notes=(
            "Non-viable Step-1 variant, recorded per register-every-variant rule. Shared "
            "pattern across all 9 variants: the ATR trail stop is the drag, the RSI-overbought "
            "exit is the profit source - a stop-multiplier sweep is the hypothesis-driven next "
            "lever (not blind tuning). Long only; short mirror + other candle sizes not yet run."
        ),
    ),
    StrategyDef(
        name="rsi_reversal__p9_os20_ob80",
        asset_class=AssetClass.EQUITY_SWING,
        categories=(TradeCategory.SWING,),
        timeframe="1d",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.914, pfgross=1.152, win_rate_pct=41.38, n_trades=30325, avg_held_hrs=15.0 * TRADING_HOURS_PER_DAY,
            avg_net_inr=-122.82,
            universe="full_2680",
            run_ref="rsi-reversal-variant-sweep-research.yml run 37358065924 (2026-10-05, daily/5y, LONG, calls the REAL main.add_strategy_signal 'rsi_reversal')",
        ),
        source=".github/workflows/rsi-reversal-variant-sweep-research.yml (real main.add_strategy_signal 'rsi_reversal')",
        evidence=(
            "Run 37358065924 variant p9_os20_ob80: PFnet 0.914, PFgross 1.152, n=30,325, win 41.38%, "
            "avg_net Rs-122.82, avg held 15.0d. NOT VIABLE (< PFNET_LIVE_FLOOR). "
            "trail_stop_hit bucket PFnet < 0.23 while rsi_overbought_exit PFnet >> 1."
        ),
        notes=(
            "Non-viable Step-1 variant, recorded per register-every-variant rule. Shared "
            "pattern across all 9 variants: the ATR trail stop is the drag, the RSI-overbought "
            "exit is the profit source - a stop-multiplier sweep is the hypothesis-driven next "
            "lever (not blind tuning). Long only; short mirror + other candle sizes not yet run."
        ),
    ),

    StrategyDef(
        name="pin_bar_reversal__baseline__long__5m__pr2d0_srl20_srt0d5__v1",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.BUY,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.024, pfgross=0.536, win_rate_pct=2.94, n_trades=311872, avg_held_hrs=31.2 / 60,
            avg_net_inr=-1746.48,
            universe="full_2680 (2642/2688 fetched)",
            run_ref="pin-bar-reversal-full-universe-validation.yml run 37358058707 (2026-10-05, 5m/60d, LONG, calls the REAL main.add_strategy_signal 'pin_bar_reversal')",
        ),
        source=".github/workflows/pin-bar-reversal-full-universe-validation.yml (real main.add_strategy_signal 'pin_bar_reversal')",
        evidence=(
            "Run 37358058707: PFnet 0.024, PFgross 0.536 (< 1 BEFORE costs), n=311,872, win 2.94%, "
            "avg_net Rs-1,746.48, avg held 31.2 min. trail_stop_hit n=155,838 (50%) win 0.53%; "
            "bearish_pin_exit n=137,283 PFnet 0.042; max_hold_timeout n=3,140 PFnet 0.409. NOT VIABLE."
        ),
        notes=(
            "Baseline params only (pin_ratio=2.0, sr_lookback=20, sr_tolerance_pct=0.5). ~118 trades "
            "per symbol in 60 days and top symbols are cash ETFs (LIQUIDBEES/LIQUIDCASE): the entry "
            "appears to fire on nearly every pin bar with no volatility/liquidity filter - a hypothesis "
            "from the numbers, not confirmed in code. No edge pre-cost, so cost drag is not the cause. "
            "Not tuned from this one result; any sweep/short mirror/other candle size gets its own tag."
        ),
    ),

    # ---- FUTURES / OPTIONS ------------------------------------------------
    # No entries: kotak_real_orders.py has NO futures or options order-
    # placement path at all (equity CNC/MIS only). Every options idea in
    # docs/STRATEGY_LOG.md is "Template (untested)" or "Proposed -
    # untested" - backtest-only, nothing ever placed an options or futures
    # order in this codebase. A "top 5" in either category is not
    # meaningful until real execution is built - that is itself a separate,
    # larger infrastructure project, not a backtest/research task. See
    # docs/STRATEGY_LOG.md rows #10-12, #29 for the closest existing
    # (untested) candidates once that execution path exists.

    StrategyDef(
        name="fvg3c__breakaway__short__5m__ap14_cb2_cr1d5_elproximal_mh60_mw20_mg0d25_rr2d0_sp0d25_sb0d7_tgwick__v1",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.SHORT_SELL,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.089, pfgross=0.922, win_rate_pct=13.85, n_trades=265155, avg_held_hrs=123.9 / 60,
            avg_net_inr=-1534.13,
            universe="full_2680 (2642/2688 fetched)",
            run_ref="fvg3c-full-universe-research.yml run 37436244446 (2026-10-06, 5m/60d, SHORT, calls the REAL main.py scan function)",
        ),
        source=".github/workflows/fvg3c-full-universe-research.yml (real main.py scan/entry/exit functions)",
        evidence=(
            "Run 37436244446 baseline: PFnet 0.089, PFgross 0.922, n=265,155, win 13.85%, "
            "avg_net Rs-1,534.13, avg held 123.9 min. NOT VIABLE (< PFNET_LIVE_FLOOR)."
        ),
        notes=(
            "FVG 3rd-candle breakaway, baseline params only, recorded per register-every-variant rule. "
            "Candle-size sweep, parameter grid and opposite-direction comparison still owed (backlog B-16/B-17/B-40/B-33/B-11)."
        ),
    ),

    StrategyDef(
        name="fvg3c__rejection__short__5m__ap14_cb2_cr1d5_elproximal_mh60_mw20_mg0d25_rr2d0_sp0d25_sb0d7_tgwick__v1",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.SHORT_SELL,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.084, pfgross=0.836, win_rate_pct=13.9, n_trades=134502, avg_held_hrs=124.0 / 60,
            avg_net_inr=-1584.81,
            universe="full_2680 (2642/2688 fetched)",
            run_ref="fvg3c-full-universe-research.yml run 37436244446 (2026-10-06, 5m/60d, SHORT, calls the REAL main.py scan function)",
        ),
        source=".github/workflows/fvg3c-full-universe-research.yml (real main.py scan/entry/exit functions)",
        evidence=(
            "Run 37436244446 baseline: PFnet 0.084, PFgross 0.836, n=134,502, win 13.9%, "
            "avg_net Rs-1,584.81, avg held 124.0 min. NOT VIABLE (< PFNET_LIVE_FLOOR)."
        ),
        notes=(
            "FVG 3rd-candle rejection, baseline params only, recorded per register-every-variant rule. "
            "Candle-size sweep, parameter grid and opposite-direction comparison still owed (backlog B-16/B-17/B-40/B-33/B-11)."
        ),
    ),

    StrategyDef(
        name="fvg3c__rejection__long__5m__ap14_cb2_cr1d5_elproximal_mh60_mw20_mg0d25_rr2d0_sp0d25_sb0d7_tgwick__v1",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.BUY,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.083, pfgross=0.644, win_rate_pct=12.39, n_trades=114499, avg_held_hrs=118.9 / 60,
            avg_net_inr=-1706.48,
            universe="full_2680 (2642/2688 fetched)",
            run_ref="fvg3c-full-universe-research.yml run 37436244446 (2026-10-06, 5m/60d, LONG, calls the REAL main.py scan function)",
        ),
        source=".github/workflows/fvg3c-full-universe-research.yml (real main.py scan/entry/exit functions)",
        evidence=(
            "Run 37436244446 baseline: PFnet 0.083, PFgross 0.644, n=114,499, win 12.39%, "
            "avg_net Rs-1,706.48, avg held 118.9 min. NOT VIABLE (< PFNET_LIVE_FLOOR)."
        ),
        notes=(
            "FVG 3rd-candle rejection, baseline params only, recorded per register-every-variant rule. "
            "Candle-size sweep, parameter grid and opposite-direction comparison still owed (backlog B-16/B-17/B-40/B-33/B-11)."
        ),
    ),

    StrategyDef(
        name="fvg3c__breakaway__long__5m__ap14_cb2_cr1d5_elproximal_mh60_mw20_mg0d25_rr2d0_sp0d25_sb0d7_tgwick__v1",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.BUY,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.071, pfgross=0.615, win_rate_pct=10.85, n_trades=261263, avg_held_hrs=111.3 / 60,
            avg_net_inr=-1729.79,
            universe="full_2680 (2642/2688 fetched)",
            run_ref="fvg3c-full-universe-research.yml run 37436244446 (2026-10-06, 5m/60d, LONG, calls the REAL main.py scan function)",
        ),
        source=".github/workflows/fvg3c-full-universe-research.yml (real main.py scan/entry/exit functions)",
        evidence=(
            "Run 37436244446 baseline: PFnet 0.071, PFgross 0.615, n=261,263, win 10.85%, "
            "avg_net Rs-1,729.79, avg held 111.3 min. NOT VIABLE (< PFNET_LIVE_FLOOR)."
        ),
        notes=(
            "FVG 3rd-candle breakaway, baseline params only, recorded per register-every-variant rule. "
            "Candle-size sweep, parameter grid and opposite-direction comparison still owed (backlog B-16/B-17/B-40/B-33/B-11)."
        ),
    ),

    StrategyDef(
        name="fvg3c__valid_retest__short__5m__ap14_cb2_cr1d5_elproximal_mh60_mw20_mg0d25_rr2d0_sp0d25_sb0d7_tgwick__v1",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.SHORT_SELL,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.06, pfgross=0.963, win_rate_pct=11.55, n_trades=2225, avg_held_hrs=108.4 / 60,
            avg_net_inr=-1557.29,
            universe="full_2680 (2642/2688 fetched)",
            run_ref="fvg3c-full-universe-research.yml run 37436244446 (2026-10-06, 5m/60d, SHORT, calls the REAL main.py scan function)",
        ),
        source=".github/workflows/fvg3c-full-universe-research.yml (real main.py scan/entry/exit functions)",
        evidence=(
            "Run 37436244446 baseline: PFnet 0.06, PFgross 0.963, n=2,225, win 11.55%, "
            "avg_net Rs-1,557.29, avg held 108.4 min. NOT VIABLE (< PFNET_LIVE_FLOOR)."
        ),
        notes=(
            "FVG 3rd-candle valid retest, baseline params only, recorded per register-every-variant rule. "
            "Candle-size sweep, parameter grid and opposite-direction comparison still owed (backlog B-16/B-17/B-40/B-33/B-11)."
        ),
    ),

    StrategyDef(
        name="fvg3c__valid_retest__long__5m__ap14_cb2_cr1d5_elproximal_mh60_mw20_mg0d25_rr2d0_sp0d25_sb0d7_tgwick__v1",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.BUY,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.059, pfgross=0.683, win_rate_pct=10.43, n_trades=1840, avg_held_hrs=125.0 / 60,
            avg_net_inr=-1715.82,
            universe="full_2680 (2642/2688 fetched)",
            run_ref="fvg3c-full-universe-research.yml run 37436244446 (2026-10-06, 5m/60d, LONG, calls the REAL main.py scan function)",
        ),
        source=".github/workflows/fvg3c-full-universe-research.yml (real main.py scan/entry/exit functions)",
        evidence=(
            "Run 37436244446 baseline: PFnet 0.059, PFgross 0.683, n=1,840, win 10.43%, "
            "avg_net Rs-1,715.82, avg held 125.0 min. NOT VIABLE (< PFNET_LIVE_FLOOR)."
        ),
        notes=(
            "FVG 3rd-candle valid retest, baseline params only, recorded per register-every-variant rule. "
            "Candle-size sweep, parameter grid and opposite-direction comparison still owed (backlog B-16/B-17/B-40/B-33/B-11)."
        ),
    ),

    StrategyDef(
        name="snd_zone__supply_retest__short__5m__ap14_bb0d5_bc1_cf3_enlimit_proximal_ex1d5_mh60_rt1_za200_rr2d0_sp0d25__v1",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.SHORT_SELL,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.052, pfgross=1.684, win_rate_pct=8.69, n_trades=15110, avg_held_hrs=68.8 / 60,
            avg_net_inr=-1365.72,
            universe="full_2680 (2642/2688 fetched)",
            run_ref="snd-zone-full-universe-research.yml run 37436620518 (2026-10-06, 5m/60d, SHORT, calls the REAL main.py scan function)",
        ),
        source=".github/workflows/snd-zone-full-universe-research.yml (real main.py scan/entry/exit functions)",
        evidence=(
            "Run 37436620518 baseline: PFnet 0.052, PFgross 1.684, n=15,110, win 8.69%, "
            "avg_net Rs-1,365.72, avg held 68.8 min. NOT VIABLE (< PFNET_LIVE_FLOOR)."
        ),
        notes=(
            "Supply & Demand supply retest, baseline params only, recorded per register-every-variant rule. "
            "Candle-size sweep, parameter grid and opposite-direction comparison still owed (backlog B-16/B-17/B-40/B-33/B-11)."
        ),
    ),

    StrategyDef(
        name="snd_zone__demand_retest__long__5m__ap14_bb0d5_bc1_cf3_enlimit_proximal_ex1d5_mh60_rt1_za200_rr2d0_sp0d25__v1",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.BUY,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.046, pfgross=1.197, win_rate_pct=7.66, n_trades=20278, avg_held_hrs=73.2 / 60,
            avg_net_inr=-1505.39,
            universe="full_2680 (2642/2688 fetched)",
            run_ref="snd-zone-full-universe-research.yml run 37436620518 (2026-10-06, 5m/60d, LONG, calls the REAL main.py scan function)",
        ),
        source=".github/workflows/snd-zone-full-universe-research.yml (real main.py scan/entry/exit functions)",
        evidence=(
            "Run 37436620518 baseline: PFnet 0.046, PFgross 1.197, n=20,278, win 7.66%, "
            "avg_net Rs-1,505.39, avg held 73.2 min. NOT VIABLE (< PFNET_LIVE_FLOOR)."
        ),
        notes=(
            "Supply & Demand demand retest, baseline params only, recorded per register-every-variant rule. "
            "Candle-size sweep, parameter grid and opposite-direction comparison still owed (backlog B-16/B-17/B-40/B-33/B-11)."
        ),
    ),

    StrategyDef(
        name="dmi_adx__adx_gate__short__5m__am20d0_tl20d0_mh60_p14_rr2d0_sa2d0__v1",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.SHORT_SELL,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.148, pfgross=1.067, win_rate_pct=21.34, n_trades=8448, avg_held_hrs=139.1 / 60,
            avg_net_inr=-1447.59,
            universe="full_2680 (2642/2688 fetched)",
            run_ref="dmi-adx-full-universe-research.yml run 37436623456 (2026-10-06, 5m/60d, SHORT, calls the REAL main.py scan function)",
        ),
        source=".github/workflows/dmi-adx-full-universe-research.yml (real main.py scan/entry/exit functions)",
        evidence=(
            "Run 37436623456 baseline: PFnet 0.148, PFgross 1.067, n=8,448, win 21.34%, "
            "avg_net Rs-1,447.59, avg held 139.1 min. NOT VIABLE (< PFNET_LIVE_FLOOR)."
        ),
        notes=(
            "DMI/ADX adx_gate, baseline params only, recorded per register-every-variant rule. "
            "Candle-size sweep, parameter grid and opposite-direction comparison still owed (backlog B-16/B-17/B-40/B-33/B-11)."
        ),
    ),

    StrategyDef(
        name="dmi_adx__adx_gate__long__5m__am20d0_tl20d0_mh60_p14_rr2d0_sa2d0__v1",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.BUY,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.136, pfgross=0.788, win_rate_pct=19.7, n_trades=14338, avg_held_hrs=110.8 / 60,
            avg_net_inr=-1680.18,
            universe="full_2680 (2642/2688 fetched)",
            run_ref="dmi-adx-full-universe-research.yml run 37436623456 (2026-10-06, 5m/60d, LONG, calls the REAL main.py scan function)",
        ),
        source=".github/workflows/dmi-adx-full-universe-research.yml (real main.py scan/entry/exit functions)",
        evidence=(
            "Run 37436623456 baseline: PFnet 0.136, PFgross 0.788, n=14,338, win 19.7%, "
            "avg_net Rs-1,680.18, avg held 110.8 min. NOT VIABLE (< PFNET_LIVE_FLOOR)."
        ),
        notes=(
            "DMI/ADX adx_gate, baseline params only, recorded per register-every-variant rule. "
            "Candle-size sweep, parameter grid and opposite-direction comparison still owed (backlog B-16/B-17/B-40/B-33/B-11)."
        ),
    ),

    StrategyDef(
        name="dmi_adx__cross__short__5m__am20d0_tl20d0_mh60_p14_rr2d0_sa2d0__v1",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.SHORT_SELL,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.127, pfgross=0.959, win_rate_pct=18.54, n_trades=204289, avg_held_hrs=166.9 / 60,
            avg_net_inr=-1470.68,
            universe="full_2680 (2642/2688 fetched)",
            run_ref="dmi-adx-full-universe-research.yml run 37436623456 (2026-10-06, 5m/60d, SHORT, calls the REAL main.py scan function)",
        ),
        source=".github/workflows/dmi-adx-full-universe-research.yml (real main.py scan/entry/exit functions)",
        evidence=(
            "Run 37436623456 baseline: PFnet 0.127, PFgross 0.959, n=204,289, win 18.54%, "
            "avg_net Rs-1,470.68, avg held 166.9 min. NOT VIABLE (< PFNET_LIVE_FLOOR)."
        ),
        notes=(
            "DMI/ADX cross, baseline params only, recorded per register-every-variant rule. "
            "Candle-size sweep, parameter grid and opposite-direction comparison still owed (backlog B-16/B-17/B-40/B-33/B-11)."
        ),
    ),

    StrategyDef(
        name="dmi_adx__adx_turn__long__5m__am20d0_tl20d0_mh60_p14_rr2d0_sa2d0__v1",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.BUY,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.111, pfgross=0.78, win_rate_pct=16.64, n_trades=55639, avg_held_hrs=127.6 / 60,
            avg_net_inr=-1664.98,
            universe="full_2680 (2642/2688 fetched)",
            run_ref="dmi-adx-full-universe-research.yml run 37436623456 (2026-10-06, 5m/60d, LONG, calls the REAL main.py scan function)",
        ),
        source=".github/workflows/dmi-adx-full-universe-research.yml (real main.py scan/entry/exit functions)",
        evidence=(
            "Run 37436623456 baseline: PFnet 0.111, PFgross 0.78, n=55,639, win 16.64%, "
            "avg_net Rs-1,664.98, avg held 127.6 min. NOT VIABLE (< PFNET_LIVE_FLOOR)."
        ),
        notes=(
            "DMI/ADX adx_turn, baseline params only, recorded per register-every-variant rule. "
            "Candle-size sweep, parameter grid and opposite-direction comparison still owed (backlog B-16/B-17/B-40/B-33/B-11)."
        ),
    ),

    StrategyDef(
        name="dmi_adx__adx_turn__short__5m__am20d0_tl20d0_mh60_p14_rr2d0_sa2d0__v1",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.SHORT_SELL,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.103, pfgross=1.073, win_rate_pct=16.67, n_trades=67275, avg_held_hrs=137.2 / 60,
            avg_net_inr=-1469.3,
            universe="full_2680 (2642/2688 fetched)",
            run_ref="dmi-adx-full-universe-research.yml run 37436623456 (2026-10-06, 5m/60d, SHORT, calls the REAL main.py scan function)",
        ),
        source=".github/workflows/dmi-adx-full-universe-research.yml (real main.py scan/entry/exit functions)",
        evidence=(
            "Run 37436623456 baseline: PFnet 0.103, PFgross 1.073, n=67,275, win 16.67%, "
            "avg_net Rs-1,469.3, avg held 137.2 min. NOT VIABLE (< PFNET_LIVE_FLOOR)."
        ),
        notes=(
            "DMI/ADX adx_turn, baseline params only, recorded per register-every-variant rule. "
            "Candle-size sweep, parameter grid and opposite-direction comparison still owed (backlog B-16/B-17/B-40/B-33/B-11)."
        ),
    ),

    StrategyDef(
        name="dmi_adx__cross__long__5m__am20d0_tl20d0_mh60_p14_rr2d0_sa2d0__v1",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.BUY,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.093, pfgross=0.651, win_rate_pct=14.57, n_trades=221736, avg_held_hrs=140.8 / 60,
            avg_net_inr=-1729.74,
            universe="full_2680 (2642/2688 fetched)",
            run_ref="dmi-adx-full-universe-research.yml run 37436623456 (2026-10-06, 5m/60d, LONG, calls the REAL main.py scan function)",
        ),
        source=".github/workflows/dmi-adx-full-universe-research.yml (real main.py scan/entry/exit functions)",
        evidence=(
            "Run 37436623456 baseline: PFnet 0.093, PFgross 0.651, n=221,736, win 14.57%, "
            "avg_net Rs-1,729.74, avg held 140.8 min. NOT VIABLE (< PFNET_LIVE_FLOOR)."
        ),
        notes=(
            "DMI/ADX cross, baseline params only, recorded per register-every-variant rule. "
            "Candle-size sweep, parameter grid and opposite-direction comparison still owed (backlog B-16/B-17/B-40/B-33/B-11)."
        ),
    ),

    StrategyDef(
        name="box_theory__zone_touch__bidirectional__5m__tol15_wick2d0__v1",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.BIDIRECTIONAL,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.134, pfgross=0.845, win_rate_pct=10.36, n_trades=219377, avg_held_hrs=129.1 / 60,
            avg_net_inr=-1686.11,
            universe="full_2680 (2642/2688 fetched)",
            run_ref="box-theory-variant-sweep-research.yml run 37408733557 (2026-10-06, 5m/60d, BOTH directions pooled, research-stage reimplementation)",
        ),
        source=".github/workflows/box-theory-variant-sweep-research.yml (research-stage Box Theory implementation; workflow variant tag box_theory__tol15_wick2.0)",
        evidence=(
            "Run 37408733557 variant tol15_wick2.0: PFnet 0.134, PFgross 0.845, n=219,377, win 10.36%, "
            "avg_net Rs-1,686.11, avg held 129.1 min. Per side: long PFnet 0.102, short PFnet 0.191. "
            "NOT VIABLE (< PFNET_LIVE_FLOOR) in either direction."
        ),
        notes=(
            "Box Theory step-1 variant, recorded per register-every-variant rule; metrics are the pooled "
            "both-direction run (per-side PFgross/avg_net not printed by the workflow, so per-side rows "
            "are not split out - never guessed). Candle-size sweep and per-direction split owed (B-16/B-17)."
        ),
    ),

    StrategyDef(
        name="box_theory__zone_touch__bidirectional__5m__tol20_wick2d0__v1",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.BIDIRECTIONAL,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.133, pfgross=0.834, win_rate_pct=10.35, n_trades=238730, avg_held_hrs=126.5 / 60,
            avg_net_inr=-1692.74,
            universe="full_2680 (2642/2688 fetched)",
            run_ref="box-theory-variant-sweep-research.yml run 37408733557 (2026-10-06, 5m/60d, BOTH directions pooled, research-stage reimplementation)",
        ),
        source=".github/workflows/box-theory-variant-sweep-research.yml (research-stage Box Theory implementation; workflow variant tag box_theory__tol20_wick2.0)",
        evidence=(
            "Run 37408733557 variant tol20_wick2.0: PFnet 0.133, PFgross 0.834, n=238,730, win 10.35%, "
            "avg_net Rs-1,692.74, avg held 126.5 min. Per side: long PFnet 0.101, short PFnet 0.19. "
            "NOT VIABLE (< PFNET_LIVE_FLOOR) in either direction."
        ),
        notes=(
            "Box Theory step-1 variant, recorded per register-every-variant rule; metrics are the pooled "
            "both-direction run (per-side PFgross/avg_net not printed by the workflow, so per-side rows "
            "are not split out - never guessed). Candle-size sweep and per-direction split owed (B-16/B-17)."
        ),
    ),

    StrategyDef(
        name="box_theory__zone_touch__bidirectional__5m__tol25_wick2d5__v1",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.BIDIRECTIONAL,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.129, pfgross=0.815, win_rate_pct=10.11, n_trades=242407, avg_held_hrs=122.8 / 60,
            avg_net_inr=-1704.6,
            universe="full_2680 (2642/2688 fetched)",
            run_ref="box-theory-variant-sweep-research.yml run 37408733557 (2026-10-06, 5m/60d, BOTH directions pooled, research-stage reimplementation)",
        ),
        source=".github/workflows/box-theory-variant-sweep-research.yml (research-stage Box Theory implementation; workflow variant tag box_theory__tol25_wick2.5)",
        evidence=(
            "Run 37408733557 variant tol25_wick2.5: PFnet 0.129, PFgross 0.815, n=242,407, win 10.11%, "
            "avg_net Rs-1,704.6, avg held 122.8 min. Per side: long PFnet 0.098, short PFnet 0.183. "
            "NOT VIABLE (< PFNET_LIVE_FLOOR) in either direction."
        ),
        notes=(
            "Box Theory step-1 variant, recorded per register-every-variant rule; metrics are the pooled "
            "both-direction run (per-side PFgross/avg_net not printed by the workflow, so per-side rows "
            "are not split out - never guessed). Candle-size sweep and per-direction split owed (B-16/B-17)."
        ),
    ),

    StrategyDef(
        name="box_theory__zone_touch__bidirectional__5m__tol15_wick2d5__v1",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.BIDIRECTIONAL,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.132, pfgross=0.839, win_rate_pct=10.17, n_trades=205206, avg_held_hrs=128.0 / 60,
            avg_net_inr=-1689.85,
            universe="full_2680 (2642/2688 fetched)",
            run_ref="box-theory-variant-sweep-research.yml run 37408733557 (2026-10-06, 5m/60d, BOTH directions pooled, research-stage reimplementation)",
        ),
        source=".github/workflows/box-theory-variant-sweep-research.yml (research-stage Box Theory implementation; workflow variant tag box_theory__tol15_wick2.5)",
        evidence=(
            "Run 37408733557 variant tol15_wick2.5: PFnet 0.132, PFgross 0.839, n=205,206, win 10.17%, "
            "avg_net Rs-1,689.85, avg held 128.0 min. Per side: long PFnet 0.101, short PFnet 0.187. "
            "NOT VIABLE (< PFNET_LIVE_FLOOR) in either direction."
        ),
        notes=(
            "Box Theory step-1 variant, recorded per register-every-variant rule; metrics are the pooled "
            "both-direction run (per-side PFgross/avg_net not printed by the workflow, so per-side rows "
            "are not split out - never guessed). Candle-size sweep and per-direction split owed (B-16/B-17)."
        ),
    ),

    StrategyDef(
        name="box_theory__zone_touch__bidirectional__5m__tol25_wick2d0__v1",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.BIDIRECTIONAL,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.132, pfgross=0.823, win_rate_pct=10.32, n_trades=258092, avg_held_hrs=123.9 / 60,
            avg_net_inr=-1700.17,
            universe="full_2680 (2642/2688 fetched)",
            run_ref="box-theory-variant-sweep-research.yml run 37408733557 (2026-10-06, 5m/60d, BOTH directions pooled, research-stage reimplementation)",
        ),
        source=".github/workflows/box-theory-variant-sweep-research.yml (research-stage Box Theory implementation; workflow variant tag box_theory__tol25_wick2.0)",
        evidence=(
            "Run 37408733557 variant tol25_wick2.0: PFnet 0.132, PFgross 0.823, n=258,092, win 10.32%, "
            "avg_net Rs-1,700.17, avg held 123.9 min. Per side: long PFnet 0.1, short PFnet 0.189. "
            "NOT VIABLE (< PFNET_LIVE_FLOOR) in either direction."
        ),
        notes=(
            "Box Theory step-1 variant, recorded per register-every-variant rule; metrics are the pooled "
            "both-direction run (per-side PFgross/avg_net not printed by the workflow, so per-side rows "
            "are not split out - never guessed). Candle-size sweep and per-direction split owed (B-16/B-17)."
        ),
    ),

    StrategyDef(
        name="box_theory__zone_touch__bidirectional__5m__tol20_wick2d5__v1",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.BIDIRECTIONAL,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.13, pfgross=0.826, win_rate_pct=10.13, n_trades=223771, avg_held_hrs=125.2 / 60,
            avg_net_inr=-1697.51,
            universe="full_2680 (2642/2688 fetched)",
            run_ref="box-theory-variant-sweep-research.yml run 37408733557 (2026-10-06, 5m/60d, BOTH directions pooled, research-stage reimplementation)",
        ),
        source=".github/workflows/box-theory-variant-sweep-research.yml (research-stage Box Theory implementation; workflow variant tag box_theory__tol20_wick2.5)",
        evidence=(
            "Run 37408733557 variant tol20_wick2.5: PFnet 0.13, PFgross 0.826, n=223,771, win 10.13%, "
            "avg_net Rs-1,697.51, avg held 125.2 min. Per side: long PFnet 0.099, short PFnet 0.185. "
            "NOT VIABLE (< PFNET_LIVE_FLOOR) in either direction."
        ),
        notes=(
            "Box Theory step-1 variant, recorded per register-every-variant rule; metrics are the pooled "
            "both-direction run (per-side PFgross/avg_net not printed by the workflow, so per-side rows "
            "are not split out - never guessed). Candle-size sweep and per-direction split owed (B-16/B-17)."
        ),
    ),

    StrategyDef(
        name="box_theory__zone_touch__bidirectional__5m__tol15_wick1d5__v1",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.BIDIRECTIONAL,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.138, pfgross=0.851, win_rate_pct=10.64, n_trades=233145, avg_held_hrs=130.6 / 60,
            avg_net_inr=-1682.96,
            universe="full_2680 (2642/2688 fetched)",
            run_ref="box-theory-variant-sweep-research.yml run 37408733557 (2026-10-06, 5m/60d, BOTH directions pooled, research-stage reimplementation)",
        ),
        source=".github/workflows/box-theory-variant-sweep-research.yml (research-stage Box Theory implementation; workflow variant tag box_theory__tol15_wick1.5)",
        evidence=(
            "Run 37408733557 variant tol15_wick1.5: PFnet 0.138, PFgross 0.851, n=233,145, win 10.64%, "
            "avg_net Rs-1,682.96, avg held 130.6 min. Per side: long PFnet 0.105, short PFnet 0.197. "
            "NOT VIABLE (< PFNET_LIVE_FLOOR) in either direction."
        ),
        notes=(
            "Box Theory step-1 variant, recorded per register-every-variant rule; metrics are the pooled "
            "both-direction run (per-side PFgross/avg_net not printed by the workflow, so per-side rows "
            "are not split out - never guessed). Candle-size sweep and per-direction split owed (B-16/B-17)."
        ),
    ),

    StrategyDef(
        name="box_theory__zone_touch__bidirectional__5m__tol25_wick1d5__v1",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.BIDIRECTIONAL,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.135, pfgross=0.828, win_rate_pct=10.6, n_trades=273094, avg_held_hrs=125.4 / 60,
            avg_net_inr=-1697.53,
            universe="full_2680 (2642/2688 fetched)",
            run_ref="box-theory-variant-sweep-research.yml run 37408733557 (2026-10-06, 5m/60d, BOTH directions pooled, research-stage reimplementation)",
        ),
        source=".github/workflows/box-theory-variant-sweep-research.yml (research-stage Box Theory implementation; workflow variant tag box_theory__tol25_wick1.5)",
        evidence=(
            "Run 37408733557 variant tol25_wick1.5: PFnet 0.135, PFgross 0.828, n=273,094, win 10.6%, "
            "avg_net Rs-1,697.53, avg held 125.4 min. Per side: long PFnet 0.102, short PFnet 0.194. "
            "NOT VIABLE (< PFNET_LIVE_FLOOR) in either direction."
        ),
        notes=(
            "Box Theory step-1 variant, recorded per register-every-variant rule; metrics are the pooled "
            "both-direction run (per-side PFgross/avg_net not printed by the workflow, so per-side rows "
            "are not split out - never guessed). Candle-size sweep and per-direction split owed (B-16/B-17)."
        ),
    ),

    StrategyDef(
        name="box_theory__zone_touch__bidirectional__5m__tol20_wick1d5__v1",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.BIDIRECTIONAL,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.137, pfgross=0.84, win_rate_pct=10.63, n_trades=253307, avg_held_hrs=127.8 / 60,
            avg_net_inr=-1689.98,
            universe="full_2680 (2642/2688 fetched)",
            run_ref="box-theory-variant-sweep-research.yml run 37408733557 (2026-10-06, 5m/60d, BOTH directions pooled, research-stage reimplementation)",
        ),
        source=".github/workflows/box-theory-variant-sweep-research.yml (research-stage Box Theory implementation; workflow variant tag box_theory__tol20_wick1.5)",
        evidence=(
            "Run 37408733557 variant tol20_wick1.5: PFnet 0.137, PFgross 0.84, n=253,307, win 10.63%, "
            "avg_net Rs-1,689.98, avg held 127.8 min. Per side: long PFnet 0.103, short PFnet 0.196. "
            "NOT VIABLE (< PFNET_LIVE_FLOOR) in either direction."
        ),
        notes=(
            "Box Theory step-1 variant, recorded per register-every-variant rule; metrics are the pooled "
            "both-direction run (per-side PFgross/avg_net not printed by the workflow, so per-side rows "
            "are not split out - never guessed). Candle-size sweep and per-direction split owed (B-16/B-17)."
        ),
    ),

    StrategyDef(
        name="parabolic_sar__reversal__bidirectional__5m__afinit0d01_afmax0d3__v1",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.BIDIRECTIONAL,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.113, pfgross=0.852, win_rate_pct=11.97, n_trades=492386, avg_held_hrs=133.1 / 60,
            avg_net_inr=-1493.17,
            universe="full_2680 (2642/2688 fetched)",
            run_ref="parabolic-sar-variant-sweep-research.yml run 37408735190 (2026-10-06, 5m/60d, BOTH directions pooled, research-stage reimplementation)",
        ),
        source=".github/workflows/parabolic-sar-variant-sweep-research.yml (research-stage Parabolic SAR implementation; workflow variant tag parabolic_sar__afinit0.01_afmax0.3)",
        evidence=(
            "Run 37408735190 variant afinit0.01_afmax0.3: PFnet 0.113, PFgross 0.852, n=492,386, win 11.97%, "
            "avg_net Rs-1,493.17, avg held 133.1 min. Per side: long PFnet 0.11, short PFnet 0.116. "
            "NOT VIABLE (< PFNET_LIVE_FLOOR) in either direction."
        ),
        notes=(
            "Parabolic SAR step-1 variant, recorded per register-every-variant rule; metrics are the pooled "
            "both-direction run (per-side PFgross/avg_net not printed by the workflow, so per-side rows "
            "are not split out - never guessed). Candle-size sweep and per-direction split owed (B-16/B-17)."
        ),
    ),

    StrategyDef(
        name="parabolic_sar__reversal__bidirectional__5m__afinit0d03_afmax0d1__v1",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.BIDIRECTIONAL,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.071, pfgross=0.738, win_rate_pct=8.08, n_trades=882374, avg_held_hrs=78.4 / 60,
            avg_net_inr=-1615.44,
            universe="full_2680 (2642/2688 fetched)",
            run_ref="parabolic-sar-variant-sweep-research.yml run 37408735190 (2026-10-06, 5m/60d, BOTH directions pooled, research-stage reimplementation)",
        ),
        source=".github/workflows/parabolic-sar-variant-sweep-research.yml (research-stage Parabolic SAR implementation; workflow variant tag parabolic_sar__afinit0.03_afmax0.1)",
        evidence=(
            "Run 37408735190 variant afinit0.03_afmax0.1: PFnet 0.071, PFgross 0.738, n=882,374, win 8.08%, "
            "avg_net Rs-1,615.44, avg held 78.4 min. Per side: long PFnet 0.073, short PFnet 0.069. "
            "NOT VIABLE (< PFNET_LIVE_FLOOR) in either direction."
        ),
        notes=(
            "Parabolic SAR step-1 variant, recorded per register-every-variant rule; metrics are the pooled "
            "both-direction run (per-side PFgross/avg_net not printed by the workflow, so per-side rows "
            "are not split out - never guessed). Candle-size sweep and per-direction split owed (B-16/B-17)."
        ),
    ),

    StrategyDef(
        name="parabolic_sar__reversal__bidirectional__5m__afinit0d03_afmax0d3__v1",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.BIDIRECTIONAL,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.063, pfgross=0.741, win_rate_pct=7.6, n_trades=1009860, avg_held_hrs=68.9 / 60,
            avg_net_inr=-1626.38,
            universe="full_2680 (2642/2688 fetched)",
            run_ref="parabolic-sar-variant-sweep-research.yml run 37408735190 (2026-10-06, 5m/60d, BOTH directions pooled, research-stage reimplementation)",
        ),
        source=".github/workflows/parabolic-sar-variant-sweep-research.yml (research-stage Parabolic SAR implementation; workflow variant tag parabolic_sar__afinit0.03_afmax0.3)",
        evidence=(
            "Run 37408735190 variant afinit0.03_afmax0.3: PFnet 0.063, PFgross 0.741, n=1,009,860, win 7.6%, "
            "avg_net Rs-1,626.38, avg held 68.9 min. Per side: long PFnet 0.067, short PFnet 0.059. "
            "NOT VIABLE (< PFNET_LIVE_FLOOR) in either direction."
        ),
        notes=(
            "Parabolic SAR step-1 variant, recorded per register-every-variant rule; metrics are the pooled "
            "both-direction run (per-side PFgross/avg_net not printed by the workflow, so per-side rows "
            "are not split out - never guessed). Candle-size sweep and per-direction split owed (B-16/B-17)."
        ),
    ),

    StrategyDef(
        name="parabolic_sar__reversal__bidirectional__5m__afinit0d01_afmax0d1__v1",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.BIDIRECTIONAL,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.114, pfgross=0.852, win_rate_pct=11.99, n_trades=488066, avg_held_hrs=134.2 / 60,
            avg_net_inr=-1491.26,
            universe="full_2680 (2642/2688 fetched)",
            run_ref="parabolic-sar-variant-sweep-research.yml run 37408735190 (2026-10-06, 5m/60d, BOTH directions pooled, research-stage reimplementation)",
        ),
        source=".github/workflows/parabolic-sar-variant-sweep-research.yml (research-stage Parabolic SAR implementation; workflow variant tag parabolic_sar__afinit0.01_afmax0.1)",
        evidence=(
            "Run 37408735190 variant afinit0.01_afmax0.1: PFnet 0.114, PFgross 0.852, n=488,066, win 11.99%, "
            "avg_net Rs-1,491.26, avg held 134.2 min. Per side: long PFnet 0.111, short PFnet 0.117. "
            "NOT VIABLE (< PFNET_LIVE_FLOOR) in either direction."
        ),
        notes=(
            "Parabolic SAR step-1 variant, recorded per register-every-variant rule; metrics are the pooled "
            "both-direction run (per-side PFgross/avg_net not printed by the workflow, so per-side rows "
            "are not split out - never guessed). Candle-size sweep and per-direction split owed (B-16/B-17)."
        ),
    ),

    StrategyDef(
        name="parabolic_sar__reversal__bidirectional__5m__afinit0d02_afmax0d3__v1",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.BIDIRECTIONAL,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.078, pfgross=0.782, win_rate_pct=9.07, n_trades=774717, avg_held_hrs=88.1 / 60,
            avg_net_inr=-1585.38,
            universe="full_2680 (2642/2688 fetched)",
            run_ref="parabolic-sar-variant-sweep-research.yml run 37408735190 (2026-10-06, 5m/60d, BOTH directions pooled, research-stage reimplementation)",
        ),
        source=".github/workflows/parabolic-sar-variant-sweep-research.yml (research-stage Parabolic SAR implementation; workflow variant tag parabolic_sar__afinit0.02_afmax0.3)",
        evidence=(
            "Run 37408735190 variant afinit0.02_afmax0.3: PFnet 0.078, PFgross 0.782, n=774,717, win 9.07%, "
            "avg_net Rs-1,585.38, avg held 88.1 min. Per side: long PFnet 0.081, short PFnet 0.076. "
            "NOT VIABLE (< PFNET_LIVE_FLOOR) in either direction."
        ),
        notes=(
            "Parabolic SAR step-1 variant, recorded per register-every-variant rule; metrics are the pooled "
            "both-direction run (per-side PFgross/avg_net not printed by the workflow, so per-side rows "
            "are not split out - never guessed). Candle-size sweep and per-direction split owed (B-16/B-17)."
        ),
    ),

    StrategyDef(
        name="parabolic_sar__reversal__bidirectional__5m__afinit0d02_afmax0d2__v1",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.BIDIRECTIONAL,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.078, pfgross=0.782, win_rate_pct=9.07, n_trades=774826, avg_held_hrs=88.2 / 60,
            avg_net_inr=-1585.39,
            universe="full_2680 (2642/2688 fetched)",
            run_ref="parabolic-sar-variant-sweep-research.yml run 37408735190 (2026-10-06, 5m/60d, BOTH directions pooled, research-stage reimplementation)",
        ),
        source=".github/workflows/parabolic-sar-variant-sweep-research.yml (research-stage Parabolic SAR implementation; workflow variant tag parabolic_sar__afinit0.02_afmax0.2)",
        evidence=(
            "Run 37408735190 variant afinit0.02_afmax0.2: PFnet 0.078, PFgross 0.782, n=774,826, win 9.07%, "
            "avg_net Rs-1,585.39, avg held 88.2 min. Per side: long PFnet 0.081, short PFnet 0.076. "
            "NOT VIABLE (< PFNET_LIVE_FLOOR) in either direction."
        ),
        notes=(
            "Parabolic SAR step-1 variant, recorded per register-every-variant rule; metrics are the pooled "
            "both-direction run (per-side PFgross/avg_net not printed by the workflow, so per-side rows "
            "are not split out - never guessed). Candle-size sweep and per-direction split owed (B-16/B-17)."
        ),
    ),

    StrategyDef(
        name="parabolic_sar__reversal__bidirectional__5m__afinit0d01_afmax0d2__v1",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.BIDIRECTIONAL,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.113, pfgross=0.852, win_rate_pct=11.97, n_trades=492370, avg_held_hrs=133.1 / 60,
            avg_net_inr=-1493.14,
            universe="full_2680 (2642/2688 fetched)",
            run_ref="parabolic-sar-variant-sweep-research.yml run 37408735190 (2026-10-06, 5m/60d, BOTH directions pooled, research-stage reimplementation)",
        ),
        source=".github/workflows/parabolic-sar-variant-sweep-research.yml (research-stage Parabolic SAR implementation; workflow variant tag parabolic_sar__afinit0.01_afmax0.2)",
        evidence=(
            "Run 37408735190 variant afinit0.01_afmax0.2: PFnet 0.113, PFgross 0.852, n=492,370, win 11.97%, "
            "avg_net Rs-1,493.14, avg held 133.1 min. Per side: long PFnet 0.111, short PFnet 0.116. "
            "NOT VIABLE (< PFNET_LIVE_FLOOR) in either direction."
        ),
        notes=(
            "Parabolic SAR step-1 variant, recorded per register-every-variant rule; metrics are the pooled "
            "both-direction run (per-side PFgross/avg_net not printed by the workflow, so per-side rows "
            "are not split out - never guessed). Candle-size sweep and per-direction split owed (B-16/B-17)."
        ),
    ),

    StrategyDef(
        name="parabolic_sar__reversal__bidirectional__5m__afinit0d02_afmax0d1__v1",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.BIDIRECTIONAL,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.083, pfgross=0.78, win_rate_pct=9.25, n_trades=731065, avg_held_hrs=93.2 / 60,
            avg_net_inr=-1578.86,
            universe="full_2680 (2642/2688 fetched)",
            run_ref="parabolic-sar-variant-sweep-research.yml run 37408735190 (2026-10-06, 5m/60d, BOTH directions pooled, research-stage reimplementation)",
        ),
        source=".github/workflows/parabolic-sar-variant-sweep-research.yml (research-stage Parabolic SAR implementation; workflow variant tag parabolic_sar__afinit0.02_afmax0.1)",
        evidence=(
            "Run 37408735190 variant afinit0.02_afmax0.1: PFnet 0.083, PFgross 0.78, n=731,065, win 9.25%, "
            "avg_net Rs-1,578.86, avg held 93.2 min. Per side: long PFnet 0.083, short PFnet 0.082. "
            "NOT VIABLE (< PFNET_LIVE_FLOOR) in either direction."
        ),
        notes=(
            "Parabolic SAR step-1 variant, recorded per register-every-variant rule; metrics are the pooled "
            "both-direction run (per-side PFgross/avg_net not printed by the workflow, so per-side rows "
            "are not split out - never guessed). Candle-size sweep and per-direction split owed (B-16/B-17)."
        ),
    ),

    StrategyDef(
        name="parabolic_sar__reversal__bidirectional__5m__afinit0d03_afmax0d2__v1",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.BIDIRECTIONAL,),
        timeframe="5m",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.063, pfgross=0.74, win_rate_pct=7.6, n_trades=1000552, avg_held_hrs=69.5 / 60,
            avg_net_inr=-1625.83,
            universe="full_2680 (2642/2688 fetched)",
            run_ref="parabolic-sar-variant-sweep-research.yml run 37408735190 (2026-10-06, 5m/60d, BOTH directions pooled, research-stage reimplementation)",
        ),
        source=".github/workflows/parabolic-sar-variant-sweep-research.yml (research-stage Parabolic SAR implementation; workflow variant tag parabolic_sar__afinit0.03_afmax0.2)",
        evidence=(
            "Run 37408735190 variant afinit0.03_afmax0.2: PFnet 0.063, PFgross 0.74, n=1,000,552, win 7.6%, "
            "avg_net Rs-1,625.83, avg held 69.5 min. Per side: long PFnet 0.067, short PFnet 0.06. "
            "NOT VIABLE (< PFNET_LIVE_FLOOR) in either direction."
        ),
        notes=(
            "Parabolic SAR step-1 variant, recorded per register-every-variant rule; metrics are the pooled "
            "both-direction run (per-side PFgross/avg_net not printed by the workflow, so per-side rows "
            "are not split out - never guessed). Candle-size sweep and per-direction split owed (B-16/B-17)."
        ),
    ),

    StrategyDef(
        name="gap_up_fade__fade__short__15m__atr0d5__v1",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.SHORT_SELL,),
        timeframe="15m",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.378, pfgross=1.301, win_rate_pct=24.27, n_trades=17937, avg_held_hrs=409.7 / 60,
            avg_net_inr=-511.26,
            universe="full_2680 (2628/2688 fetched)",
            run_ref="gap-up-fade-short-atr-mult-sweep-research.yml run 37512478604 (2026-10-07 IST, 15m/60d, sample_every=1, real main.py gap_up_fade functions)",
        ),
        source="main.py (gap_up_fade_entry_signal_short/gap_up_fade_exit_reason_short) via .github/workflows/gap-up-fade-short-atr-mult-sweep-research.yml",
        evidence=(
            "Run 37512478604 at 15m, ATR stop multiple 0.5: PFnet 0.378, PFgross 1.301, n=17,937, win 24.27%, "
            "avg_net Rs-511.26, avg held 409.7 min. NOT VIABLE (< PFNET_LIVE_FLOOR). Same shape as 5m: "
            "max_hold_timeout exits profitable, trail_stop_hit exits lose."
        ),
        notes=(
            "Gap-Up Fade short, 15m candle cell of the ATR sweep; bar-count constants mean 15m bars here. "
            "Registered per register-every-variant rule (pass or fail). 1h/1d still owed, 4h resample not built."
        ),
    ),

    StrategyDef(
        name="gap_up_fade__fade__short__15m__atr1d0__v1",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.SHORT_SELL,),
        timeframe="15m",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.435, pfgross=1.334, win_rate_pct=27.21, n_trades=14756, avg_held_hrs=499.7 / 60,
            avg_net_inr=-477.99,
            universe="full_2680 (2628/2688 fetched)",
            run_ref="gap-up-fade-short-atr-mult-sweep-research.yml run 37512478604 (2026-10-07 IST, 15m/60d, sample_every=1, real main.py gap_up_fade functions)",
        ),
        source="main.py (gap_up_fade_entry_signal_short/gap_up_fade_exit_reason_short) via .github/workflows/gap-up-fade-short-atr-mult-sweep-research.yml",
        evidence=(
            "Run 37512478604 at 15m, ATR stop multiple 1.0: PFnet 0.435, PFgross 1.334, n=14,756, win 27.21%, "
            "avg_net Rs-477.99, avg held 499.7 min. NOT VIABLE (< PFNET_LIVE_FLOOR). Same shape as 5m: "
            "max_hold_timeout exits profitable, trail_stop_hit exits lose."
        ),
        notes=(
            "Gap-Up Fade short, 15m candle cell of the ATR sweep; bar-count constants mean 15m bars here. "
            "Registered per register-every-variant rule (pass or fail). 1h/1d still owed, 4h resample not built."
        ),
    ),

    StrategyDef(
        name="gap_up_fade__fade__short__15m__atr1d5__v1",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.SHORT_SELL,),
        timeframe="15m",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.459, pfgross=1.333, win_rate_pct=28.98, n_trades=13098, avg_held_hrs=566.4 / 60,
            avg_net_inr=-460.08,
            universe="full_2680 (2628/2688 fetched)",
            run_ref="gap-up-fade-short-atr-mult-sweep-research.yml run 37512478604 (2026-10-07 IST, 15m/60d, sample_every=1, real main.py gap_up_fade functions)",
        ),
        source="main.py (gap_up_fade_entry_signal_short/gap_up_fade_exit_reason_short) via .github/workflows/gap-up-fade-short-atr-mult-sweep-research.yml",
        evidence=(
            "Run 37512478604 at 15m, ATR stop multiple 1.5: PFnet 0.459, PFgross 1.333, n=13,098, win 28.98%, "
            "avg_net Rs-460.08, avg held 566.4 min. NOT VIABLE (< PFNET_LIVE_FLOOR). Same shape as 5m: "
            "max_hold_timeout exits profitable, trail_stop_hit exits lose."
        ),
        notes=(
            "Gap-Up Fade short, 15m candle cell of the ATR sweep; bar-count constants mean 15m bars here. "
            "Registered per register-every-variant rule (pass or fail). 1h/1d still owed, 4h resample not built."
        ),
    ),

    StrategyDef(
        name="gap_up_fade__fade__short__15m__atr2d0__v1",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.SHORT_SELL,),
        timeframe="15m",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.468, pfgross=1.334, win_rate_pct=29.52, n_trades=12337, avg_held_hrs=603.2 / 60,
            avg_net_inr=-448.22,
            universe="full_2680 (2628/2688 fetched)",
            run_ref="gap-up-fade-short-atr-mult-sweep-research.yml run 37512478604 (2026-10-07 IST, 15m/60d, sample_every=1, real main.py gap_up_fade functions)",
        ),
        source="main.py (gap_up_fade_entry_signal_short/gap_up_fade_exit_reason_short) via .github/workflows/gap-up-fade-short-atr-mult-sweep-research.yml",
        evidence=(
            "Run 37512478604 at 15m, ATR stop multiple 2.0: PFnet 0.468, PFgross 1.334, n=12,337, win 29.52%, "
            "avg_net Rs-448.22, avg held 603.2 min. NOT VIABLE (< PFNET_LIVE_FLOOR). Same shape as 5m: "
            "max_hold_timeout exits profitable, trail_stop_hit exits lose."
        ),
        notes=(
            "Gap-Up Fade short, 15m candle cell of the ATR sweep; bar-count constants mean 15m bars here. "
            "Registered per register-every-variant rule (pass or fail). 1h/1d still owed, 4h resample not built."
        ),
    ),

    StrategyDef(
        name="gap_up_fade__fade__short__15m__atr2d5__v1",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.SHORT_SELL,),
        timeframe="15m",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.47, pfgross=1.325, win_rate_pct=29.49, n_trades=11880, avg_held_hrs=627.6 / 60,
            avg_net_inr=-443.62,
            universe="full_2680 (2628/2688 fetched)",
            run_ref="gap-up-fade-short-atr-mult-sweep-research.yml run 37512478604 (2026-10-07 IST, 15m/60d, sample_every=1, real main.py gap_up_fade functions)",
        ),
        source="main.py (gap_up_fade_entry_signal_short/gap_up_fade_exit_reason_short) via .github/workflows/gap-up-fade-short-atr-mult-sweep-research.yml",
        evidence=(
            "Run 37512478604 at 15m, ATR stop multiple 2.5: PFnet 0.47, PFgross 1.325, n=11,880, win 29.49%, "
            "avg_net Rs-443.62, avg held 627.6 min. NOT VIABLE (< PFNET_LIVE_FLOOR). Same shape as 5m: "
            "max_hold_timeout exits profitable, trail_stop_hit exits lose."
        ),
        notes=(
            "Gap-Up Fade short, 15m candle cell of the ATR sweep; bar-count constants mean 15m bars here. "
            "Registered per register-every-variant rule (pass or fail). 1h/1d still owed, 4h resample not built."
        ),
    ),

    StrategyDef(
        name="gap_up_fade__fade__short__15m__atr3d0__v1",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.SHORT_SELL,),
        timeframe="15m",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.463, pfgross=1.31, win_rate_pct=29.59, n_trades=11659, avg_held_hrs=640.7 / 60,
            avg_net_inr=-446.79,
            universe="full_2680 (2628/2688 fetched)",
            run_ref="gap-up-fade-short-atr-mult-sweep-research.yml run 37512478604 (2026-10-07 IST, 15m/60d, sample_every=1, real main.py gap_up_fade functions)",
        ),
        source="main.py (gap_up_fade_entry_signal_short/gap_up_fade_exit_reason_short) via .github/workflows/gap-up-fade-short-atr-mult-sweep-research.yml",
        evidence=(
            "Run 37512478604 at 15m, ATR stop multiple 3.0: PFnet 0.463, PFgross 1.31, n=11,659, win 29.59%, "
            "avg_net Rs-446.79, avg held 640.7 min. NOT VIABLE (< PFNET_LIVE_FLOOR). Same shape as 5m: "
            "max_hold_timeout exits profitable, trail_stop_hit exits lose."
        ),
        notes=(
            "Gap-Up Fade short, 15m candle cell of the ATR sweep; bar-count constants mean 15m bars here. "
            "Registered per register-every-variant rule (pass or fail). 1h/1d still owed, 4h resample not built."
        ),
    ),

    StrategyDef(
        name="gap_up_fade__fade__short__15m__atr4d0__v1",
        asset_class=AssetClass.EQUITY_INTRADAY,
        categories=(TradeCategory.SHORT_SELL,),
        timeframe="15m",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,
        metrics=Metrics(
            pfnet=0.455, pfgross=1.293, win_rate_pct=29.66, n_trades=11477, avg_held_hrs=651.9 / 60,
            avg_net_inr=-451.55,
            universe="full_2680 (2628/2688 fetched)",
            run_ref="gap-up-fade-short-atr-mult-sweep-research.yml run 37512478604 (2026-10-07 IST, 15m/60d, sample_every=1, real main.py gap_up_fade functions)",
        ),
        source="main.py (gap_up_fade_entry_signal_short/gap_up_fade_exit_reason_short) via .github/workflows/gap-up-fade-short-atr-mult-sweep-research.yml",
        evidence=(
            "Run 37512478604 at 15m, ATR stop multiple 4.0: PFnet 0.455, PFgross 1.293, n=11,477, win 29.66%, "
            "avg_net Rs-451.55, avg held 651.9 min. NOT VIABLE (< PFNET_LIVE_FLOOR). Same shape as 5m: "
            "max_hold_timeout exits profitable, trail_stop_hit exits lose."
        ),
        notes=(
            "Gap-Up Fade short, 15m candle cell of the ATR sweep; bar-count constants mean 15m bars here. "
            "Registered per register-every-variant rule (pass or fail). 1h/1d still owed, 4h resample not built."
        ),
    ),
]


def strategies_by_status(status: StrategyStatus) -> list[StrategyDef]:
    return [s for s in REGISTRY if s.status == status]


def strategies_by_asset_class(asset_class: AssetClass) -> list[StrategyDef]:
    return [s for s in REGISTRY if s.asset_class == asset_class]


def strategies_by_category(category: TradeCategory) -> list[StrategyDef]:
    return [s for s in REGISTRY if category in s.categories]


def _ranked_by_pfnet(pool: list) -> list:
    """Best validated PFnet first; strategies with no metrics yet sort
    last (never crash, never silently outrank a measured result with an
    unmeasured one). Shared by leaderboard() and
    top_strategies_for_monitoring() so both use exactly the same
    ranking - the registry keeps growing, but "what's currently best"
    must mean the same thing everywhere it's asked."""
    return sorted(
        pool,
        key=lambda s: s.metrics.pfnet if s.metrics is not None else float("-inf"),
        reverse=True,
    )


def leaderboard(category: TradeCategory, top_n: int = 5) -> list[dict]:
    """Rank every registered strategy in `category` by validated PFnet,
    best first. Strategies with no metrics yet sort last (never crash,
    never silently outrank a measured result with an unmeasured one).

    Each row carries `viable` explicitly (PFnet >= PFNET_LIVE_FLOOR) so a
    caller can never mistake "ranked #1 in this pool" for "profitable" -
    see this module's own docstring. Returns fewer than `top_n` rows
    when fewer than `top_n` strategies are registered for that category -
    never pads with fabricated entries."""
    ranked = _ranked_by_pfnet(strategies_by_category(category))
    return [
        {
            "rank": i + 1,
            "name": s.name,
            "status": s.status.value,
            "pfnet": s.metrics.pfnet if s.metrics else None,
            "win_rate_pct": s.metrics.win_rate_pct if s.metrics else None,
            "avg_held_hrs": round(s.metrics.avg_held_hrs, 1) if s.metrics and s.metrics.avg_held_hrs is not None else None,
            "n_trades": s.metrics.n_trades if s.metrics else None,
            "universe": s.metrics.universe if s.metrics else None,
            "viable": s.is_viable(),
        }
        for i, s in enumerate(ranked[:top_n])
    ]


def viable_leaderboard(category: TradeCategory, floor: float = PFNET_LIVE_FLOOR) -> list[dict]:
    """Every strategy in `category` that actually clears real breakeven
    (PFnet >= floor), ranked best-first, with NO top-N cap - 2026-09-30,
    explicit user instruction: "There is change in strategy leaderboard.
    Keep only viable ones on trade view... I do not want just top 5, but
    I want all that qualify pfnet >= 1 in backtesting", across all 5
    categories.

    Deliberately a SEPARATE function from leaderboard(), not a change to
    it or to TOP_N_PER_CATEGORY: that constant exists to bound live
    per-stock monitoring cost (see top_strategies_for_monitoring()'s own
    docstring and CLAUDE.md's 2026-09-29 "25 strategy-checks per cycle"
    thumb rule) - an unrelated design goal this dashboard-display change
    must not silently touch. A strategy with no metrics yet (is_viable()
    returns None) is excluded, same as a strategy that fails the floor -
    "qualify" means a validated PFnet >= floor, never an unmeasured one
    treated as passing by default."""
    ranked = _ranked_by_pfnet(strategies_by_category(category))
    viable = [s for s in ranked if s.is_viable(floor) is True]
    return [
        {
            "rank": i + 1,
            "name": s.name,
            "status": s.status.value,
            "pfnet": s.metrics.pfnet if s.metrics else None,
            "win_rate_pct": s.metrics.win_rate_pct if s.metrics else None,
            "avg_held_hrs": round(s.metrics.avg_held_hrs, 1) if s.metrics and s.metrics.avg_held_hrs is not None else None,
            "n_trades": s.metrics.n_trades if s.metrics else None,
            "universe": s.metrics.universe if s.metrics else None,
            "viable": True,
        }
        for i, s in enumerate(viable)
    ]


def all_strategies_info() -> dict:
    """Every registered strategy's own record, keyed by name - unlike
    leaderboard()'s top-N-per-category view, this includes EVERY strategy
    regardless of current rank. 2026-09-30, explicit user instruction
    ("I want to get those dashed cells filled too... which strategy and
    what are details of that strategy"): the trade-view dashboard's per-
    row strategy lookup needs "what does THIS specific strategy's own
    record say", not "is it currently in some category's top 5" - a
    strategy can be a live trade's actual entry logic while sitting well
    outside the top TOP_N_PER_CATEGORY (e.g. range_short_staged_ladder,
    PFnet 0.21, is the real wired short_sell exit mechanic but ranks
    outside short_sell's current top 5), and coming up empty there would
    wrongly read as "no data" rather than "not top-ranked".

    `category`/`rank` report the first category (in TradeCategory
    declaration order) where this strategy places in that category's OWN
    current top TOP_N_PER_CATEGORY leaderboard, or None/None if it
    doesn't rank in any category it belongs to right now - `categories`
    always lists every category it's registered under regardless of
    rank, so a caller can still label it even when unranked."""
    info = {}
    for s in REGISTRY:
        best_category, best_rank = None, None
        for cat in TradeCategory:
            if cat not in s.categories:
                continue
            match = next((r for r in leaderboard(cat, top_n=TOP_N_PER_CATEGORY) if r["name"] == s.name), None)
            if match is not None:
                best_category, best_rank = cat.value, match["rank"]
                break
        info[s.name] = {
            "categories": [c.value for c in s.categories],
            "category": best_category,
            "rank": best_rank,
            "status": s.status.value,
            "pfnet": s.metrics.pfnet if s.metrics else None,
            "win_rate_pct": s.metrics.win_rate_pct if s.metrics else None,
            "avg_held_hrs": round(s.metrics.avg_held_hrs, 1) if s.metrics and s.metrics.avg_held_hrs is not None else None,
            "n_trades": s.metrics.n_trades if s.metrics else None,
            "viable": s.is_viable(),
        }
    return info


def top_strategies_for_monitoring() -> list:
    """The strategies actually eligible to be checked during a monitoring
    cycle right now: the union of each TradeCategory's own current top-
    TOP_N_PER_CATEGORY leaderboard slot (see _ranked_by_pfnet/leaderboard),
    never the whole REGISTRY.

    This is the code behind CLAUDE.md's 2026-09-29 "the pool keeps growing,
    but only the top 5 per category ever get monitored" thumb rule: REGISTRY
    can and should keep growing forever as more strategies get tried, but a
    strategy only ever gets its entry_fn checked while it's actually ranked
    in the top TOP_N_PER_CATEGORY of at least one category by validated
    PFnet. The moment a better strategy is validated and added, it displaces
    the worst-ranked incumbent from this pool automatically - nothing here
    needs to be told when a strategy "graduates" or "falls out"; re-ranking
    the live REGISTRY on every call is what makes that automatic.

    A strategy occupying top-5 slots in more than one category (the
    2026-09-29 multi-category thumb rule) is returned exactly once here,
    never once per category - it still only ever costs ONE entry_fn call
    per symbol per cycle, however many of the (up to)
    MAX_STRATEGY_CHECKS_PER_SYMBOL_PER_CYCLE slots it occupies."""
    seen = set()
    top = []
    for category in TradeCategory:
        ranked = _ranked_by_pfnet(strategies_by_category(category))
        for strat in ranked[:TOP_N_PER_CATEGORY]:
            if strat.name not in seen:
                seen.add(strat.name)
                top.append(strat)
    return top


def scan_universe(symbols, as_of_data_fn, statuses=None):
    """Walk `symbols` one at a time; for each symbol, check every
    strategy in the CURRENT top_strategies_for_monitoring() pool, in that
    pool's order, before moving to the next symbol - never the whole
    REGISTRY (see top_strategies_for_monitoring()'s own docstring). Pass
    `statuses` (an iterable of StrategyStatus) to further restrict that
    pool to specific statuses (e.g. `(StrategyStatus.LIVE,)`); leave it
    None (the default) to check every current top-5-per-category
    strategy regardless of status - the normal case for this pool-
    monitoring design, since tracking RESEARCH-status strategies toward
    validation is the whole point of the pool. This function only ever
    returns candidate signals; it never places an order regardless of a
    strategy's status - that gate lives entirely in main.py/
    kotak_real_orders.py, untouched by this module.

    `as_of_data_fn(symbol)` must return whatever each strategy's
    `entry_fn` needs - left abstract here since this scaffold does not
    fetch data itself. A strategy with `entry_fn=None` (the normal case
    for anything not yet wired into this module) is skipped rather than
    raising, so registering or promoting a strategy's status never by
    itself risks a crash in a future caller.

    Design-only skeleton: not called from main.py's live scheduler.
    """
    candidates = top_strategies_for_monitoring()
    if statuses is not None:
        candidates = [s for s in candidates if s.status in statuses]
    signals = []
    for symbol in symbols:
        data = as_of_data_fn(symbol)
        for strat in candidates:
            if strat.entry_fn is None:
                continue
            result = strat.entry_fn(data)
            if result:
                signals.append({"symbol": symbol, "strategy": strat.name, "signal": result})
    return signals
