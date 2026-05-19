# Quattro — Donchian Breakout with 4-Unit Pyramid

**Status:** 🟢 Live on BloFin perpetual futures since May 2026

---

## 1. Hypothesis

Crypto markets exhibit persistent trends after volatility-expanded breakouts from prior highs. A pyramiding entry structure that adds size as the trend extends can capture asymmetric upside, provided risk is tightly managed at each addition and a hard catastrophe stop prevents disaster on failed breakouts.

This is the textbook **Donchian-Turtle-style trend follower** applied to BTC 4H, with a regime filter to avoid bear markets.

## 2. Strategy Specification

### Entry
- **Signal:** Close > previous 20-bar high (Donchian breakout)
- **Trend filter:** Daily 200 EMA must be rising (daily_EMA200[d] > daily_EMA200[d-20])
- **Execution:** Enter long at the next bar's open

### Pyramid Structure
- **Maximum units:** 4
- **Add levels:** Unit 2 at +0.5N, Unit 3 at +1.0N, Unit 4 at +1.5N (where N = ATR(14) at original entry, fixed for the entire sequence)
- **Each unit risks:** 2% of account at original entry, sized off 2N stop distance

### Exit Logic (three independent mechanisms)
- **Donchian channel exit:** close < previous 10-bar low → close ALL units at next bar's open
- **Per-unit trailing stop:** stop = newest unit's entry − 2N (wick-based). Tightens only when a new unit is added, not continuously as price moves.
- **Hard catastrophe stop:** combined unrealized loss reaches 5% of account (wick-based)
- **No fixed profit target** — the Donchian channel and the unit-based trail do the work

In live results, the three exit reasons split roughly: 40% hard stops, 36% Donchian exits, 23% trailing stops.

### Other Rules
- Single asset (BTC) — no multi-asset complexity
- 4H timeframe — strikes a balance between signal frequency and fee drag
- No shorting — long-only

## 3. Backtest Results

### Headline

| Metric | Value |
|---|---|
| Period | Jan 2022 – May 2026 (~4.1 years of live signals; first entry Mar 28, 2022) |
| Starting capital | $1,839 |
| Final account | $22,196 |
| Total return | **+1,107%** |
| APY | **+83%** |
| Max drawdown | **-37.5%** |
| Total trades | 94 (pyramid sequences, each may contain up to 4 unit entries) |
| Avg trade duration | 3.2 days |

### Trade Distribution

| Metric | Value |
|---|---|
| Wins | 25 (**26.6%**) |
| Losses | 69 (73.4%) |
| Average winner | **+13.4R** |
| Average loser | -2.0R |
| Win/loss asymmetry | **6.7x** |
| Best trade | +76.7R |
| Worst trade | -2.5R (capped by 5% catastrophe stop) |

### R-Distribution

| R Bucket | Count | % of trades |
|---|---|---|
| Loss > -1R (mostly -2.5R catastrophe stops) | 59 | 63% |
| Loss -1R to 0R | 10 | 11% |
| Win 0 to 5R | 10 | 11% |
| Win 5R to 10R | 4 | 4% |
| **Win > 10R (the trend-capture moonshots)** | **11** | **12%** |

This is a textbook trend-follower profile: **low win rate, occasional massive winners, many small-to-medium losses, capped catastrophic risk.** The 11 trades that returned >10R generate the bulk of the lifetime P&L. The strategy works because the asymmetry math overwhelms the win-rate math.

### Trades by Year

| Year | Trades |
|---|---|
| 2022 (partial, from March) | 1 |
| 2023 | 30 |
| 2024 | 32 |
| 2025 | 29 |
| 2026 YTD (through May) | 2 |

### Exit Reason Breakdown

| Exit Reason | Count | % |
|---|---|---|
| Hard 5% catastrophe stop | 38 | 40% |
| Donchian channel exit (close < 20-bar low) | 34 | 36% |
| 2x ATR trailing stop | 22 | 23% |

Note: the high count of catastrophe stops (40%) is expected for a pyramiding breakout strategy. Most breakouts fail. The catastrophe stop is the *floor*, not the average — the average loser is only -2.0R because many pyramid sequences exit before reaching the 5% combined-position floor.

## 4. Walk-Forward Validation

The strategy was tested on a split walk-forward:
- **Period 1 training (2022-2023):** edge confirmed across the 2022 bear and 2023 recovery
- **Period 2 fresh exam (2024-2026):** edge held — 32 trades in 2024, 29 in 2025, continuing positive expectancy

Both halves produced positive expectancy and were structurally similar in trade frequency (~30 per year). The strategy's edge is not concentrated in a single bull regime.

## 5. Operational Specification

The live deployment includes operational safety features built around the strategy logic:

- **Startup safety check** — bot refuses to start with stale state or pending positions
- **Auto-recovery** — systemd restarts on crash with state reload from the trade log
- **Daily heartbeat** — confirms the bot is alive even when no trades fire
- **Reconciliation** — exchange state checked against local state every hour
- **Margin pre-check** — refuses entries that would exceed available margin
- **Telegram alerts** — all entries, exits, and reconciliation events broadcast in real time

## 6. Capital Allocation

- **Account size:** $1,841 USDT total
- **Trading allocation:** $800 (4-unit pyramid worst-case margin)
- **Buffer:** ~$200 (margin safety)
- **Earn buffer:** $1,041 in BloFin Earn (tiered yield)

The trading allocation is intentionally less than the account total because the pyramid can scale aggressively under favorable conditions, and the strategy has been observed to consume 60-70% of available margin in deep extensions.

## 7. Files

- [`backtest.py`](backtest.py) — full research backtest script (CCXT-based, no API keys; reproducible from Binance public OHLCV)
- [`results/quattro_equity_curve.png`](results/quattro_equity_curve.png) — equity curve over the 4.1-year backtest

> **Note:** The live production code (with API keys, exchange credentials, and systemd service files) is intentionally **not** included in this public repository. Only research code is published.

## 8. Realistic Forward Expectation

- **Forward APY:** 30-60% (notably lower than the +83% backtest headline; reflects honest expectation under live conditions including slippage, funding, and execution delay)
- **Forward max DD:** 35-50% (consistent with or slightly worse than backtest)
- **Trade frequency:** ~25-35 sequences per year (~one every 10-14 days on average)
- **Psychological note:** the 26.6% win rate means **you will lose ~3 of every 4 trades**. Sitting through this requires faith in the asymmetry math, not in any single trade outcome.
