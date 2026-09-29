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
            pfnet=0.06, pfgross=None, win_rate_pct=None, n_trades=None,
            universe="52_symbol_sample", run_ref="universal-score-entry-floor-research.yml run 36444172866 (2026-09-28)",
        ),
        risk_profile={"UNIVERSAL_ENTRY_SCORE_MIN": 85.0},
        source=".github/workflows/universal-score-entry-floor-research.yml",
        evidence=(
            "run 36444172866 (2026-09-28): TREND-only PFnet 0.09->0.13, PFgross 1.11->1.64, "
            "win% 11.6->17.1 as the entry floor rises 70->85; ALL-population PFnet unchanged "
            "at ~0.06 since TREND is only ~17% of trade volume and RANGE (untouched) dominates."
        ),
        notes="One replay result, not full-universe. Needs full pytest + full-universe validation replay + explicit user go-ahead before any live wiring.",
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
            "strategy; mirrors as a real order via is_real_swing_trading_enabled()."
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
            "every real trade taken to date."
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
