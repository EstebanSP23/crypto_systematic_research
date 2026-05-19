# Bear Edge — Killed

**Verdict:** ⚠️ Best variant returns +0.8% APY — fails the lending benchmark.

---

## 1. Hypothesis

Crypto markets exhibit weekend / Sunday-night sell pressure as Asian-session liquidity thins. A systematic short strategy entering near weekend open and exiting Monday/Tuesday could harvest a small but consistent edge from this behavioral pattern.

## 2. Strategy Specification

- **Direction:** Short BTC (single asset)
- **Entry windows tested:**
  - Variant A — no day-of-week filter (continuous)
  - Variant B — entries restricted to Thursday-Saturday
- **Stop:** 1R fixed
- **Target:** 1R fixed (symmetric — coin-flip with edge expected from timing)
- **Fees:** 0.10% per leg

## 3. Backtest Results

| Variant | Trades | WR% | Expectancy | Total Return | APY | Max DD |
|---|---|---|---|---|---|---|
| A — no filter | 344 | 51.5% | +0.013R | +3.4% | **+0.8%** | -20.3% |
| B — Thu-Sat only | 164 | 45.7% | -0.031R | **-5.5%** | -1.3% | -16.6% |

Period: Jan 2022 – May 2026 (~4.3 years). Starting $1,839.

## 4. Why It Was Killed

Variant A is barely positive: **+0.8% APY** with **-20.3% max drawdown**. That is less than 1/7th of USDT lending's 6% APY, with massive drawdown exposure.

Variant B (the "smarter" version restricting to specific days) is *worse* — net negative over 4 years.

The "weekend short" pattern that motivated the strategy turned out to be too weak to overcome 0.20% round-trip fees on 344 trades. The 51.5% win rate suggests there IS a small directional edge, but the size of the edge (+0.013R per trade) is dominated by the cost of capturing it.

## 5. The Lesson

**Win rate above 50% is meaningless without expectancy above 0 net of fees.** A strategy that wins 51.5% of the time but earns less per win than it pays in fees is not an edge — it's a slow grinder of capital.

Additionally: shorting crypto is structurally hard. The market has a long-term upward drift on the major assets; capturing short edge requires either very precise timing (which fees punish) or being right about regime (which is hard).

## 6. Files

- Source script: `backtest_bearedge.py`
- Trade CSVs: `backtest_bearedge_A_nofilter.csv`, `backtest_bearedge_B_thu_sat.csv`
- Chart: `bearedge_equity.png`
