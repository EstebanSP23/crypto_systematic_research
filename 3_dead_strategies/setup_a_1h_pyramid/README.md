# Setup A on 1H Timeframe — Killed

**Verdict:** 🚨 Lost 75% of capital. Fees destroyed an otherwise marginal edge.

---

## 1. Hypothesis

The same Setup A "Spring" compression-breakout signal that produced ~+6% APY on the 4H timeframe should produce more trades — and therefore more compounded returns — when applied to the 1H timeframe. Same logic, more opportunities.

This is the standard "more trades = more profit" intuition. It is also the standard rookie mistake.

## 2. Strategy Specification

Identical to Setup A on 4H, except applied to 1H candles. Same scoring system, same entry threshold (score ≥ 8), same exit rules.

## 3. Backtest Results — Disastrous

| Timeframe | Trades | WR% | Expectancy | Total Return | APY | Max DD |
|---|---|---|---|---|---|---|
| **1H** | **904** | 35.2% | **-0.016R** | **-75.3%** | **-34.2%** | **-87.2%** |
| 1D (reference) | 47 | 36.2% | +0.188R | +12.4% | +4.3% | -19.3% |
| 4H (the killed full variant) | 250 | 36.0% | +0.093R | +21.1% | +6.0% | -38.5% |

Period: Jan 2023 – May 2026 (~3.3 years). Starting $1,839.

**Identical signal logic. Win rate identical (35-36%) across all three timeframes. The 1H version lost three quarters of capital while the 1D version made money.**

## 4. Why It Was Killed

**Fee drag.** That's the entire story.

The strategy has a tiny per-trade edge — about +0.09R on 4H and +0.19R on 1D. That edge gets crushed when the per-trade fee cost approaches the per-trade gross expectancy:

- Each trade pays ~0.20% in round-trip fees
- On 1D: 47 trades × 0.20% = ~9.4% cumulative fee drag (recoverable by the +12% return)
- On 4H: 250 trades × 0.20% = ~50% cumulative fee drag (barely covered)
- **On 1H: 904 trades × 0.20% = ~181% cumulative fee drag — mathematically impossible to overcome**

The 1H strategy doesn't have a worse signal. It has the SAME signal applied so many times that the fee burden exceeds any plausible gross edge.

## 5. The Lesson

**Trade frequency is not free.** Every trade pays fees, slippage, and (on perpetuals) potential funding. A strategy that needs to win by 0.5% per trade cannot be deployed on a timeframe where the round-trip cost is 0.20% per trade — you start every trade in a hole.

The general principle:
- **High timeframe (1D, 1W):** few trades, fees rarely dominate
- **Mid timeframe (4H):** fees are meaningful — need ≥0.5R per-trade edge
- **Low timeframe (1H, 15m):** fees are catastrophic — need ≥2R per-trade edge, or institutional fees

Most retail strategies that look good on a backtest of a low timeframe are not modeling fees correctly. Add fees and they evaporate.

## 6. Files

- Source script: `backtest_setupA_multi_tf.py`
- Trade CSVs: `setupA_trades_1h.csv` (the disaster), `setupA_trades_1d.csv` (the reference that worked)
