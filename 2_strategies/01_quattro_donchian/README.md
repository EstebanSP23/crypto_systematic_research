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
- **Add trigger:** every +0.5 N (where N = ATR at original entry) above the original entry price
- **Each unit risks:** 2% of equity at original entry

### Exit Logic
- **Hard catastrophe stop:** 5% of equity loss across the combined position
- **Trailing stop:** 2x ATR below the highest reached price (wick-based on the high, not just close)
- **No fixed profit target** — the trail does the work

### Other Rules
- Single asset (BTC) — no multi-asset complexity
- 4H timeframe — slow enough to avoid fee drag, fast enough for ~6-12 trades/year
- No shorting — long-only

## 3. Backtest Results

- **Period tested:** January 2021 – May 2026 (~4.5 years)
- **Final return:** +1107%
- **Max drawdown:** -37.5%
- **Trades:** ~30 total (low frequency by design)
- **Win rate:** ~40% (typical trend-follower profile)
- **Average winner / average loser:** ~5x

## 4. Walk-Forward Validation

The strategy was tested on a split walk-forward:
- **Period 1 training (2021-2023):** edge confirmed
- **Period 2 fresh exam (2024-2026):** edge held, no severe degradation

Both halves of the walk-forward produced positive expectancy, confirming the edge is not concentrated in a single bull regime.

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

- `backtest.py` — research backtest (to be added)
- `results/` — equity curves, walk-forward charts (to be added)

> **Note:** The live production code (with API keys, exchange credentials, and systemd service files) is intentionally **not** included in this public repository. Only research code is published.

## 8. Realistic Forward Expectation

- **Forward APY:** 15-30% (lower than the backtest headline; reflects honest expectation under live conditions including slippage, funding, and execution delay)
- **Forward max DD:** 30-45% (consistent with backtest range)
- **Trade frequency:** 6-12 per year — patience required between trades
