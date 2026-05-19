# Setup B — Pullback to Moving Average in Uptrend — Killed

**Verdict:** 🚨 -64% drawdown on the 4H variant disqualifies despite positive total return. 1D variant barely beats lending.

---

## 1. Hypothesis

The textbook trend continuation pattern: in an uptrend (close > 50 SMA > 200 SMA), a pullback to the 20 EMA followed by a reversal candle should be a high-probability buying opportunity. Entry on a stop-buy at the reversal candle's high should ensure you only buy if the pullback resolves bullishly.

## 2. Strategy Specification

- **Universe:** BTC, ETH, SOL, LINK, ADA, ARB, SUI, SEI
- **Timeframes tested:** 4H and 1D
- **Trend filter:** close > 50 SMA > 200 SMA
- **Pullback:** within the last 5 bars, low touched or penetrated the 20 EMA
- **Reversal candle:** today close > open, close > prior close, close in upper half of range
- **Entry:** stop-buy at the high of the reversal candle (expires next bar if untriggered)
- **Stop:** lowest low of the last 5 bars
- **Manage:** 50% off at 2R, trail rest with 20-bar low

## 3. Backtest Results

| Timeframe | Trades | WR% | Expectancy | Return | APY | **Max DD** |
|---|---|---|---|---|---|---|
| **4H** | 339 | 33.0% | +0.099R | +12.3% | +2.8% | **-64.4%** |
| 1D | 57 | 33.3% | +0.139R | +8.1% | +2.9% | -23.4% |

Period: Jan 2022 – May 2026 (~4.4 years). Starting $1,839.

## 4. Why It Was Killed

**The 4H variant has a -64.4% maximum drawdown.** No human (and no risk-managed institution) sits through that. By the time you've reached -60%, you've either capitulated, deleveraged, or doubled down and gotten further wrecked. A strategy unplayable by humans is not a deployable strategy regardless of how the final balance looks.

The 1D variant has more tolerable drawdown (-23%) but only produces **+2.9% APY** — less than half of USDT lending. Same problem as several other rejected strategies: positive but not enough to justify the operational complexity over the no-effort alternative.

Year-by-year for Setup B 4H also reveals concerning recent decay:
- 2024: +$588 (good year)
- 2025: +$294 (weakening)
- 2026 YTD: -$351 (negative)

## 5. The Lesson

**Total return alone is not a useful metric.** A strategy that ends positive over a 4-year period but has -64% drawdown along the way is not a deployable strategy — it's a stress-test of the operator's psychology.

Risk-adjusted metrics (return / max DD, Sharpe, Calmar) matter more than total return for any strategy you actually intend to run with real money. Setup B's Calmar ratio (APY / max DD) is +2.8% / 64% = **0.04** — meaning each percentage point of return cost you 23 percentage points of drawdown to capture. That ratio is far worse than even passive holding.

## 6. Files

- Source script: `backtest_setups_BC.py` (this file also contains Setup C, the surviving Apex variant)
- Chart: `setups_BC.png`
