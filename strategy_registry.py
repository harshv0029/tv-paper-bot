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
    """The 5 pools the user asked to track a top-5 leaderboard for
    (2026-09-29). Distinct from AssetClass: a category is "what kind of
    trade is this" (direction/timeframe), not "what instrument". A
    strategy is never confined to exactly one of these - see
    StrategyDef.categories and CLAUDE.md's 2026-09-29 "a strategy is not
    confined to one TradeCategory" thumb rule."""
    SHORT_SELL = "short_sell"
    BUY = "buy"
    SWING = "swing"
    FUTURES = "futures"
    OPTIONS = "options"


# CLAUDE.md, 2026-09-29 thumb rule: 5 categories x this many leaderboard
# slots each bounds live per-stock monitoring cost at a fixed number of
# strategy-checks per round-robin cycle, regardless of how large the
# overall registry grows.
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
            pfnet=1.145, pfgross=1.336, win_rate_pct=42.65, n_trades=279,
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
            pfnet=1.153, pfgross=1.342, win_rate_pct=44.29, n_trades=280,
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
        name="minervini_vcp_livermore_confirmed",
        asset_class=AssetClass.EQUITY_SWING,
        categories=(TradeCategory.SWING,),
        timeframe="1d",
        status=StrategyStatus.RESEARCH,
        entry_fn=None,  # minervini_vcp_entry_signal_livermore_confirmed exists in main.py but is not wired into any scan
        metrics=Metrics(
            pfnet=2.043, pfgross=2.658, win_rate_pct=33.88, n_trades=121,
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
        status=StrategyStatus.RESEARCH,
        entry_fn=None,  # main.py.power_play_entry_signal/power_play_exit_reason exist but are not wired into _run_swing_scan
        metrics=Metrics(
            pfnet=5.023, pfgross=5.820, win_rate_pct=44.95, n_trades=109,
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
            "sizes. A real answer needs the full universe at each timeframe, not yet run."
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
            "n_trades": s.metrics.n_trades if s.metrics else None,
            "universe": s.metrics.universe if s.metrics else None,
            "viable": s.is_viable(),
        }
        for i, s in enumerate(ranked[:top_n])
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
