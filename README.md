# Crypto Systematic Trading Research

### Production-Style Quantitative Research Pipeline for BTC and Major Crypto Assets

---

## 1. Executive Summary

**Crypto Systematic Trading Research** is a portfolio project documenting the design, backtesting, walk-forward validation, and live deployment of systematic trading strategies on crypto perpetual futures markets.

The project answers a core analytical question:

**Which technical-indicator-based trading strategies survive rigorous walk-forward validation when applied to crypto assets, and which are exposed as curve-fit artifacts?**

To answer that question, the system evaluates:

- Trend-following breakout strategies (Donchian, multi-month highs)
- Mean-reversion strategies (1H mean reversion, pullback-to-MA)
- Volatility-compression strategies (BBWP, NR7, Bull Spring)
- Risk-premium harvesting (funding-rate carry)
- Single-asset vs multi-asset universes
- Multiple timeframes (1H, 4H, 1D, 5D, 1W)
- Walk-forward train/test splits
- Sensitivity analysis across parameter grids

The backtest workflow uses real OHLCV data from Binance via CCXT, covering 2017-2026. One strategy (**Quattro**) is currently **live-deployed** on BloFin perpetual futures via a VPS-hosted CCXT pipeline.

This project is explicitly designed to demonstrate the analytical rigor required to **separate real edges from curve-fit noise** — a skill that is rare in retail trading research and directly transferable to any role requiring quantitative judgment under uncertainty.

---

## 2. Research Context

Systematic crypto trading is one of the most adversarial domains in quantitative finance:

- Markets are accessible 24/7 with low retail fees
- The universe of strategies tested by retail traders is enormous
- Most positive backtests fail in live deployment due to curve-fitting
- The data has only ~10 years of meaningful history (BTC), limiting statistical confidence
- Online trading content systematically over-reports winners and under-reports failures

The challenge is not finding strategies with positive backtests — those are trivial to construct. The challenge is distinguishing **real edges** from **statistical artifacts of in-sample data mining**.

This project addresses that challenge head-on:

- Every strategy is tested with walk-forward validation (Period 1 training / Period 2 fresh exam)
- Parameter sensitivity grids surface curve-fit risk explicitly
- A documented "kill list" preserves the reasoning behind rejected strategies
- Forward expectations are reported honestly, without inflating in-sample numbers

---

## 3. Research Objective

The purpose of this project is to build an analytical pipeline that helps answer questions such as:

- Does this strategy survive out-of-sample testing, or is it curve-fit to a specific market regime?
- Is the apparent edge robust across reasonable parameter variations, or concentrated in one magic configuration?
- After realistic fees and slippage, does the strategy outperform passive lending or buy-and-hold?
- What is the realistic forward-expected APY and maximum drawdown — not the inflated headline number?
- Which strategies justify live deployment, and which should remain in research?
- When a "refinement" appears to improve results, is it real signal or hindsight curve-fit?

---

## 4. Architecture Overview

```text
CCXT API (Binance / BloFin OHLCV)
        |
        v
Raw Data Cache (pickle, 2017-2026)
        |
        v
Indicator Layer
  - Moving averages (SMA, EMA — 5, 20, 50, 200)
  - ATR(14)
  - Donchian channels (20-bar, 1080-bar)
  - Bollinger Band Width Percentile (BBWP)
  - Volume rolling averages
        |
        v
Backtest Engine
-----------------------------------
  - Trend-following (breakout, pyramid, Donchian)
  - Mean-reversion (1H counter-trend)
  - Volatility-compression (Spring, Bull Spring)
  - Carry (funding-rate arbitrage)
  - Multi-asset / multi-timeframe variants
-----------------------------------
        |
        v
Walk-Forward Validation
  - Period 1 training (2022-2023, in-sample)
  - Period 2 fresh exam (2024-2026, out-of-sample)
  - Verdict: edge real / edge degraded / curve-fit
        |
        v
Sensitivity Analysis
  - 3-axis parameter grid (lookback x ATR mult x volume mult)
  - Robustness score = count of positive-expectancy cells
  - Curve-fit detector = P1-effect vs P2-effect asymmetry
        |
        v
Decision Layer
  - Deploy live  (Quattro)
  - Validated, deployable (Apex no-pyramid, 5 EMA + filter)
  - Kill list (8+ failed strategies with documented reasons)
        |
        v
Live Deployment Layer (Quattro only)
  - BloFin perpetual futures via CCXT
  - Linux VPS hosted with systemd auto-recovery
  - Telegram alerts for entries, exits, reconciliation
  - Daily heartbeat and margin pre-checks
```

---

## 5. Strategy Universe & Assumptions

### Asset Universe

| Strategy | Assets | Rationale |
|---|---|---|
| Quattro (live) | BTC | Largest liquidity, longest history, no asset-rotation noise |
| Apex (validated) | BTC, ETH, SOL, LINK, ADA, ARB, SUI, SEI | Diversified majors + selected altcoins with 1+ year of history |
| 5 EMA + filter | BTC | Single-asset trend filter, longest backtest window |
| Kill list strategies | Varies (single-asset BTC and multi-asset baskets) | Per strategy hypothesis |

### Date Range

- **2017-08 to 2026-05** (BTC daily) — captures 2018 bear, 2020-21 bull, 2022 bear, 2023-24 recovery
- **2022-01 to 2026-05** (multi-asset 4H) — practical universe limit given altcoin launch dates

### Capital & Fee Assumptions

- **Initial capital:** $1,839 (matches live deployment account)
- **Risk per trade:** 2% of equity (Apex, Quattro), or position-sized for fixed-1x (5 EMA)
- **Maximum concurrent positions:** 3 (multi-asset strategies)
- **Maximum leverage:** 20x (live constraint), but rarely binding
- **Fees:** 0.10% per leg (taker fee on BloFin perpetuals)
- **Slippage:** modeled as zero (acceptable at this account size on BTC; would be larger on smaller alts at scale)
- **Funding costs:** not modeled (acknowledged limitation; matters most for long-duration positions on perpetuals)

### Behavioral Assumptions

- Entries execute at the next bar's open after signal
- Stops execute at exact level (assumes liquid markets, no gap-through)
- All positions sized at signal time using current account balance (not initial)
- Walk-forward periods are pre-defined, not optimized against

---

## 6. Data & Backtest Pipeline Layers

### Raw Data Layer

Raw OHLCV data is fetched from Binance via CCXT and cached locally as pickle files. Each asset is fetched once per backtest session and reused across all strategies. The cache enables reproducible results without repeated API calls.

- `btc_1d_cache.pkl` — BTC daily, 2017-08 to 2026-05
- `ohlcv_4h_cache.pkl` — 8-asset universe at 4H, 2021-01 onwards

### Indicator Layer

Indicators are computed per-strategy at backtest time. Each strategy module includes a `compute_indicators()` function that adds derived columns to the OHLCV DataFrame:

- Moving averages: `sma50`, `sma200`, `ema5`, `ema200`
- Volatility: `atr14`, `bbwp` (Bollinger Band Width Percentile)
- Volume: `vol_sma20`
- Channels: `high_20`, `low_20`, `high_1080` (180-day high)
- Slope filters: `ema200_lag20` for trend-rising detection

### Backtest Engine Layer

Each strategy has its own `run_backtest()` function with consistent inputs (data dict, start/end dates) and outputs (trades DataFrame, final account value, equity history). The engine handles:

- Position management (entry, scale-out at 2R, trailing stop)
- Multi-position state across an asset universe
- Hard stop loss and trailing stop tracking
- Fee accrual per leg
- Equity curve construction

### Walk-Forward Validation Layer

Each strategy is run twice — once on Period 1 (training) and once on Period 2 (fresh exam). The same code runs on both periods; only the date window changes. This isolates curve-fit risk: a real edge survives Period 2; a curve-fit one degrades sharply.

### Sensitivity Analysis Layer

Selected strategies (notably Apex) are tested across a 3-axis parameter grid (typically 27 combinations). The reported metric is **the count of grid cells with positive out-of-sample expectancy**, not the headline best-cell APY. This explicitly avoids the "pick the best of N samples" curve-fit trap.

---

## 7. Core Strategy Modules

### `2_strategies/01_quattro_donchian/`
The live-deployed strategy. Donchian 20-bar breakout on BTC 4H with a daily 200 EMA rising filter and a 4-unit pyramid structure (+0.5N intervals). Risk-managed via 2x ATR trailing stop and 5% hard catastrophe stop.

**Status:** live on BloFin since May 2026. Backtest Jan 2022 – May 2026: +1,107% return, +83% APY, -37.5% max DD, 94 trades, 26.6% win rate, 6.7x avg-win/avg-loss asymmetry.

### `2_strategies/02_apex_no_pyramid/`
Multi-asset 6-month-high breakout on 4H. 8-asset universe with 50/200 SMA trend filter and 1.5x volume confirmation. 50% scale-out at 2R, then trail with 20-bar low.

**Status:** validated via walk-forward (P1 +24% APY, P2 +6% APY) and sensitivity grid (27/27 configs positive out-of-sample). Deployable on a separate sub-account.

### `2_strategies/03_five_ema_filter/`
Single-asset BTC trend filter on the weekly timeframe. Long only when close > 5 EMA AND the daily 200 EMA is rising over the trailing 20 days. 100% all-in sizing.

**Status:** research-validated 2018-2026 (+38.6% APY vs B&H +23%, max DD -40%). Awaiting live deployment decision.

### `3_dead_strategies/`
Eight rejected strategies, each documented with hypothesis, backtest result, and reason for kill. Examples:

| Strategy | Reason for kill |
|---|---|
| Apex *with* pyramid | Curve-fit to 2023 bull regime; failed walk-forward |
| Setup A "Spring" (BBWP compression breakout) | Too selective; ~2% APY barely beats fees |
| Bear Edge (BTC shorts) | Negative expectancy after fees |
| Counterpunch (1H mean reversion) | Did not beat USDT lending |
| Bull Spring (long compression with BBWP exit) | Lost money in walk-forward |
| Setup B (pullback to MA in uptrend) | -64% drawdown disqualified |
| Funding Rate Carry on BTC | 3% APY, inferior to USDT lending |
| Setup A on 1H | Fees destroyed the edge (-75% return) |

This kill list is intentionally featured because **rejecting strategies with rigor is the analytical skill that separates real research from cherry-picked storytelling**.

### `4_methodology/`
The validation framework applied to every strategy. Includes:

- Walk-forward validation guide
- Curve-fit detection patterns
- Sensitivity grid construction
- Honest forward-expectation reporting

---

## 8. Visualization & Reporting Layer

Research outputs are produced as matplotlib charts and CSV exports. Key visualizations include:

### Equity & Drawdown
- Strategy equity curves vs buy-and-hold benchmark
- Drawdown panels under each equity curve
- Walk-forward P1 / P2 visual split

### Per-Asset Diagnostics
- Asset x year P&L heatmap
- Per-asset cumulative R curves
- Trade-by-trade R bars colored by asset

### Sensitivity Diagnostics
- 3-axis parameter grid summary tables
- Top/bottom cells by out-of-sample APY
- Robustness verdict (count of positive cells)

### Trade-Level Analysis
- R-distribution histograms (winners vs losers)
- Hold-time asymmetry (winners run, losers cut)
- Outlier trade enumeration (top 5 winners, top 5 losers)

A Power BI executive dashboard layer is planned as a future addition for portfolio review.

---

## 9. Key Skills Demonstrated

- **Quantitative methodology** — walk-forward validation, sensitivity analysis, curve-fit detection
- **Data engineering** — API integration (CCXT), OHLCV caching, indicator pipeline
- **Statistical reasoning** — sample-size awareness, robustness scoring, honest forward expectations
- **Python for finance** — pandas, NumPy, matplotlib, vectorized backtesting
- **Production deployment** — Linux VPS, systemd services, Telegram alerts, auto-reconciliation
- **Risk management** — position sizing, drawdown analysis, multi-strategy capital allocation
- **Business judgment** — knowing when to deploy, when to research more, and when to kill
- **Technical writing** — strategy documentation, methodology explanations, kill-list reasoning

---

## 10. Repository Structure

```text
crypto_systematic_research/
├── README.md                  ← this file
├── LICENSE                    ← MIT
├── .gitignore                 ← Python defaults
│
├── 0_project_admin/           ← project planning, decision log
│
├── 1_data/                    ← OHLCV caching and access layer
│   └── README.md
│
├── 2_strategies/              ← validated and live strategies
│   ├── README.md
│   ├── 01_quattro_donchian/
│   │   ├── README.md
│   │   ├── backtest.py
│   │   └── results/
│   ├── 02_apex_no_pyramid/
│   │   ├── README.md
│   │   ├── backtest.py
│   │   ├── sensitivity_grid.py
│   │   └── results/
│   └── 03_five_ema_filter/
│       ├── README.md
│       ├── backtest.py
│       └── results/
│
├── 3_dead_strategies/         ← the kill list — one folder per rejected strategy
│   ├── README.md
│   ├── apex_with_pyramid/
│   ├── setup_a_spring/
│   ├── bear_edge/
│   ├── counterpunch/
│   ├── bull_spring/
│   ├── setup_b_pullback/
│   ├── funding_rate_carry/
│   └── setup_a_1h_pyramid/
│
├── 4_methodology/             ← validation framework documentation
│   ├── README.md
│   ├── walkforward_validation.md
│   ├── curvefit_detection.md
│   └── sensitivity_analysis.md
│
└── 5_outputs/                 ← consolidated charts and CSV exports
```

---

## 11. Current Outputs

### Backtest Results
- Quattro: +1,107% return / +83% APY over Jan 2022 – May 2026 (4.1 years), -37.5% max DD, 94 trades, 26.6% win rate, walk-forward validated
- Apex no-pyramid: +24% APY P1 → +6% APY P2, 27/27 sensitivity cells positive out-of-sample
- 5 EMA + 200 EMA filter (1W BTC): +38.6% APY 2018-2026, max DD -40%
- 8 rejected strategies with documented kill reasons

### Visualization Outputs
- Equity curves with B&H benchmarks
- Drawdown panels
- Per-asset x year heatmaps
- Sensitivity grid summary tables
- Trade-by-trade outlier analysis

### Live Deployment
- One strategy (Quattro) live on BloFin perpetual futures
- VPS-hosted with auto-recovery, daily reconciliation, Telegram alerts
- Code-side architecture matches the research pipeline (no rewrite at deployment)

---

## 12. How to Reproduce

1. Clone this repository
2. Install Python 3.11+ and the dependencies: `pip install ccxt pandas numpy matplotlib`
3. Run any strategy's `backtest.py` — it will fetch and cache OHLCV data on first run (5-10 min)
4. Subsequent runs read from the local cache and complete in seconds
5. Walk-forward and sensitivity outputs are deterministic given the cached data
6. Live deployment code is **not included** for security; only research code is published

Note: live trading results will differ from backtests due to slippage, funding costs, and execution timing. Backtests are research tools, not deployment forecasts.

---

## 13. Why This Project Matters

In quantitative trading, the difference between a profitable trader and a losing one is rarely about finding signals — it is almost entirely about telling **real signals apart from data-mining artifacts**.

The same discipline applies to any analytics role:

- A revenue forecast that survives held-out validation is worth deploying
- A KPI that only "improved" after redefining the metric is curve-fit, not progress
- A customer segment that looks profitable after manually excluding outliers is suspect
- A model that beats the benchmark in-sample but not out-of-sample is noise dressed as signal

This project documents the discipline applied to one of the noisiest possible domains:

- Backtest rigorously, but do not trust backtests
- Walk-forward validate, but do not curve-fit the walk-forward window
- Reject parameters that look magical
- Document failures, not just successes
- Deploy live only after exhausting reasons to doubt

The goal is not to claim a magic system. It is to demonstrate the **process of separating real edges from noise** — the same skill that distinguishes great revenue analysis from confirmation-biased dashboards in any business context.

---

## 14. Tools Used

- **Python 3.11+** — backtesting engine, indicator computation, data pipeline
- **CCXT** — Binance and BloFin API integration
- **pandas / NumPy** — vectorized data processing and indicator math
- **matplotlib** — research visualization and equity curves
- **Power BI** *(planned)* — executive performance review dashboards
- **Linux VPS + systemd** — live deployment infrastructure (Frankfurt, Ubuntu 24.04)
- **Telegram Bot API** — live alerts and reconciliation reports
- **Git / GitHub** — version control and public portfolio presentation

---

*Project by [EstebanSP23](https://github.com/EstebanSP23) — Data Analytics Portfolio*
